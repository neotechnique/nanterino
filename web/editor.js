/**
 * Nanterino visual graph editor (Game Creator 2 style node editor).
 *
 * Purpose : draw / edit the robot dialogue graph as nodes (Trigger, Condition, Action, End; legacy Goto / State) and
 *           round-trip it through the node-document contract (Notes/graph-visual-format.md).
 * Boundary: talks only to GET /api/graph/visual, /api/graph/vocab, /api/graph, /api/graph/versions, /api/graph/vars,
 *           /api/graph/trace, POST /api/graph/visual, /api/graph/simulate, /api/graph/reset,
 *           /api/graph/versions/<id>/restore, GET /web/vendor/tabler/<name>.svg (icons) and WS /ws (live state,
 *           heartbeat, last_transition). graph.yaml stays the only executed artifact; the server compiles and
 *           validates, this page never decides what is valid on its own (client checks below are structural
 *           hints only). Wave 2 adds: icons (read from the vocabulary, never chosen here), disabled chains,
 *           panels Tester / Versions / Journal, editable intents, forms for say_text / set_expression / wait / gaze.
 *           computeChains() mirrors the server compiler's chain keys (<state>/t<n>, global/t<n>, <state>/enter)
 *           so a simulator or journal entry (which only carries a chain key) can light its nodes.
 *           Groups (cosmetic frames, meta.frames): drawn in #frames, saved only in graph.layout.json by the server;
 *           they never reach graph.yaml.
 *           L6 (2026-10-31): one State node per state (hub; trigger input accepts state links only; no go-to, no auto bands),
 *           gradient wires (paintWires), post-it notes (meta.notes, #notes layer), left-button-only dragging and a right-click
 *           context menu (installButtonGuards / openContextFor), link meta {reason, description} on hops into a state node.
 *           L8: safe navigation (installSafeNav): Space+drag and hand tool (H) pan only, wheel pans / Ctrl+wheel zooms,
 *           persisted read-only lock (L, editBlocked()), canvas view keys, "?" help popover.
 *           Vars L2 (2026-10-31, contract "Variables et triggers sans entrée"): the state is the system variable `etat`;
 *           no State hub / go-to node is drawn any more (a legacy hub only survives as an inert card), a trigger has NO
 *           input port (Drawflow node with 0 inputs + a drop guard that toasts), "etat = X" conditions / set_var(etat)
 *           actions / var_changed(etat) triggers place the chains (computeChains mirrors that), the auto frames
 *           `auto-<state>` are the columns (jump bar, minimap, semantic cards, live / simulated state glow).
 *           Variables panel (tab "vars": Noms / Listes) edits doc.variables; GET /api/graph/vars feeds its live column
 *           (polled <= 1 Hz only while the tab is open). Inspector args of type var / list / value / enum are typed
 *           controls; the Tester shows the simulated variables of each trace entry (changed ones highlighted).
 *           L3 (2026-10-31): if/else pairs arrive as ONE condition using its Faux output (server side); every wire,
 *           including the one being dragged (paintDragWire), is a gradient from the SOURCE node kind colour to the
 *           target kind colour: a Faux wire starts green like its condition, the red pastille is only a port marker.
 *           L4 (2026-11-01): no Start node (palette, Insérer menu and import drop it; a trigger starts its chain); wires
 *           follow dragged nodes again: the gradient <defs> sits after the wire path (Drawflow writes svg.children[0]).
 * Invariants:
 *   - The Drawflow canvas is the working copy; every node keeps its full server model in node.data.model
 *     (unknown params such as `group` or `global: true` and unknown node fields survive a round trip).
 *   - serialize() is the single exit point of the document (used by save, undo history and dirty check).
 *   - Node ids are our own `n<k>` ids (Drawflow's numeric ids are never sent).
 *   - NEVER touches /api/control (it rewrites config.json).
 * Test    : open /editor; add `#debug=roundtrip` to run the in-page round-trip check (result in the overlay),
 *           `#debug=select` / `#debug=error` for the screenshot scenarios. Library: Drawflow 0.0.60 (MIT, vendored).
 */
(function () {
  'use strict';

  // ---------- tiny helpers ----------
  const $ = (s, r) => (r || document).querySelector(s);
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const isNum = (s) => /^-?\d+(\.\d+)?$/.test(String(s).trim());
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const k in attrs || {}) {
      const v = attrs[k];
      if (k === 'class') e.className = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) e.setAttribute(k, v === true ? '' : v);
    }
    for (const c of kids.flat()) {
      if (c == null || c === false) continue;
      e.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return e;
  }
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  // Icons: CSS mask over the vendored Tabler SVG, coloured by currentColor. Names come from the vocabulary
  // (validated again here because they end up in a style attribute).
  const ICON_OK = /^[a-z0-9-]{1,40}$/;
  const icoUrl = (n) => "url('/web/vendor/tabler/" + (ICON_OK.test(n || '') ? n : 'circle-dot') + ".svg')";
  const icoHtml = (n, color) => `<span class="ico" style="--ic:${icoUrl(n)}${color ? ';color:' + color : ''}"></span>`;
  function ico(n, color) {
    const e = h('span', { class: 'ico' });
    e.style.setProperty('--ic', icoUrl(n));
    if (color) e.style.color = color;
    return e;
  }
  const errLog = [];
  ['error', 'warn'].forEach((lv) => {          // console errors count for the verification scenarios
    const orig = console[lv];
    console[lv] = function () { if (lv === 'error') errLog.push('console.error ' + Array.from(arguments).join(' ')); return orig.apply(console, arguments); };
  });
  window.addEventListener('error', (e) => { errLog.push(String(e.message)); dbg('ERR ' + e.message); });
  window.addEventListener('unhandledrejection', (e) => { errLog.push(String(e.reason)); dbg('REJ ' + e.reason); });
  function dbg(msg) {
    if (!location.hash.includes('debug') || location.hash.includes('quiet')) return;
    let d = $('#dbg');
    if (!d) { d = h('div', { id: 'dbg' }); document.body.append(d); }
    d.textContent += msg + '\n';
  }

  const KINDS = {
    // Legacy Start (lot L4: the server no longer produces it, rebuild() drops one found in an old document, the palette
    // and the context menu never offer it). Kept only so code paths that still name the kind stay harmless.
    start:     { label: 'Début',            cls: 'start',     ins: 0, outs: 1, color: 'var(--start)',   icon: 'flag' },
    // Vars L2: a trigger starts a chain, it has NO input port (contract: inputs = 0; the server refuses any wire into it).
    trigger:   { label: 'Déclencheur',      cls: 'trigger',   ins: 0, outs: 1, color: 'var(--trigger)', icon: 'bolt' },
    condition: { label: 'Condition',        cls: 'condition', ins: 1, outs: 2, color: 'var(--cond)',    icon: 'git-branch' },
    action:    { label: 'Action',           cls: 'action',    ins: 1, outs: 1, color: 'var(--action)',  icon: 'player-play' },
    // Legacy terminal (only drawn when a document still carries one; the palette never offers it).
    goto:      { label: "Aller à l'état",   cls: 'goto',      ins: 1, outs: 0, color: 'var(--goto)',    icon: 'arrow-right' },
    end:       { label: 'Fin',              cls: 'end',       ins: 1, outs: 0, color: 'var(--end)',     icon: 'square' },
    // Legacy L6 hub (import tolerance only: the server never produces it now). Drawn as an inert card, no ports.
    state:     { label: 'État (ancien)',    cls: 'state',     ins: 0, outs: 0, color: 'var(--state)',   icon: 'circle-dot' },
  };
  const NOT_IN_PALETTE = new Set(['start', 'goto', 'state']);
  const NODE_KINDS = ['trigger', 'condition', 'action', 'end'];   // "Blocs" section of the palette (L4: no Start)
  // Post-it palette (pastel), first = default.
  const NOTE_COLORS = [['Jaune', '#fff59d'], ['Rose', '#f8bbd0'], ['Vert', '#c8e6c9'], ['Bleu', '#bbdefb'], ['Orange', '#ffe0b2'], ['Violet', '#e1bee7']];
  // Link rules (mirror of graph_visual.from_visual; the server stays the judge): Start is display only (no link),
  // NOTHING enters a trigger (it starts a chain), everything else may feed any node that has an input.
  const NO_TRIGGER_INPUT = "Un déclencheur n'a pas d'entrée : il démarre une chaîne. Reliez sa sortie à une condition ou à une action.";
  function linkProblem(from, to) {
    const a = from.kind, b = to.kind;
    if (b === 'start') return 'Le nœud Début ne reçoit aucun lien.';
    if (b === 'trigger') return NO_TRIGGER_INPUT;
    if (a === 'start') return "Le nœud Début ne se relie à rien : l'état de départ est fixé par le robot.";
    if (a === 'state' || b === 'state') return "Les anciens nœuds État ne se relient plus : utilisez « Changer d'état » (action) et la condition « etat = … ».";
    return null;
  }

  // ---------- state ----------
  let V = { events: [], actions: [], guards: [], delays: [], since: [], states: [], intents: [], kinds: [] };
  let meta = { version: 1, states: [], intents: {}, order: [] };   // top-level doc fields other than nodes/links
  let editor = null;
  const nidToDf = new Map();       // our node id -> Drawflow id
  let loading = false;
  let selDf = null;
  let hist = [], histIdx = -1, savedSnap = '';
  let serverErrors = [];           // [{node,message,intent?}] from the last POST
  let simErrors = [];              // same shape, from the last POST /api/graph/simulate (400)
  let intentErrs = {};             // intent name -> server message
  let simState = null;             // state the simulator ended in (band highlight)
  const freshIds = new Set();      // ids of nodes dropped from the palette and not yet validated / saved
  let issues = new Map();          // nid -> [{level,message}] (client analysis + server errors)
  // Branch analysis from POST /api/graph/check: warnings (several branches of a trigger that change the state)
  // and, per trigger with several outgoing branches, the engine's execution order (rank).
  let fanInfo = { warnings: [], fans: {} };
  let checkTimer = null, lastCheckKey = '';
  let globalIssues = [];           // issues without a node
  let liveState = null;
  let lastWs = 0, lastAge = null;
  let idCounter = 0;
  let addJitter = 0;
  // Extra data of the hop into a state node: key "from|port|to" -> {reason?, description?} (the transition's journal
  // reason, and its description when no node of the chain can carry it). Rebuilt from doc.links, written back by serialize().
  let linkMeta = new Map();
  let selConn = null;              // {out, in, cls} (Drawflow ids) of the selected wire, else null
  const linkKey = (f, p, t) => f + '|' + p + '|' + t;

  const byId = (list, id) => (list || []).find((x) => x.id === id);
  // Triggerable events = vocabulary events + one `intent.<id>` event per recognised intent.
  // Intents of the document being edited (meta.intents) count too: a new intent is usable as a trigger at once.
  const INTENT_NAME = /^[a-z][a-z0-9_]{0,31}$/;
  const evs = () => {
    const out = V.events.slice(), seen = new Set();
    V.intents.forEach((i) => { seen.add(i.id); out.push({ id: i.event || 'intent.' + i.id, label: 'Intention « ' + i.id + ' »', help: i.label, icon: i.icon || 'message' }); });
    Object.keys(meta.intents || {}).forEach((n) => { if (!seen.has(n) && n !== 'question') out.push({ id: 'intent.' + n, label: 'Intention « ' + n + ' »', help: (meta.intents[n] || {}).description || '', icon: (meta.intents[n] || {}).icon || 'message' }); });
    return out;
  };
  const stateLabel = (id) => { const s = byId(V.states, id); return s ? s.label : id; };
  const stateIcon = (id) => {
    const d = (meta.states || []).find((x) => x.id === id), s = byId(V.states, id);
    return (d && d.icon) || (s && s.icon) || 'circle-dot';
  };
  // Header icon of a node: the vocabulary entry it uses, else its kind icon.
  function iconOf(m) {
    const p = m.params || {}, k = KINDS[m.kind];
    if (m.kind === 'trigger') {
      if (p.type === 'event' && p.event === 'var_changed' && p.name === 'etat' && p.value) return stateIcon(p.value);
      if (p.type === 'event') { const e = byId(evs(), p.event); return (e && e.icon) || k.icon; }
      if (p.type === 'after') { const s = byId(V.since, p.since || 'state'); return (s && s.icon) || 'clock'; }
      if (p.type === 'enter') return stateIcon(p.state);
    }
    if (m.kind === 'condition' && p.type === 'guard') { const g = byId(V.guards, p.guard); return (g && g.icon) || k.icon; }
    if (m.kind === 'action') { const a = byId(V.actions, p.action); return (a && a.icon) || k.icon; }
    return k.icon;
  }
  const stateColor = (id) => {
    if (id === 'global') return '#8a6d1d';
    const s = (meta.states || []).find((x) => x.id === id);
    return s && s.color ? s.color : '#566';
  };

  // ---------- variables (Vars L2) ----------
  // Two sources: system variables come from the vocabulary (V.variables, `system`/`readonly`, never in the document);
  // user variables and lists are the document's own `variables` block ({names: {id: {type, value, choices?, description}},
  // lists: {id: {type, items? | from? | intent?, description}}}), edited by the Variables panel and saved with the doc.
  // A list bound to a source (`from` = config key, `intent` = intent words) is read-only here; its items are shown
  // from the vocabulary snapshot. The server stays the validator (types, names, deleting a used variable = 400).
  const VAR_NAME = /^[a-z][a-z0-9_]{0,31}$/;
  const docVars = () => {
    meta.variables = meta.variables && typeof meta.variables === 'object' ? meta.variables : {};
    if (!meta.variables.names || typeof meta.variables.names !== 'object') meta.variables.names = {};
    if (!meta.variables.lists || typeof meta.variables.lists !== 'object') meta.variables.lists = {};
    return meta.variables;
  };
  const sysVars = () => (((V.variables || {}).names) || []).filter((v) => v.system);
  // Every name variable: [{id, type, label?, description, choices?, value?, system, readonly}], system ones first.
  function varDefs() {
    const out = sysVars().map((v) => Object.assign({}, v, { system: true, readonly: true }));
    const seen = new Set(out.map((v) => v.id));
    const names = docVars().names;
    Object.keys(names).forEach((id) => { if (!seen.has(id)) out.push(Object.assign({ id, system: false, readonly: false }, names[id])); });
    return out;
  }
  // Every list: [{id, type, items, description, readonly, source}] (source = {cfg} | {intent} for a bound list).
  function listDefs() {
    const snap = {}; (((V.variables || {}).lists) || []).forEach((l) => { snap[l.id] = l; });
    const lists = docVars().lists;
    return Object.keys(lists).map((id) => {
      const l = lists[id] || {}, bound = !!(l.from || l.intent);
      return { id, type: l.type || 'string', description: l.description || '', readonly: bound,
        source: l.from ? { cfg: l.from } : l.intent ? { intent: l.intent } : null,
        items: bound ? (((snap[id] || {}).items) || []) : (Array.isArray(l.items) ? l.items : []) };
    });
  }
  const varDef = (id) => varDefs().find((v) => v.id === id) || null;
  const listDef = (id) => listDefs().find((l) => l.id === id) || null;
  const typeLabel = (t, lists) => ((byId(lists ? V.list_types : V.var_types, t) || {}).label || t);
  const opLabel = (o) => ({ '=': '=', '!=': '≠', '<': '<', '<=': '≤', '>': '>', '>=': '≥', in: 'parmi', not_in: 'hors de' }[o] || o);
  // A value as shown on a card: the etat value by its state label, `$x` as "x", lists joined.
  const valText = (name, v) => {
    if (Array.isArray(v)) return v.map((x) => valText(name, x)).join(', ');
    if (name === 'etat') return stateLabel(v);
    if (typeof v === 'string' && v.startsWith('$')) return v === '$utterance' ? 'la phrase entendue' : v.slice(1);
    if (v === true) return 'vrai';
    if (v === false) return 'faux';
    return v == null || v === '' ? '?' : String(v);
  };
  // Nodes that use a variable or list (model ids): args name/list/value "$x", var_changed trigger name.
  function varUses(id, doc) {
    const out = [];
    ((doc || serialize()).nodes || []).forEach((n) => {
      const p = n.params || {}, a = p.args || {};
      const hit = (n.kind === 'trigger' && p.name === id) || a.name === id || a.list === id
        || [a.value, p.value].some((v) => v === '$' + id || (Array.isArray(v) && v.includes('$' + id)));
      if (hit) out.push(n.id);
    });
    return out;
  }
  // Display form of a guard that reads counters (vocabulary `as_vars`, e.g. "tours < max_tours").
  const asVars = (gid) => (byId(V.guards, gid) || {}).as_vars || '';
  // A state-entry trigger: legacy `enter`, or var_changed on etat (never disabled, never ordered).
  const isEnterTrig = (m) => { const p = m.params || {}; return p.type === 'enter' || (p.type === 'event' && p.event === 'var_changed' && p.name === 'etat'); };
  // Structural problems of a node's typed arguments (vocabulary `args`): unknown / wrongly typed / read-only variable
  // or list, missing value. Hints only: the server compiler gives the final word.
  function argIssues(spec, args) {
    const out = [];
    ((spec && spec.args) || []).forEach((a) => {
      const v = args[a.name], lab = a.label || a.name;
      if (a.type === 'var') {
        if (v == null || v === '') { out.push('À choisir : ' + lab + '.'); return; }
        const d = varDef(v);
        if (!d) out.push(`Variable inconnue : « ${v} ».`);
        else if ((a.var_types || []).length && !a.var_types.includes(d.type)) out.push(`« ${v} » (${typeLabel(d.type)}) ne convient pas ici.`);
        else if (a.writable && d.readonly && !(v === 'etat' && spec.id === 'set_var')) out.push(`La variable système « ${v} » est en lecture seule.`);
      } else if (a.type === 'list') {
        if (v == null || v === '') { out.push('À choisir : ' + lab + '.'); return; }
        const d = listDef(v);
        if (!d) out.push(`Liste inconnue : « ${v} ».`);
        else if ((a.list_types || []).length && !a.list_types.includes(d.type)) out.push(`La liste « ${v} » (${typeLabel(d.type, true)}) ne convient pas ici.`);
        else if (a.writable && d.readonly) out.push(`La liste « ${v} » est liée à une source : lecture seule.`);
      } else if (a.type === 'value' && !a.optional && (v == null || v === '' || (Array.isArray(v) && !v.length))) out.push('À remplir : ' + lab + '.');
    });
    return out;
  }

  // ---------- network ----------
  async function api(path, opts) {
    const r = await fetch(path, opts);
    let j = null;
    try { j = await r.json(); } catch (e) { /* non JSON */ }
    return { status: r.status, ok: r.ok, json: j };
  }
  const postJson = (path, body) => api(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body == null ? {} : body),
  });

  // ---------- model access ----------
  function dfData() { return editor.drawflow.drawflow[editor.module].data; }
  function dfNode(dfid) { return dfData()[dfid]; }
  function model(dfid) { const n = dfNode(dfid); return n ? n.data.model : null; }
  function nidOf(dfid) { const m = model(dfid); return m ? m.id : null; }

  function nextNid() {
    let mx = idCounter;
    for (const id in dfData()) { const m = /^n(\d+)$/.exec(model(id).id); if (m) mx = Math.max(mx, +m[1]); }
    idCounter = mx + 1;
    return 'n' + idCounter;
  }

  // ---------- node rendering ----------
  function delayText(d) {
    const k = V.delays.find((x) => x.key === d);
    return k ? `${k.label} (${k.value} s)` : (d === '' || d == null ? '?' : `${d} s`);
  }
  function summary(m) {
    const p = m.params || {};
    switch (m.kind) {
      case 'start': return 'État de départ : ' + stateLabel(p.state);
      case 'trigger':
        if (p.type === 'event' && p.event === 'var_changed') {
          if (p.name === 'etat') return 'Quand etat devient ' + valText('etat', p.value) + " (entrée dans l'état)";
          return 'Quand ' + (p.name || '?') + ' change' + (p.value != null && p.value !== '' ? ' (devient ' + valText(p.name, p.value) + ')' : '');
        }
        if (p.type === 'event') { const e = byId(evs(), p.event); return e ? e.label : '? ' + (p.event || ''); }
        if (p.type === 'after') {
          const s = byId(V.since, p.since || 'state');
          return 'Après ' + delayText(p.delay) + ' ' + (s ? s.label : '');
        }
        if (p.type === 'enter') return "À l'entrée dans " + stateLabel(p.state);
        return '?';
      case 'condition':
        if (p.type === 'state') return (p.negate ? 'Pas dans : ' : 'Dans : ') + (p.states || []).map(stateLabel).join(', ');
        {
          const g = byId(V.guards, p.guard), a = p.args || {}, no = p.negate ? 'Non : ' : '';
          if (p.guard === 'var_compare') return no + (a.name || '?') + ' ' + opLabel(a.op || '=') + ' ' + valText(a.name, a.value);
          if (p.guard === 'var_true') return no + (a.name || '?') + ' est vrai';
          if (p.guard === 'list_contains') return no + (a.list || '?') + ' contient ' + valText(a.list, a.value);
          if (p.guard === 'list_empty') return no + (a.list || '?') + ' est vide';
          return no + (g ? g.label : '? ' + (p.guard || '')) + (asVars(p.guard) ? ' (' + asVars(p.guard) + ')' : '');
        }
      case 'action': {
        if (p.action === 'set_var' && (p.args || {}).name === 'etat') return "Changer d'état → " + valText('etat', p.args.value) + (p.reason ? ' (' + p.reason + ')' : '');
        const a = byId(V.actions, p.action);
        const args = Object.entries(p.args || {}).map(([k, v]) => `${k}=${v}`).join(', ');
        return (a ? a.label : '? ' + (p.action || '')) + (args ? ' (' + args + ')' : '') + (p.phase === 'then' ? ' [après]' : '');
      }
      case 'goto': return '→ ' + stateLabel(p.state) + (p.reason ? ' (' + p.reason + ')' : '');
      case 'end': return 'Fin de chaîne';
      case 'state': return stateLabel(p.state);
    }
    return '';
  }
  function stateDesc(id) {
    const d = (meta.states || []).find((x) => x.id === id), s = byId(V.states, id);
    return (d && d.description) || (s && s.description) || '';
  }
  function nodeHtml(m) {
    const k = KINDS[m.kind];
    if (m.kind === 'state') {   // hub card: fixed height (the server's auto layout assumes 84 px)
      const sid = (m.params || {}).state, col = stateColor(sid);
      return `<div class="nhead">${icoHtml(stateIcon(sid), col)}<span class="ntitle">État</span></div><div class="nstate" style="color:${esc(col)}">${esc(stateLabel(sid))}</div><div class="nsum ndesc">${esc(stateDesc(sid))}</div><div class="nmsg"></div>`;
    }
    const tag = m.group === 'global' ? `<span class="ntag" style="background:${esc(stateColor(m.group))}">${esc(m.group === 'global' ? 'global' : stateLabel(m.group))}</span>` : '';
    const off = m.kind === 'trigger' && (m.params || {}).enabled === false ? '<span class="ntag off">désactivée</span>' : '';
    const scope = m.kind === 'trigger' && (m.params || {}).state && (m.params || {}).type !== 'enter'
      ? `<div class="nsum nscope">${icoHtml(stateIcon(m.params.state), stateColor(m.params.state))} dans : ${esc(stateLabel(m.params.state))}</div>` : '';
    const desc = m.description ? `<div class="nsum" style="color:var(--mut)">${esc(m.description)}</div>` : '';
    return `<div class="nhead">${icoHtml(iconOf(m), k.color)}<span class="ntitle">${esc(k.label)}</span>${off}${tag}</div><div class="nsum">${esc(summary(m))}</div>${scope}${desc}<div class="nmsg"></div>`;
  }
  function nodeEl(dfid) { return document.getElementById('node-' + dfid); }
  function refreshNode(dfid) {
    const el = nodeEl(dfid), m = model(dfid);
    if (!el || !m) return;
    const c = el.querySelector('.drawflow_content_node');
    if (c) c.innerHTML = nodeHtml(m);
    markNode(dfid);
  }

  function addNodeFromModel(m, x, y) {
    const k = KINDS[m.kind];
    const dfid = editor.addNode(m.kind, k.ins, k.outs, x, y, 'node-' + k.cls, { model: m }, nodeHtml(m), false);
    nidToDf.set(m.id, dfid);
    return dfid;
  }

  // ---------- (de)serialization ----------
  function serialize() {
    const data = dfData();
    const nodes = [], links = [];
    for (const dfid in data) {
      const d = data[dfid];
      const m = clone(d.data.model);
      m.x = Math.round(d.pos_x); m.y = Math.round(d.pos_y);
      nodes.push(m);
      for (const key in d.outputs) {
        const idx = +key.split('_')[1];
        const port = m.kind === 'condition' ? (idx === 1 ? 'true' : 'false') : 'out';
        for (const c of d.outputs[key].connections) {
          const lk = { from: m.id, port, to: nidOf(c.node) }, mt = linkMeta.get(linkKey(lk.from, port, lk.to));
          if (mt) Object.assign(lk, mt);          // reason / description of a hop into a state node
          links.push(lk);
        }
      }
    }
    // Trigger order: keep the server order, drop deleted ones, append new non-"enter" triggers by (y, x).
    const present = new Set(nodes.filter((n) => n.kind === 'trigger').map((n) => n.id));
    const order = (meta.order || []).filter((id) => present.has(id));
    const inOrder = new Set(order);
    nodes.filter((n) => n.kind === 'trigger' && !inOrder.has(n.id) && !isEnterTrig(n))
      .sort((a, b) => a.y - b.y || a.x - b.x).forEach((n) => order.push(n.id));
    const doc = {};
    for (const k in meta) if (!['nodes', 'links', 'order', 'error', 'pending'].includes(k)) doc[k] = clone(meta[k]);
    doc.nodes = nodes; doc.links = links; doc.order = order;
    return doc;
  }

  function rebuild(doc, keepView) {
    loading = true;
    meta = {};
    for (const k in doc) if (!['nodes', 'links', 'error', 'pending'].includes(k)) meta[k] = clone(doc[k]);
    if (!meta.version) meta.version = 1;
    nidToDf.clear();
    // L4: an interaction still in progress refers to DOM nodes that clear() is about to drop (undo/redo during a drag)
    editor.drag = false; editor.drag_point = false; editor.connection = false; editor.editor_selected = false;
    editor.ele_selected = null; editor.node_selected = null; editor.connection_selected = null; editor.connection_ele = null;
    editor.clear();
    selDf = null; selConn = null;
    linkMeta = new Map();
    (doc.links || []).forEach((l) => {
      const mt = {};
      if (l.reason) mt.reason = l.reason;
      if (l.description) mt.description = l.description;
      if (Object.keys(mt).length) linkMeta.set(linkKey(l.from, l.port, l.to), mt);
    });
    (doc.nodes || []).forEach((n) => {
      // Lot L4: a legacy Start node (old saved document / undo entry) is dropped silently: triggers start their chains
      // and the start state is fixed by the code. Its wires are skipped below (no Drawflow id), the server ignores it.
      if (n.kind === 'start') { dbg('legacy start node dropped ' + n.id); return; }
      const m = clone(n); delete m.x; delete m.y;
      m.params = m.params || {}; m.description = m.description || '';
      addNodeFromModel(m, n.x || 0, n.y || 0);
    });
    (doc.links || []).forEach((l) => {
      const a = nidToDf.get(l.from), b = nidToDf.get(l.to);
      if (a == null || b == null) return;
      // Vars L2: a port the kind no longer has (wire into a trigger, legacy hub / Start wires) is not drawn
      // (Drawflow would throw on a missing input); the server refuses such wires anyway.
      const ka = KINDS[model(a).kind], kb = KINDS[model(b).kind];
      if (!kb || !kb.ins || !ka || !ka.outs || (l.port === 'false' && ka.outs < 2)) { dbg('wire skipped ' + l.from + '>' + l.to); return; }
      editor.addConnection(a, b, l.port === 'false' ? 'output_2' : 'output_1', 'input_1');
    });
    docVars();               // the variables block always exists from here on (stable dirty snapshot)
    loading = false;
    if (!keepView) initialView();
    if (selFrame && !frameById(selFrame)) selFrame = null;
    if (selNote && !noteById(selNote)) selNote = null;
    analyze();
    paintWires();
    drawFrames();
    drawNotes();
    drawJumpbar(); zoomVars();
    renderPalette();
    renderInspector();
    renderIntents();
    if (curTab === 'vars') renderVars();
    if (curTab === 'tester') renderTester();
  }

  // ---------- history ----------
  const snap = () => JSON.stringify(serialize());
  let commitTimer = null;
  function commitSoon() {
    if (loading) return;
    clearTimeout(commitTimer);
    commitTimer = setTimeout(commit, 0);   // coalesce the several events of one gesture (e.g. node removal)
  }
  function commit() {
    if (loading) return;
    const s = snap();
    if (s !== hist[histIdx]) {
      hist = hist.slice(0, histIdx + 1); hist.push(s);
      if (hist.length > 100) hist.shift();
      histIdx = hist.length - 1;
    }
    analyze(); updateBar();
  }
  function undo() { if (editBlocked()) return; if (histIdx > 0) { histIdx--; rebuild(JSON.parse(hist[histIdx]), true); updateBar(); } }
  function redo() { if (editBlocked()) return; if (histIdx < hist.length - 1) { histIdx++; rebuild(JSON.parse(hist[histIdx]), true); updateBar(); } }
  function updateBar() {
    $('#btnUndo').disabled = histIdx <= 0;
    $('#btnRedo').disabled = histIdx >= hist.length - 1;
    $('#dirty').hidden = hist[histIdx] === savedSnap;
  }

  // ---------- chains: structural keys (mirror of graph_visual.compile) ----------
  // The server reports a fired transition by its chain key; this walks a document the way the compiler does
  // (triggers in `order`, then by (y, x); true branch before false branch; per-state counters) and returns
  //   keys: Map key -> [node ids of that path], byTrigger: Map trigger id -> [keys].
  // Chains the compiler would reject are skipped, which is also what it does (and then simulate answers 400).
  function computeChains(doc) {
    const nodes = {}; (doc.nodes || []).forEach((n) => { nodes[n.id] = n; });
    const adj = new Map(), stateIn = new Map(), hubOf = {};
    (doc.nodes || []).forEach((n) => { if (n.kind === 'state' && n.params && n.params.state && !hubOf[n.params.state]) hubOf[n.params.state] = n.id; });
    (doc.links || []).forEach((l) => {
      const a = nodes[l.from], b = nodes[l.to]; if (!a || !b) return;
      if (a.kind === 'start') return;                                          // Start is display only
      if (a.kind === 'state') {                                                // legacy hub -> trigger: "valid in this state"
        if (b.kind === 'trigger') { if (!stateIn.has(l.to)) stateIn.set(l.to, []); if (!stateIn.get(l.to).includes(l.from)) stateIn.get(l.to).push(l.from); }
        return;
      }
      const k = l.from + '|' + l.port; if (!adj.has(k)) adj.set(k, []); adj.get(k).push(l.to);
    });
    const trig = (doc.nodes || []).filter((n) => n.kind === 'trigger').map((n) => n.id);
    let ordered = [...new Set((doc.order || []).filter((i) => nodes[i] && nodes[i].kind === 'trigger'))];
    const seen = new Set(ordered);
    ordered = ordered.concat(trig.filter((i) => !seen.has(i)).sort((a, b) => (nodes[a].y || 0) - (nodes[b].y || 0) || (nodes[a].x || 0) - (nodes[b].x || 0)));
    const paths = (tid) => {
      const out = [];
      const rec = (nid, chain) => {
        if (chain.some((c) => c[0] === nid)) return;
        const n = nodes[nid]; if (!n) return;
        // terminals: a legacy hub / go-to, or End; an action whose output is unlinked ends the chain (implicit end)
        if (n.kind === 'goto' || n.kind === 'end' || n.kind === 'state') { out.push(chain.concat([[nid, false]])); return; }
        if (n.kind === 'condition') {
          [['true', false], ['false', true]].forEach(([port, inv]) => (adj.get(nid + '|' + port) || []).forEach((t) => rec(t, chain.concat([[nid, inv]]))));
          return;
        }
        const next = adj.get(nid + '|out') || [];
        if (!next.length && n.kind === 'action') { out.push(chain.concat([[nid, false], [null, false]])); return; }
        next.forEach((t) => rec(t, chain.concat([[nid, false]])));
      };
      rec(tid, []);
      return out;
    };
    const keys = new Map(), byTrigger = new Map(), counts = {};
    let gcount = 0;
    const next = (st) => { counts[st] = counts[st] || 0; return st + '/t' + counts[st]++; };
    ordered.forEach((tid) => {
      let p = nodes[tid].params || {};
      const mine = [];
      byTrigger.set(tid, mine);
      // Vars L2: "etat becomes X" (var_changed on etat) is the on_enter of X
      if (p.type === 'event' && p.event === 'var_changed' && p.name === 'etat') {
        if (p.value == null || p.value === '') return;
        p = Object.assign({}, p, { type: 'enter', state: p.value });
      }
      // states the trigger is linked from (legacy hubs) + the legacy `params.state`: the chain's scope
      const linked = (stateIn.get(tid) || []).map((s) => nodes[s].params && nodes[s].params.state).filter(Boolean);
      const scope = [...new Set(linked.concat((p.type === 'event' || p.type === 'after') && p.state ? [p.state] : []))];
      paths(tid).forEach((path) => {
        const ids = path.map((x) => x[0]).filter((x) => x != null);
        const hubs = (sts) => sts.map((s) => hubOf[s]).filter(Boolean);        // legacy source hubs light up with the chain
        const mid = path.slice(1, -1);
        if (p.type === 'enter') {
          if (mid.some(([nid]) => nid && nodes[nid].kind === 'condition')) return;   // refused by the compiler
          const k = p.state + '/enter'; if (!keys.has(k)) { keys.set(k, ids.concat(hubs([p.state]))); mine.push(k); } return;
        }
        const pos = [], neg = []; let force = false, dupOk = true;
        if ((p.type === 'event' || p.type === 'after') && scope.length) { pos.push(scope.slice()); force = !!p.global || scope.length > 1; dupOk = false; }
        mid.forEach(([nid, inv]) => {
          const n = nid && nodes[nid]; if (!n || n.kind !== 'condition') return;
          const q = n.params || {}, a = q.args || {};
          let isNeg = !!q.negate !== inv;
          if (q.type === 'state') { dupOk = false; (isNeg ? neg : pos).push(q.states || []); force = force || (!isNeg && !!q.global); return; }
          if (q.type === 'guard' && q.guard === 'var_compare' && a.name === 'etat') {
            const sts = ['in', 'not_in'].includes(a.op) ? [...new Set(Array.isArray(a.value) ? a.value : [a.value])] : [a.value];
            isNeg = isNeg !== ['!=', 'not_in'].includes(a.op);
            (isNeg ? neg : pos).push(sts); force = force || (!isNeg && !!q.global);
          }
        });
        let single = pos.length === 1 && pos[0].length === 1 && !neg.length && !force, places = null;
        let src = pos.length ? pos[0] : [];
        if (!single && dupOk && pos.length && !neg.length && !force) {
          places = pos[0].filter((s) => pos.slice(1).every((o) => o.includes(s)));
          if (!places.length) return;
          if (places.length === 1) { single = true; src = places; places = null; }
        }
        let ks;
        if (single) ks = [next(src[0])];
        else if (places) ks = places.map(next);          // one transition per state (duplicated chain, same fan)
        else {
          if (p.type === 'after') return;
          if (pos.length && !pos[0].filter((s) => pos.slice(1).every((o) => o.includes(s))).length) return;
          ks = ['global/t' + gcount++];
        }
        ks.forEach((key) => { keys.set(key, ids.concat(hubs(src.filter((s) => linked.includes(s))))); mine.push(key); });
      });
    });
    return { keys, byTrigger };
  }
  let liveChains = { keys: new Map(), byTrigger: new Map() };   // chains of the document the robot runs (last loaded / saved)

  // Nodes belonging to a disabled chain (reachable from a disabled trigger and from no enabled one).
  function disabledNodes() {
    const data = dfData(), reach = (start) => {
      const seen = new Set(), st = [start];
      while (st.length) {
        const d = st.pop(); if (seen.has(d)) continue; seen.add(d);
        if (d !== start && data[d].data.model.kind === 'state') continue;   // a hub ends the chain: its outputs start OTHER chains
        for (const key in data[d].outputs) data[d].outputs[key].connections.forEach((c) => st.push(String(c.node)));
      }
      return seen;
    };
    const off = new Set(), on = new Set();
    for (const dfid in data) {
      const m = data[dfid].data.model;
      if (m.kind !== 'trigger') continue;
      reach(dfid).forEach((d) => ((m.params || {}).enabled === false ? off : on).add(d));
    }
    const out = new Set();
    off.forEach((d) => { if (!on.has(d) && data[d] && data[d].data.model.kind !== 'state') out.add(data[d].data.model.id); });
    return out;
  }
  // Highlight state: nodes lit by the simulator ("now" = current step, "past" = already fired) as model ids.
  const lit = { now: new Set(), past: new Set() };
  function paintChains() {
    if (!editor) return;
    const data = dfData(), off = disabledNodes();
    for (const dfid in data) {
      const el = nodeEl(dfid); if (!el) continue;
      const id = data[dfid].data.model.id;
      el.classList.toggle('disabled', off.has(id));
      el.classList.toggle('lit-now', lit.now.has(id));
      el.classList.toggle('lit-past', lit.past.has(id) && !lit.now.has(id));
    }
    // L7: while a simulation / journal entry is displayed, its wires glow too (now = cyan, past = blue) and
    // everything else is dimmed (container class `simdim`); cleared with the lights (Réinitialiser).
    const on = lit.now.size > 0 || lit.past.size > 0;
    if (!editor.container) return;
    editor.container.classList.toggle('simdim', on);
    editor.container.querySelectorAll('svg.connection').forEach((svg) => {
      const cl = svg.classList, a = data[cl[2] ? cl[2].slice(14) : ''], b = data[cl[1] ? cl[1].slice(13) : ''];
      const ia = a && a.data.model.id, ib = b && b.data.model.id;
      const now = on && lit.now.has(ia) && lit.now.has(ib);
      cl.toggle('wlit-now', now);
      cl.toggle('wlit-past', on && !now && (lit.past.has(ia) || lit.now.has(ia)) && (lit.past.has(ib) || lit.now.has(ib)));
    });
  }
  function blinkChain(key) {
    const ids = liveChains.keys.get(key); if (!ids) return;
    if (curTab === 'journal') focusChainIds(ids);    // L7 fix round: the journal follows the live chain
    ids.forEach((nid) => {
      const el = nodeEl(nidToDf.get(nid)); if (!el) return;
      el.classList.remove('blink'); void el.offsetWidth; el.classList.add('blink');
      setTimeout(() => el.classList.remove('blink'), 2000);
    });
  }
  // Pan (keeping the zoom, at least 0.35) so that a node is in the middle of the canvas.
  function panTo(nid, minZoom) {
    const dfid = nidToDf.get(nid); if (dfid == null) return;
    const d = dfNode(dfid), st = $('#drawflow'), z = Math.max(editor.zoom, minZoom || 0.35);
    setView(z, st.clientWidth / 2 - (d.pos_x + 107) * z, st.clientHeight / 2 - (d.pos_y + 40) * z);
  }

  // ---------- analysis (structural hints, not the validator) ----------
  function analyze() {
    const data = dfData();
    const out = new Map();
    // A node the user just dropped from the palette gets mild "todo" hints (no coloured outline) until the
    // first validate / save, instead of errors for the fields it has not had time to receive yet.
    const add = (nid, level, message) => {
      if (freshIds.has(nid)) { if (level === 'warn') return; level = 'todo'; }   // structural warnings wait until validate
      if (!out.has(nid)) out.set(nid, []); out.get(nid).push({ level, message });
    };
    const incoming = {}, outgoing = {};
    for (const dfid in data) { incoming[dfid] = 0; outgoing[dfid] = 0; }
    for (const dfid in data) {
      for (const key in data[dfid].outputs) for (const c of data[dfid].outputs[key].connections) {
        outgoing[dfid]++; incoming[c.node] = (incoming[c.node] || 0) + 1;
      }
    }
    const stateIds = new Set(V.states.map((s) => s.id));
    for (const dfid in data) {
      const m = data[dfid].data.model, p = m.params || {}, id = m.id;
      if (m.kind === 'trigger') {
        if (p.type === 'event' && !byId(evs(), p.event)) add(id, 'err', 'Événement inconnu ou manquant.');
        if (p.type === 'event' && p.event === 'var_changed') {
          if (!p.name) add(id, 'err', '« Une variable change » : choisir la variable.');
          else if (!varDef(p.name)) add(id, 'err', `Variable inconnue : « ${p.name} ».`);
          else if (p.name === 'etat' && (p.value == null || p.value === '')) add(id, 'err', "« Quand etat change » : choisir l'état (la valeur) qui déclenche la chaîne.");
        }
        if (data[dfid].inputs && (data[dfid].inputs.input_1 || { connections: [] }).connections.length) add(id, 'err', NO_TRIGGER_INPUT);
        if (p.type === 'after' && (p.delay === '' || p.delay == null)) add(id, 'err', 'Délai manquant.');
        if (p.type === 'enter' && !stateIds.has(p.state)) add(id, 'err', 'État inconnu.');
        if (!['event', 'after', 'enter'].includes(p.type)) add(id, 'err', 'Type de déclencheur inconnu.');
        if (!outgoing[dfid]) add(id, 'warn', "Ce déclencheur n'a pas de chaîne.");
      } else if (m.kind === 'condition') {
        if (p.type === 'state' && !(p.states || []).length) add(id, 'err', 'Aucun état choisi.');
        if (p.type === 'guard' && !byId(V.guards, p.guard)) add(id, 'err', 'Garde inconnue ou manquante.');
        else if (p.type === 'guard') argIssues(byId(V.guards, p.guard), p.args || {}).forEach((msg) => add(id, 'err', msg));
      } else if (m.kind === 'action') {
        if (!byId(V.actions, p.action)) add(id, 'err', 'Action inconnue ou manquante.');
        else {
          argIssues(byId(V.actions, p.action), p.args || {}).forEach((msg) => add(id, 'err', msg));
          const need = REQUIRED_ARGS[p.action] || [];
          need.forEach((k) => { const v = (p.args || {})[k]; if (v == null || v === '') add(id, 'err', 'À remplir : ' + ((((byId(V.actions, p.action) || {}).args || []).find((x) => x.name === k)) || {}).label + '.'); });
        }
      } else if (m.kind === 'goto') {
        if (!stateIds.has(p.state)) add(id, 'err', "État d'arrivée inconnu.");
      } else if (m.kind === 'state') {
        add(id, 'warn', "Ancien nœud État : il n'est plus utilisé (supprimez-le ; l'état se teste avec « etat = … » et se change avec l'action « Changer d'état »).");
      }
      if (!['start', 'trigger', 'state'].includes(m.kind) && !incoming[dfid]) add(id, 'warn', "Nœud non relié : il serait perdu à l'enregistrement.");
      if (m.kind === 'condition') {
        // Vars L2: an action with an unlinked output ends its chain; a condition needs at least one linked output
        const o1 = data[dfid].outputs.output_1, o2 = data[dfid].outputs.output_2;
        if (!(o1 && o1.connections.length) && !(o2 && o2.connections.length)) add(id, 'warn', 'La condition n’a aucune suite : relier au moins une de ses sorties.');
      }
      if (m.kind === 'action' && p.action === 'set_var' && (p.args || {}).name === 'etat' && p.args.value && !stateIds.has(p.args.value)) add(id, 'err', 'État de destination inconnu.');
      if (m.kind === 'condition') {
        for (const c of (data[dfid].inputs.input_1 || { connections: [] }).connections) {
          const src = data[c.node];
          if (src && src.data.model.kind === 'action') add(id, 'err', 'Une condition ne peut pas suivre une action.');
        }
      }
    }
    globalIssues = [];
    Object.keys(meta.intents || {}).forEach((n) => {
      const it = meta.intents[n] || {};
      if (!INTENT_NAME.test(n)) globalIssues.push({ level: 'err', message: `Intention « ${n} » : nom invalide.` });
      if (!it.words_from && !it.regex && !(it.words || []).length) globalIssues.push({ level: 'warn', message: `Intention « ${n} » : aucun mot (ajoutez au moins un mot ou une expression).` });
    });
    intentErrs = {};
    serverErrors.concat(simErrors).forEach((e) => {
      if (e.intent) { intentErrs[e.intent] = e.message; globalIssues.push({ level: 'err', message: `Intention « ${e.intent} » : ${e.message}` }); }
      else if (e.variable && !(e.node && nidToDf.has(e.node))) globalIssues.push({ level: 'err', message: `Variable « ${e.variable} » : ${e.message}` });
      else if (e.node && nidToDf.has(e.node)) add(e.node, 'err', e.message);
      else globalIssues.push({ level: 'err', message: e.message });
    });
    (fanInfo.warnings || []).forEach((w) => {
      (new Set([w.node].concat(w.nodes || []))).forEach((id) => {
        if (nidToDf.has(id)) add(id, 'warn', id === w.node ? w.message : "Cette destination est en concurrence avec une autre branche du même déclencheur : une seule changera l'état.");
      });
    });
    issues = out;
    for (const dfid in data) markNode(dfid);
    paintOrderBadges();
    scheduleCheck();
    paintChains();
    drawBands();
    paintWires();
    renderMsgs();
  }
  // ---------- branch order (GC2-like: every branch without state change runs, one branch changes the state) ----------
  function scheduleCheck() {
    clearTimeout(checkTimer);
    checkTimer = setTimeout(runCheck, 500);
  }
  async function runCheck() {
    if (!editor || loading) return;
    let doc;
    try { doc = serialize(); } catch (e) { return; }
    const key = JSON.stringify(doc);
    if (key === lastCheckKey) return;              // nothing changed since the last dry run: no loop through analyze()
    lastCheckKey = key;
    const r = await postJson('/api/graph/check', doc);
    if (!r.json || r.status >= 500) return;
    fanInfo = { warnings: r.json.warnings || [], fans: r.json.fans || {} };
    analyze();
  }
  // A small numbered badge on each target of a node with several outgoing links = execution order.
  function paintOrderBadges() {
    document.querySelectorAll('.ordbadge').forEach((e) => e.remove());
    const fans = fanInfo.fans || {};
    for (const tid in fans) {
      const groups = new Map();                    // path prefix -> Map(next node id -> {rank, ignored})
      fans[tid].forEach((b) => {
        for (let i = 0; i < b.nodes.length - 1; i++) {
          const key = b.nodes.slice(0, i + 1).join('>');
          if (!groups.has(key)) groups.set(key, new Map());
          const g = groups.get(key), nx = b.nodes[i + 1], cur = g.get(nx);
          g.set(nx, { rank: cur ? Math.min(cur.rank, b.rank) : b.rank, ignored: cur ? cur.ignored && b.ignored : b.ignored, moves: (cur && cur.moves) || b.moves });
        }
      });
      groups.forEach((g) => {
        if (g.size < 2) return;
        g.forEach((v, nid) => {
          const df = nidToDf.get(nid), el = df != null ? nodeEl(df) : null;
          if (!el) return;
          el.append(h('span', { class: 'ordbadge' + (v.ignored ? ' ign' : ''), title: v.ignored ? "Ordre " + v.rank + " : ignorée, une autre branche change déjà l'état." : 'Ordre d\'exécution ' + v.rank + (v.moves ? ' (change l\'état)' : '') }, String(v.rank)));
        });
      });
    }
  }
  function markNode(dfid) {
    const el = nodeEl(dfid), m = model(dfid);
    if (!el || !m) return;
    const list = issues.get(m.id) || [];
    const hasErr = list.some((i) => i.level === 'err');
    el.classList.toggle('err', hasErr);
    el.classList.toggle('warn', !hasErr && list.some((i) => i.level === 'warn'));
    const msg = el.querySelector('.nmsg');
    if (msg) msg.textContent = list.map((i) => i.message).join(' ');
    el.title = list.map((i) => (i.level === 'err' ? 'Erreur : ' : i.level === 'todo' ? 'À faire : ' : 'Attention : ') + i.message).join('\n');
  }
  function markLive() { drawBands(); }

  function renderMsgs() {
    const box = $('#msgs'), tg = $('#btnMsgs');
    const all = [];
    issues.forEach((list, nid) => list.forEach((i) => all.push({ ...i, nid })));
    globalIssues.forEach((i) => all.push({ ...i, nid: null }));
    const ne = all.filter((i) => i.level === 'err').length, nw = all.length - ne;
    tg.hidden = !all.length;
    tg.textContent = `${ne} erreur(s), ${nw} avertissement(s)`;
    box.innerHTML = '';
    all.sort((a, b) => (a.level === b.level ? 0 : a.level === 'err' ? -1 : 1)).forEach((i) => {
      const m = i.nid ? model(nidToDf.get(i.nid)) : null;
      const where = m ? KINDS[m.kind].label + ' ' + m.id + ' : ' : '';
      box.append(h('div', { class: 'm ' + i.level, onclick: () => i.nid && focusNode(i.nid) }, where + i.message));
    });
    if (!all.length) box.hidden = true;
  }

  // ---------- view ----------
  // Vars L2: a state is a column (automatic frame `auto-<state>`, no hub node). The helpers below keep the old "band"
  // vocabulary for navigation: bandRects() = the column frame when present, else the bounding box of every node whose
  // `group` is that state; used to jump to a state, the minimap and the first view.
  function nodeBox(dfid) {
    const d = dfNode(dfid), el = nodeEl(dfid);
    return { x0: d.pos_x, y0: d.pos_y, x1: d.pos_x + (el ? el.offsetWidth : 214), y1: d.pos_y + (el ? el.offsetHeight : 80) };
  }
  function bandRects() {
    const g = {};
    for (const dfid in dfData()) {
      const m = model(dfid); if (!m.group) continue;
      const b = nodeBox(dfid), r = g[m.group] || (g[m.group] = { x0: 1e9, y0: 1e9, x1: -1e9, y1: -1e9 });
      r.x0 = Math.min(r.x0, b.x0); r.y0 = Math.min(r.y0, b.y0); r.x1 = Math.max(r.x1, b.x1); r.y1 = Math.max(r.y1, b.y1);
    }
    for (const k in g) { g[k].x0 -= 24; g[k].x1 += 24; g[k].y0 -= 48; g[k].y1 += 24; }
    // Vars L2: the automatic column frame of a state (auto-<state>) is the column when the user kept it
    frames().forEach((f) => { if (f.id.startsWith('auto-')) g[f.id.slice(5)] = { x0: f.x, y0: f.y, x1: f.x + f.w, y1: f.y + f.h }; });
    return g;
  }
  // Live robot state / simulated state: the matching automatic column frame `auto-<state>` glows (class live / sim);
  // a legacy state node too.
  function drawBands() {
    if (!editor) return;
    frameEls.forEach((el, fid) => {
      const g = fid.startsWith('auto-') ? fid.slice(5) : null;
      el.classList.toggle('live', !!g && g === liveState);
      el.classList.toggle('sim', !!g && g === simState);
    });
    const data = dfData();
    for (const dfid in data) {
      const m = data[dfid].data.model; if (m.kind !== 'state') continue;
      const el = nodeEl(dfid); if (!el) continue;
      el.classList.toggle('live', m.params.state === liveState);
      el.classList.toggle('sim', m.params.state === simState);
    }
  }

  // ---------- wires: colour gradient from the source kind colour to the target kind colour ----------
  // Drawflow draws every connection as <svg class="connection node_in_node-X node_out_node-Y output_k input_k"><path
  // class="main-path" d="M x1 y1 C ... x2 y2">, in canvas coordinates. A userSpaceOnUse linearGradient from the path's
  // first to its last point (the same space as `d`) follows the wire whatever its shape; it is refreshed whenever
  // Drawflow redraws a node's wires (updateConnectionNodes is wrapped in boot()).
  // INVARIANT (lot L4 fix "wires don't follow a dragged node"): Drawflow 0.0.60 updates a wire by writing `d` into
  // `svg.children[0]` (updateConnectionNodes, updateConnection, reroute code) instead of looking up `.main-path`. The
  // gradient <defs> is therefore APPENDED after the path; inserted first (as in L3) it received every new `d` and the
  // visible path froze at its first shape while its node moved.
  const KIND_HEX = { start: '#2ea043', end: '#e5534b', trigger: '#e3b341', action: '#4f8ef7', condition: '#56d364', state: '#a371f7', goto: '#a371f7' };
  let gradSeq = 0;
  function paintWires(only) {
    if (!editor || !editor.container) return;
    const data = dfData();
    const sel = only ? `svg.connection.node_in_${only}, svg.connection.node_out_${only}` : 'svg.connection';
    editor.container.querySelectorAll(sel).forEach((svg) => {
      const cl = svg.classList;
      if (cl.length < 5) return;
      const inId = cl[1].slice(13), outId = cl[2].slice(14), path = svg.querySelector('.main-path');
      const a = data[outId], b = data[inId];
      if (!path || !a || !b) return;
      const nums = (path.getAttribute('d') || '').match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/g);
      if (!nums || nums.length < 4) return;
      let x1 = +nums[0], y1 = +nums[1], x2 = +nums[nums.length - 2], y2 = +nums[nums.length - 1];
      if (x1 === x2 && y1 === y2) x2 += 1;
      let g = svg.querySelector('linearGradient');
      if (!g) {
        const NS = 'http://www.w3.org/2000/svg';
        const defs = document.createElementNS(NS, 'defs');
        g = document.createElementNS(NS, 'linearGradient');
        g.id = 'wg' + (++gradSeq);
        g.setAttribute('gradientUnits', 'userSpaceOnUse');
        g.append(document.createElementNS(NS, 'stop'), document.createElementNS(NS, 'stop'));
        defs.append(g); svg.append(defs);   // L4: AFTER the path, Drawflow writes `d` into svg.children[0]
      }
      g.setAttribute('x1', x1); g.setAttribute('y1', y1); g.setAttribute('x2', x2); g.setAttribute('y2', y2);
      const stops = g.querySelectorAll('stop');
      stops[0].setAttribute('offset', '0'); stops[0].setAttribute('stop-color', KIND_HEX[a.data.model.kind] || '#8b949e');
      stops[1].setAttribute('offset', '1'); stops[1].setAttribute('stop-color', KIND_HEX[b.data.model.kind] || '#8b949e');
      path.style.stroke = `url(#${g.id})`;
      // L7: "returning" wires (into a state hub, or from a hub to another column) are drawn faded by default
      const am = a.data.model, bm = b.data.model;
      cl.toggle('ret', (bm.kind === 'state' && am.kind !== 'start') || (am.kind === 'state' && am.group !== bm.group));
      svg.dataset.src = am.id; svg.dataset.dst = bm.id;
      const idx = +cl[3].split('_')[1], port = a.data.model.kind === 'condition' ? (idx === 1 ? 'true' : 'false') : 'out';
      const mt = linkMeta.get(linkKey(a.data.model.id, port, b.data.model.id));
      let t = path.querySelector('title');
      if (mt && mt.reason) { if (!t) { t = document.createElementNS('http://www.w3.org/2000/svg', 'title'); path.append(t); } t.textContent = 'Raison : ' + mt.reason; }
      else if (t) t.remove();
    });
    scheduleBadges();
    applyRetFocus();
  }

  // Lot L3: the wire being dragged out of a port (Drawflow's `connection_ele`, classes "connection" only until it is
  // dropped) gets the same gradient: it STARTS with the source node's kind colour (green for a condition, whatever
  // its port: the red / green pastille of Vrai / Faux is only a port marker) and ends with the colour of the node
  // under the pointer, or the source colour while it hangs in the void. Called on connectionStart and on every
  // Drawflow updateConnection (pointer move); paintWires() takes over once the wire is linked.
  let dragSrcKind = null;
  function paintDragWire(clientX, clientY) {
    const svg = editor && editor.connection_ele;
    if (!svg || !dragSrcKind) return;
    const path = svg.querySelector('.main-path');
    const nums = path && (path.getAttribute('d') || '').match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/g);
    const NS = 'http://www.w3.org/2000/svg';
    let g = svg.querySelector('linearGradient');
    if (!g) {
      const defs = document.createElementNS(NS, 'defs');
      g = document.createElementNS(NS, 'linearGradient');
      g.id = 'wg' + (++gradSeq);
      g.setAttribute('gradientUnits', 'userSpaceOnUse');
      g.append(document.createElementNS(NS, 'stop'), document.createElementNS(NS, 'stop'));
      defs.append(g); svg.append(defs);     // L4: after the path (Drawflow's updateConnection writes children[0])
    }
    if (nums && nums.length >= 4) {
      let x2 = +nums[nums.length - 2];
      if (+nums[0] === x2 && +nums[1] === +nums[nums.length - 1]) x2 += 1;
      g.setAttribute('x1', nums[0]); g.setAttribute('y1', nums[1]); g.setAttribute('x2', x2); g.setAttribute('y2', nums[nums.length - 1]);
    }
    let dst = dragSrcKind;
    if (clientX != null) {
      const el = document.elementFromPoint(clientX, clientY);
      const ne = el && el.closest && el.closest('.drawflow-node');
      const m = ne ? model(ne.id.replace('node-', '')) : null;
      if (m) dst = m.kind;
    }
    const stops = g.querySelectorAll('stop');
    stops[0].setAttribute('offset', '0'); stops[0].setAttribute('stop-color', KIND_HEX[dragSrcKind] || '#8b949e');
    stops[1].setAttribute('offset', '1'); stops[1].setAttribute('stop-color', KIND_HEX[dst] || '#8b949e');
    if (path) path.style.stroke = `url(#${g.id})`;
  }

  // ---------- returning wires: faded by default, "→ État" proxy badges, focus on hover / selection (L7) ----------
  // LEGACY (L6/L7 hub drawing; Vars L2 draws no hub, so nothing below fires on a current document): a wire that ends
  // in a state hub was drawn at ~12 % opacity (CSS `svg.connection.ret`); each chain end got a small badge "→ <État>"
  // right of its last node instead (click = pan to the hub). Hovering or selecting a node, hub,
  // wire or badge lights the related returning wires (class `rel`, full gradient) and fades the others
  // (container class `retfocus`). Pure drawing: nothing here is saved.
  let badgesEl = null, badgeRaf = 0, retHover = null;
  const RET_KEY = 'nanterino.editor.retWires';
  function retVisible() { try { return localStorage.getItem(RET_KEY) === 'visible'; } catch (e) { return false; } }
  function setRetVisible(on) {
    try { localStorage.setItem(RET_KEY, on ? 'visible' : 'discret'); } catch (e) { /* private window: per page only */ }
    document.body.classList.toggle('ret-visible', on);
    const b = $('#btnRet'); if (b) b.textContent = 'Fils de retour : ' + (on ? 'visibles' : 'discrets');
  }
  function scheduleBadges() { if (!badgeRaf) badgeRaf = requestAnimationFrame(() => { badgeRaf = 0; drawBadges(); }); }
  function drawBadges() {
    if (!editor || !editor.precanvas) return;
    if (!badgesEl || !badgesEl.isConnected) { badgesEl = h('div', { id: 'rbadges' }); editor.precanvas.append(badgesEl); }
    badgesEl.innerHTML = '';
    const stack = new Map();
    editor.container.querySelectorAll('svg.connection.ret').forEach((svg) => {
      const src = svg.dataset.src, dst = svg.dataset.dst, sd = nidToDf.get(src), dd = nidToDf.get(dst);
      if (sd == null || dd == null) return;
      const dm = model(dd), sm = model(sd);
      if (!dm || dm.kind !== 'state' || !sm || sm.kind === 'state' || sm.kind === 'start') return;   // badge only for a chain end -> hub
      const b = nodeBox(sd), k = stack.get(src) || 0; stack.set(src, k + 1);
      const st = dm.params.state;
      const el = h('div', { class: 'rbadge', 'data-src': src, 'data-dst': dst, title: 'Retour vers l’état « ' + stateLabel(st) + ' » (clic : y aller)',
        style: `left:${b.x1 + 14}px;top:${(b.y0 + b.y1) / 2 - 12 + k * 28}px;--c:${stateColor(st)}` }, ico(stateIcon(st), stateColor(st)), h('span', {}, '→ ' + stateLabel(st)));
      el.addEventListener('mousedown', (e) => e.stopPropagation());   // no canvas pan from a badge
      el.addEventListener('click', (e) => { e.stopPropagation(); panTo(dst, 0.5); const he = nodeEl(dd); if (he) { he.classList.remove('blink'); void he.offsetWidth; he.classList.add('blink'); setTimeout(() => he.classList.remove('blink'), 2000); } });
      badgesEl.append(el);
    });
  }
  // Model ids of the chains that contain `nid` (from the analysed document), plus nid itself.
  function chainIdsOf(nid) {
    const out = new Set([nid]);
    try { const ch = computeChains(serialize()); ch.keys.forEach((ids) => { if (ids.includes(nid)) ids.forEach((x) => out.add(x)); }); } catch (e) { /* half-built doc */ }
    return out;
  }
  // Focus source: hovered thing first, else the selected node / wire. Returns a predicate on (src, dst) or null.
  function retFocusPred() {
    let f = retHover;
    if (!f && selDf != null && model(selDf)) f = { node: model(selDf).id };
    if (!f && editor && editor.connection_selected) { const svg = editor.connection_selected.closest && editor.connection_selected.closest('svg.connection'); if (svg && svg.dataset.src) f = { wire: [svg.dataset.src, svg.dataset.dst] }; }
    if (!f) return null;
    const kindOf = (id) => { const d = nidToDf.get(id); const m = d == null ? null : model(d); return m ? m.kind : null; };
    if (f.node && kindOf(f.node) === 'state') { const s = f.node; return (a, b) => a === s || b === s; }
    const seed = f.node || (kindOf(f.wire[0]) === 'state' ? f.wire[1] : f.wire[0]);
    const R = chainIdsOf(seed);
    return (a, b) => (f.wire && a === f.wire[0] && b === f.wire[1]) || (R.has(a) && kindOf(a) !== 'state') || (R.has(b) && kindOf(b) !== 'state');
  }
  function applyRetFocus() {
    if (!editor || !editor.container) return;
    const pred = retFocusPred();
    editor.container.classList.toggle('retfocus', !!pred);
    editor.container.querySelectorAll('svg.connection').forEach((svg) => svg.classList.toggle('rel', !!pred && svg.classList.contains('ret') && pred(svg.dataset.src, svg.dataset.dst)));
    if (badgesEl) badgesEl.querySelectorAll('.rbadge').forEach((el) => el.classList.toggle('rel', !!pred && pred(el.dataset.src, el.dataset.dst)));
  }
  function installRetHover() {
    const root = editor.container;
    root.addEventListener('mouseover', (e) => {
      const t = e.target, bd = t.closest && t.closest('.rbadge'), nd = !bd && t.closest && t.closest('.drawflow-node'), w = !bd && !nd && t.closest && t.closest('svg.connection');
      const next = bd ? { wire: [bd.dataset.src, bd.dataset.dst] } : nd ? { node: nidOf(nd.id.replace('node-', '')) } : w && w.dataset.src ? { wire: [w.dataset.src, w.dataset.dst] } : null;
      if (JSON.stringify(next) !== JSON.stringify(retHover)) { retHover = next; applyRetFocus(); }
    });
    root.addEventListener('mouseleave', () => { if (retHover) { retHover = null; applyRetFocus(); } });
    // selection changes arrive through Drawflow's own click handling: re-evaluate just after it
    editor.container.addEventListener('mouseup', () => setTimeout(applyRetFocus, 0));
  }

  // ---------- overview helpers (L7 fix round): zoom-scaled frame titles, semantic zoom, jump bar, minimap ----------
  // --fts on precanvas = scale of the automatic frame titles so they never get smaller than ~14 px on screen;
  // below SEM_ZOOM the container gets `semzoom`: each column shows a big card (state, chain count, in/out wires)
  // and the nodes fade. Jump bar chips and the minimap live inside #drawflow but stop their own presses (no pan).
  const SEM_ZOOM = 0.25;
  let jumpEl = null, miniEl = null, miniRaf = 0;
  const MINI_KEY = 'nanterino.editor.minimap';
  function zoomVars() {
    if (!editor || !editor.precanvas) return;
    const z = editor.zoom || 1;
    editor.precanvas.style.setProperty('--fts', String(Math.max(1, 14 / (13 * z))));
    editor.container.classList.toggle('semzoom', z < SEM_ZOOM);
    scheduleMinimap();
  }
  const stopPress = (el) => ['mousedown', 'touchstart', 'pointerdown', 'wheel', 'dblclick'].forEach((t) => el.addEventListener(t, (e) => e.stopPropagation(), { passive: true }));
  // Fit one state column (its band rect) at a readable zoom 0.6-0.8, top of the column (hub) in view.
  function focusColumn(g) {
    const r = bandRects()[g], c = $('#drawflow'); if (!r) return false;
    const w = r.x1 - r.x0, hh = r.y1 - r.y0;
    const z = Math.max(0.6, Math.min(0.8, c.clientWidth / (w * 1.05), c.clientHeight / (hh * 1.05)));
    const cx = w * z <= c.clientWidth ? (c.clientWidth - w * z) / 2 - r.x0 * z : 20 - r.x0 * z;
    setView(z, cx, 50 - r.y0 * z);          // 50: below the jump bar
    return true;
  }
  function drawJumpbar() {
    if (!editor) return;
    if (!jumpEl || !jumpEl.isConnected) { jumpEl = h('div', { id: 'jumpbar', role: 'toolbar', 'aria-label': 'Aller à un état' }); stopPress(jumpEl); editor.container.append(jumpEl); }
    jumpEl.innerHTML = '';
    const groups = new Set(Object.values(dfData()).map((d) => d.data.model.group).filter(Boolean));
    (meta.states || []).forEach((s) => {
      if (!groups.has(s.id)) return;
      jumpEl.append(h('button', { type: 'button', class: 'jchip', 'data-g': s.id, title: 'Aller à la colonne « ' + stateLabel(s.id) + ' »', style: '--c:' + stateColor(s.id),
        onclick: () => focusColumn(s.id) }, ico(stateIcon(s.id), stateColor(s.id)), stateLabel(s.id)));
    });
    if (groups.has('global')) jumpEl.append(h('button', { type: 'button', class: 'jchip', 'data-g': 'global', title: 'Aller aux règles globales', style: '--c:#e0504d', onclick: () => focusColumn('global') }, ico('git-branch', '#e0504d'), 'Globales'));
  }
  function miniOpen() { try { return localStorage.getItem(MINI_KEY) !== 'closed'; } catch (e) { return true; } }
  function scheduleMinimap() { if (!miniRaf) miniRaf = requestAnimationFrame(() => { miniRaf = 0; drawMinimap(); }); }
  function drawMinimap() {
    if (!editor || !editor.container) return;
    if (!miniEl || !miniEl.isConnected) {
      const cv = h('canvas', { width: 200, height: 130, 'aria-label': 'Carte du graphe (clic : y aller)' });
      const tog = h('button', { type: 'button', class: 'mtog', title: 'Afficher / masquer la carte' });
      miniEl = h('div', { id: 'minimap' }, tog, cv);
      stopPress(miniEl);
      tog.onclick = () => { const open = !miniEl.classList.contains('open'); try { localStorage.setItem(MINI_KEY, open ? 'open' : 'closed'); } catch (e) { /* per page */ } miniEl.classList.toggle('open', open); drawMinimap(); };
      cv.addEventListener('click', (e) => {
        const m = miniEl._map; if (!m) return;
        const r = cv.getBoundingClientRect(), x = m.x0 + (e.clientX - r.x) / m.s, y = m.y0 + (e.clientY - r.y) / m.s;
        focusRect({ x0: x, y0: y, x1: x, y1: y }, editor.zoom);
      });
      miniEl.classList.toggle('open', miniOpen());
      editor.container.append(miniEl);
    }
    miniEl.querySelector('.mtog').textContent = miniEl.classList.contains('open') ? '▾ Carte' : '▸ Carte';
    if (!miniEl.classList.contains('open')) return;
    const cv = miniEl.querySelector('canvas'), ctx2 = cv.getContext('2d');
    const rects = Object.entries(bandRects()), b = bbox();
    if (!b) return;
    const pad = 30, x0 = b.x0 - pad, y0 = b.y0 - pad, s = Math.min(cv.width / (b.x1 - b.x0 + 2 * pad), cv.height / (b.y1 - b.y0 + 2 * pad));
    miniEl._map = { x0, y0, s };
    ctx2.clearRect(0, 0, cv.width, cv.height);
    ctx2.fillStyle = '#0d1117cc'; ctx2.fillRect(0, 0, cv.width, cv.height);
    rects.forEach(([g, r]) => { ctx2.fillStyle = stateColor(g) + '88'; ctx2.fillRect((r.x0 - x0) * s, (r.y0 - y0) * s, (r.x1 - r.x0) * s, (r.y1 - r.y0) * s); });
    const st = editor.container.getBoundingClientRect(), a = canvasPoint(st.x, st.y), c = canvasPoint(st.right, st.bottom);
    ctx2.strokeStyle = '#ffffff'; ctx2.lineWidth = 1.5;
    ctx2.strokeRect((a.x - x0) * s, (a.y - y0) * s, (c.x - a.x) * s, (c.y - a.y) * s);
  }
  // Semantic-zoom card of an automatic frame: state name, chain count, wires in / out of the column.
  function frameCard(f) {
    const g = f.id.startsWith('auto-') ? f.id.slice(5) : null; if (!g) return null;
    let chains = 0, inn = 0, out = 0;
    const data = dfData();
    // Vars L2: in = state changes to this state made by other columns, out = state changes made here to another state
    for (const id in data) {
      const m = data[id].data.model, p = m.params || {};
      if (m.group === g && m.kind === 'trigger') chains++;
      if (m.kind === 'action' && p.action === 'set_var' && (p.args || {}).name === 'etat') {
        const to = p.args.value;
        if (to === g && m.group !== g) inn++;
        if (m.group === g && to !== g) out++;
      }
    }
    return h('div', { class: 'fcard' }, h('div', { class: 'fcname' }, f.title || g), h('div', { class: 'fcstat' }, chains + ' chaîne' + (chains > 1 ? 's' : '') + ' · ↘ ' + inn + ' entrant' + (inn > 1 ? 's' : '') + ' · ↗ ' + out + ' sortant' + (out > 1 ? 's' : '')));
  }
  // Pan / zoom to a chain: its non-hub nodes at ~0.75, or the whole chain when larger (zoom >= 0.3).
  function focusChainIds(ids) {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    (ids || []).forEach((nid) => { const d = nidToDf.get(nid); const m = d == null ? null : model(d); if (!m || m.kind === 'state') return; const b = nodeBox(d); x0 = Math.min(x0, b.x0); y0 = Math.min(y0, b.y0); x1 = Math.max(x1, b.x1 + 120); y1 = Math.max(y1, b.y1); });
    if (x0 > x1) { const first = (ids || [])[0]; if (first) panTo(first, 0.75); return; }
    const c = $('#drawflow'), w = x1 - x0, hh = y1 - y0;
    const z = Math.max(0.3, Math.min(0.75, c.clientWidth / (w * 1.15), (c.clientHeight - 50) / (hh * 1.15)));
    setView(z, c.clientWidth / 2 - ((x0 + x1) / 2) * z, 25 + c.clientHeight / 2 - ((y0 + y1) / 2) * z);
  }
  // ---------- groups (cosmetic frames, "Groupe") ----------
  // meta.frames = [{id, title, color, x, y, w, h, note?}] lives in the document (serialize() copies meta), so undo/redo,
  // dirty tracking and Enregistrer cover it for free. The server stores it only in graph.layout.json: it is never
  // compiled into graph.yaml. Drawn in a #frames layer inside precanvas (so pan/zoom apply), after #bands and before
  // the nodes; only the title bar and the resize handle take pointer events, the rest lets clicks reach the canvas.
  const FRAME_COLORS = [['Jaune', '#e3b341'], ['Bleu', '#4f8ef7'], ['Vert', '#56d364'], ['Rouge', '#e5534b'],
    ['Violet', '#a371f7'], ['Orange', '#f0883e'], ['Gris', '#8b949e'], ['Cyan', '#39c5cf']];
  const FRAME_PAD = { l: 32, r: 32, t: 72, b: 32 };      // around a node box; t leaves room for the 30 px title bar and the band title
  let selFrame = null;
  let framesEl = null;
  let frameDrag = null;
  const frameEls = new Map();
  const frames = () => (meta.frames = Array.isArray(meta.frames) ? meta.frames : []);
  const frameById = (id) => frames().find((f) => f.id === id);
  function ensureFrames() {
    if (!framesEl || !framesEl.isConnected) { framesEl = h('div', { id: 'frames' }); editor.precanvas.insertBefore(framesEl, editor.precanvas.firstChild); }
    return framesEl;
  }
  // Readable text colour on a frame colour (#rrggbb).
  function inkOn(hex) {
    const n = parseInt(hex.slice(1), 16), lum = 0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255);
    return lum > 150 ? '#10141a' : '#ffffff';
  }
  function placeFrame(f, el) {
    el.style.cssText = `--c:${f.color};--ink:${inkOn(f.color)};left:${f.x}px;top:${f.y}px;width:${f.w}px;height:${f.h}px`;
  }
  function drawFrames() {
    if (!editor) return;
    const root = ensureFrames(); root.innerHTML = ''; frameEls.clear();
    frames().forEach((f) => {
      const text = h('span', { class: 'ftext' }, f.title || '(sans nom)');
      if (!f.title) text.classList.add('empty');
      const title = h('div', { class: 'ftitle', title: 'Glisser pour déplacer le groupe et ses nœuds. Double-clic pour renommer.' }, ico('square'), text);
      const grip = h('div', { class: 'fresize', title: 'Redimensionner' });
      const el = h('div', { class: 'frame' + (f.auto ? ' auto' : '') + (f.id === selFrame ? ' sel' : ''), 'data-fid': f.id }, title, grip);
      placeFrame(f, el);
      if (f.auto) { const card = frameCard(f); if (card) el.append(card); }   // semantic-zoom card (CSS shows it below 0.25)
      for (const part of [title, grip]) {
        part.addEventListener('mousedown', (e) => startFrameDrag(e, f, part === grip ? 'resize' : 'move'));
        part.addEventListener('touchstart', (e) => startFrameDrag(e, f, part === grip ? 'resize' : 'move'), { passive: false });
      }
      title.addEventListener('dblclick', (e) => { e.stopPropagation(); editFrameTitle(f); });
      frameEls.set(f.id, el);
      root.append(el);
    });
    drawBands();             // live / simulated state glow on the auto column frames
  }
  function clearNodeSelection() {
    if (editor.node_selected) { editor.node_selected.classList.remove('selected'); editor.node_selected = null; }
    selDf = null;
  }
  function selectFrame(id) {
    if (selFrame === id) return;
    clearNodeSelection();
    if (selNote) { selNote = null; noteEls.forEach((el) => el.classList.remove('sel')); }
    selFrame = id;
    drawFrames(); renderInspector();
    if (id && innerWidth <= 900) document.body.classList.remove('hide-right');
  }
  function unselectFrame() { if (selFrame) { selFrame = null; drawFrames(); renderInspector(); } }
  const evPoint = (e) => (e.touches && e.touches[0]) || (e.changedTouches && e.changedTouches[0]) || e;
  function startFrameDrag(e, f, mode) {
    if (e.button) return;                 // left button / touch only
    e.stopPropagation(); e.preventDefault();   // Drawflow must not pan the canvas or select a node
    selectFrame(f.id);
    const p = evPoint(e), ctr = (b) => [(b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2];
    const inside = (cx, cy) => cx >= f.x && cx <= f.x + f.w && cy >= f.y && cy <= f.y + f.h;
    frameDrag = { f, mode, cx: p.clientX, cy: p.clientY, ox: f.x, oy: f.y, ow: f.w, oh: f.h, moved: false, nodes: [], frames: [] };
    if (mode === 'move') {
      // Nodes whose centre lies in the frame at drag start follow it (and so do the frames wholly centred inside).
      frameDrag.nodes = Object.keys(dfData()).filter((dfid) => inside(...ctr(nodeBox(dfid))))
        .map((dfid) => ({ dfid, x: dfNode(dfid).pos_x, y: dfNode(dfid).pos_y }));
      frameDrag.frames = frames().filter((g) => g !== f && inside(g.x + g.w / 2, g.y + g.h / 2)).map((g) => ({ g, x: g.x, y: g.y }));
    }
  }
  function moveFrameDrag(e) {
    const d = frameDrag; if (!d) return;
    if (e.cancelable) e.preventDefault();
    const p = evPoint(e), dx = (p.clientX - d.cx) / editor.zoom, dy = (p.clientY - d.cy) / editor.zoom;
    if (!d.moved && Math.hypot(p.clientX - d.cx, p.clientY - d.cy) < 3) return;   // a click is not a move
    d.moved = true;
    const f = d.f;
    if (d.mode === 'resize') { f.w = Math.max(80, Math.round(d.ow + dx)); f.h = Math.max(60, Math.round(d.oh + dy)); }
    else {
      f.x = Math.round(d.ox + dx); f.y = Math.round(d.oy + dy);
      d.nodes.forEach((n) => {
        const nd = dfNode(n.dfid), el = nodeEl(n.dfid);
        nd.pos_x = n.x + dx; nd.pos_y = n.y + dy;
        if (el) { el.style.left = nd.pos_x + 'px'; el.style.top = nd.pos_y + 'px'; }
        editor.updateConnectionNodes('node-' + n.dfid);
      });
      d.frames.forEach((o) => { o.g.x = Math.round(o.x + dx); o.g.y = Math.round(o.y + dy); const el = frameEls.get(o.g.id); if (el) placeFrame(o.g, el); });
    }
    const el = frameEls.get(f.id); if (el) placeFrame(f, el);
  }
  function endFrameDrag() {
    const d = frameDrag; if (!d) return;
    frameDrag = null;
    if (!d.moved) return;
    drawBands(); drawFrames(); renderInspector();
    commitSoon();
  }
  function editFrameTitle(f) {
    const el = frameEls.get(f.id), t = el && el.querySelector('.ftext'); if (!t) return;
    const inp = h('input', { class: 'finput', type: 'text', maxlength: 60 });
    inp.value = f.title;
    t.replaceWith(inp); inp.focus(); inp.select();
    let done = false;
    const fin = (ok) => {
      if (done) return; done = true;
      if (ok && inp.value !== f.title) { f.title = inp.value.slice(0, 60); commitSoon(); }
      drawFrames(); renderInspector(); renderPalette();
    };
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') fin(true); else if (e.key === 'Escape') fin(false); });
    inp.addEventListener('blur', () => fin(true));
    for (const ev of ['mousedown', 'dblclick']) inp.addEventListener(ev, (e) => e.stopPropagation());
  }
  function editFrame(f, patch, rerender) {
    Object.assign(f, patch);
    if (f.note === '' || f.note == null) delete f.note;
    drawFrames(); renderPalette();
    if (rerender) renderInspector();
    commitSoon();
  }
  function deleteFrame(id) {
    if (editBlocked()) return;
    meta.frames = frames().filter((f) => f.id !== id);
    if (selFrame === id) selFrame = null;
    drawFrames(); renderInspector(); renderPalette();
    commitSoon();
  }
  // "Groupe" / key G: a frame around the selected node's chain(s) (Drawflow selects one node at a time, so the
  // whole rule it belongs to is wrapped), else a default box at the visible centre.
  function addFrame(at) {
    if (editBlocked()) return null;
    let b = null;
    if (!at && selDf != null && dfNode(selDf)) {
      const nid = nidOf(selDf), ids = new Set([nid]);
      try { computeChains(serialize()).keys.forEach((arr) => { if (arr.includes(nid)) arr.forEach((i) => ids.add(i)); }); } catch (e) { /* keep the single node */ }
      ids.forEach((i) => {
        const dfid = nidToDf.get(i); if (dfid == null) return;
        if (i !== nid && model(dfid).kind === 'state') return;   // a chain's source / target state hubs stay outside its group
        const nb = nodeBox(dfid);
        b = b ? { x0: Math.min(b.x0, nb.x0), y0: Math.min(b.y0, nb.y0), x1: Math.max(b.x1, nb.x1), y1: Math.max(b.y1, nb.y1) } : nb;
      });
    }
    let x, y, w, hh;
    if (b) { x = b.x0 - FRAME_PAD.l; y = b.y0 - FRAME_PAD.t; w = b.x1 - b.x0 + FRAME_PAD.l + FRAME_PAD.r; hh = b.y1 - b.y0 + FRAME_PAD.t + FRAME_PAD.b; }
    else {
      const st = $('#stage').getBoundingClientRect(), c = at && typeof at.x === 'number' && !at.target ? at : canvasPoint(st.x + st.width / 2, st.y + st.height / 2);
      w = 420; hh = 260; x = at ? c.x : c.x - w / 2; y = at ? c.y : c.y - hh / 2;   // at a given point: top-left corner there
    }
    const used = new Set(frames().map((f) => f.id));
    let k = 1; while (used.has('f' + k)) k++;
    const f = { id: 'f' + k, title: 'Groupe ' + (frames().length + 1), color: FRAME_COLORS[frames().length % FRAME_COLORS.length][1],
      x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(hh) };
    frames().push(f);
    selFrame = null; selectFrame(f.id);
    renderPalette(); commitSoon();
  }
  function focusFrame(id) {
    const f = frameById(id); if (!f) return;
    focusRect({ x0: f.x, y0: f.y, x1: f.x + f.w, y1: f.y + f.h });
    selectFrame(id);
  }
  function renderFrameInspector(box, f) {
    box.append(h('div', { class: 'insttitle' }, ico('square', f.color), 'Groupe', h('small', { class: 'hint' }, f.id)));
    const name = textCtl(f.title, (v) => editFrame(f, { title: v.slice(0, 60) }));
    name.maxLength = 60;
    box.append(field('Nom', name));
    const sw = h('div', { class: 'swatches' });
    FRAME_COLORS.forEach(([n, c]) => sw.append(h('button', { type: 'button', class: 'sw' + (c === f.color ? ' on' : ''), title: n, 'aria-label': n,
      style: 'background:' + c, onclick: () => editFrame(f, { color: c }, true) })));
    const custom = h('input', { type: 'color', class: 'swc', title: 'Couleur personnalisée' });
    custom.value = f.color;
    custom.addEventListener('change', () => editFrame(f, { color: custom.value.toLowerCase() }, true));
    sw.append(custom);
    box.append(h('div', { class: 'fld' }, h('span', {}, 'Couleur'), sw));
    box.append(field('Note', areaCtl(f.note || '', (v) => editFrame(f, { note: v }), 2000), 'Texte libre, purement décoratif : le robot ne le lit pas.'));
    box.append(h('p', { class: 'hint' }, 'Un groupe ne change rien au comportement du robot : il sert seulement à ranger le graphe. Glisser la barre de titre déplace aussi les nœuds qu’il contient.'));
    box.append(h('button', { type: 'button', class: 'danger', onclick: () => deleteFrame(f.id) }, 'Supprimer le groupe (les nœuds restent)'));
  }

  function bbox() {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const dfid in dfData()) { const b = nodeBox(dfid); x0 = Math.min(x0, b.x0); y0 = Math.min(y0, b.y0); x1 = Math.max(x1, b.x1); y1 = Math.max(y1, b.y1); }
    return x0 > x1 ? null : { x0, y0, x1, y1 };
  }
  function fitZoom() {
    const b = bbox(), c = $('#drawflow');
    if (!b) return 1;
    // L7: the column layout is wide (~14 000 px): allow a smaller zoom so "Ajuster" really shows everything
    return Math.max(0.02, Math.min(1, c.clientWidth / ((b.x1 - b.x0) * 1.1), c.clientHeight / ((b.y1 - b.y0) * 1.1)));
  }
  // "Ajuster": whole graph, centred, ~5 % padding each side.
  function fit() {
    const b = bbox(), c = $('#drawflow');
    if (!b) return;
    const w = b.x1 - b.x0, hh = b.y1 - b.y0, top = 44;   // L7 fix round: leave the jump bar row free
    const z = Math.min(fitZoom(), (c.clientHeight - top) / (hh * 1.08));
    setView(z, (c.clientWidth - w * z) / 2 - b.x0 * z, top + (c.clientHeight - top - hh * z) / 2 - b.y0 * z);
  }
  // Jump to a state band: fit it to the canvas (or use a fixed readable zoom when given).
  function focusRect(r, zoom) {
    const c = $('#drawflow');
    const w = r.x1 - r.x0, hh = r.y1 - r.y0;
    const z = zoom || Math.max(0.1, Math.min(1, c.clientWidth / (w * 1.05), c.clientHeight / (hh * 1.05)));
    const cx = w * z <= c.clientWidth ? (c.clientWidth - w * z) / 2 - r.x0 * z : 20 - r.x0 * z;
    const cy = hh * z <= c.clientHeight ? (c.clientHeight - hh * z) / 2 - r.y0 * z : 20 - r.y0 * z;
    setView(z, cx, cy);
    return true;
  }
  function focusBand(gid, zoom) {
    const r = bandRects()[gid];
    return r ? focusRect(r, zoom) : false;
  }
  // First view: the true fit when readable, else a readable zoom on the start state's band.
  function initialView() {
    if (fitZoom() >= 0.5) { fit(); return; }
    // L7 / Vars L2: open on the top-left corner of the start state's column (its first chains) at a readable
    // zoom, so the column titles run along the top of the screen. L4: no Start node, the start state is veille.
    const r = bandRects().veille;
    if (!r) { fit(); return; }
    const x0 = r.x0, z = 0.75;
    setView(z, 16 - x0 * z, 16 - (r.y0 - 30) * z);
  }
  function setView(z, cx, cy) {
    // Drawflow scales around the centre of its canvas (no transform-origin), so convert the wanted
    // top-left based translation: screen = tx + O + z*(p - O)  =>  tx = cx - O*(1 - z).
    const ox = editor.precanvas.clientWidth / 2, oy = editor.precanvas.clientHeight / 2;
    cx -= ox * (1 - z); cy -= oy * (1 - z);
    editor.zoom = z; editor.zoom_last_value = z; editor.canvas_x = cx; editor.canvas_y = cy;
    editor.precanvas.style.transform = `translate(${cx}px, ${cy}px) scale(${z})`;
    zoomVars();
  }
  function focusNode(nid) {
    const dfid = nidToDf.get(nid);
    if (dfid == null) return;
    const d = dfNode(dfid), st = $('#drawflow'), z = Math.max(editor.zoom, 0.6);
    setView(z, st.clientWidth / 2 - (d.pos_x + 107) * z, st.clientHeight / 2 - (d.pos_y + 40) * z);
    selectDf(dfid);
  }
  function canvasPoint(clientX, clientY) {
    const r = editor.precanvas.getBoundingClientRect();
    return { x: (clientX - r.x) / editor.zoom, y: (clientY - r.y) / editor.zoom };
  }

  // ---------- post-it notes ----------
  // meta.notes = [{id, text, color, x, y, w, h, title?}] lives in the document (serialize() copies meta), so undo/redo, the
  // dirty flag and "Enregistrer" cover it. The server keeps it only in graph.layout.json: never compiled. Drawn in a #notes
  // layer inside precanvas (pan/zoom apply), above the frames and wires, below the nodes. Only the left button/primary touch
  // drags or resizes (header = move, corner = resize); the text area edits in place.
  let selNote = null, notesEl = null, noteDrag = null;
  const noteEls = new Map();
  const notes = () => (meta.notes = Array.isArray(meta.notes) ? meta.notes : []);
  const noteById = (id) => notes().find((n) => n.id === id);
  function ensureNotes() {
    if (!notesEl || !notesEl.isConnected) { notesEl = h('div', { id: 'notes' }); editor.precanvas.insertBefore(notesEl, ensureFrames().nextSibling); }
    return notesEl;
  }
  function placeNote(n, el) {
    el.style.cssText = `--c:${n.color};left:${n.x}px;top:${n.y}px;width:${n.w}px;height:${n.h}px`;
  }
  function drawNotes() {
    if (!editor) return;
    const root = ensureNotes(); root.innerHTML = ''; noteEls.clear();
    notes().forEach((n) => {
      const ta = h('textarea', { class: 'ptext', maxlength: 2000, placeholder: 'Écrivez ici…', 'aria-label': 'Texte du post-it' });
      ta.value = n.text || '';
      ta.addEventListener('input', () => { n.text = ta.value; });
      ta.addEventListener('change', () => { n.text = ta.value; commitSoon(); if (selNote === n.id) renderInspector(); });
      ta.addEventListener('focus', () => selectNote(n.id, true));
      const head = h('div', { class: 'phead', title: 'Glisser pour déplacer le post-it' }, ico('message'), h('span', { class: 'ptitle' + (n.title ? '' : ' empty') }, n.title || 'Post-it'),
        h('button', { type: 'button', class: 'pdel', title: 'Supprimer le post-it', 'aria-label': 'Supprimer le post-it',
          onclick: (e) => { e.stopPropagation(); deleteNote(n.id); } }, '×'));
      const grip = h('div', { class: 'presize', title: 'Redimensionner' });
      const el = h('div', { class: 'postit' + (n.id === selNote ? ' sel' : ''), 'data-nid': n.id }, head, ta, grip);
      placeNote(n, el);
      el.addEventListener('mousedown', (e) => { e.stopPropagation(); if (e.button === 0) selectNote(n.id, true); });   // no canvas pan from a note
      // L7: pointer events + pointer capture (mouse, pen and touch alike): the drag keeps receiving its moves
      // even when the pointer leaves the note, and one document-level pointermove/up pair (boot) drives it.
      for (const part of [head, grip]) part.addEventListener('pointerdown', (e) => startNoteDrag(e, n, part === grip ? 'resize' : 'move'));
      head.addEventListener('dblclick', () => { selectNote(n.id); const t = $('#inspector input.ntitleinp'); if (t) t.focus(); });
      noteEls.set(n.id, el);
      root.append(el);
    });
  }
  function selectNote(id, keepFocus) {
    if (selNote === id) return;
    clearNodeSelection();
    if (selFrame) { selFrame = null; drawFrames(); }
    selNote = id;
    noteEls.forEach((el, k) => el.classList.toggle('sel', k === id));
    renderInspector();
    if (id && innerWidth <= 900 && !keepFocus) document.body.classList.remove('hide-right');
  }
  function unselectNote() { if (selNote) { selNote = null; noteEls.forEach((el) => el.classList.remove('sel')); renderInspector(); } }
  function startNoteDrag(e, n, mode) {
    if (e.button || e.isPrimary === false) return;          // left button / primary touch only
    if (e.target.closest && e.target.closest('.pdel')) return;   // the × button keeps its own click
    e.stopPropagation(); e.preventDefault();
    selectNote(n.id, true);
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch (err) { /* synthetic event without a live pointer */ }
    noteDrag = { n, mode, pid: e.pointerId, cx: e.clientX, cy: e.clientY, ox: n.x, oy: n.y, ow: n.w, oh: n.h, moved: false };
  }
  function moveNoteDrag(e) {
    const d = noteDrag; if (!d || (d.pid != null && e.pointerId !== d.pid)) return;
    if (e.cancelable) e.preventDefault();
    const p = evPoint(e), dx = (p.clientX - d.cx) / editor.zoom, dy = (p.clientY - d.cy) / editor.zoom;
    if (!d.moved && Math.hypot(p.clientX - d.cx, p.clientY - d.cy) < 3) return;
    d.moved = true;
    if (d.mode === 'resize') { d.n.w = Math.max(120, Math.round(d.ow + dx)); d.n.h = Math.max(90, Math.round(d.oh + dy)); }
    else { d.n.x = Math.round(d.ox + dx); d.n.y = Math.round(d.oy + dy); }
    const el = noteEls.get(d.n.id); if (el) placeNote(d.n, el);
  }
  function endNoteDrag(e) {
    const d = noteDrag; if (!d || (e && d.pid != null && e.pointerId !== d.pid)) return;
    noteDrag = null;
    if (!d.moved) return;
    {                                 // a note never covers a node: moved or grown onto one, it slides to the nearest free spot
      const p = noteSpot(d.n.x, d.n.y, d.n.w, d.n.h, d.n.id);
      d.n.x = p.x; d.n.y = p.y;
      const el = noteEls.get(d.n.id); if (el) placeNote(d.n, el);
    }
    commitSoon();
  }
  // Nearest position (spiral on a 40 px grid around x, y) where a w x h note touches no node, badge or other note.
  function noteSpot(x, y, w, hh, selfId, okFn) {   // okFn(x, y): extra constraint on a candidate (L4: visible spot)
    const boxes = Object.keys(dfData()).map((id) => nodeBox(id));
    notes().forEach((o) => { if (o.id !== selfId) boxes.push({ x0: o.x, y0: o.y, x1: o.x + o.w, y1: o.y + o.h }); });
    // L7 fix round: keep clear of each hub's wire fan too (from the hub's output port to its first chain layer)
    const bands = bandRects(), data = dfData();
    for (const id in data) {
      const m = data[id].data.model; if (m.kind !== 'state') continue;
      const hb = nodeBox(id), r = bands[m.group];
      boxes.push({ x0: hb.x1, y0: hb.y0, x1: hb.x0 + 330, y1: r ? r.y1 : hb.y1 });
    }
    const M = 18, free = (px, py) => (!okFn || okFn(px, py)) && boxes.every((b) => px + w + M < b.x0 || px > b.x1 + M || py + hh + M < b.y0 || py > b.y1 + M);
    if (free(x, y)) return { x: Math.round(x), y: Math.round(y) };
    for (let r = 1; r <= 60; r++) {
      let best = null;
      for (let i = -r; i <= r; i++) for (let j = -r; j <= r; j++) {
        if (Math.max(Math.abs(i), Math.abs(j)) !== r) continue;
        const px = x + i * 40, py = y + j * 40, dd = Math.hypot(i, j);
        if (free(px, py) && (!best || dd < best[2])) best = [px, py, dd];
      }
      if (best) return { x: Math.round(best[0]), y: Math.round(best[1]) };
    }
    return { x: Math.round(x), y: Math.round(y), free: false };   // nothing free nearby: the caller decides
  }
  function editNote(n, patch, rerender) {
    Object.assign(n, patch);
    if (!n.title) delete n.title;
    const el = noteEls.get(n.id);
    if (el) { placeNote(n, el); const pt = el.querySelector('.ptitle'); pt.textContent = n.title || 'Post-it'; pt.classList.toggle('empty', !n.title); const ta = el.querySelector('textarea'); if (ta.value !== (n.text || '')) ta.value = n.text || ''; }
    renderPalette();
    if (rerender) renderInspector();
    commitSoon();
  }
  function deleteNote(id) {
    if (editBlocked()) return;
    meta.notes = notes().filter((n) => n.id !== id);
    if (selNote === id) selNote = null;
    drawNotes(); renderInspector(); renderPalette();
    commitSoon();
  }
  // New note at a canvas point (default: centre of the view). Returns the note.
  function addNote(pt) {
    if (editBlocked()) return null;
    if (notes().length >= 200) { toast('200 post-it au plus.', 'err'); return null; }
    if (!pt) { const st = $('#stage').getBoundingClientRect(); pt = canvasPoint(st.x + st.width / 2 - 110, st.y + st.height / 2 - 80); }
    const used = new Set(notes().map((n) => n.id));
    let k = 1; while (used.has('p' + k)) k++;
    // L7: auto-placed where it covers no node. L4: preferably where its header can be grabbed (inside the visible
    // stage, below the jump bar); without such a spot the nearest free one is used and the view is panned to it (the
    // default view now starts flush with the first column, so that spot used to sit under the jump bar).
    const stR = $('#stage').getBoundingClientRect(), jb = $('#jumpbar'), pr = editor.precanvas.getBoundingClientRect();
    const top = Math.max(stR.y, jb ? jb.getBoundingClientRect().bottom : stR.y) + 8, z = editor.zoom;
    const visible = (px, py) => { const sx = pr.x + px * z, sy = pr.y + py * z;
      return sx >= stR.x + 8 && sy >= top && sx + 220 * z <= stR.right - 8 && sy + 40 * z <= stR.bottom - 8; };
    const vs = noteSpot(pt.x, pt.y, 220, 160, null, visible);
    const spot = vs.free !== false ? vs : noteSpot(pt.x, pt.y, 220, 160);
    const pan = !visible(spot.x, spot.y);
    const n = { id: 'p' + k, text: '', color: NOTE_COLORS[0][1], x: spot.x, y: spot.y, w: 220, h: 160 };
    notes().push(n);
    if (pan) focusRect({ x0: n.x, y0: n.y, x1: n.x + n.w, y1: n.y + n.h }, editor.zoom);   // same zoom, note centred
    selNote = null; drawNotes(); selectNote(n.id);
    renderPalette(); commitSoon();
    const ta = noteEls.get(n.id) && noteEls.get(n.id).querySelector('textarea'); if (ta) ta.focus();
    return n;
  }
  function focusNoteBox(id) {
    const n = noteById(id); if (!n) return;
    focusRect({ x0: n.x, y0: n.y, x1: n.x + n.w, y1: n.y + n.h }, Math.max(editor.zoom, 0.6));
    selectNote(id);
  }
  function renderNoteInspector(box, n) {
    box.append(h('div', { class: 'insttitle' }, ico('message', n.color), 'Post-it', h('small', { class: 'hint' }, n.id)));
    const t = textCtl(n.title || '', (v) => editNote(n, { title: v.slice(0, 60) }));
    t.maxLength = 60; t.classList.add('ntitleinp');
    box.append(field('Titre (facultatif)', t));
    box.append(field('Texte', areaCtl(n.text || '', (v) => editNote(n, { text: v }), 2000), '2000 caractères au plus. Le robot ne lit jamais les post-it.'));
    const sw = h('div', { class: 'swatches' });
    NOTE_COLORS.forEach(([nm, c]) => sw.append(h('button', { type: 'button', class: 'sw' + (c === n.color ? ' on' : ''), title: nm, 'aria-label': nm, style: 'background:' + c, onclick: () => editNote(n, { color: c }, true) })));
    box.append(h('div', { class: 'fld' }, h('span', {}, 'Couleur'), sw));
    box.append(h('button', { type: 'button', class: 'danger', onclick: () => deleteNote(n.id) }, 'Supprimer le post-it'));
  }

  // ---------- mouse buttons: only the LEFT button grabs anything ----------
  // Middle and right buttons must never start a Drawflow drag (node, wire, canvas pan). A capture listener on window
  // swallows them before Drawflow sees them; the native context menu is replaced by ours (see openCtx).
  function installButtonGuards() {
    const inCanvas = (e) => e.target && e.target.closest && e.target.closest('#drawflow');
    // registered first so it runs before the guard below: any press outside the menu closes it
    window.addEventListener('mousedown', (e) => { if (ctx && !(e.target.closest && e.target.closest('.ctx'))) closeCtx(); }, true);
    window.addEventListener('wheel', () => closeCtx(), true);
    window.addEventListener('blur', () => closeCtx());
    ['mousedown', 'pointerdown', 'mouseup', 'auxclick'].forEach((ev) => window.addEventListener(ev, (e) => {
      if (e.button !== 0 && inCanvas(e)) { if (e.cancelable) e.preventDefault(); e.stopImmediatePropagation(); }
    }, true));
    window.addEventListener('touchstart', (e) => { if (e.touches && e.touches.length > 1 && inCanvas(e)) e.stopImmediatePropagation(); }, true);
    window.addEventListener('contextmenu', (e) => {
      if (e.target.closest && e.target.closest('.ctx')) { e.preventDefault(); return; }
      if (!inCanvas(e)) { return; }
      e.preventDefault(); e.stopImmediatePropagation();
      openContextFor(e);
    }, true);
  }

  // ---------- safe navigation (L8): Space+drag, wheel pan, hand tool (H), lock mode (L), keyboard pan ----------
  // Ways to move the view that can never edit anything, plus a persisted read-only lock:
  //  - Space held (focus not in a text field), the hand tool or the lock: every trusted left press inside the canvas is
  //    taken in the WINDOW CAPTURE phase, before Drawflow / node / frame / post-it / wire handlers, and becomes a plain
  //    view pan (setRawView). The press never reaches them, so nothing can be selected, moved, linked or resized.
  //  - Lock only: a press released without moving still selects the node / wire / post-it under it (replayed as a
  //    synthetic, untrusted press that this interceptor lets through) so the inspector can be READ; inputs are disabled.
  //  - Wheel = pan (Shift = horizontal, trackpad deltaX/deltaY both), Ctrl+wheel / pinch = zoom around the cursor.
  //    Drawflow's own wheel zoom never runs (stopped in the capture phase).
  // Invariants: only trusted events are intercepted (internal helpers such as selectDf() dispatch synthetic presses);
  // every edit entry point (addAt, addFrame, addNote, pasteNode, undo, redo, delete*, palette drop, keys, context menu,
  // inspector inputs) checks editBlocked(); save() checks navLocked only (saving is not an edit of the canvas).
  const LOCK_KEY = 'nanterino.editor.locked';
  const NAV_SKIP = '#jumpbar, #minimap, .ctx, .rbadge';          // overlays that handle their own presses (navigation)
  const RO_PANELS = '#inspector, #intents, #versions, #vars';    // Tester and Journal stay usable (viewing, simulating)
  let navLocked = false, navHand = false, navSpace = false, navPan = null, helpEl = null;
  function editBlocked(quiet) {
    if (!navLocked && !navHand) return false;
    if (!quiet) toast(navLocked ? 'Verrouillé — lecture seule (L pour déverrouiller).' : 'Outil main actif — H pour éditer.', 'err');
    return true;
  }
  const isTyping = (t) => !!(t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable));
  const inCanvasEv = (e) => !!(e.target && e.target.closest && e.target.closest('#drawflow'));
  // Drawflow coordinates (translate is applied around the precanvas centre; see setView for the top-left variant).
  function setRawView(z, cx, cy) {
    editor.zoom = z; editor.zoom_last_value = z; editor.canvas_x = cx; editor.canvas_y = cy;
    editor.precanvas.style.transform = `translate(${cx}px, ${cy}px) scale(${z})`;
    editor.dispatch('translate', { x: cx, y: cy });
    zoomVars();
  }
  function panBy(dx, dy) { setRawView(editor.zoom, editor.canvas_x + dx, editor.canvas_y + dy); }
  // Zoom keeping the canvas point under (clientX, clientY) fixed: precanvas left = B + cx + ox(1 - z), so
  // cx' = cx + clientX - p.x*z' - rect.x + ox(z' - z) (same for y).
  function zoomAt(clientX, clientY, factor) {
    const z = editor.zoom, z2 = Math.min(editor.zoom_max, Math.max(editor.zoom_min, z * factor));
    if (Math.abs(z2 - z) < 1e-6) return;
    const r = editor.precanvas.getBoundingClientRect(), p = canvasPoint(clientX, clientY);
    const ox = editor.precanvas.clientWidth / 2, oy = editor.precanvas.clientHeight / 2;
    setRawView(z2, editor.canvas_x + clientX - p.x * z2 - r.x + ox * (z2 - z), editor.canvas_y + clientY - p.y * z2 - r.y + oy * (z2 - z));
  }
  function zoomCentre(factor) { const r = $('#drawflow').getBoundingClientRect(); zoomAt(r.x + r.width / 2, r.y + r.height / 2, factor); }
  function onNavWheel(e) {
    if (!inCanvasEv(e) || e.target.closest(NAV_SKIP)) return;
    const zoom = e.ctrlKey || e.metaKey;                       // trackpad pinch arrives as ctrlKey wheel
    if (!zoom && e.target.closest('textarea')) return;         // a long post-it text scrolls itself
    e.preventDefault(); e.stopImmediatePropagation();
    closeCtx();
    const k = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
    let dx = e.deltaX * k, dy = e.deltaY * k;
    if (zoom) { zoomAt(e.clientX, e.clientY, Math.exp(-Math.max(-300, Math.min(300, dy)) * 0.002)); return; }
    if (e.shiftKey && !dx) { dx = dy; dy = 0; }
    panBy(-dx, -dy);
  }
  const navMode = () => navSpace || navHand || navLocked;
  function evPt(e) { return e.touches ? (e.touches[0] || e.changedTouches[0]) : e; }
  function onNavDown(e) {
    if (!e.isTrusted || !inCanvasEv(e)) return;
    if (navPan) { if (e.cancelable) e.preventDefault(); e.stopImmediatePropagation(); return; }   // same press, other event type
    if (!navMode() || e.target.closest(NAV_SKIP)) return;
    if (e.type === 'touchstart' ? e.touches.length !== 1 : e.button !== 0) return;          // other buttons: installButtonGuards
    if (e.cancelable) e.preventDefault();
    e.stopImmediatePropagation();
    const p = evPt(e);
    navPan = { x: p.clientX, y: p.clientY, cx: editor.canvas_x, cy: editor.canvas_y, moved: false, target: e.target, select: navLocked && !navHand && !navSpace };
    document.body.classList.add('nav-panning');
    $('#drawflow').focus({ preventScroll: true });
  }
  function onNavMove(e) {
    if (!navPan) return;
    const p = evPt(e); if (!p) return;
    const dx = p.clientX - navPan.x, dy = p.clientY - navPan.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) navPan.moved = true;
    if (navPan.moved) setRawView(editor.zoom, navPan.cx + dx, navPan.cy + dy);
    if (e.cancelable) e.preventDefault();
    e.stopImmediatePropagation();
  }
  function onNavUp(e) {
    if (!navPan) return;
    if (e.cancelable) e.preventDefault();
    e.stopImmediatePropagation();
    const pan = navPan; navPan = null;
    document.body.classList.remove('nav-panning');
    if (!pan.moved && pan.select && e.type !== 'pointercancel') lockSelect(pan.target);
  }
  // Lock: a click (no drag) shows what is under it in the inspector. Synthetic presses are untrusted, so onNavDown lets them through.
  function lockSelect(t) {
    if (!t || !t.isConnected) return;
    const note = t.closest('.postit'), node = t.closest('.drawflow-node'), wire = t.closest('path.main-path');
    const press = (el) => { el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true })); };
    if (note) selectNote(note.dataset.nid);
    else if (node) selectDf(node.id.replace('node-', ''));
    else if (wire) press(wire);
    else press(editor.precanvas);                     // bare canvas: Drawflow unselects
  }
  // Clicks / double-clicks that follow an intercepted press must not reach node, frame-title or post-it handlers.
  function onNavClick(e) {
    if (!e.isTrusted || !navMode() || !inCanvasEv(e) || e.target.closest(NAV_SKIP)) return;
    e.preventDefault(); e.stopImmediatePropagation();
  }
  function onNavKey(e) {
    const free = !isTyping(e.target) && !ctx && $('#modal').hidden;
    if (e.key === ' ' || e.code === 'Space') {
      if (!free) return;
      e.preventDefault(); e.stopImmediatePropagation();          // no page scroll, no button activation
      if (e.type === 'keydown' && !navSpace) { navSpace = true; updateNavUi(); }
      else if (e.type === 'keyup' && navSpace) { navSpace = false; updateNavUi(); }
      return;
    }
    if (e.type !== 'keydown' || !free) return;
    const plain = !e.ctrlKey && !e.metaKey && !e.altKey, k = e.key;
    if (plain && (k === 'h' || k === 'H')) { e.preventDefault(); e.stopImmediatePropagation(); setHand(!navHand); return; }
    if (plain && (k === 'l' || k === 'L')) { e.preventDefault(); e.stopImmediatePropagation(); setLock(!navLocked); return; }
    if (plain && k === '?') { e.preventDefault(); e.stopImmediatePropagation(); toggleHelp(); return; }
    if (k === 'Escape' && helpEl && !helpEl.hidden) { toggleHelp(false); return; }
    // read-only: editing keys stop here (Drawflow's own Delete handler included)
    const mod = e.ctrlKey || e.metaKey;
    if (editBlocked(true) && (k === 'Delete' || k === 'Backspace' || (plain && /^[gnGN]$/.test(k)) || (mod && /^[vzyxVZYX]$/.test(k)))) {
      e.preventDefault(); e.stopImmediatePropagation(); editBlocked(); return;
    }
    // view keys: only while the canvas itself has the focus
    const dfEl = $('#drawflow'), a = document.activeElement;
    if (!(a === dfEl || (dfEl.contains(a) && !isTyping(a))) || mod || e.altKey) return;
    const step = e.shiftKey ? 240 : 60;
    const arrows = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
    if (arrows[k]) { e.preventDefault(); e.stopImmediatePropagation(); panBy(arrows[k][0], arrows[k][1]); }
    else if (k === '+' || k === '=') { e.preventDefault(); e.stopImmediatePropagation(); zoomCentre(1.2); }
    else if (k === '-' || k === '_') { e.preventDefault(); e.stopImmediatePropagation(); zoomCentre(1 / 1.2); }
    else if (k === '0') { e.preventDefault(); e.stopImmediatePropagation(); fit(); }
  }
  function setHand(on) { navHand = !!on; updateNavUi(); }
  function setLock(on) {
    navLocked = !!on;
    try { if (navLocked) localStorage.setItem(LOCK_KEY, '1'); else localStorage.removeItem(LOCK_KEY); } catch (e) { /* per page only */ }
    updateNavUi();
  }
  // Read-only panels and canvas text fields; buttons/inputs this code disabled are marked so unlocking restores only them.
  function applyReadOnly() {
    const on = navLocked || navHand;
    document.querySelectorAll(RO_PANELS).forEach((p) => p.querySelectorAll('input, textarea, select, button').forEach((el) => {
      if (el.classList.contains('navok')) return;          // navigation inside a panel (sub-tabs, list picker) stays usable
      if (on && !el.disabled) { el.disabled = true; el.dataset.navro = '1'; }
      else if (!on && el.dataset.navro) { el.disabled = false; delete el.dataset.navro; }
    }));
    document.querySelectorAll('#drawflow textarea, #drawflow input').forEach((el) => {
      if (on && !el.readOnly) { el.readOnly = true; el.dataset.navro = '1'; }
      else if (!on && el.dataset.navro) { el.readOnly = false; delete el.dataset.navro; }
    });
  }
  function readOnlyMenu(items) {
    const keep = new Set(['Ajuster la vue', 'Copier']);
    return [{ label: navLocked ? 'Verrouillé — lecture seule' : 'Outil main — lecture seule', icon: navLocked ? 'lock' : 'hand-stop', disabled: true }, { sep: true }]
      .concat(items.map((it) => (it.sep || (keep.has(it.label) && !it.disabled) ? it : { label: it.label, icon: it.icon, disabled: true })));
  }
  function updateNavUi() {
    const b = document.body;
    b.classList.toggle('nav-grab', navSpace || navHand);
    b.classList.toggle('nav-hand', navHand);
    b.classList.toggle('nav-locked', navLocked);
    b.classList.toggle('nav-ro', navHand || navLocked);
    const bh = $('#btnHand'), bl = $('#btnLock');
    if (bh) { bh.classList.toggle('on', navHand); bh.setAttribute('aria-pressed', String(navHand)); }
    if (bl) {
      bl.classList.toggle('on', navLocked); bl.setAttribute('aria-pressed', String(navLocked));
      const i = bl.querySelector('.ico'); if (i) i.style.setProperty('--ic', icoUrl(navLocked ? 'lock' : 'lock-open'));
      bl.title = navLocked ? 'Déverrouiller (L)' : 'Verrouiller : lecture seule (L)';
    }
    const ban = $('#navBanner');
    if (ban) {
      ban.innerHTML = '';
      if (navLocked) ban.append(h('span', { class: 'nb-lock' }, ico('lock'), 'Verrouillé — lecture seule'), h('small', {}, 'L pour déverrouiller'));
      if (navHand) ban.append(h('span', { class: 'nb-hand' }, ico('hand-stop'), 'Outil main — H pour éditer'));
      ban.hidden = !navLocked && !navHand;
    }
    applyReadOnly();
  }
  function toggleHelp(force) {
    if (!helpEl) return;
    helpEl.hidden = force === undefined ? !helpEl.hidden : !force;
    const b = $('#btnHelp'); if (b) b.classList.toggle('on', !helpEl.hidden);
  }
  function buildHelp() {
    const rows = [
      ['Espace + glisser', 'déplacer la vue (rien ne peut être sélectionné ni modifié)'],
      ['Molette', 'défiler haut / bas'], ['Maj + molette', 'défiler gauche / droite'],
      ['Ctrl + molette, pincer', 'zoom autour du curseur'],
      ['H', 'outil main : chaque glisser déplace la vue, aucun clic n’édite'],
      ['L', 'verrouiller : lecture seule (mémorisé)'],
      ['Flèches (Maj = vite)', 'déplacer la vue — canevas actif'], ['+ / −', 'zoom — canevas actif'], ['0', 'ajuster — canevas actif'],
      ['Glisser à gauche', 'sur le vide : déplacer la vue ; sur un nœud : le déplacer'],
      ['Clic droit', 'menu'], ['?', 'cette aide']];
    helpEl = h('div', { id: 'navHelp', class: 'navhelp', role: 'dialog', 'aria-label': 'Commandes de navigation', hidden: true },
      h('div', { class: 'nhtitle' }, ico('question-mark'), 'Navigation', h('button', { type: 'button', class: 'nhclose', title: 'Fermer', onclick: () => toggleHelp(false) }, '×')),
      h('dl', {}, rows.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)])));   // h() flattens one level only
    ['mousedown', 'pointerdown', 'wheel'].forEach((t) => helpEl.addEventListener(t, (e) => e.stopPropagation(), { passive: true }));
    $('#stage').append(helpEl);
  }
  function installSafeNav() {
    const dfEl = $('#drawflow');
    dfEl.tabIndex = 0;                                         // the canvas can hold the focus (arrow / + / - / 0 keys)
    navLocked = (() => { try { return localStorage.getItem(LOCK_KEY) === '1'; } catch (e) { return false; } })();
    // focus the canvas on any press in it (not on its text fields), so the view keys work right after a click
    window.addEventListener('pointerdown', (e) => { if (e.isTrusted && inCanvasEv(e) && !isTyping(e.target) && !e.target.closest(NAV_SKIP)) dfEl.focus({ preventScroll: true }); }, true);
    ['pointerdown', 'mousedown', 'touchstart'].forEach((t) => window.addEventListener(t, onNavDown, { capture: true, passive: false }));
    ['pointermove', 'mousemove', 'touchmove'].forEach((t) => window.addEventListener(t, onNavMove, { capture: true, passive: false }));
    ['pointerup', 'mouseup', 'touchend', 'pointercancel', 'touchcancel'].forEach((t) => window.addEventListener(t, onNavUp, { capture: true, passive: false }));
    ['click', 'dblclick'].forEach((t) => window.addEventListener(t, onNavClick, true));
    window.addEventListener('wheel', onNavWheel, { capture: true, passive: false });
    window.addEventListener('keydown', onNavKey, true);
    window.addEventListener('keyup', onNavKey, true);
    window.addEventListener('blur', () => { if (navSpace) { navSpace = false; updateNavUi(); } });
    buildHelp();
    $('#btnHand').onclick = () => setHand(!navHand);
    $('#btnLock').onclick = () => setLock(!navLocked);
    $('#btnHelp').onclick = (e) => { e.stopPropagation(); toggleHelp(); };
    document.addEventListener('click', (e) => { if (helpEl && !helpEl.hidden && !helpEl.contains(e.target)) toggleHelp(false); });
    // re-render of the inspector / panels / post-its: keep the read-only state on the new inputs
    const mo = new MutationObserver(() => { if (navLocked || navHand) applyReadOnly(); });
    mo.observe($('#right'), { childList: true, subtree: true });
    mo.observe(editor.precanvas, { childList: true, subtree: true });
    updateNavUi();
  }

  // ---------- context menu (right click) ----------
  // A floating menu at the cursor: French labels, icons, arrow keys / Enter / Esc, submenus on hover or Right arrow,
  // kept inside the viewport. Items: [{label, icon, fn, sub, search, disabled, sep}] ; `sub` is a list or a function returning one.
  let ctx = null;
  function closeCtx() { if (ctx) { ctx.menus.forEach((m) => m.remove()); ctx.el.remove(); ctx = null; } }
  // Esc: close the innermost submenu (focus goes back to its parent row), else the whole menu.
  function escMenu() {
    if (!ctx) return;
    if (ctx.menus.length > 1) {
      closeSubsFrom(ctx.menus.length - 2);
      const parent = ctx.menus[ctx.menus.length - 1], rows = parent.querySelectorAll('.cit:not(.dis)');
      const open = [...rows].find((r) => r.querySelector('.carr'));
      (open || rows[0] || parent).focus();
    } else closeCtx();
  }
  function openCtx(x, y, items) {
    closeCtx();
    const root = h('div', { class: 'ctx', role: 'menu', tabindex: '-1' });
    ctx = { el: root, menus: [root] };
    document.body.append(root);
    fillMenu(root, items, 0);
    placeMenu(root, x, y);
    const first = root.querySelector('.cit:not(.dis)'); if (first) first.focus(); else root.focus();
  }
  function placeMenu(el, x, y) {
    // L7: never taller than the viewport (the menu scrolls inside), so every entry stays reachable
    el.style.maxHeight = Math.max(120, innerHeight - 8) + 'px';
    el.style.left = '0px'; el.style.top = '0px';
    const r = el.getBoundingClientRect(), W = innerWidth, H = innerHeight;
    el.style.left = Math.max(4, Math.min(x, W - r.width - 4)) + 'px';
    el.style.top = Math.max(4, Math.min(y, H - r.height - 4)) + 'px';
  }
  function fillMenu(el, items, depth) {
    el.innerHTML = '';
    items.forEach((it) => {
      if (it.sep) { el.append(h('div', { class: 'csep' })); return; }
      if (it.search) {
        const inp = h('input', { type: 'search', class: 'csearch', placeholder: it.search.placeholder || 'Rechercher…', 'aria-label': 'Rechercher' });
        inp.addEventListener('input', () => { it.search.onInput(inp.value.trim().toLowerCase()); });
        inp.addEventListener('keydown', (e) => { e.stopPropagation(); if (ctx) ctx.kbd = Date.now(); if (e.key === 'Escape') escMenu(); else if (e.key === 'ArrowDown') { e.preventDefault(); focusNext(el, 1, inp); } else if (e.key === 'Enter') { const f = el.querySelector('.cit:not(.dis)'); if (f) f.click(); } });
        el.append(inp); return;
      }
      const row = h('div', { class: 'cit' + (it.disabled ? ' dis' : ''), role: 'menuitem', tabindex: '-1', 'aria-disabled': it.disabled ? 'true' : null },
        it.icon ? ico(it.icon, it.color) : h('span', { class: 'ico-sp' }), h('span', { class: 'clab' }, it.label), it.sub ? h('span', { class: 'carr' }, '▸') : null);
      if (!it.disabled) {
        row.addEventListener('click', (e) => {
          e.stopPropagation();
          if (it.sub) { openSub(row, it, depth); return; }
          closeCtx(); if (it.fn) it.fn();
        });
        // a stationary pointer re-fires mouseenter when the menu re-lays out after a key press: ignore it for a moment
        if (it.sub) row.addEventListener('mouseenter', () => { if (!ctx || (ctx.kbd && Date.now() - ctx.kbd < 800)) return; openSub(row, it, depth); });
        else row.addEventListener('mouseenter', () => { closeSubsFrom(depth); row.focus(); });
      }
      el.append(row);
    });
  }
  function closeSubsFrom(depth) {
    if (!ctx) return;
    while (ctx.menus.length > depth + 1) ctx.menus.pop().remove();
  }
  function openSub(row, it, depth) {
    closeSubsFrom(depth);          // keep the menus up to this row's own level, drop any submenu already open under it
    const sub = h('div', { class: 'ctx csub', role: 'menu', tabindex: '-1' });
    document.body.append(sub); ctx.menus.push(sub);
    const list = typeof it.sub === 'function' ? it.sub(sub, depth + 1) : it.sub;
    fillMenu(sub, list, depth + 1);
    const pr = row.getBoundingClientRect();
    sub.style.left = '0px'; sub.style.top = '0px';
    const r = sub.getBoundingClientRect();
    let x = pr.right - 2; if (x + r.width > innerWidth - 4) x = Math.max(4, pr.left - r.width + 2);
    placeMenu(sub, x, pr.top - 4);
    const first = sub.querySelector('.csearch') || sub.querySelector('.cit:not(.dis)'); if (first) first.focus();
  }
  function focusNext(menu, dir, cur) {
    const rows = [...menu.querySelectorAll(':scope > .cit:not(.dis), :scope > .csearch')];
    if (!rows.length) return;
    let i = rows.indexOf(cur || document.activeElement);
    i = i < 0 ? (dir > 0 ? 0 : rows.length - 1) : (i + dir + rows.length) % rows.length;
    rows[i].focus();
  }
  function ctxKey(e) {
    if (!ctx) return false;
    const menu = ctx.menus[ctx.menus.length - 1];
    ctx.kbd = Date.now();
    if (e.key === 'Escape') escMenu();
    else if (e.key === 'ArrowDown') focusNext(menu, 1);
    else if (e.key === 'ArrowUp') focusNext(menu, -1);
    else if (e.key === 'ArrowRight') { const a = document.activeElement; if (a && a.classList.contains('cit') && a.querySelector('.carr')) a.click(); }
    else if (e.key === 'ArrowLeft') { if (ctx.menus.length > 1) { closeSubsFrom(ctx.menus.length - 2); const rows = ctx.menus[ctx.menus.length - 1].querySelectorAll('.cit:not(.dis)'); if (rows[0]) rows[0].focus(); } }
    else if (e.key === 'Enter' || e.key === ' ') { const a = document.activeElement; if (a && a.classList.contains('cit')) a.click(); }
    else if (e.key === 'Tab') { /* keep focus inside the menu */ }
    else return false;
    e.preventDefault(); e.stopPropagation();
    return true;
  }

  // What can follow a node (kinds valid after it, from the server's rules): start -> nothing (display only); trigger and
  // condition (true / false) -> condition, action, end (+ changing the state); action -> action, end (+ changing the state;
  // never a condition). Nothing ever leads INTO a trigger.
  function kindsAfter(kind) {
    switch (kind) {
      case 'start': return [];
      case 'trigger': return ['condition', 'action', 'end'];
      case 'condition': return ['condition', 'action', 'end'];
      case 'action': return ['action', 'end'];
      default: return [];
    }
  }
  const canGoToState = (kind) => ['trigger', 'condition', 'action'].includes(kind);
  const KIND_ICON = (k) => KINDS[k].icon;
  // Node to create from a menu entry: {kind, preset} ; vocabulary entries pre-fill the node.
  function nodeChoices(kinds) {
    return kinds.map((k) => ({ label: KINDS[k].label, icon: KINDS[k].icon, color: KINDS[k].color, kind: k }));
  }
  // Vars L2 shortcut rows: "Changer d'état → X" = an action set_var(etat, X) (replaces the old "État : X" / "Aller à : X").
  const moveChoices = () => V.states.map((s) => ({ label: "Changer d'état → " + s.label, icon: stateIcon(s.id), kind: 'action',
    preset: { action: 'set_var', args: { name: 'etat', value: s.id } }, hay: "changer d'état " + s.label + ' ' + s.id }));
  // Submenu content "insert a node" with a search field; `make(choice)` performs the insertion.
  function insertSub(kinds, make, opts) {
    return (subEl, depth) => {
      const base = nodeChoices(kinds);
      const vocab = [];
      if (kinds.includes('trigger')) evs().forEach((e) => vocab.push({ label: e.label, icon: e.icon, kind: 'trigger', preset: { event: e.id }, hay: e.label + e.id }));
      if (kinds.includes('condition')) V.guards.forEach((g) => vocab.push({ label: g.label, icon: g.icon, kind: 'condition', preset: { guard: g.id }, hay: g.label + g.id }));
      if (kinds.includes('action')) V.actions.forEach((a) => vocab.push({ label: a.label, icon: a.icon, kind: 'action', preset: { action: a.id }, hay: a.label + a.id }));
      const stateRows = (opts && opts.moves) ? moveChoices() : [];
      const toItem = (c) => ({ label: c.label, icon: c.icon, color: c.color, fn: () => make(c) });
      const render = (q) => {
        const rows = q ? vocab.concat(stateRows).filter((c) => c.hay.toLowerCase().includes(q)).slice(0, 14).concat(base.filter((c) => c.label.toLowerCase().includes(q))) : base;
        fillMenu(subEl, [{ search: { placeholder: 'Rechercher un nœud…', onInput: render } }].concat(rows.map(toItem), stateRows.length && !q ? [{ sep: true }].concat(stateRows.map(toItem)) : []), depth);
        const s = subEl.querySelector('.csearch'); if (s && q) { s.value = q; s.focus(); }
      };
      return [{ search: { placeholder: 'Rechercher un nœud…', onInput: render } }].concat(base.map(toItem), stateRows.length ? [{ sep: true }].concat(stateRows.map(toItem)) : []);
    };
  }
  let clipboard = null;           // in-editor clipboard: a node model {kind, description, params}
  function copyNode(dfid) {
    const m = model(dfid); if (!m) return false;
    if (m.kind === 'state' || m.kind === 'start') { toast('Un nœud ' + KINDS[m.kind].label + ' est unique : il ne se copie pas.', 'err'); return false; }
    clipboard = { kind: m.kind, description: m.description || '', params: clone(m.params || {}), group: m.group };
    return true;
  }
  function pasteNode(pt) {
    if (!clipboard || editBlocked()) return;
    const m = { id: nextNid(), kind: clipboard.kind, description: clipboard.description, params: clone(clipboard.params) };
    if (clipboard.group) m.group = clipboard.group;
    delete m.params.fan;                                    // a pasted trigger is a fresh one
    if (!pt) { const st = $('#stage').getBoundingClientRect(); pt = canvasPoint(st.x + st.width / 2 - 100, st.y + st.height / 2 - 40); }
    freshIds.add(m.id);
    const dfid = addNodeFromModel(m, Math.round(pt.x), Math.round(pt.y));
    commitSoon(); selectDf(dfid); analyze();
  }
  function duplicateNode(dfid) {
    if (!copyNode(dfid)) return;
    const d = dfNode(dfid);
    pasteNode({ x: d.pos_x + 40, y: d.pos_y + 40 });
  }
  function toggleChain(dfid) {
    const m = model(dfid); if (!m || m.kind !== 'trigger' || isEnterTrig(m)) return;
    m.params.enabled = m.params.enabled === false;           // false -> true, true/undefined -> false
    if (m.params.enabled === true) delete m.params.enabled;
    refreshNode(dfid); if (selDf === dfid) renderInspector();
    analyze(); commitSoon();
  }
  // Link `fromDf` (output class) to `toDf`, honouring the same rules as a manual link.
  function linkNodes(fromDf, outCls, toDf) {
    const a = model(fromDf), b = model(toDf), why = a && b ? linkProblem(a, b) : 'Nœud introuvable.';
    if (why) { toast(why, 'err'); return false; }
    editor.addConnection(fromDf, toDf, outCls, 'input_1');
    return true;
  }
  // Insert a new node after `dfid` (port = output class) and link it.
  function insertAfter(dfid, outCls, choice) {
    const d = dfNode(dfid);
    const nd = addAt(choice.kind, choice.preset, { x: d.pos_x + 260, y: d.pos_y }, { select: true });
    if (nd != null) linkNodes(dfid, outCls, nd);
  }
  // Split the wire (fromDf outCls -> toDf) into from -> new -> to.
  function splitWire(w, choice) {
    const a = dfNode(w.out), b = dfNode(w.in);
    if (!a || !b) return;
    const ma = model(w.out), mb = model(w.in);
    const nm = defaultModel(choice.kind, choice.preset), probe = { kind: choice.kind };
    if (linkProblem(ma, probe) || linkProblem(probe, mb)) { toast('Ce nœud ne peut pas s’insérer ici.', 'err'); return; }
    const idx = +w.outCls.split('_')[1], port = ma.kind === 'condition' ? (idx === 1 ? 'true' : 'false') : 'out';
    const oldKey = linkKey(ma.id, port, mb.id), meta0 = linkMeta.get(oldKey);
    editor.removeSingleConnection(w.out, w.in, w.outCls, 'input_1');
    linkMeta.delete(oldKey);
    const x = Math.round((a.pos_x + b.pos_x) / 2), y = Math.round((a.pos_y + b.pos_y) / 2);
    freshIds.add(nm.id);
    const nd = addNodeFromModel(nm, x, y);
    editor.addConnection(w.out, nd, w.outCls, 'input_1');
    editor.addConnection(nd, w.in, 'output_1', 'input_1');
    if (meta0) linkMeta.set(linkKey(nm.id, 'out', mb.id), meta0);   // the hop into a state keeps its reason / description
    selectDf(nd); commitSoon(); analyze(); paintWires();
  }
  function colorMenu(list, cur, apply) {
    return list.map(([nm, c]) => ({ label: nm + (c === cur ? ' ✓' : ''), icon: 'square', color: c, fn: () => apply(c) }));
  }
  // Build and open the menu that matches what was right-clicked.
  function openContextFor(e) {
    const t = e.target, x = e.clientX, y = e.clientY, pt = canvasPoint(x, y);
    const noteEl = t.closest('.postit'), frameEl = t.closest('.frame'), nodeElm = t.closest('.drawflow-node'), pathEl = t.closest('path.main-path');
    let items;
    if (noteEl) {
      const n = noteById(noteEl.dataset.nid);
      if (n) selectNote(n.id, true);
      items = [
        { label: 'Modifier', icon: 'eraser', fn: () => { const ta = noteEls.get(n.id).querySelector('textarea'); ta.focus(); } },
        { label: 'Couleur', icon: 'square', sub: colorMenu(NOTE_COLORS, n.color, (c) => editNote(n, { color: c }, true)) },
        { sep: true }, { label: 'Supprimer', icon: 'x', fn: () => deleteNote(n.id) }];
    } else if (frameEl && frameEl.dataset.fid) {
      const f = frameById(frameEl.dataset.fid);
      selectFrame(f.id);
      items = [
        { label: 'Renommer', icon: 'eraser', fn: () => editFrameTitle(f) },
        { label: 'Couleur', icon: 'square', sub: colorMenu(FRAME_COLORS, f.color, (c) => editFrame(f, { color: c }, true)) },
        { sep: true }, { label: 'Supprimer', icon: 'x', fn: () => deleteFrame(f.id) }];
    } else if (nodeElm) {
      const dfid = nodeElm.id.replace('node-', ''), m = model(dfid);
      selectDf(dfid);
      const after = [];
      const kinds = kindsAfter(m.kind);
      const ports = m.kind === 'condition' ? [['output_1', ' (Vrai)'], ['output_2', ' (Faux)']] : [['output_1', '']];
      ports.forEach(([cls, suffix]) => {
        after.push({ label: 'Insérer après' + suffix, icon: 'plus', disabled: !kinds.length && !canGoToState(m.kind),
          sub: insertSub(kinds, (c) => insertAfter(dfid, cls, c), { moves: canGoToState(m.kind) }) });
      });
      items = after.concat([{ sep: true },
        { label: 'Dupliquer', icon: 'plus', disabled: m.kind === 'state' || m.kind === 'start', fn: () => duplicateNode(dfid) },
        { label: 'Copier', icon: 'text-caption', disabled: m.kind === 'state' || m.kind === 'start', fn: () => copyNode(dfid) }]);
      if (m.kind === 'trigger' && !isEnterTrig(m)) items.push({ label: (m.params || {}).enabled === false ? 'Activer la chaîne' : 'Désactiver la chaîne', icon: 'power', fn: () => toggleChain(dfid) });
      items.push({ label: 'Grouper', icon: 'square', fn: () => { selectDf(dfid); addFrame(); } },
        { label: 'Ajouter un post-it ici', icon: 'message', fn: () => { const d = dfNode(dfid); addNote({ x: d.pos_x, y: d.pos_y + nodeBox(dfid).y1 - nodeBox(dfid).y0 + 24 }); } },
        { sep: true }, { label: 'Supprimer', icon: 'x', fn: () => editor.removeNodeId('node-' + dfid) });
    } else if (pathEl && pathEl.parentElement.classList.length >= 5) {
      const cl = pathEl.parentElement.classList, w = { in: cl[1].slice(13), out: cl[2].slice(14), outCls: cl[3] };
      selConn = w;
      const ma = model(w.out), mb = model(w.in);
      const ok = ['condition', 'action'].filter((k) => !linkProblem(ma, { kind: k }) && !linkProblem({ kind: k }, mb) && !(k === 'condition' && ma.kind === 'action'));
      items = [
        { label: 'Insérer un nœud au milieu', icon: 'plus', disabled: !ok.length, sub: insertSub(ok, (c) => splitWire(w, c)) },
        { sep: true },
        { label: 'Supprimer le fil', icon: 'x', fn: () => { editor.removeSingleConnection(w.out, w.in, w.outCls, 'input_1'); selConn = null; renderInspector(); } }];
    } else {
      items = [
        { label: 'Insérer un nœud', icon: 'plus', sub: insertSub(NODE_KINDS, (c) => addAt(c.kind, c.preset, pt, { exact: true }), { moves: true }) },
        { label: 'Insérer un post-it', icon: 'message', fn: () => addNote(pt) },
        { label: 'Insérer un groupe', icon: 'square', fn: () => addFrame(pt) },
        { label: 'Coller', icon: 'text-caption', disabled: !clipboard, fn: () => pasteNode(pt) },
        { sep: true }, { label: 'Ajuster la vue', icon: 'eye', fn: fit }];
    }
    if (editBlocked(true)) items = readOnlyMenu(items);
    openCtx(x, y, items);
  }

  // ---------- adding nodes ----------
  function defaultModel(kind, preset) {
    const m = { id: nextNid(), kind, description: '', params: {} };
    const p = m.params;
    const firstState = (V.states[0] || {}).id || '';
    if (kind === 'trigger') { p.type = 'event'; p.event = (V.events[0] || {}).id || ''; }
    if (kind === 'condition') { p.type = 'guard'; p.guard = (V.guards[0] || {}).id || ''; p.negate = false; }
    if (kind === 'action') { p.action = (V.actions[0] || {}).id || ''; p.args = {}; p.phase = 'do'; }
    if (kind === 'goto' || kind === 'state') p.state = firstState;
    if (kind === 'start') p.state = 'veille';
    if (preset) {
      if (preset.event) { p.type = 'event'; p.event = preset.event; }
      if (preset.guard) p.guard = preset.guard;
      if (preset.action) { p.action = preset.action; p.args = preset.args ? clone(preset.args) : {}; }
      if (preset.state) p.state = preset.state;
    }
    return m;
  }
  // Add a node of `kind`. Options: exact (place it exactly at `pt`, no nudging away from other nodes), select (default true).
  // Returns the Drawflow id, null if refused. (Vars L2: no State hubs any more; a trigger is never linked on creation.)
  function addAt(kind, preset, pt, opts) {
    opts = opts || {};
    if (kind === 'start') { toast("Le nœud Début n'existe plus : un déclencheur démarre sa chaîne tout seul.", 'err'); return null; }   // L4
    if (kind === 'state' || kind === 'goto') { toast("Les nœuds État / Aller à n'existent plus : utilisez l'action « Changer d'état ».", 'err'); return null; }
    if (editBlocked()) return null;
    const sel = selDf != null && dfNode(selDf) ? selDf : null;
    if (!pt) {
      // Preferred spot: right of the selected node, else the middle of the visible canvas.
      if (sel != null) pt = { x: dfNode(sel).pos_x + 260, y: dfNode(sel).pos_y };
      else { const st = $('#stage').getBoundingClientRect(); pt = canvasPoint(st.x + st.width / 2 - 100, st.y + st.height / 2 - 40); }
    }
    if (!opts.exact) pt = freeSpot(pt.x, pt.y);
    const m = defaultModel(kind, preset);
    freshIds.add(m.id);
    const dfid = addNodeFromModel(m, Math.round(pt.x), Math.round(pt.y));
    commitSoon();
    if (opts.select !== false) selectDf(dfid);
    if (!isVisible(m.id)) panTo(m.id, 0.6);
    analyze();
    return dfid;
  }
  // Nearest position (on a 250 x 130 grid around the wanted one) where a new 214 x 120 node touches no other node.
  function freeSpot(x, y) {
    const boxes = Object.keys(dfData()).map((id) => nodeBox(id));
    const free = (px, py) => boxes.every((b) => px + 230 < b.x0 || px > b.x1 + 16 || py + 130 < b.y0 || py > b.y1 + 16);
    const cand = [];
    for (let i = -8; i <= 8; i++) for (let j = -8; j <= 8; j++) cand.push([i * 250 * 0.5, j * 130 * 0.5, Math.hypot(i * 1.2, j)]);
    cand.sort((a, b) => a[2] - b[2]);
    for (const [dx, dy] of cand) if (free(x + dx, y + dy)) return { x: Math.round(x + dx), y: Math.round(y + dy) };
    return { x, y };
  }
  function selectDf(dfid) {
    // Drawflow has no public "select"; emulate the click it listens to.
    const el = nodeEl(dfid);
    if (el) { el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true })); }
  }

  function renderPalette() {
    const q = $('#search').value.trim().toLowerCase();
    const box = $('#palette'); box.innerHTML = '';
    const items = [];
    const rects = bandRects();
    // Vars L2: the columns (one automatic frame per state) are navigation targets; changing the state is an action
    V.states.forEach((st) => { if (rects[st.id]) items.push({ sec: 'Colonnes (cliquer pour y aller)', kind: 'band', band: true, id: st.id, label: st.label, sub: 'etat = ' + st.id, icon: stateIcon(st.id), hay: 'colonne état ' + st.label + st.id }); });
    if (rects.global) items.push({ sec: 'Colonnes (cliquer pour y aller)', kind: 'band', band: true, id: 'global', label: 'Règles globales', sub: 'global', icon: 'git-branch', hay: 'global règles globales' });
    items.push({ sec: 'Groupes (cliquer pour y aller)', kind: 'frame', fn: () => addFrame(), label: 'Groupe', sub: 'nouveau (G)', icon: 'plus', color: '#e3b341', hay: 'groupe nouveau cadre commentaire' });
    frames().forEach((f) => items.push({ sec: 'Groupes (cliquer pour y aller)', kind: 'frame', fn: () => focusFrame(f.id), label: f.title || '(sans nom)', sub: '', icon: 'square', color: f.color, hay: 'groupe ' + f.title + ' ' + (f.note || '') }));
    items.push({ sec: 'Notes', kind: 'note', fn: () => addNote(), label: 'Post-it', sub: 'nouveau (N)', icon: 'plus', color: NOTE_COLORS[0][1], hay: 'note post-it postit nouveau' });
    notes().forEach((n) => items.push({ sec: 'Notes', kind: 'note', fn: () => focusNoteBox(n.id), label: n.title || (n.text || '').slice(0, 24) || '(vide)', sub: '', icon: 'message', color: n.color, hay: 'note post-it ' + (n.title || '') + ' ' + (n.text || '') }));
    NODE_KINDS.forEach((k) => items.push({ sec: 'Blocs', kind: k, label: KINDS[k].label, sub: '', icon: KINDS[k].icon, hay: KINDS[k].label + ' ' + k }));
    evs().forEach((e) => items.push({ sec: 'Événements', kind: 'trigger', preset: { event: e.id }, label: e.label, sub: e.id, icon: e.icon, hay: e.label + e.id + (e.help || '') }));
    V.guards.forEach((g) => items.push({ sec: 'Conditions', kind: 'condition', preset: { guard: g.id }, label: g.label, sub: g.id, icon: g.icon, hay: g.label + g.id + (g.help || '') }));
    V.actions.forEach((a) => items.push({ sec: 'Actions', kind: 'action', preset: { action: a.id }, label: a.label, sub: a.id, icon: a.icon, hay: a.label + a.id + (a.help || '') }));
    moveChoices().forEach((c) => items.push({ sec: "Changer d'état", kind: 'action', preset: c.preset, label: c.label.replace("Changer d'état → ", '→ '), sub: 'set_var etat', icon: c.icon, hay: c.hay }));
    let sec = '';
    items.filter((i) => !q || i.hay.toLowerCase().includes(q)).forEach((i) => {
      if (i.sec !== sec) { sec = i.sec; box.append(h('div', { class: 'psec' }, sec)); }
      const el = h('div', { class: 'pitem', draggable: i.band || i.fn ? null : 'true', title: i.hay },
        ico(i.icon, i.color || (i.band ? stateColor(i.id) : KINDS[i.kind].color)), i.label, h('small', {}, i.sub));
      el.addEventListener('click', () => { if (i.fn) i.fn(); else if (i.band) focusBand(i.id); else addAt(i.kind, i.preset); if (innerWidth <= 900) document.body.classList.add('hide-left'); });
      el.addEventListener('dragstart', (ev) => { ev.dataTransfer.setData('text/plain', JSON.stringify({ kind: i.kind, preset: i.preset || null })); });
      box.append(el);
    });
  }

  // ---------- inspector ----------
  function field(label, control, help) {
    // A custom dropdown holds clickable rows: a <label> around it would re-click its button, so use a <div>.
    const tag = control && control.classList && control.classList.contains('dd') ? 'div' : 'label';
    return h(tag, { class: 'fld' }, h('span', {}, label), control, help ? h('div', { class: 'help' }, help) : null);
  }
  // Dropdown that can show an icon per entry (a native <select> cannot). options: [{v, l, icon}].
  function iconSelect(options, value, onchange) {
    const opts = options.slice();
    if (value != null && value !== '' && !opts.some((o) => String(o.v) === String(value))) opts.unshift({ v: value, l: '(inconnu) ' + value, icon: 'circle-dot' });
    const root = h('div', { class: 'dd' }), btn = h('button', { type: 'button', class: 'ddb' }), list = h('div', { class: 'ddl', hidden: true });
    const cur = () => opts.find((o) => String(o.v) === String(value));
    const paint = () => {
      btn.innerHTML = ''; const c = cur();
      btn.append(ico(c && c.icon), h('span', { class: 'ddt' }, c ? c.l : '(choisir)'), h('span', { class: 'ddc' }, '▾'));
    };
    opts.forEach((o) => list.append(h('div', { class: 'ddi' + (String(o.v) === String(value) ? ' on' : ''), title: o.l,
      onclick: (e) => { e.stopPropagation(); value = o.v; list.hidden = true; paint(); onchange(o.v); } }, ico(o.icon), o.l)));
    btn.addEventListener('click', (e) => { e.stopPropagation(); const was = list.hidden; document.querySelectorAll('.ddl').forEach((l) => { l.hidden = true; }); list.hidden = !was; });
    paint(); root.append(btn, list);
    return root;
  }
  function areaCtl(value, onchange, maxlen) {
    const t = h('textarea', { maxlength: maxlen || null, rows: 3 });
    t.value = value == null ? '' : value;
    t.addEventListener('change', () => onchange(t.value));
    return t;
  }
  function selectCtl(options, value, onchange) {
    const s = h('select', {});
    const opts = options.slice();
    if (value != null && value !== '' && !opts.some((o) => String(o.v) === String(value))) opts.unshift({ v: value, l: '(inconnu) ' + value });
    opts.forEach((o) => s.append(h('option', { value: o.v }, o.l)));
    s.value = value == null ? '' : value;
    s.addEventListener('change', () => onchange(s.value));
    return s;
  }
  function textCtl(value, onchange, type, list) {
    const i = h('input', { type: type || 'text', list: list || null });
    i.value = value == null ? '' : value;
    i.addEventListener('change', () => onchange(i.value));
    return i;
  }
  function checkCtl(label, value, onchange, icon) {
    const c = h('input', { type: 'checkbox' }); c.checked = !!value;
    c.addEventListener('change', () => onchange(c.checked));
    return h('label', { class: 'chk' }, c, icon ? ico(icon) : null, label);
  }
  function edit(fn, rerender) {
    const m = model(selDf); if (!m) return;
    fn(m);
    refreshNode(selDf);
    if (rerender) renderInspector();
    commitSoon();
  }
  const numOrKey = (v) => { v = String(v).trim(); return isNum(v) ? Number(v) : v; };

  // Inspector of the selected wire: the hop into a state node carries the journal reason (and a description when the
  // chain has no node of its own to hold it).
  function renderWireInspector(box) {
    const w = selConn, a = model(w.out), b = model(w.in);
    if (!a || !b) { selConn = null; return false; }
    const idx = +w.outCls.split('_')[1], port = a.kind === 'condition' ? (idx === 1 ? 'true' : 'false') : 'out', key = linkKey(a.id, port, b.id);
    box.append(h('div', { class: 'insttitle' }, ico('arrow-right', KIND_HEX[a.kind]), 'Fil', h('small', { class: 'hint' }, `${a.id} → ${b.id}`)));
    if (b.kind === 'state') {
      const mt = linkMeta.get(key) || {};
      const setMeta = (k, v) => { const cur = Object.assign({}, linkMeta.get(key) || {}); if (v) cur[k] = v; else delete cur[k]; if (Object.keys(cur).length) linkMeta.set(key, cur); else linkMeta.delete(key); paintWires(); commitSoon(); };
      box.append(field("Vers l'état", h('input', { type: 'text', disabled: true, value: stateLabel(b.params.state) })));
      box.append(field('Raison (journal)', textCtl(mt.reason || '', (v) => setMeta('reason', v.trim().slice(0, 100))), 'Texte libre affiché dans le journal quand cette chaîne change l’état ; par défaut, l’événement déclencheur.'));
      box.append(field('Description de la chaîne', areaCtl(mt.description || '', (v) => setMeta('description', v.trim().slice(0, 500)), 500), 'Utile seulement si aucun nœud de la chaîne ne peut porter la description.'));
    } else box.append(h('p', { class: 'hint' }, 'Ce fil relie deux nœuds de la même chaîne.'));
    box.append(h('button', { type: 'button', class: 'danger', onclick: () => { editor.removeSingleConnection(w.out, w.in, w.outCls, 'input_1'); selConn = null; renderInspector(); } }, 'Supprimer le fil'));
    return true;
  }

  // ---------- typed argument controls (Vars L2) ----------
  // Required plain args per action (var / list / value args are described by the vocabulary itself).
  const REQUIRED_ARGS = { say_text: ['text'], set_expression: ['name', 'seconds'], wait: ['seconds'], gaze: ['mode'] };
  const ORDER_OPS = ['<', '<=', '>', '>='];
  // Default value written when a variable / list is picked for a required `value` (so a checkbox or a select never
  // shows a value the document does not hold). Text has no default.
  function defaultValueFor(type, choices) {
    if (type === 'bool') return false;
    if (type === 'number' || type === 'duration') return 0;
    if (type === 'choice') return (choices || [])[0];
    return undefined;
  }
  // Controls for a vocabulary argument list. `cur` = current values, `set(name, value)` writes one ('' / null = remove).
  //   var   -> variables filtered by var_types; `writable` hides read-only ones (etat stays offered to set_var: it is
  //            the state change)
  //   list  -> lists filtered by list_types; `writable` hides source-bound lists
  //   value -> control by the type of the variable / list items named by `of`: checkbox (bool), number (number,
  //            duration), select (choice; etat = the states, a set of states with in / not_in), text (string, with a
  //            "$utterance" switch when the vocabulary offers it)
  //   enum  -> select with the vocabulary labels (op: = != in not_in on etat; order operators only for numbers)
  function argFields(box, specArgs, cur, set, ctx) {
    ctx = ctx || {};
    const stateOpts = V.states.map((s) => ({ v: s.id, l: s.label }));
    const kindOf = (name) => ((specArgs || []).find((x) => x.name === name) || {}).type;
    const refDef = (arg) => {
      const ref = cur[arg.of];
      if (ref == null || ref === '') return null;
      return kindOf(arg.of) === 'list' ? listDef(ref) : varDef(ref);
    };
    (specArgs || []).forEach((arg, i) => {
      const v = cur[arg.name], lab = arg.label || arg.name;
      const dependent = (specArgs || []).find((x) => x.type === 'value' && x.of === arg.name && !x.optional);
      const pick = (x, def) => {
        set(arg.name, x);
        if (dependent && def) { const dv = def.id === 'etat' ? (V.states[0] || {}).id : defaultValueFor(def.type, def.choices); if (dv !== undefined) set(dependent.name, dv); }
      };
      if (arg.type === 'var') {
        const opts = varDefs().filter((d) => (!(arg.var_types || []).length || arg.var_types.includes(d.type))
          && (!arg.writable || !d.readonly || (d.id === 'etat' && ctx.id === 'set_var')));
        const sel = selectCtl([{ v: '', l: '(choisir une variable)' }].concat(opts.map((d) => ({ v: d.id, l: d.id + ' — ' + typeLabel(d.type) + (d.system ? ' (système)' : '') }))),
          v == null ? '' : v, (x) => pick(x, varDef(x)));
        sel.classList.add('varsel');
        const d = v ? varDef(v) : null;
        box.append(field(lab, sel, d ? (d.description || d.label || '') : (opts.length ? '' : 'Aucune variable de ce type : créez-en une dans le panneau Variables.')));
      } else if (arg.type === 'list') {
        const opts = listDefs().filter((l) => (!(arg.list_types || []).length || arg.list_types.includes(l.type)) && (!arg.writable || !l.readonly));
        const sel = selectCtl([{ v: '', l: '(choisir une liste)' }].concat(opts.map((l) => ({ v: l.id, l: l.id + ' — ' + typeLabel(l.type, true) + ' (' + l.items.length + ')' }))),
          v == null ? '' : v, (x) => pick(x, null));
        sel.classList.add('varsel');
        box.append(field(lab, sel, opts.length ? '' : 'Aucune liste de ce type : créez-en une dans le panneau Variables.'));
      } else if (arg.type === 'value') {
        const d = refDef(arg), isList = kindOf(arg.of) === 'list';
        if (!d) { box.append(field(lab, h('div', { class: 'hint' }, isList ? "Choisir d'abord la liste." : "Choisir d'abord la variable."))); return; }
        const opt = !!arg.optional, none = opt ? '(toute valeur)' : '(choisir)';
        let ctl;
        if (!isList && d.id === 'etat') {
          if (['in', 'not_in'].includes(cur.op)) {
            const chosen = Array.isArray(v) ? v : (v ? [v] : []);
            ctl = h('div', { class: 'statechk' });
            V.states.forEach((s) => ctl.append(checkCtl(s.label, chosen.includes(s.id), (c) => {
              const st = new Set(chosen); c ? st.add(s.id) : st.delete(s.id);
              set(arg.name, V.states.map((x) => x.id).filter((x) => st.has(x)));
            }, stateIcon(s.id))));
          } else ctl = selectCtl([{ v: '', l: none }].concat(stateOpts), v == null ? '' : v, (x) => set(arg.name, x));
        } else if (d.type === 'choice') {
          ctl = selectCtl([{ v: '', l: none }].concat((d.choices || []).map((c) => ({ v: c, l: c }))), v == null ? '' : v, (x) => set(arg.name, x));
        } else if (d.type === 'bool') {
          if (opt) ctl = selectCtl([{ v: '', l: none }, { v: 'true', l: 'vrai' }, { v: 'false', l: 'faux' }], v == null ? '' : String(v), (x) => set(arg.name, x === '' ? '' : x === 'true'));
          else ctl = checkCtl('vrai', v === true || v === 'true', (c) => set(arg.name, c));
        } else if (d.type === 'number' || d.type === 'duration') {
          ctl = h('input', { type: 'number', step: 'any', min: d.type === 'duration' ? 0 : null });
          ctl.value = v == null ? '' : v;
          ctl.addEventListener('change', () => set(arg.name, ctl.value === '' ? '' : Number(ctl.value)));
        } else {
          const utt = arg.utterance && v === '$utterance';
          ctl = h('div', {});
          if (!utt) ctl.append(textCtl(v, (x) => set(arg.name, x)));
          if (arg.utterance) ctl.append(checkCtl('la phrase entendue ($utterance)', utt, (c) => set(arg.name, c ? '$utterance' : '')));
        }
        box.append(field(lab + (isList ? ' (' + typeLabel(d.type, true) + ')' : ' (' + typeLabel(d.type) + ')'), ctl, opt ? 'Facultatif.' : ''));
      } else if (arg.type === 'enum') {
        let options = (arg.options || []).slice();
        const labels = Object.assign({ in: 'parmi', not_in: 'hors de' }, arg.labels || {});
        if (arg.name === 'op' && cur.name) {
          const d = varDef(cur.name);
          if (cur.name === 'etat') options = ['=', '!=', 'in', 'not_in'];
          else if (d && !['number', 'duration'].includes(d.type)) options = options.filter((o) => !ORDER_OPS.includes(o));
        }
        const optLabel = (o) => (arg.name === 'op' ? opLabel(o) + '  ' : '') + (labels[o] || (byId(evs(), o) || {}).label || String(o));
        const required = (ctx.required || []).includes(arg.name) || arg.name === 'op';
        box.append(field(lab, selectCtl((arg.name === 'op' ? [] : [{ v: '', l: required ? '(à choisir)' : '(aucun)' }]).concat(options.map((o) => ({ v: o, l: optLabel(o) }))), v == null ? (arg.name === 'op' ? '=' : '') : v, (x) => set(arg.name, x)),
          arg.name === 'op' ? '' : required ? 'Obligatoire : choisir une valeur.' : 'Facultatif.'));
      } else if (arg.type === 'number') {
        const lid = 'dl-arg' + i;
        const dl = (arg.options || []).length ? h('datalist', { id: lid }, (arg.options || []).map((o) => h('option', { value: o }))) : null;
        box.append(field(lab + ((arg.options || []).length && !/clé/.test(lab) ? ' (nombre, ou clé de réglage)' : ''), textCtl(v, (x) => set(arg.name, x === '' ? '' : numOrKey(x)), 'text', dl ? lid : null)));
        if (dl) box.append(dl);
      } else if (arg.max_len > 100) {
        box.append(field(lab, areaCtl(v, (x) => set(arg.name, x), arg.max_len), `${arg.max_len} caractères au plus.`));
      } else box.append(field(lab, textCtl(v, (x) => set(arg.name, x))));
    });
  }

  function renderInspector() {
    const box = $('#inspector'); box.innerHTML = '';
    const fr = selFrame && frameById(selFrame);
    if (fr) { renderFrameInspector(box, fr); return; }
    const nt = selNote && noteById(selNote);
    if (nt) { renderNoteInspector(box, nt); return; }
    if (selConn && selDf == null && renderWireInspector(box)) return;
    const m = selDf != null ? model(selDf) : null;
    if (!m) { box.append(h('p', { class: 'hint' }, 'Sélectionnez un nœud pour le modifier, ou ajoutez-en un depuis la palette.')); return; }
    const p = m.params;
    box.append(h('div', { class: 'insttitle' }, ico(iconOf(m), KINDS[m.kind].color),
      KINDS[m.kind].label, h('small', { class: 'hint' }, m.id + (m.group ? ' · ' + (m.group === 'global' ? 'global' : stateLabel(m.group)) : ''))));
    const helpOf = (list, id) => (byId(list, id) || {}).help || '';
    const stateOpts = V.states.map((s) => ({ v: s.id, l: s.label, icon: stateIcon(s.id) }));

    if (m.kind === 'start') {
      box.append(field('État de départ (fixé par le code)', h('input', { type: 'text', disabled: true, value: stateLabel(p.state) })));
    }
    if (m.kind === 'trigger') {
      const types = [{ v: 'event', l: 'Un événement arrive' }, { v: 'after', l: 'Après un délai' }].concat(p.type === 'enter' ? [{ v: 'enter', l: "À l'entrée dans un état (ancien)" }] : []);
      box.append(field('Type', selectCtl(types, p.type, (v) => edit((mm) => {
        const wasOff = mm.params.enabled === false;
        mm.params = { type: v };
        if (v === 'event') mm.params.event = (V.events[0] || {}).id;
        if (v === 'after') { mm.params.delay = (V.delays[0] || {}).key || 5; mm.params.since = 'state'; }
        if (wasOff) mm.params.enabled = false;
      }, true))));
      const isEnter = p.type === 'enter' || (p.type === 'event' && p.event === 'var_changed' && p.name === 'etat');
      if (p.type === 'event') box.append(field('Événement', iconSelect(evs().map((e) => ({ v: e.id, l: e.label, icon: e.icon })), p.event, (v) => edit((mm) => {
        mm.params.event = v; delete mm.params.name; delete mm.params.value;
      }, true)), helpOf(evs(), p.event)));
      if (p.type === 'event' && p.event === 'var_changed') {
        // the trigger's own params carry name / value (not `args`): same typed controls
        argFields(box, (byId(V.events, 'var_changed') || {}).args || [], p, (k, v) => edit((mm) => {
          if (v === '' || v == null) delete mm.params[k]; else mm.params[k] = v;
          if (k === 'name') delete mm.params.value;
        }, true), { id: 'var_changed' });
        if (p.name === 'etat') box.append(h('p', { class: 'hint' }, "« Quand etat devient X » = entrée dans l'état X : seulement des actions, ni condition ni changement d'état ; jamais désactivée."));
      }
      if (!isEnter) {
        box.append(h('p', { class: 'hint' }, "Un déclencheur n'a pas d'entrée. Pour le limiter à un état, ajoutez juste après lui une condition « etat = … » (clic droit → Insérer après → Comparer une variable)."));
        box.append(h('p', { class: 'hint fannote' }, "Plusieurs branches : toutes celles qui ne changent pas d'état s'exécutent (dans l'ordre des numéros), puis une seule branche change d'état : la première qui correspond."));
        const fb = (fanInfo.fans || {})[m.id];
        if (fb && fb.length > 1) box.append(h('p', { class: 'hint' }, 'Ordre actuel : ' + fb.slice().sort((a, b) => a.rank - b.rank).map((b) => b.rank + ' → ' + b.target + (b.moves ? ' (change l\'état)' : '') + (b.ignored ? ' [ignorée]' : '')).join(' ; ')));
        box.append(checkCtl('Chaîne activée', p.enabled !== false, (c) => edit((mm) => { mm.params.enabled = c; }, true), 'power'));
        if (p.enabled === false) box.append(h('p', { class: 'hint' }, "Désactivée : la chaîne reste dans le fichier mais le robot l'ignore (grisée sur le canvas)."));
      }
      if (p.type === 'after') {
        box.append(field('Délai (secondes, ou clé de réglage)', textCtl(p.delay, (v) => edit((mm) => { mm.params.delay = numOrKey(v); }, true), 'text', 'dl-delays'),
          'Clés : ' + V.delays.map((d) => `${d.key} = ${d.value} s`).join(' ; ')));
        box.append(h('datalist', { id: 'dl-delays' }, V.delays.map((d) => h('option', { value: d.key }))));
        box.append(field('Compté', selectCtl(V.since.map((s) => ({ v: s.id, l: s.label })), p.since || 'state', (v) => edit((mm) => { mm.params.since = v; }))));
        box.append(h('p', { class: 'hint' }, 'Un délai doit être rattaché à un état : condition « etat = … » (ou « etat parmi … ») juste après.'));
      }
      if (p.type === 'enter') box.append(field('État', iconSelect(stateOpts, p.state, (v) => edit((mm) => { mm.params.state = v; }, true)), 'Ancienne forme : préférez « Une variable change » sur etat.'));
    }
    if (m.kind === 'condition') {
      const types = [{ v: 'guard', l: 'Une condition (garde ou variable)' }].concat(p.type === 'state' ? [{ v: 'state', l: "L'état courant (ancien)" }] : []);
      box.append(field('Type', selectCtl(types, p.type, (v) => edit((mm) => {
        mm.params = { type: v, negate: !!mm.params.negate };
        if (v === 'guard') mm.params.guard = (V.guards[0] || {}).id; else mm.params.states = [];
      }, true))));
      if (p.type === 'guard') {
        box.append(field('Condition', iconSelect(V.guards.map((g) => ({ v: g.id, l: g.label + (g.as_vars ? ' (' + g.as_vars + ')' : ''), icon: g.icon })), p.guard, (v) => edit((mm) => {
          mm.params.guard = v; delete mm.params.global;
          const g = byId(V.guards, v);
          if (g && (g.args || []).length) { mm.params.args = {}; if (v === 'var_compare') mm.params.args.op = '='; } else delete mm.params.args;
        }, true)), helpOf(V.guards, p.guard)));
        if (asVars(p.guard)) box.append(h('p', { class: 'hint' }, ico('text-caption'), ' En variables : ', h('code', {}, asVars(p.guard))));
        const g = byId(V.guards, p.guard);
        if (g && (g.args || []).length) argFields(box, g.args, p.args || {}, (k, v) => edit((mm) => {
          mm.params.args = mm.params.args || {};
          if (v === '' || v == null) delete mm.params.args[k]; else mm.params.args[k] = v;
          if (k === 'name' || k === 'list') { delete mm.params.args.value; if (k === 'name' && mm.params.guard === 'var_compare') mm.params.args.op = '='; delete mm.params.global; }
          if (k === 'op' && (['in', 'not_in'].includes(v) !== Array.isArray(mm.params.args.value))) delete mm.params.args.value;
        }, true), { id: p.guard });
        const a = p.args || {};
        if (p.guard === 'var_compare' && a.name === 'etat' && ['=', 'in'].includes(a.op || '=')) {
          box.append(checkCtl('Règle globale (évaluée avec les règles globales, limitée à ces états)', p.global, (c) => edit((mm) => { if (c) mm.params.global = true; else delete mm.params.global; })));
        }
        if (p.guard === 'var_compare' && a.name === 'etat') box.append(h('p', { class: 'hint' }, "La condition sur etat range la chaîne dans la colonne de l'état (plusieurs états : une copie par état). Sans condition sur etat, la règle est globale."));
      }
      if (p.type === 'state') {
        const wrap = h('div', { class: 'fld' }, h('span', {}, 'États'));
        V.states.forEach((s) => wrap.append(checkCtl(s.label, (p.states || []).includes(s.id), (c) => edit((mm) => {
          const set = new Set(mm.params.states || []); c ? set.add(s.id) : set.delete(s.id); mm.params.states = [...set];
        }), stateIcon(s.id))));
        box.append(wrap);
        box.append(checkCtl('Règle globale (limitée à ces états)', p.global, (c) => edit((mm) => { if (c) mm.params.global = true; else delete mm.params.global; })));
      }
      box.append(checkCtl('Inverser (non)', p.negate, (c) => edit((mm) => { mm.params.negate = c; })));
      box.append(h('p', { class: 'hint' }, 'Sorties : « Vrai » continue la chaîne ; « Faux » démarre la branche suivante.'));
    }
    if (m.kind === 'action') {
      box.append(field('Action', iconSelect(V.actions.map((a) => ({ v: a.id, l: a.label, icon: a.icon })), p.action, (v) => edit((mm) => { mm.params.action = v; mm.params.args = {}; delete mm.params.reason; }, true)), helpOf(V.actions, p.action)));
      const a = byId(V.actions, p.action);
      argFields(box, (a && a.args) || [], p.args || {}, (k, v) => edit((mm) => {
        mm.params.args = mm.params.args || {};
        if (v === '' || v == null) delete mm.params.args[k]; else mm.params.args[k] = v;
        if (k === 'name' || k === 'list') delete mm.params.args.value;
        if (!(mm.params.action === 'set_var' && mm.params.args.name === 'etat')) delete mm.params.reason;
      }, true), { id: p.action, required: REQUIRED_ARGS[p.action] || [] });
      const move = p.action === 'set_var' && (p.args || {}).name === 'etat';
      if (move) {
        box.append(field('Raison (journal)', textCtl(p.reason || '', (v) => edit((mm) => { v = v.trim().slice(0, 100); if (v) mm.params.reason = v; else delete mm.params.reason; }, true)),
          'Texte libre affiché dans le journal quand cette chaîne change l’état ; par défaut, l’événement déclencheur.'));
        box.append(h('p', { class: 'hint' }, "Changer d'état : les actions avant ce nœud s'exécutent avant le changement, celles après lui juste après (dans le nouvel état). Un seul changement d'état par chaîne."));
      } else {
        box.append(field('Quand', selectCtl([{ v: 'do', l: "Avant le changement d'état" }, { v: 'then', l: "Après le changement d'état" }], p.phase || 'do', (v) => edit((mm) => { mm.params.phase = v; })),
          "Utile seulement sans action « Changer d'état » dans la chaîne (sinon la position décide : avant / après elle)."));
      }
    }
    if (m.kind === 'state') {
      const nIn = ((dfNode(selDf).inputs.input_1 || {}).connections || []).length, nOut = ((dfNode(selDf).outputs.output_1 || {}).connections || []).length;
      box.append(field('État', h('input', { type: 'text', disabled: true, value: stateLabel(p.state) }), stateDesc(p.state)));
      box.append(h('p', { class: 'hint' }, `Il y a un seul nœud par état. Entrée : ${nIn} chaîne(s) qui y arrivent. Sortie : ${nOut} déclencheur(s) valables dans cet état.`));
      box.append(h('p', { class: 'hint' }, "Pour changer l'état du robot, reliez le dernier nœud d'une chaîne à l'entrée (à gauche) de ce nœud. Cliquez sur le fil pour noter la raison qui apparaît dans le journal."));
    }
    if (m.kind === 'goto') {
      box.append(field("État d'arrivée", iconSelect(stateOpts, p.state, (v) => edit((mm) => { mm.params.state = v; }, true)), (byId(V.states, p.state) || {}).description || ''));
      box.append(field('Raison (journal)', textCtl(p.reason, (v) => edit((mm) => { if (v) mm.params.reason = v; else delete mm.params.reason; }))));
    }
    if (m.kind === 'end') box.append(h('p', { class: 'hint' }, "Fin de chaîne : aucun changement d'état."));

    const ta = h('textarea', {}); ta.value = m.description || '';
    ta.addEventListener('change', () => edit((mm) => { mm.description = ta.value; }));
    if (m.kind !== 'state') box.append(field('Description', ta));
    (issues.get(m.id) || []).forEach((i) => box.append(h('div', { class: 'iss ' + i.level }, i.message)));
    box.append(h('button', { class: 'danger', onclick: () => { editor.removeNodeId('node-' + selDf); } }, 'Supprimer ce nœud'));
  }

  // ---------- intents panel (editable: words, regex, only_in, description, new intents) ----------
  // The document (meta.intents) is the working copy; the server validates names, regexes and states at save /
  // simulate time and answers with {intent: name, message}. A shared list (`words_from`) is shown read-only.
  function intentChanged(rerender) {
    commitSoon();
    renderPalette();
    if (rerender) renderIntents();
    if (selDf != null) renderInspector();
  }
  function intentCard(name) {
    const it = meta.intents[name] || (meta.intents[name] = {});
    const sv = byId(V.intents, name) || {};
    const card = h('div', { class: 'intent' });
    card.append(h('div', { class: 'ihead' }, ico(it.icon || sv.icon || 'message', 'var(--cond)'), h('code', {}, 'intent.' + name)));
    if (intentErrs[name]) card.append(h('div', { class: 'ierr' }, intentErrs[name]));
    // Vars L2: lists bound to this intent's words (or to its shared config key) are visible in the Variables panel
    listDefs().filter((l) => l.source && (l.source.intent === name || (it.words_from && l.source.cfg === it.words_from))).forEach((l) => card.append(
      h('div', { class: 'note' }, 'Aussi visible comme liste ', h('a', { href: '#', class: 'navok', onclick: (e) => { e.preventDefault(); varsUi.tab = 'lists'; varsUi.list = l.id; activateTab('vars'); } }, '« ' + l.id + ' »'), ' dans le panneau Variables.')));
    if (it.words_from) {
      card.append(h('div', { class: 'note' }, `Liste partagée avec la config (clé « ${it.words_from} ») : à modifier dans la configuration du robot.`));
    } else {
      const mode = it.regex != null ? 'regex' : 'words';
      card.append(field('Reconnaissance', selectCtl([{ v: 'words', l: 'Liste de mots' }, { v: 'regex', l: 'Expression régulière' }], mode, (v) => {
        if (v === 'regex') { delete it.words; it.regex = it.regex || ''; } else { delete it.regex; it.words = it.words || []; }
        intentChanged(true);
      })));
      if (mode === 'regex') {
        const rx = h('input', { type: 'text', class: 'rx', spellcheck: 'false' }); rx.value = it.regex || '';
        rx.addEventListener('change', () => { it.regex = rx.value; intentChanged(false); });
        card.append(field('Expression (validée par le robot)', rx));
      } else {
        const wrap = h('div', { class: 'fld' }, h('span', {}, 'Mots reconnus'));
        (it.words || []).forEach((w, idx) => wrap.append(h('span', { class: 'chip' }, w,
          h('button', { type: 'button', title: 'Retirer', onclick: () => { it.words.splice(idx, 1); intentChanged(true); } }, '×'))));
        if (!(it.words || []).length) wrap.append(h('div', { class: 'note' }, 'Aucun mot pour l’instant.'));
        const inp = h('input', { type: 'text', placeholder: 'Ajouter un mot ou une phrase' });
        const add = () => {
          const ws = inp.value.split(',').map((x) => x.trim()).filter(Boolean);
          if (!ws.length) return;
          it.words = (it.words || []).concat(ws.filter((x) => !(it.words || []).includes(x)));
          intentChanged(true);
        };
        inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
        wrap.append(h('div', { class: 'addrow' }, inp, h('button', { type: 'button', onclick: add }, 'Ajouter')));
        card.append(wrap);
      }
    }
    const only = h('div', { class: 'fld' }, h('span', {}, 'Seulement dans les états (aucun coché : partout)'));
    V.states.forEach((s) => only.append(checkCtl(s.label, (it.only_in || []).includes(s.id), (c) => {
      const set = new Set(it.only_in || []); c ? set.add(s.id) : set.delete(s.id);
      if (set.size) it.only_in = V.states.map((x) => x.id).filter((x) => set.has(x)); else delete it.only_in;
      intentChanged(false);
    }, stateIcon(s.id))));
    card.append(only);
    const ta = h('textarea', {}); ta.value = it.description || '';
    ta.addEventListener('change', () => { it.description = ta.value; intentChanged(false); });
    card.append(field('Description', ta));
    return card;
  }
  function renderIntents() {
    const box = $('#intents'); box.innerHTML = '';
    box.append(h('p', { class: 'hint' }, 'Phrases que le robot reconnaît et transforme en événement « intent.… », utilisable comme déclencheur. La première intention qui correspond gagne.'));
    Object.keys(meta.intents || {}).forEach((n) => box.append(intentCard(n)));
    V.intents.filter((i) => i.fixed).forEach((i) => box.append(h('div', { class: 'intent' },
      h('div', { class: 'ihead' }, ico(i.icon || 'question-mark', 'var(--cond)'), h('code', {}, 'intent.' + i.id)),
      h('div', { class: 'note' }, 'Intention implicite : toute phrase qui ne correspond à aucune autre. Non modifiable.'))));
    const nm = h('input', { type: 'text', placeholder: 'nom_de_l_intention', maxlength: 32, style: 'flex:1;width:auto;min-width:0' });
    const create = () => {
      const n = nm.value.trim();
      if (!INTENT_NAME.test(n)) { toast('Nom invalide : minuscules, chiffres et _, commence par une lettre, 32 caractères au plus.', 'err'); return; }
      if (n === 'question' || (meta.intents || {})[n]) { toast('Ce nom est déjà pris.', 'err'); return; }
      meta.intents = meta.intents || {};
      meta.intents[n] = { words: [], description: '' };
      toast(`Intention « ${n} » créée : ajoutez au moins un mot. Elle est utilisable comme déclencheur « intent.${n} ».`, 'ok');
      intentChanged(true);
    };
    nm.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); create(); } });
    box.append(h('div', { class: 'sect' }, 'Nouvelle intention'), h('div', { class: 'addrow rowbtns' }, nm, h('button', { type: 'button', class: 'primary', onclick: create }, 'Créer')));
  }

  // ---------- Variables panel (Vars L2: Game Creator 2 style Local Variables, tabs Noms / Listes) ----------
  // Edits the document's `variables` block (meta.variables) like the intents panel edits meta.intents: every change goes
  // through commitSoon() (undo / dirty / save), the server validates at save time (a deleted variable that a node still
  // uses = 400, located on that node). System variables (etat, tours, ...) and source-bound lists are read-only and
  // marked with a lock. The live column reads GET /api/graph/vars once a second, only while this tab is open.
  const varsUi = { tab: 'names', sel: null, list: null, live: null, timer: null, uses: null };
  function varsChanged(rerender) {
    commitSoon();
    analyze();
    if (rerender) renderVars();
    if (selDf != null && curTab === 'node') renderInspector();
  }
  const takenName = (id) => varDefs().some((v) => v.id === id) || listDefs().some((l) => l.id === id);
  function checkNewName(id, old) {
    if (!VAR_NAME.test(id)) return 'Nom invalide : minuscules, chiffres et _, commence par une lettre, 32 caractères au plus.';
    if (id !== old && takenName(id)) return 'Ce nom est déjà pris (les variables et les listes partagent les noms).';
    return null;
  }
  // Rename a variable or list everywhere in the canvas (args name / list, trigger name, "$name" values).
  function renameUses(old, nu) {
    const swap = (v) => (v === '$' + old ? '$' + nu : Array.isArray(v) ? v.map(swap) : v);
    for (const dfid in dfData()) {
      const m = model(dfid), p = m.params || {}, a = p.args || {};
      let hit = false;
      if (m.kind === 'trigger' && p.name === old) { p.name = nu; hit = true; }
      if (a.name === old) { a.name = nu; hit = true; }
      if (a.list === old) { a.list = nu; hit = true; }
      ['value'].forEach((k) => { if (a[k] !== undefined && swap(a[k]) !== a[k]) { a[k] = swap(a[k]); hit = true; } if (p[k] !== undefined && m.kind === 'trigger' && swap(p[k]) !== p[k]) { p[k] = swap(p[k]); hit = true; } });
      if (hit) refreshNode(dfid);
    }
  }
  // Delete only when nothing uses it; otherwise list the users (clickable) and refuse.
  function deleteVarOrList(id, isList) {
    const uses = varUses(id);
    if (uses.length) {
      varsUi.uses = { id, nodes: uses };
      toast(`« ${id} » est utilisée par ${uses.length} nœud(s) : ${uses.join(', ')}. Retirez-la de ces nœuds d'abord.`, 'err');
      renderVars(); return false;
    }
    delete docVars()[isList ? 'lists' : 'names'][id];
    if (isList) varsUi.list = null; else varsUi.sel = null;
    varsUi.uses = null;
    toast(`« ${id} » supprimée.`, 'ok');
    varsChanged(true); return true;
  }
  function liveText(v) {
    if (v === undefined) return '—';
    if (Array.isArray(v)) return '[' + v.length + ']';
    if (v === true) return 'vrai';
    if (v === false) return 'faux';
    return String(v);
  }
  async function pollVars() {
    if (curTab !== 'vars') return;
    const r = await api('/api/graph/vars');
    if (!r.ok || !r.json) return;
    varsUi.live = r.json;
    document.querySelectorAll('#vars [data-live]').forEach((el) => {
      const [kind, id] = el.dataset.live.split(':');
      el.textContent = liveText(((r.json[kind] || {})[id]));
    });
  }
  function startVarsPoll() {
    if (varsUi.timer) return;
    pollVars();
    varsUi.timer = setInterval(pollVars, 1000);       // <= 1 Hz, only while the tab is open
  }
  function stopVarsPoll() { clearInterval(varsUi.timer); varsUi.timer = null; }
  // Typed input of a variable's initial value (or a list item): checkbox / number / select / text.
  function valueInput(type, choices, value, onchange) {
    if (type === 'bool') { const c = h('input', { type: 'checkbox' }); c.checked = value === true; c.addEventListener('change', () => onchange(c.checked)); return c; }
    if (type === 'number' || type === 'duration') {
      const i = h('input', { type: 'number', step: 'any', min: type === 'duration' ? 0 : null }); i.value = value == null ? '' : value;
      i.addEventListener('change', () => onchange(i.value === '' ? 0 : Number(i.value))); return i;
    }
    if (type === 'choice') return selectCtl((choices || []).map((c) => ({ v: c, l: c })), value, onchange);
    const i = h('input', { type: 'text' }); i.value = value == null ? '' : value;
    i.addEventListener('change', () => onchange(i.value)); return i;
  }
  function usesBox(id) {
    if (!varsUi.uses || varsUi.uses.id !== id) return null;
    return h('div', { class: 'iss err vuses' }, `Suppression refusée : « ${id} » est utilisée par `,
      varsUi.uses.nodes.map((nid, k) => [k ? ', ' : '', h('a', { href: '#', class: 'navok', onclick: (e) => { e.preventDefault(); focusNode(nid); } }, nid)]).flat(), '.');
  }
  function renderVarNames(box) {
    const defs = varDefs(), names = docVars().names;
    const tbl = h('table', { class: 'vtable' }, h('thead', {}, h('tr', {}, h('th', {}, 'Nom'), h('th', {}, 'Type'), h('th', {}, 'Initiale'), h('th', { title: 'Valeur actuelle sur le robot' }, 'Live'))));
    const tb = h('tbody', {});
    defs.forEach((d) => {
      const init = d.system ? (d.id === 'etat' ? 'départ' : '—') : liveText(d.value);
      const tr = h('tr', { class: 'vrow' + (varsUi.sel === d.id ? ' on' : '') + (d.readonly ? ' ro' : ''), 'data-var': d.id, title: d.description || '',
        onclick: () => { varsUi.sel = varsUi.sel === d.id ? null : d.id; varsUi.uses = null; renderVars(); } },
        h('td', {}, d.readonly ? h('span', { class: 'lock', title: 'Variable système : lecture seule' }, ico('lock')) : null, h('code', {}, d.id)),
        h('td', {}, typeLabel(d.type)), h('td', {}, init), h('td', { class: 'vlive', 'data-live': 'names:' + d.id }, liveText(((varsUi.live || {}).names || {})[d.id])));
      tb.append(tr);
      if (d.description) tb.append(h('tr', { class: 'vdesc' }, h('td', { colspan: 4 }, d.description)));
    });
    tbl.append(tb);
    box.append(tbl);
    const d = varsUi.sel ? defs.find((x) => x.id === varsUi.sel) : null;
    if (d && d.readonly) {
      box.append(h('div', { class: 'vedit' }, h('div', { class: 'insttitle' }, ico('lock'), h('code', {}, d.id), h('small', { class: 'hint' }, 'système')),
        h('p', { class: 'hint' }, (d.description || '') + (d.id === 'etat' ? ' Changer : action « Changer d’état » ; tester : condition « etat = … ».' : ' Lecture seule : tenue par le robot.')),
        d.choices ? h('p', { class: 'hint' }, 'Valeurs : ' + d.choices.join(', ')) : null));
    } else if (d) {
      const v = names[d.id];
      const ed = h('div', { class: 'vedit' }, h('div', { class: 'insttitle' }, ico('text-caption'), h('code', {}, d.id)));
      const nm = h('input', { type: 'text', maxlength: 32, value: d.id });
      ed.append(field('Nom', h('div', { class: 'addrow' }, nm, h('button', { type: 'button', onclick: () => {
        const nu = nm.value.trim(); if (nu === d.id) return;
        const why = checkNewName(nu, d.id); if (why) { toast(why, 'err'); return; }
        const n2 = {}; Object.keys(names).forEach((k) => { n2[k === d.id ? nu : k] = names[k]; }); docVars().names = n2;
        renameUses(d.id, nu); varsUi.sel = nu; toast(`Renommée en « ${nu} » (et dans les nœuds qui l'utilisent).`, 'ok'); varsChanged(true);
      } }, 'Renommer'))));
      ed.append(field('Type', selectCtl((V.var_types || []).map((t) => ({ v: t.id, l: t.label })), v.type, (t) => {
        v.type = t; if (t === 'choice') v.choices = v.choices && v.choices.length ? v.choices : ['a', 'b']; else delete v.choices;
        v.value = t === 'string' ? '' : defaultValueFor(t, v.choices); varsChanged(true);
      }), 'Changer le type remet la valeur initiale à zéro.'));
      if (v.type === 'choice') {
        const ci = h('input', { type: 'text', value: (v.choices || []).join(', ') });
        ci.addEventListener('change', () => {
          const cs = [...new Set(ci.value.split(',').map((x) => x.trim()).filter(Boolean))];
          if (!cs.length) { toast('Un choix demande au moins une valeur.', 'err'); return; }
          v.choices = cs; if (!cs.includes(v.value)) v.value = cs[0]; varsChanged(true);
        });
        ed.append(field('Valeurs possibles (séparées par des virgules)', ci));
      }
      ed.append(field('Valeur initiale', valueInput(v.type, v.choices, v.value, (x) => { v.value = x; varsChanged(true); }), 'Valeur au chargement du graphe (les valeurs repartent de là à chaque chargement).'));
      const ta = h('textarea', { rows: 2 }); ta.value = v.description || '';
      ta.addEventListener('change', () => { if (ta.value.trim()) v.description = ta.value.trim(); else delete v.description; varsChanged(false); });
      ed.append(field('Description', ta));
      const ub = usesBox(d.id); if (ub) ed.append(ub);
      const used = varUses(d.id);
      ed.append(h('p', { class: 'hint' }, used.length ? `Utilisée par ${used.length} nœud(s) : ${used.join(', ')}.` : "Utilisée par aucun nœud."));
      ed.append(h('button', { type: 'button', class: 'danger', onclick: () => deleteVarOrList(d.id, false) }, 'Supprimer la variable'));
      box.append(ed);
    }
    // new variable
    const nn = h('input', { type: 'text', placeholder: 'nom_de_variable', maxlength: 32, style: 'flex:1;width:auto;min-width:0', 'data-new': 'var' });
    const nt = selectCtl((V.var_types || []).map((t) => ({ v: t.id, l: t.label })), 'number', () => {});
    nt.setAttribute('data-new', 'vartype');
    const create = () => {
      const id = nn.value.trim(), why = checkNewName(id, null);
      if (why) { toast(why, 'err'); return; }
      const t = nt.value, v = { type: t };
      if (t === 'choice') v.choices = ['a', 'b'];
      v.value = t === 'string' ? '' : defaultValueFor(t, v.choices);
      docVars().names[id] = v; varsUi.sel = id;
      toast(`Variable « ${id} » créée.`, 'ok'); varsChanged(true);
    };
    nn.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); create(); } });
    box.append(h('div', { class: 'sect' }, 'Nouvelle variable'), h('div', { class: 'addrow rowbtns' }, nn, nt, h('button', { type: 'button', class: 'primary', 'data-new': 'varadd', onclick: create }, 'Ajouter')));
  }
  function renderVarLists(box) {
    const lists = listDefs(), raw = docVars().lists;
    const wrap = h('div', { class: 'vlists' });
    const left = h('div', { class: 'vlleft' });
    lists.forEach((l) => left.append(h('button', { type: 'button', class: 'vlitem navok' + (varsUi.list === l.id ? ' on' : ''), 'data-list': l.id, title: l.description || '',
      onclick: () => { varsUi.list = l.id; varsUi.uses = null; renderVars(); } },
      l.readonly ? h('span', { class: 'lock' }, ico('lock')) : null, h('code', {}, l.id), h('small', {}, ' ' + l.items.length))));
    if (!lists.length) left.append(h('p', { class: 'hint' }, 'Aucune liste.'));
    const right = h('div', { class: 'vlright' });
    const l = lists.find((x) => x.id === varsUi.list) || null;
    if (!l) right.append(h('p', { class: 'hint' }, 'Choisir une liste à gauche.'));
    else {
      right.append(h('div', { class: 'insttitle' }, l.readonly ? ico('lock') : ico('text-caption'), h('code', {}, l.id), h('small', { class: 'hint' }, typeLabel(l.type, true))));
      if (l.description) right.append(h('p', { class: 'hint' }, l.description));
      if (l.readonly) {
        right.append(h('div', { class: 'note' }, l.source && l.source.cfg ? `Liée à la configuration du robot (clé « ${l.source.cfg} ») : à modifier dans la configuration. Lecture seule ici.`
          : `Mots de l’intention « ${(l.source || {}).intent} » : à modifier dans le panneau Intentions. Lecture seule ici.`));
      } else {
        const r = raw[l.id];
        right.append(field('Type des éléments', selectCtl((V.list_types || []).map((t) => ({ v: t.id, l: t.label })), r.type || 'string', (t) => {
          const conv = (x) => (t === 'number' ? (isNum(x) ? Number(x) : 0) : t === 'bool' ? (x === true || x === 'true' || x === 'vrai') : String(x));
          r.type = t; r.items = (r.items || []).map(conv); varsChanged(true);
        })));
      }
      const ul = h('ol', { class: 'vitems' });
      l.items.forEach((it, k) => {
        const li = h('li', {}, h('span', { class: 'vit' }, liveText(it)));
        if (!l.readonly) {
          const items = raw[l.id].items;
          const mv = (d) => { const j = k + d; if (j < 0 || j >= items.length) return; [items[k], items[j]] = [items[j], items[k]]; varsChanged(true); };
          li.append(h('span', { class: 'vbtns' },
            h('button', { type: 'button', title: 'Monter', disabled: k === 0, onclick: () => mv(-1) }, '↑'),
            h('button', { type: 'button', title: 'Descendre', disabled: k === items.length - 1, onclick: () => mv(1) }, '↓'),
            h('button', { type: 'button', title: 'Retirer', onclick: () => { items.splice(k, 1); varsChanged(true); } }, '×')));
        }
        ul.append(li);
      });
      if (!l.items.length) right.append(h('p', { class: 'hint' }, 'Liste vide.'));
      right.append(ul);
      right.append(h('p', { class: 'hint' }, 'Valeur live : ', h('span', { 'data-live': 'lists:' + l.id }, liveText(((varsUi.live || {}).lists || {})[l.id])), ' élément(s) sur le robot.'));
      if (!l.readonly) {
        const r = raw[l.id];
        let val = r.type === 'bool' ? false : r.type === 'number' ? 0 : '';
        const inp = valueInput(r.type || 'string', null, val, (x) => { val = x; });
        inp.setAttribute('data-new', 'item');
        const add = () => {
          if (r.type !== 'bool' && r.type !== 'number') val = inp.value.trim();
          if (val === '' || val == null) { toast('Élément vide.', 'err'); return; }
          r.items = (r.items || []).concat([val]); varsChanged(true);
        };
        if (inp.tagName === 'INPUT' && inp.type === 'text') inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
        right.append(h('div', { class: 'addrow' }, inp, h('button', { type: 'button', 'data-new': 'itemadd', onclick: add }, 'Ajouter')));
        const nm = h('input', { type: 'text', maxlength: 32, value: l.id });
        right.append(field('Nom', h('div', { class: 'addrow' }, nm, h('button', { type: 'button', onclick: () => {
          const nu = nm.value.trim(); if (nu === l.id) return;
          const why = checkNewName(nu, l.id); if (why) { toast(why, 'err'); return; }
          const n2 = {}; Object.keys(raw).forEach((k) => { n2[k === l.id ? nu : k] = raw[k]; }); docVars().lists = n2;
          renameUses(l.id, nu); varsUi.list = nu; varsChanged(true);
        } }, 'Renommer'))));
        const ta = h('textarea', { rows: 2 }); ta.value = r.description || '';
        ta.addEventListener('change', () => { if (ta.value.trim()) r.description = ta.value.trim(); else delete r.description; varsChanged(false); });
        right.append(field('Description', ta));
        const ub = usesBox(l.id); if (ub) right.append(ub);
        right.append(h('button', { type: 'button', class: 'danger', onclick: () => deleteVarOrList(l.id, true) }, 'Supprimer la liste'));
      } else { const ub = usesBox(l.id); if (ub) right.append(ub); }
    }
    wrap.append(left, right);
    box.append(wrap);
    const nn = h('input', { type: 'text', placeholder: 'nom_de_liste', maxlength: 32, style: 'flex:1;width:auto;min-width:0', 'data-new': 'list' });
    const nt = selectCtl((V.list_types || []).map((t) => ({ v: t.id, l: t.label })), 'string', () => {});
    nt.setAttribute('data-new', 'listtype');
    const create = () => {
      const id = nn.value.trim(), why = checkNewName(id, null);
      if (why) { toast(why, 'err'); return; }
      docVars().lists[id] = { type: nt.value, items: [] }; varsUi.list = id;
      toast(`Liste « ${id} » créée.`, 'ok'); varsChanged(true);
    };
    nn.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); create(); } });
    box.append(h('div', { class: 'sect' }, 'Nouvelle liste'), h('div', { class: 'addrow rowbtns' }, nn, nt, h('button', { type: 'button', class: 'primary', 'data-new': 'listadd', onclick: create }, 'Ajouter')));
  }
  function renderVars() {
    const box = $('#vars'); if (!box) return;
    const keep = box.scrollTop;
    box.innerHTML = '';
    box.append(h('p', { class: 'hint' }, 'Variables du graphe (comme les variables locales de Game Creator 2) : les déclencheurs « Une variable change » les écoutent, les actions les changent, les conditions les testent. Enregistrées avec le graphe ; leurs valeurs repartent de la valeur initiale à chaque chargement.'));
    const nV = varDefs().length, nL = listDefs().length;
    box.append(h('div', { class: 'vtabs' },
      h('button', { type: 'button', class: 'navok' + (varsUi.tab === 'names' ? ' on' : ''), 'data-vtab': 'names', onclick: () => { varsUi.tab = 'names'; renderVars(); } }, `Noms (${nV})`),
      h('button', { type: 'button', class: 'navok' + (varsUi.tab === 'lists' ? ' on' : ''), 'data-vtab': 'lists', onclick: () => { varsUi.tab = 'lists'; renderVars(); } }, `Listes (${nL})`)));
    if (varsUi.tab === 'lists') renderVarLists(box); else renderVarNames(box);
    box.scrollTop = keep;
  }

  // ---------- toast / modal ----------
  // Toasts stack top-right of the canvas (never over the drawer or the nodes' ports area).
  function toast(msg, kind) {
    const box = $('#toasts'), t = h('div', { class: 'toast ' + (kind || '') }, msg);
    box.append(t);
    while (box.children.length > 4) box.firstChild.remove();
    setTimeout(() => t.remove(), 6000);
  }
  function modal(title, body, buttons) {
    $('#mTitle').textContent = title;
    const b = $('#mBody'); b.innerHTML = ''; b.append(body);
    const bt = $('#mBtns'); bt.innerHTML = '';
    buttons.forEach((x) => bt.append(h('button', { class: x.cls || '', onclick: () => { $('#modal').hidden = true; x.fn && x.fn(); } }, x.label)));
    $('#modal').hidden = false;
  }
  function toYaml(o, ind) {
    ind = ind || '';
    const scalar = (v) => (typeof v === 'string' ? (/^[\w .\-/éèêàùçîôÉ']+$/.test(v) && v !== '' && !/^(true|false|null|\d+)$/i.test(v) ? v : JSON.stringify(v)) : v === null ? 'null' : String(v));
    if (Array.isArray(o)) {
      if (!o.length) return '[]';
      return o.map((v) => (v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length
        ? ind + '- ' + toYaml(v, ind + '  ').replace(/^\s+/, '') : ind + '- ' + (v && typeof v === 'object' ? toYaml(v, ind + '  ') : scalar(v)))).join('\n');
    }
    if (o && typeof o === 'object') {
      const ks = Object.keys(o);
      if (!ks.length) return '{}';
      return ks.map((k) => {
        const v = o[k];
        if (v && typeof v === 'object' && (Array.isArray(v) ? v.length : Object.keys(v).length)) return ind + k + ':\n' + toYaml(v, ind + '  ');
        return ind + k + ': ' + (v && typeof v === 'object' ? toYaml(v) : scalar(v));
      }).join('\n');
    }
    return ind + scalar(o);
  }

  // ---------- toolbar actions ----------
  function validate(showToast) {
    freshIds.clear();          // from here on, empty required fields count as real errors
    analyze();
    let ne = 0, nw = 0;
    issues.forEach((l) => l.forEach((i) => (i.level === 'err' ? ne++ : nw++)));
    globalIssues.forEach((i) => (i.level === 'err' ? ne++ : nw++));
    if (showToast) {
      toast(ne ? `${ne} erreur(s) à corriger, ${nw} avertissement(s).` : nw ? `Aucune erreur, ${nw} avertissement(s).` : "Structure correcte. Le robot fait la validation finale à l'enregistrement.", ne ? 'err' : 'ok');
      if (ne + nw) $('#msgs').hidden = false;
    }
    return ne;
  }
  async function postDoc(doc) {
    const r = await postJson('/api/graph/visual', doc);
    if (r.ok) {
      serverErrors = [];
      savedSnap = snap();
      liveChains = computeChains(doc);
      if (curTab === 'versions') loadVersions();
      toast(r.json.message || 'Enregistré.', r.json.applied ? 'ok' : '');
      const b = $('#banner');
      b.hidden = r.json.applied !== false;
      if (r.json.applied === false) { b.className = ''; b.textContent = 'Graphe enregistré : il sera appliqué à la prochaine veille.'; }
    } else {
      serverErrors = (r.json && r.json.errors) || [{ node: null, message: 'Erreur ' + r.status }];
      toast(serverErrors.length + " erreur(s) refusée(s) par le robot : rien n'a été écrit.", 'err');
      $('#msgs').hidden = false;
    }
    analyze(); updateBar();
    if (!r.ok && curTab === 'intents') renderIntents();     // show the per-intent server message
    return r;
  }
  async function save() {
    if (navLocked) { toast('Verrouillé — lecture seule : enregistrement désactivé (L pour déverrouiller).', 'err'); return; }
    if (validate(false)) { validate(true); return; }
    await postDoc(serialize());
  }
  async function loadAll() {
    const [vocab, vis] = await Promise.all([api('/api/graph/vocab'), api('/api/graph/visual')]);
    if (!vocab.ok || !vis.ok) { toast('Impossible de charger le graphe (' + (vocab.status || vis.status) + ').', 'err'); return; }
    V = vocab.json; serverErrors = []; simErrors = [];
    (V.kinds || []).forEach((k) => { if (KINDS[k.id] && k.icon) KINDS[k.id].icon = k.icon; });
    renderPalette();
    rebuild(vis.json, false);
    liveChains = computeChains(vis.json);
    renderPalette();
    if (curTab === 'versions') loadVersions();
    hist = [snap()]; histIdx = 0; savedSnap = hist[0];
    const b = $('#banner');
    if (vis.json.error) { b.hidden = false; b.className = 'bad'; b.textContent = 'Le fichier du graphe a été refusé au démarrage : ' + vis.json.error; }
    else if (vis.json.pending) { b.hidden = false; b.className = ''; b.textContent = "Un graphe enregistré attend la prochaine veille pour s'appliquer."; }
    else b.hidden = true;
    updateBar();
    return vis.json;
  }

  // ---------- live view ----------
  // Live snapshot: WS /ws when the server has a WebSocket library, otherwise GET /api/live polling
  // (same snapshot, 2 Hz). Polling only runs while no WS message arrived recently.
  function onLive(s) {
    if (!lastWs) dbg('live first snapshot state=' + s.state);
    lastWs = Date.now();
    onLastTransition(s.last_transition || null);
    lastAge = s.heartbeat ? s.heartbeat.age_ms : null;
    if (s.state !== liveState) { liveState = s.state; $('#liveState').textContent = 'État : ' + stateLabel(s.state); markLive(); }
    paintHeart();
  }
  // After two failed handshakes (server without a WebSocket library) stop retrying for the session:
  // each attempt would log a console error. Polling /api/live keeps the live view working.
  let wsFails = 0, wsOpened = false;
  function connectWs() {
    let ws;
    try { ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws'); } catch (e) { return; }
    ws.onopen = () => { wsOpened = true; wsFails = 0; };
    ws.onmessage = (m) => { try { onLive(JSON.parse(m.data)); } catch (e) { /* ignore bad frame */ } };
    ws.onclose = () => { if (!wsOpened && ++wsFails >= 2) return; setTimeout(connectWs, wsOpened ? 3000 : 1500); };
  }
  async function pollLive() {
    if (Date.now() - lastWs < 1500) return;
    try { const r = await api('/api/live'); if (r.ok && r.json) onLive(r.json); } catch (e) { /* offline: heart turns red */ }
  }

  function paintHeart() {
    const el = $('#heart');
    const stale = Date.now() - lastWs > 2000;
    const age = stale || lastAge == null ? 1e9 : lastAge;
    el.className = 'heart ' + (age < 500 ? 'ok' : age < 2000 ? 'slow' : 'dead');
    el.title = stale ? 'Pas de nouvelles du robot' : `Dernier battement : ${lastAge} ms`;
  }

  // ---------- right-hand panels (tabs) ----------
  let curTab = 'node';
  function activateTab(name) {
    const leaving = curTab;
    curTab = name;
    document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === name));
    document.querySelectorAll('#right .panel').forEach((p) => { p.hidden = p.dataset.panel !== name; });
    if (leaving === 'tester' && name !== 'tester') clearSimLights();   // simulator lights never linger over the live view
    if (name === 'node') renderInspector();
    if (name === 'intents') renderIntents();
    if (name === 'vars') { renderVars(); startVarsPoll(); } else stopVarsPoll();
    if (name === 'tester') { renderTester(); if (sim.trace.length) selectTrace(sim.sel < 0 ? sim.trace.length - 1 : sim.sel, false); else simRun(false); }
    if (name === 'versions') loadVersions();
    if (name === 'journal') loadJournal();
    if (innerWidth <= 900) document.body.classList.remove('hide-right');
  }
  // Transition reasons are free text set by the graph (goto "reason"), else the triggering event id.
  const REASONS = { appel: 'Nom du robot entendu', ask: 'Question tapée', chanson: 'Demande de chanson', max_turns: "Trop d'échanges",
    pas_compris: 'Parole non comprise', phrase: 'Phrase dite', refus: 'Le visiteur veut partir', silence: 'Silence prolongé',
    visage_perdu: 'Le visage disparaît', source: 'Bouton Démarrer', start: 'Démarrage', hush: '« Tais-toi »', stop: 'Bouton Stop',
    off: 'Bouton Éteindre', on: 'Bouton Allumer' };
  const reasonLabel = (r) => REASONS[r] || (byId(evs(), r) || {}).label || String(r);
  const fmtTime = (t) => new Date(t * 1000).toLocaleTimeString('fr-FR');
  const isVisible = (nid) => {
    const el = nodeEl(nidToDf.get(nid)); if (!el) return false;
    const a = el.getBoundingClientRect(), b = $('#drawflow').getBoundingClientRect();
    return a.left >= b.left && a.right <= b.right && a.top >= b.top && a.bottom <= b.bottom;
  };

  // ---------- Tester (POST /api/graph/simulate on the CURRENT, possibly unsaved, document) ----------
  // The whole step list is replayed on every call (the simulator is deterministic and isolated), so the
  // panel never has to keep a robot-side session. The latest step's fired chains light up one by one.
  const sim = { steps: [], start: '', trace: [], final: null, chains: null, sel: -1, say: '', faces: 2, wait: 7, note: '', docErrors: [], timers: [], busy: false, again: false };
  const stepText = (s) => (s.event != null ? ((byId(evs(), s.event) || {}).label || s.event) : s.say != null ? `Le visiteur dit « ${s.say} »` : s.wait_s != null ? `Attendre ${s.wait_s} s` : `${s.faces} visage(s) vu(s)`);
  const stepIcon = (s) => (s.event != null ? ((byId(evs(), s.event) || {}).icon || 'bolt') : s.say != null ? 'microphone' : s.wait_s != null ? 'hourglass' : 'users');
  function startStateId() {
    if (sim.start && (meta.states || []).some((s) => s.id === sim.start)) return sim.start;
    const st = Object.values(dfData()).map((d) => d.data.model).find((m) => m.kind === 'start');
    return (st && st.params.state) || 'veille';
  }
  function clearSimLights() {
    sim.timers.forEach(clearTimeout); sim.timers = [];
    lit.now = new Set(); lit.past = new Set(); simState = null;
    paintChains(); drawBands();
  }
  function addStep(step) { sim.note = ''; sim.steps.push(step); simRun(true); }
  async function simRun(animate) {
    if (sim.busy) { sim.again = true; return; }
    sim.busy = true;
    const doc = serialize();
    let r;
    try { r = await postJson('/api/graph/simulate', { doc, start_state: startStateId(), steps: sim.steps }); }
    catch (e) { r = { ok: false, status: 0, json: { errors: [{ message: 'Réseau : ' + e }] } }; }
    sim.busy = false;
    simErrors = []; sim.docErrors = [];
    if (!r.ok) {
      const errs = (r.json && r.json.errors) || [{ node: null, message: 'Erreur ' + r.status }];
      const stepErr = errs.filter((e) => e.step != null);
      if (stepErr.length) {                       // refused step(s): drop them, tell why, replay without
        const bad = new Set(stepErr.map((e) => e.step));
        sim.steps = sim.steps.filter((_, i) => !bad.has(i));
        sim.note = 'Pas refusé par le simulateur : ' + stepErr.map((e) => e.message).join(' ');
        return simRun(false);
      }
      simErrors = errs; sim.docErrors = errs; sim.trace = []; sim.final = null; sim.sel = -1;
      clearSimLights(); analyze(); renderTester();
      if (simErrors.some((e) => e.node)) $('#msgs').hidden = false;
      return r;
    }
    sim.trace = r.json.trace || []; sim.final = r.json.final || null; sim.chains = computeChains(doc);
    analyze();
    const last = sim.steps.length - 1;
    const fresh = sim.trace.map((e, i) => (e.step === last ? i : -1)).filter((i) => i >= 0);
    sim.timers.forEach(clearTimeout); sim.timers = [];
    if (animate && fresh.length > 1) {
      fresh.forEach((i, k) => sim.timers.push(setTimeout(() => selectTrace(i, k === fresh.length - 1 ? 'fit' : true), k * 400)));
      selectTrace(fresh[0], true);
    } else selectTrace(sim.trace.length - 1, 'fit');
    renderTester();
    if (sim.again) { sim.again = false; return simRun(false); }
    return r;
  }
  // Light the chain of trace entry i (current) and every entry before it (already fired).
  function selectTrace(i, pan) {
    sim.sel = i;
    const idsOf = (e) => (sim.chains && sim.chains.keys.get(e.chain)) || [];
    lit.now = new Set(i >= 0 && sim.trace[i] ? idsOf(sim.trace[i]) : []);
    lit.past = new Set();
    sim.trace.slice(0, Math.max(i, 0)).forEach((e) => idsOf(e).forEach((x) => lit.past.add(x)));
    simState = sim.trace[i] ? sim.trace[i].to : null;
    paintChains(); drawBands(); renderSimTrace();
    // L7 fix round: every displayed step brings its chain to the middle of the canvas (~0.75 zoom, or the whole
    // chain when larger); `pan === false` (tab switch) keeps the user's view
    if (pan !== false && i >= 0 && sim.trace[i]) focusChainIds(idsOf(sim.trace[i]));
  }
  // Frame every lit node (fired chains in blue, current one in yellow) when they fit at zoom >= 0.3;
  // otherwise keep that zoom and centre on the current chain.
  function fitLit() {
    const box = (set) => {
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      set.forEach((nid) => { const d = nidToDf.get(nid); if (d == null) return; const b = nodeBox(d); x0 = Math.min(x0, b.x0); y0 = Math.min(y0, b.y0); x1 = Math.max(x1, b.x1); y1 = Math.max(y1, b.y1); });
      return x0 > x1 ? null : { x0, y0, x1, y1 };
    };
    const all = box(new Set([...lit.now, ...lit.past])), now = box(lit.now), c = $('#drawflow');
    if (!all || !now) return;
    const w = all.x1 - all.x0, hh = all.y1 - all.y0;
    const z = Math.max(0.3, Math.min(1, c.clientWidth / (w * 1.1), c.clientHeight / (hh * 1.1)));
    const b = w * z <= c.clientWidth && hh * z <= c.clientHeight ? all : now;
    setView(z, c.clientWidth / 2 - ((b.x0 + b.x1) / 2) * z, c.clientHeight / 2 - ((b.y0 + b.y1) / 2) * z);
  }
  function renderSimTrace() {
    const box = $('#simTrace'); if (!box) return;
    box.innerHTML = ''; $('#simStatus').innerHTML = '';   // status card sits outside the scrolling trace so it never gets clipped
    if (sim.note) box.append(h('div', { class: 'simerr' }, sim.note));
    sim.docErrors.forEach((e) => box.append(h('div', { class: 'simerr', onclick: () => e.node && focusNode(e.node) }, (e.node ? e.node + ' : ' : '') + e.message)));
    if (sim.docErrors.length) box.append(h('p', { class: 'hint' }, 'Le robot refuse ce document : corrigez les nœuds en rouge, puis relancez.'));
    const f = sim.final;
    if (f) {
      const ex = f.expression ? (typeof f.expression === 'string' ? f.expression : f.expression.name) : 'aucune';
      $('#simStatus').append(h('div', { class: 'simstate' }, ico(stateIcon(f.state)), 'État simulé : ', h('b', {}, stateLabel(f.state)),
        h('span', { class: 'hint' }, `· tours ${f.turns} · expression ${ex} · regard ${f.gaze_mode}`)));
    }
    // Vars L2: simulated variables after the selected trace entry (else the final ones); changed ones highlighted
    // against the entry before it.
    const cur = sim.trace[sim.sel] ? sim.trace[sim.sel].vars : (f && f.vars);
    if (cur) {
      const prev = sim.sel > 0 && sim.trace[sim.sel - 1] ? sim.trace[sim.sel - 1].vars : null;
      const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
      const grid = h('div', { class: 'simvars', title: 'Variables simulées après ce pas (en couleur : changées par ce pas)' },
        h('span', { class: 'svlab' }, sim.trace[sim.sel] ? 'Variables après la ligne choisie :' : 'Variables à la fin :'));
      Object.keys(cur.names || {}).forEach((k) => {
        const v = cur.names[k], chg = !!prev && !same(v, (prev.names || {})[k]);
        grid.append(h('span', { class: 'sv' + (chg ? ' chg' : ''), 'data-svar': k }, h('code', {}, k), ' = ', k === 'etat' ? stateLabel(v) : liveText(v)));
      });
      Object.keys(cur.lists || {}).forEach((k) => {
        const v = cur.lists[k], chg = !!prev && !same(v, (prev.lists || {})[k]);
        grid.append(h('span', { class: 'sv list' + (chg ? ' chg' : ''), 'data-svar': k, title: (v || []).join(' · ') }, h('code', {}, k), ' ', liveText(v)));
      });
      $('#simStatus').append(grid);
    }
    for (let st = -1; st < sim.steps.length; st++) {
      const rows = sim.trace.map((e, i) => ({ e, i })).filter((x) => x.e.step === st);
      const s = sim.steps[st];
      box.append(h('div', { class: 'sstep' }, ico(st < 0 ? 'flag' : stepIcon(s)), st < 0 ? 'Démarrage' : `${st + 1}. ${stepText(s)}`));
      if (!rows.length) box.append(h('div', { class: 'note' }, 'Rien ne se déclenche.'));
      rows.forEach(({ e, i }) => box.append(h('div', { class: 'trow' + (i === sim.sel ? ' sel' : ''), onclick: () => selectTrace(i, true) },
        h('div', {}, ico(stateIcon(e.to)), ' ', e.moved ? [stateLabel(e.from), h('span', { class: 'arrow' }, ' → '), stateLabel(e.to)] : ['Reste en ', stateLabel(e.to)],
          h('span', { class: 'hint' }, e.reason ? '  (' + reasonLabel(e.reason) + ')' : '')),
        h('div', { class: 'meta' }, `${Number(e.t).toFixed(1)} s · chaîne ${e.chain}` + ((e.effects || []).length ? ' · ' + e.effects.join(', ') : '')))));
    }
    const sel = box.querySelector('.trow.sel');
    if (sel) sel.scrollIntoView({ block: 'nearest' });
  }
  function renderTester() {
    const box = $('#tester'); if (!box) return;
    box.innerHTML = '';
    box.append(h('p', { class: 'hint' }, "Essaie le graphe en cours d'édition (même non enregistré) sur un robot simulé : sans son ni micro, le vrai robot n'est jamais touché."));
    box.append(field('État de départ', selectCtl((meta.states || []).map((s) => ({ v: s.id, l: stateLabel(s.id) })), startStateId(), (v) => { sim.start = v; sim.note = ''; simRun(false); })));
    // Result first (state + trace, scrolls on its own), controls below.
    box.append(h('div', { id: 'simStatus' }), h('div', { id: 'simTrace' }));
    box.append(h('div', { class: 'sect' }, 'Un événement arrive'));
    const grid = h('div', { class: 'evgrid' });
    V.events.forEach((e) => grid.append(h('button', { type: 'button', title: e.help || e.label, onclick: () => addStep({ event: e.id }) }, ico(e.icon), h('span', { class: 't' }, e.label))));
    box.append(grid);
    box.append(h('div', { class: 'sect' }, 'Le visiteur dit…'));
    const say = h('input', { type: 'text', placeholder: 'ex. au revoir', style: 'flex:1;width:auto;min-width:0' }); say.value = sim.say;
    say.addEventListener('input', () => { sim.say = say.value; });
    const doSay = () => { const t = say.value.trim(); if (!t) return; sim.say = ''; addStep({ say: t }); };
    say.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); doSay(); } });
    box.append(h('div', { class: 'rowbtns' }, say, h('button', { type: 'button', onclick: doSay }, ico('microphone'), 'Dire')));
    box.append(h('div', { class: 'sect' }, 'Laisser passer du temps'));
    const wn = h('input', { type: 'number', min: 0.1, step: 0.5, 'aria-label': 'secondes' }); wn.value = sim.wait;
    wn.addEventListener('input', () => { sim.wait = wn.value; });
    box.append(h('div', { class: 'rowbtns' },
      h('button', { type: 'button', onclick: () => addStep({ wait_s: 5 }) }, ico('hourglass'), 'Attendre 5 s'),
      h('button', { type: 'button', onclick: () => addStep({ wait_s: 10 }) }, ico('hourglass'), 'Attendre 10 s'),
      wn, h('button', { type: 'button', onclick: () => { const n = Number(wn.value); if (n > 0 && n <= 3600) addStep({ wait_s: n }); } }, 'Attendre (s)')));
    const fn = h('input', { type: 'number', min: 0, max: 20, step: 1, 'aria-label': 'visages' }); fn.value = sim.faces;
    fn.addEventListener('input', () => { sim.faces = fn.value; });
    box.append(h('div', { class: 'sect' }, 'Visages vus par la caméra (facultatif)'),
      h('div', { class: 'rowbtns' }, fn, h('button', { type: 'button', onclick: () => { const n = Math.max(0, Math.min(20, parseInt(fn.value, 10) || 0)); addStep({ faces: n }); } }, ico('users'), 'Appliquer')));
    box.append(h('div', { class: 'rowbtns', style: 'margin-top:12px' },
      h('button', { type: 'button', class: 'danger', onclick: async () => { sim.steps = []; sim.note = ''; await simRun(false); clearSimLights(); } }, ico('refresh'), 'Réinitialiser'),   // L7: no highlight after a reset
      h('button', { type: 'button', onclick: () => { sim.steps.pop(); sim.note = ''; simRun(false); }, disabled: !sim.steps.length }, ico('x'), 'Retirer le dernier pas')));
    renderSimTrace();
  }

  // ---------- Versions (GET /api/graph/versions, POST .../restore) ----------
  async function loadVersions() {
    const box = $('#versions'); if (!box) return;
    box.innerHTML = ''; box.append(h('p', { class: 'hint' }, 'Chargement…'));
    const r = await api('/api/graph/versions');
    box.innerHTML = '';
    if (!r.ok || !r.json) { box.append(h('p', { class: 'hint' }, 'Liste indisponible (' + r.status + ').')); return; }
    box.append(h('p', { class: 'hint' }, `Une copie datée est gardée à chaque enregistrement (les ${r.json.max || 30} dernières).`));
    if (!r.json.versions.length) box.append(h('p', { class: 'hint' }, "Aucune sauvegarde pour l'instant."));
    r.json.versions.forEach((v) => {
      const s = v.summary || {};
      const sum = s.error ? 'Illisible : ' + s.error : `${s.states} états · ${s.chains} chaînes` + (s.disabled ? ` · ${s.disabled} désactivée(s)` : '');
      const when = new Date(v.date).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'medium' });
      box.append(h('div', { class: 'row' }, ico('clock'),
        h('div', { class: 'grow' }, h('div', {}, when), h('div', { class: 'sub' }, sum + ' · ' + Math.round((v.size || 0) / 1024 * 10) / 10 + ' Ko')),
        h('button', { type: 'button', disabled: !!s.error, onclick: () => confirmRestore(v, when) }, 'Restaurer')));
    });
  }
  function confirmRestore(v, when) {
    modal('Restaurer cette version ?',
      h('div', {}, h('p', {}, 'Version du ' + when + '.'),
        h('p', {}, "Le graphe actuel est sauvegardé d'abord : rien n'est perdu. Les modifications non enregistrées dans l'éditeur sont abandonnées.")),
      [{ label: 'Annuler' }, { label: 'Restaurer', cls: 'primary', fn: async () => {
        const r = await postJson('/api/graph/versions/' + encodeURIComponent(v.id) + '/restore', {});
        if (r.ok) {
          toast((r.json && r.json.message) || 'Version restaurée.', r.json && r.json.applied ? 'ok' : '');
          await loadAll();
          if (curTab === 'versions') loadVersions();
        } else {
          const why = r.json && (r.json.message || (r.json.errors || []).map((e) => e.message).join(' ') || r.json.detail) || '';
          toast('Restauration refusée (' + r.status + ') ' + why, 'err');
        }
      } }]);
  }

  // ---------- Journal (GET /api/graph/trace at open, then WS / live `last_transition`) ----------
  let journal = [], liveSeen = false, seenT = 0;
  async function loadJournal() {
    const r = await api('/api/graph/trace');
    if (r.ok && r.json) journal = (r.json.trace || []).slice(-50);
    renderJournal();
  }
  function focusChain(key) {
    const ids = liveChains.keys.get(key);
    if (!ids) { toast("Cette chaîne n'existe pas dans le graphe affiché (" + key + ').', ''); return; }
    focusNode(ids[0]); blinkChain(key);
  }
  function renderJournal() {
    const box = $('#journal'); if (!box || box.hidden) return;
    box.innerHTML = '';
    box.append(h('p', { class: 'hint' }, 'Les 50 dernières chaînes déclenchées sur le vrai robot, en direct. Cliquer une ligne pour voir sa chaîne.'));
    if (!journal.length) box.append(h('p', { class: 'hint' }, "Rien pour l'instant."));
    journal.slice().reverse().forEach((e) => {
      const ev = byId(evs(), e.event);
      box.append(h('div', { class: 'trow', onclick: () => focusChain(e.chain) },
        h('div', {}, ico(ev ? ev.icon : 'clock'), ' ', e.moved ? [stateLabel(e.from), h('span', { class: 'arrow' }, ' → '), stateLabel(e.to)] : ['Reste en ', stateLabel(e.to)]),
        h('div', { class: 'meta' }, `${fmtTime(e.t)} · ${ev ? ev.label : e.event || 'délai'}` + (e.reason && reasonLabel(e.reason) !== (ev && ev.label) ? ' · ' + reasonLabel(e.reason) : '') + ' · chaîne ' + e.chain)));
    });
  }
  function onLastTransition(lt) {
    if (!liveSeen) { liveSeen = true; seenT = lt ? lt.t : 0; return; }   // first snapshot: history, not news
    if (!lt || lt.t === seenT) return;
    seenT = lt.t;
    if (!journal.length || journal[journal.length - 1].t !== lt.t) journal.push(lt);
    journal = journal.slice(-50);
    renderJournal();
    blinkChain(lt.chain);
  }

  // ---------- no wire into a trigger (Vars L2) ----------
  // A trigger has no input port, so Drawflow silently drops a wire released on it. Tell the user why: when a wire drag
  // (editor.connection) ends over a trigger card, toast the rule. Hit-test by card rectangles (the dragged path may be
  // the topmost element under the pointer). Nothing is linked either way.
  function installTriggerDropGuard() {
    const onUp = (e) => {
      if (!editor || !editor.connection) return;
      const pt = e.changedTouches ? e.changedTouches[0] : e;
      if (!pt) return;
      const data = dfData();
      for (const dfid in data) {
        if (data[dfid].data.model.kind !== 'trigger') continue;
        const el = nodeEl(dfid); if (!el) continue;
        const r = el.getBoundingClientRect();
        if (pt.clientX >= r.left && pt.clientX <= r.right && pt.clientY >= r.top && pt.clientY <= r.bottom) {
          noInputRefusals++; toast(NO_TRIGGER_INPUT, 'err'); return;
        }
      }
    };
    editor.container.addEventListener('mouseup', onUp, true);
    editor.container.addEventListener('touchend', onUp, true);
  }
  let noInputRefusals = 0;   // test hook: wires refused because they ended on a trigger

  // ---------- boot ----------
  async function boot() {
    // Test hook: `#hold=<port>` keeps the page "loading" until a slow local image answers, so a headless
    // `firefox --screenshot` (taken at the load event) sees the finished async rendering.
    const hold = (location.hash.match(/hold=(\d+)/) || [])[1];
    if (hold) document.body.append(h('img', { src: 'http://127.0.0.1:' + hold + '/hold.gif', width: 1, height: 1 }));
    editor = new Drawflow($('#drawflow'));
    editor.reroute = false;
    editor.zoom_min = 0.03; editor.zoom_max = 1.6;
    editor.start();
    editor.on('nodeSelected', (id) => {
      selDf = id; selConn = null;
      if (selFrame) { selFrame = null; drawFrames(); }
      if (selNote) { selNote = null; noteEls.forEach((el) => el.classList.remove('sel')); }
      renderInspector(); if (innerWidth <= 900) document.body.classList.remove('hide-right');
    });
    editor.on('nodeUnselected', () => { selDf = null; renderInspector(); });
    editor.on('connectionSelected', (c) => {
      selConn = { out: c.output_id, in: c.input_id, outCls: c.output_class }; selDf = null;
      if (selNote) { selNote = null; noteEls.forEach((el) => el.classList.remove('sel')); }
      renderInspector(); if (innerWidth <= 900) document.body.classList.remove('hide-right');
    });
    editor.on('connectionUnselected', () => { selConn = null; renderInspector(); });
    editor.on('nodeMoved', commitSoon);
    editor.on('nodeRemoved', (id) => { if (loading) return; for (const [k, v] of nidToDf) if (String(v) === String(id)) nidToDf.delete(k); selDf = null; renderInspector(); commitSoon(); });
    editor.on('connectionCreated', (c) => {
      if (loading) return;
      const a = model(c.output_id), b = model(c.input_id), why = a && b ? linkProblem(a, b) : null;
      if (why) {                                  // same rules as the server; the wire is dropped at once
        editor.removeSingleConnection(c.output_id, c.input_id, c.output_class, c.input_class);
        toast(why, 'err'); return;
      }
      commitSoon();
    });
    editor.on('connectionRemoved', (c) => {
      const a = model(c.output_id), b = model(c.input_id);
      if (a && b) { const idx = +c.output_class.split('_')[1]; linkMeta.delete(linkKey(a.id, a.kind === 'condition' ? (idx === 1 ? 'true' : 'false') : 'out', b.id)); }
      if (selConn && String(selConn.out) === String(c.output_id) && String(selConn.in) === String(c.input_id)) selConn = null;
      commitSoon();
    });
    // Wires are repainted (gradient from the source kind colour to the target kind colour) whenever Drawflow redraws them.
    const origUpdate = editor.updateConnectionNodes.bind(editor);
    editor.updateConnectionNodes = (id) => { origUpdate(id); paintWires(id); };
    // L3: the dragged wire starts with its source node's kind colour (not the red / green port pastille), and a
    // freshly linked wire is painted at once (Drawflow does not redraw a node's wires when a link is created).
    editor.on('connectionStart', (c) => { const m = model(c.output_id); dragSrcKind = m ? m.kind : null; paintDragWire(); });
    const origDragUpdate = editor.updateConnection.bind(editor);
    editor.updateConnection = (x, y) => { origDragUpdate(x, y); paintDragWire(x, y); };
    editor.on('connectionCreated', (c) => { dragSrcKind = null; requestAnimationFrame(() => paintWires('node-' + c.output_id)); });
    editor.on('connectionCancel', () => { dragSrcKind = null; });
    // Lot L4: Drawflow ends a node drag / pan / wire drag on a `mouseup` of its CONTAINER only. Released over a side
    // panel (palette, inspector), the drag never ended: the node stayed glued to the pointer when it came back, and
    // after an undo rebuild the stale `ele_selected` threw TypeErrors on every move. Finish it from window, only when
    // the release happened outside the canvas (inside, Drawflow's own handler already ran and cleared the flags).
    const finishOutside = (e) => {
      if (!(editor.drag || editor.drag_point || editor.connection || editor.editor_selected)) return;
      if (editor.container.contains(e.target)) return;
      editor.dragEnd(e);
    };
    window.addEventListener('mouseup', finishOutside);
    window.addEventListener('touchend', finishOutside);
    installRetHover();
    editor.on('zoom', zoomVars); editor.on('translate', scheduleMinimap);
    setRetVisible(retVisible());
    // Vars L2: no returning wires any more (no hubs); the toggle stays wired only if a page still has the button
    if ($('#btnRet')) $('#btnRet').onclick = () => setRetVisible(!document.body.classList.contains('ret-visible'));
    $('#btnVars').onclick = () => activateTab('vars');
    installButtonGuards();
    installTriggerDropGuard();
    installSafeNav();      // L8: registered before the keydown below so its capture handlers run first

    // Keys typed in inspector fields must never reach Drawflow (its Delete handler would remove the selected node).
    window.addEventListener('keydown', (e) => {
      if (ctx) {
        if (e.target.classList && e.target.classList.contains('csearch')) return;   // the menu's search box handles its own keys
        if (ctxKey(e)) return;
      }
      if (e.target.classList && e.target.classList.contains('finput')) return;   // inline group rename handles its own Enter/Escape
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) { e.stopPropagation(); return; }
      if (selFrame && e.key === 'Delete') { e.preventDefault(); e.stopPropagation(); deleteFrame(selFrame); return; }
      if (selNote && e.key === 'Delete') { e.preventDefault(); e.stopPropagation(); deleteNote(selNote); return; }
      if (e.key.toLowerCase() === 'g' && !e.ctrlKey && !e.metaKey && !e.altKey && $('#modal').hidden) { e.preventDefault(); addFrame(); return; }
      if (e.key.toLowerCase() === 'n' && !e.ctrlKey && !e.metaKey && !e.altKey && $('#modal').hidden) { e.preventDefault(); addNote(); return; }
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'c' && selDf != null) { e.preventDefault(); copyNode(selDf); return; }
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'v' && clipboard) { e.preventDefault(); pasteNode(); return; }
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); }
      else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) { e.preventDefault(); redo(); }
    }, true);

    const dfEl = $('#drawflow');
    // Frame and note drags are tracked on the document so they survive the pointer leaving the title bar.
    document.addEventListener('mousemove', moveFrameDrag); document.addEventListener('mouseup', endFrameDrag);
    document.addEventListener('touchmove', moveFrameDrag, { passive: false }); document.addEventListener('touchend', endFrameDrag);
    // notes: ONE pointer pair (captured pointer, see startNoteDrag)
    document.addEventListener('pointermove', moveNoteDrag, { passive: false });
    document.addEventListener('pointerup', endNoteDrag); document.addEventListener('pointercancel', endNoteDrag);
    // A press on the bare canvas or on a node unselects the frame / note (their own presses stop before here).
    dfEl.addEventListener('mousedown', (e) => { if (!e.target.closest('.drawflow-node')) { unselectFrame(); unselectNote(); } });
    dfEl.addEventListener('dragover', (e) => e.preventDefault());
    dfEl.addEventListener('drop', (e) => {
      e.preventDefault();
      if (editBlocked()) return;                 // lock / hand tool: palette drops refused
      try { const d = JSON.parse(e.dataTransfer.getData('text/plain')); addAt(d.kind, d.preset, canvasPoint(e.clientX, e.clientY)); } catch (err) { /* foreign drop */ }
    });

    $('#search').addEventListener('input', renderPalette);
    $('#btnGroup').onclick = () => addFrame();
    $('#btnNote').onclick = () => addNote();
    $('#btnUndo').onclick = undo; $('#btnRedo').onclick = redo; $('#btnFit').onclick = fit;
    $('#btnValidate').onclick = () => validate(true);
    $('#btnSave').onclick = save;
    $('#btnMsgs').onclick = () => { $('#msgs').hidden = !$('#msgs').hidden; };
    $('#btnLeft').onclick = () => document.body.classList.toggle('hide-left');
    $('#btnRight').onclick = () => document.body.classList.toggle('hide-right');
    document.querySelectorAll('#tabs button').forEach((b) => { b.onclick = () => activateTab(b.dataset.tab); });
    document.addEventListener('click', () => document.querySelectorAll('.ddl').forEach((l) => { l.hidden = true; }));
    $('#btnYaml').onclick = async () => {
      const r = await api('/api/graph');
      if (!r.ok) { toast('Lecture impossible.', 'err'); return; }
      const src = r.json.source ? 'Source : ' + r.json.source + '\n\n' : '';
      modal('Graphe actif (YAML, lecture seule)', h('pre', {}, src + toYaml(r.json)), [{ label: 'Fermer' }]);
    };
    $('#btnReset').onclick = () => modal('Revenir au graphe par défaut ?',
      h('p', {}, 'Le graphe actuel est sauvegardé, puis remplacé par celui livré avec le robot. Vos positions de nœuds sont effacées.'),
      [{ label: 'Annuler' }, { label: 'Revenir au graphe par défaut', cls: 'danger', fn: async () => {
        const r = await postJson('/api/graph/reset', {});
        toast(r.ok ? r.json.message : 'Échec (' + r.status + ')', r.ok ? 'ok' : 'err');
        if (r.ok) await loadAll();
      } }]);
    $('#modal').addEventListener('click', (e) => { if (e.target.id === 'modal') $('#modal').hidden = true; });
    if (innerWidth <= 900) { document.body.classList.add('hide-left'); document.body.classList.add('hide-right'); }

    await loadAll();
    loadJournal();
    connectWs();
    setInterval(paintHeart, 500);
    setInterval(pollLive, 500);
    window.addEventListener('beforeunload', (e) => { if (hist[histIdx] !== savedSnap) { e.preventDefault(); e.returnValue = ''; } });
    runDebug();
  }

  // ---------- test hooks (used by the verification scenarios; harmless in normal use) ----------
  window.__editor = { serialize, postDoc, loadAll, errors: errLog, nodeCount: () => Object.keys(dfData()).length,
    activateTab, sim, addStep, simRun, computeChains, liveChains: () => liveChains, focusBand, focusNode, fit, intentCard, renderIntents,
    panDf: (dfid) => { const d = dfNode(dfid), st = $('#drawflow'), z = 0.9; setView(z, st.clientWidth / 2 - (d.pos_x + 400) * z, st.clientHeight / 2 - (d.pos_y + 40) * z); },
    frames, addFrame, selectFrame, focusFrame, editFrame, deleteFrame, editFrameTitle, selFrame: () => selFrame,
    dfMap: () => Object.fromEntries(nidToDf), fanInfo: () => fanInfo,   // test hooks (headless checks)
    notes, addNote, selectNote, deleteNote, editNote, selNote: () => selNote, paintWires, openContextFor, closeCtx, addAt, linkNodes, copyNode, pasteNode,
    linkMeta: () => Object.fromEntries(linkMeta), clipboard: () => clipboard, ctxOpen: () => !!ctx,
    meta: () => meta, journal: () => journal, renderVars, varsUi, varDefs, listDefs, varUses, noInputRefusals: () => noInputRefusals, kinds: () => KINDS, loadJournal, loadVersions, selectTrace, toast,
    nav: () => ({ locked: navLocked, hand: navHand, space: navSpace, zoom: editor.zoom, x: editor.canvas_x, y: editor.canvas_y }),
    setHand, setLock, toggleHelp, save,
    rebuild: (d) => rebuild(d, true),
    dfState: () => ({ drag: editor.drag, editorSel: editor.editor_selected, ele: editor.ele_selected ? (editor.ele_selected.id || editor.ele_selected.className) : null }) };   // L4 test hook: load a (legacy) document without touching the server
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function runDebug() {
    const mode = (location.hash.match(/debug=(\w+)/) || [])[1];
    if (!mode) return;
    await new Promise((r) => setTimeout(r, 800));
    if (mode === 'band') { focusBand('veille'); dbg('band'); }
    else if (mode === 'icons') { focusBand('ecoute', 0.7); dbg('icons errors=' + errLog.length); }
    else if (mode === 'tester') {
      // "visage -> dit au revoir": visage in veille, let the greeting end, then the visitor says goodbye.
      activateTab('tester');
      await sleep(300);
      sim.steps = [{ event: 'visage' }, { wait_s: 4 }, { say: 'au revoir' }];
      await simRun(false);
      await sleep(300);
      const r = sim.final;
      dbg('sim final=' + JSON.stringify(r) + ' trace=' + sim.trace.map((e) => e.chain).join(','));
    } else if (mode === 'versions') { activateTab('versions'); }
    else if (mode === 'journal') { activateTab('journal'); await sleep(500); }
    else if (mode === 'intents') {
      activateTab('intents');
      meta.intents = meta.intents || {};
      meta.intents.au_secours = { words: ['au secours', 'aidez-moi'], only_in: ['ecoute', 'relance'], description: 'Le visiteur appelle à l’aide.' };
      renderIntents(); renderPalette();
      document.querySelector('#intents').scrollTop = 99999;
      dbg('intent trigger offered: ' + !!byId(evs(), 'intent.au_secours'));
    }
    else if (mode === 'fit') { fit(); }
    else if (mode === 'select') {
      const first = Object.keys(dfData()).find((i) => model(i).kind === 'action');
      focusNode(model(first).id);
      dbg('select done; errors=' + errLog.length);
    } else if (mode === 'error') {
      const doc = serialize();
      const g = doc.nodes.find((n) => n.kind === 'action' && n.params.action === 'set_var' && (n.params.args || {}).name === 'etat');
      g.params.args.value = 'etat_inexistant';
      const r = await postDoc(doc);       // 400 expected: nothing written
      focusNode(g.id);
      dbg('POST status=' + r.status + ' errors=' + JSON.stringify(r.json));
    } else if (mode === 'roundtrip') {
      const before = (await api('/api/graph')).json;
      const vis = (await api('/api/graph/visual')).json;
      const doc = serialize();
      const norm = (d) => JSON.stringify({ n: d.nodes.length, l: d.links.length,
        nodes: d.nodes.map((n) => [n.id, n.kind, JSON.stringify(n.params), n.group || '', n.description || '']).sort(),
        links: d.links.map((l) => l.from + l.port + l.to).sort() });
      dbg('visual==serialized (ids,kind,params,group,links): ' + (norm(vis) === norm(doc)) + ' nodes=' + doc.nodes.length + ' links=' + doc.links.length);
      const r = await postJson('/api/graph/visual', doc);
      dbg('POST status=' + r.status + ' ' + JSON.stringify(r.json));
      const after = (await api('/api/graph')).json;
      const strip = (g) => { const c = clone(g); delete c.source; return JSON.stringify(c); };
      dbg('GET /api/graph identical except source: ' + (strip(before) === strip(after)) + ' (source ' + before.source + ' -> ' + after.source + ')');
      const rs = await postJson('/api/graph/reset', {});
      dbg('reset status=' + rs.status + ' ' + JSON.stringify(rs.json));
      const fin = (await api('/api/graph')).json;
      dbg('after reset identical except source: ' + (strip(before) === strip(fin)) + ' source=' + fin.source);
      dbg('console errors: ' + errLog.length);
    }
  }

  boot().catch((e) => { errLog.push(String(e)); dbg('BOOT ' + e + '\n' + (e.stack || '')); toast('Erreur au démarrage : ' + e, 'err'); });
})();
