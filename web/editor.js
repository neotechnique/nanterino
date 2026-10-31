/**
 * Nanterino visual graph editor (Game Creator 2 style node editor).
 *
 * Purpose : draw / edit the robot dialogue graph as nodes (Start, Trigger, Condition, Action, Goto, End) and
 *           round-trip it through the node-document contract (Notes/graph-visual-format.md).
 * Boundary: talks only to GET /api/graph/visual, /api/graph/vocab, /api/graph, /api/graph/versions,
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
    start:     { label: 'Début',            cls: 'start',     ins: 0, outs: 1, color: 'var(--start)',   icon: 'flag' },
    // Trigger input: optional, accepts links from state nodes only ("valid in this state"); none = global rule.
    trigger:   { label: 'Déclencheur',      cls: 'trigger',   ins: 1, outs: 1, color: 'var(--trigger)', icon: 'bolt' },
    condition: { label: 'Condition',        cls: 'condition', ins: 1, outs: 2, color: 'var(--cond)',    icon: 'git-branch' },
    action:    { label: 'Action',           cls: 'action',    ins: 1, outs: 1, color: 'var(--action)',  icon: 'player-play' },
    // Legacy terminal (only drawn when a document still carries one; the palette never offers it).
    goto:      { label: "Aller à l'état",   cls: 'goto',      ins: 1, outs: 0, color: 'var(--goto)',    icon: 'arrow-right' },
    end:       { label: 'Fin',              cls: 'end',       ins: 1, outs: 0, color: 'var(--end)',     icon: 'square' },
    // One hub per state: output = chains valid in that state, input = chains that end by going there.
    state:     { label: 'État',             cls: 'state',     ins: 1, outs: 1, color: 'var(--state)',   icon: 'circle-dot' },
  };
  const NOT_IN_PALETTE = new Set(['goto', 'state']);
  const NODE_KINDS = ['start', 'trigger', 'condition', 'action', 'end'];   // "Blocs" section of the palette
  // Post-it palette (pastel), first = default.
  const NOTE_COLORS = [['Jaune', '#fff59d'], ['Rose', '#f8bbd0'], ['Vert', '#c8e6c9'], ['Bleu', '#bbdefb'], ['Orange', '#ffe0b2'], ['Violet', '#e1bee7']];
  // Link rules (mirror of graph_visual.from_visual; the server stays the judge): Start -> state, state -> trigger,
  // a trigger only receives from a state, everything else may feed any node that has an input.
  function linkProblem(from, to) {
    const a = from.kind, b = to.kind;
    if (b === 'start') return 'Le nœud Début ne reçoit aucun lien.';
    if (a === 'start' && b !== 'state') return 'Début se relie seulement à un nœud État.';
    if (a === 'state' && b !== 'trigger') return "La sortie d'un état se relie seulement à un déclencheur.";
    if (b === 'trigger' && a !== 'state') return "Un déclencheur n'accepte de lien que depuis un nœud État.";
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
        if (p.type === 'event') { const e = byId(evs(), p.event); return e ? e.label : '? ' + (p.event || ''); }
        if (p.type === 'after') {
          const s = byId(V.since, p.since || 'state');
          return 'Après ' + delayText(p.delay) + ' ' + (s ? s.label : '');
        }
        if (p.type === 'enter') return "À l'entrée dans " + stateLabel(p.state);
        return '?';
      case 'condition':
        if (p.type === 'state') return (p.negate ? 'Pas dans : ' : 'Dans : ') + (p.states || []).map(stateLabel).join(', ');
        { const g = byId(V.guards, p.guard); return (p.negate ? 'Non : ' : '') + (g ? g.label : '? ' + (p.guard || '')); }
      case 'action': {
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
    nodes.filter((n) => n.kind === 'trigger' && !inOrder.has(n.id) && (n.params || {}).type !== 'enter')
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
      const m = clone(n); delete m.x; delete m.y;
      m.params = m.params || {}; m.description = m.description || '';
      addNodeFromModel(m, n.x || 0, n.y || 0);
    });
    (doc.links || []).forEach((l) => {
      const a = nidToDf.get(l.from), b = nidToDf.get(l.to);
      if (a == null || b == null) return;
      editor.addConnection(a, b, l.port === 'false' ? 'output_2' : 'output_1', 'input_1');
    });
    loading = false;
    if (!keepView) initialView();
    if (selFrame && !frameById(selFrame)) selFrame = null;
    if (selNote && !noteById(selNote)) selNote = null;
    analyze();
    paintWires();
    drawFrames();
    drawNotes();
    renderPalette();
    renderInspector();
    renderIntents();
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
  function undo() { if (histIdx > 0) { histIdx--; rebuild(JSON.parse(hist[histIdx]), true); updateBar(); } }
  function redo() { if (histIdx < hist.length - 1) { histIdx++; rebuild(JSON.parse(hist[histIdx]), true); updateBar(); } }
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
      if (a.kind === 'start') return;                                          // Start -> state is display only
      if (a.kind === 'state') {                                                // state -> trigger: "valid in this state"
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
        // terminals: a state node (hub form) or a legacy go-to / End; a state node's own output starts OTHER chains
        if (n.kind === 'goto' || n.kind === 'end' || n.kind === 'state') { out.push(chain.concat([[nid, false]])); return; }
        if (n.kind === 'condition') {
          [['true', false], ['false', true]].forEach(([port, inv]) => (adj.get(nid + '|' + port) || []).forEach((t) => rec(t, chain.concat([[nid, inv]]))));
          return;
        }
        (adj.get(nid + '|out') || []).forEach((t) => rec(t, chain.concat([[nid, false]])));
      };
      rec(tid, []);
      return out;
    };
    const keys = new Map(), byTrigger = new Map(), counts = {};
    let gcount = 0;
    ordered.forEach((tid) => {
      const p = nodes[tid].params || {}, mine = [];
      byTrigger.set(tid, mine);
      // states the trigger is linked from (+ the legacy `params.state`): the chain's scope
      const linked = (stateIn.get(tid) || []).map((s) => nodes[s].params && nodes[s].params.state).filter(Boolean);
      const scope = [...new Set(linked.concat((p.type === 'event' || p.type === 'after') && p.state ? [p.state] : []))];
      paths(tid).forEach((path) => {
        const ids = path.map((x) => x[0]);
        const hubs = (sts) => sts.map((s) => hubOf[s]).filter(Boolean);        // source hubs light up with the chain
        if (p.type === 'enter') { const k = p.state + '/enter'; if (!keys.has(k)) { keys.set(k, ids.concat(hubs([p.state]))); mine.push(k); } return; }
        const pos = [], neg = []; let force = false;
        if ((p.type === 'event' || p.type === 'after') && scope.length) { pos.push(scope.slice()); force = !!p.global || scope.length > 1; }
        path.slice(1, -1).forEach(([nid, inv]) => {
          const n = nodes[nid]; if (n.kind !== 'condition') return;
          const q = n.params || {}, isNeg = !!q.negate !== inv;
          if (q.type === 'state') { (isNeg ? neg : pos).push(q.states || []); force = force || (!isNeg && !!q.global); }
        });
        let key, src;
        if (pos.length === 1 && pos[0].length === 1 && !neg.length && !force) {
          const st = pos[0][0]; counts[st] = counts[st] || 0; key = st + '/t' + counts[st]++; src = [st];
        } else {
          if (p.type === 'after') return;
          if (pos.length && !pos[0].filter((s) => pos.slice(1).every((o) => o.includes(s))).length) return;
          key = 'global/t' + gcount++; src = pos.length ? pos[0] : [];
        }
        keys.set(key, ids.concat(hubs(src.filter((s) => linked.includes(s))))); mine.push(key);
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
  }
  function blinkChain(key) {
    const ids = liveChains.keys.get(key); if (!ids) return;
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
    const incoming = {}, outgoing = {}, chainIn = {};
    for (const dfid in data) { incoming[dfid] = 0; outgoing[dfid] = 0; }
    for (const dfid in data) {
      for (const key in data[dfid].outputs) for (const c of data[dfid].outputs[key].connections) {
        outgoing[dfid]++; incoming[c.node] = (incoming[c.node] || 0) + 1;
        if (data[dfid].data.model.kind !== 'start') chainIn[c.node] = (chainIn[c.node] || 0) + 1;   // Start -> state is display only
      }
    }
    const stateIds = new Set(V.states.map((s) => s.id));
    const hubSeen = new Map();       // state id -> node id of its hub (first seen)
    const hubNoIn = [];              // hubs nothing leads to
    let startState = null;
    for (const dfid in data) {
      const m = data[dfid].data.model, p = m.params || {}, id = m.id;
      if (m.kind === 'start') startState = p.state;
      if (m.kind === 'trigger') {
        if (p.type === 'event' && !byId(evs(), p.event)) add(id, 'err', 'Événement inconnu ou manquant.');
        if (p.type === 'after' && (p.delay === '' || p.delay == null)) add(id, 'err', 'Délai manquant.');
        if (p.type === 'enter' && !stateIds.has(p.state)) add(id, 'err', 'État inconnu.');
        if (!['event', 'after', 'enter'].includes(p.type)) add(id, 'err', 'Type de déclencheur inconnu.');
        if (!outgoing[dfid]) add(id, 'warn', "Ce déclencheur n'a pas de chaîne.");
      } else if (m.kind === 'condition') {
        if (p.type === 'state' && !(p.states || []).length) add(id, 'err', 'Aucun état choisi.');
        if (p.type === 'guard' && !byId(V.guards, p.guard)) add(id, 'err', 'Garde inconnue ou manquante.');
      } else if (m.kind === 'action') {
        if (!byId(V.actions, p.action)) add(id, 'err', 'Action inconnue ou manquante.');
        else {
          const need = { say_text: ['text'], set_expression: ['name', 'seconds'], wait: ['seconds'], gaze: ['mode'] }[p.action] || [];
          need.forEach((k) => { const v = (p.args || {})[k]; if (v == null || v === '') add(id, 'err', 'À remplir : ' + ((((byId(V.actions, p.action) || {}).args || []).find((x) => x.name === k)) || {}).label + '.'); });
        }
      } else if (m.kind === 'goto') {
        if (!stateIds.has(p.state)) add(id, 'err', "État d'arrivée inconnu.");
      } else if (m.kind === 'state') {
        if (!stateIds.has(p.state)) add(id, 'err', 'État inconnu.');
        else if (hubSeen.has(p.state)) add(id, 'err', `Il y a déjà un nœud pour l'état « ${stateLabel(p.state)} » : un seul nœud par état.`);
        else { hubSeen.set(p.state, id); if (!chainIn[dfid]) hubNoIn.push({ id, state: p.state }); }
      }
      if (!['start', 'trigger', 'state'].includes(m.kind) && !incoming[dfid]) add(id, 'warn', "Nœud non relié : il serait perdu à l'enregistrement.");
      if (['condition', 'action'].includes(m.kind)) {
        // dead end: a chain must finish on Aller à / Fin (the false branch of a condition may stay empty)
        const o1 = data[dfid].outputs.output_1;
        if (!o1 || !o1.connections.length) add(id, 'warn', "La chaîne ne se termine pas : relier au nœud de l'état suivant ou à « Fin ».");
      }
      if (m.kind === 'condition') {
        for (const c of (data[dfid].inputs.input_1 || { connections: [] }).connections) {
          const src = data[c.node];
          if (src && src.data.model.kind === 'action') add(id, 'err', 'Une condition ne peut pas suivre une action.');
        }
      }
    }
    globalIssues = [];
    hubNoIn.forEach((x) => { if (x.state !== startState) add(x.id, 'warn', `Aucune chaîne n'arrive dans l'état « ${stateLabel(x.state)} » : il ne sera jamais atteint.`); });
    if (Object.keys(data).length && hubSeen.size) {
      V.states.forEach((s) => { if (!hubSeen.has(s.id)) globalIssues.push({ level: 'warn', message: `L'état « ${s.label} » n'a pas de nœud : ajoutez-le depuis la palette pour y relier des déclencheurs.` }); });
    }
    Object.keys(meta.intents || {}).forEach((n) => {
      const it = meta.intents[n] || {};
      if (!INTENT_NAME.test(n)) globalIssues.push({ level: 'err', message: `Intention « ${n} » : nom invalide.` });
      if (!it.words_from && !it.regex && !(it.words || []).length) globalIssues.push({ level: 'warn', message: `Intention « ${n} » : aucun mot (ajoutez au moins un mot ou une expression).` });
    });
    intentErrs = {};
    serverErrors.concat(simErrors).forEach((e) => {
      if (e.intent) { intentErrs[e.intent] = e.message; globalIssues.push({ level: 'err', message: `Intention « ${e.intent} » : ${e.message}` }); }
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
  // State nodes are the hubs of the drawing (one per state, no automatic bands any more). The helpers below keep
  // the old "band" vocabulary for navigation: bandRects() = bounding box of every node whose `group` is a state
  // (its hub and its chains), used to jump to a state and to size the first view.
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
    return g;
  }
  // Live robot state / simulated state: the matching state node glows (class live / sim).
  function drawBands() {
    if (!editor) return;
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
        defs.append(g); svg.insertBefore(defs, svg.firstChild);
      }
      g.setAttribute('x1', x1); g.setAttribute('y1', y1); g.setAttribute('x2', x2); g.setAttribute('y2', y2);
      const stops = g.querySelectorAll('stop');
      stops[0].setAttribute('offset', '0'); stops[0].setAttribute('stop-color', KIND_HEX[a.data.model.kind] || '#8b949e');
      stops[1].setAttribute('offset', '1'); stops[1].setAttribute('stop-color', KIND_HEX[b.data.model.kind] || '#8b949e');
      path.style.stroke = `url(#${g.id})`;
      const idx = +cl[3].split('_')[1], port = a.data.model.kind === 'condition' ? (idx === 1 ? 'true' : 'false') : 'out';
      const mt = linkMeta.get(linkKey(a.data.model.id, port, b.data.model.id));
      let t = path.querySelector('title');
      if (mt && mt.reason) { if (!t) { t = document.createElementNS('http://www.w3.org/2000/svg', 'title'); path.append(t); } t.textContent = 'Raison : ' + mt.reason; }
      else if (t) t.remove();
    });
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
      const el = h('div', { class: 'frame' + (f.id === selFrame ? ' sel' : ''), 'data-fid': f.id }, title, grip);
      placeFrame(f, el);
      for (const part of [title, grip]) {
        part.addEventListener('mousedown', (e) => startFrameDrag(e, f, part === grip ? 'resize' : 'move'));
        part.addEventListener('touchstart', (e) => startFrameDrag(e, f, part === grip ? 'resize' : 'move'), { passive: false });
      }
      title.addEventListener('dblclick', (e) => { e.stopPropagation(); editFrameTitle(f); });
      frameEls.set(f.id, el);
      root.append(el);
    });
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
    meta.frames = frames().filter((f) => f.id !== id);
    if (selFrame === id) selFrame = null;
    drawFrames(); renderInspector(); renderPalette();
    commitSoon();
  }
  // "Groupe" / key G: a frame around the selected node's chain(s) (Drawflow selects one node at a time, so the
  // whole rule it belongs to is wrapped), else a default box at the visible centre.
  function addFrame(at) {
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
    return Math.max(0.05, Math.min(1, c.clientWidth / ((b.x1 - b.x0) * 1.1), c.clientHeight / ((b.y1 - b.y0) * 1.1)));
  }
  // "Ajuster": whole graph, centred, ~5 % padding each side.
  function fit() {
    const b = bbox(), c = $('#drawflow');
    if (!b) return;
    const z = fitZoom(), w = b.x1 - b.x0, hh = b.y1 - b.y0;
    setView(z, (c.clientWidth - w * z) / 2 - b.x0 * z, (c.clientHeight - hh * z) / 2 - b.y0 * z);
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
    const st = Object.values(dfData()).find((d) => d.data.model.kind === 'start');
    if (!focusBand((st && st.data.model.params.state) || 'veille', 0.9)) fit();   // 0.9: node text ~12 px on first load
  }
  function setView(z, cx, cy) {
    // Drawflow scales around the centre of its canvas (no transform-origin), so convert the wanted
    // top-left based translation: screen = tx + O + z*(p - O)  =>  tx = cx - O*(1 - z).
    const ox = editor.precanvas.clientWidth / 2, oy = editor.precanvas.clientHeight / 2;
    cx -= ox * (1 - z); cy -= oy * (1 - z);
    editor.zoom = z; editor.zoom_last_value = z; editor.canvas_x = cx; editor.canvas_y = cy;
    editor.precanvas.style.transform = `translate(${cx}px, ${cy}px) scale(${z})`;
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
      const head = h('div', { class: 'phead', title: 'Glisser pour déplacer le post-it' }, h('span', { class: 'ptitle' }, n.title || ''),
        h('button', { type: 'button', class: 'pdel', title: 'Supprimer le post-it', 'aria-label': 'Supprimer le post-it',
          onclick: (e) => { e.stopPropagation(); deleteNote(n.id); } }, '×'));
      const grip = h('div', { class: 'presize', title: 'Redimensionner' });
      const el = h('div', { class: 'postit' + (n.id === selNote ? ' sel' : ''), 'data-nid': n.id }, head, ta, grip);
      placeNote(n, el);
      el.addEventListener('mousedown', (e) => { e.stopPropagation(); if (e.button === 0) selectNote(n.id, true); });   // no canvas pan from a note
      for (const part of [head, grip]) {
        part.addEventListener('mousedown', (e) => startNoteDrag(e, n, part === grip ? 'resize' : 'move'));
        part.addEventListener('touchstart', (e) => startNoteDrag(e, n, part === grip ? 'resize' : 'move'), { passive: false });
      }
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
    if (e.button) return;                                   // left button / primary touch only
    if (e.touches && e.touches.length > 1) return;
    e.stopPropagation(); e.preventDefault();
    selectNote(n.id, true);
    const p = evPoint(e);
    noteDrag = { n, mode, cx: p.clientX, cy: p.clientY, ox: n.x, oy: n.y, ow: n.w, oh: n.h, moved: false };
  }
  function moveNoteDrag(e) {
    const d = noteDrag; if (!d) return;
    if (e.cancelable) e.preventDefault();
    const p = evPoint(e), dx = (p.clientX - d.cx) / editor.zoom, dy = (p.clientY - d.cy) / editor.zoom;
    if (!d.moved && Math.hypot(p.clientX - d.cx, p.clientY - d.cy) < 3) return;
    d.moved = true;
    if (d.mode === 'resize') { d.n.w = Math.max(120, Math.round(d.ow + dx)); d.n.h = Math.max(90, Math.round(d.oh + dy)); }
    else { d.n.x = Math.round(d.ox + dx); d.n.y = Math.round(d.oy + dy); }
    const el = noteEls.get(d.n.id); if (el) placeNote(d.n, el);
  }
  function endNoteDrag() {
    const d = noteDrag; if (!d) return;
    noteDrag = null;
    if (d.moved) commitSoon();
  }
  function editNote(n, patch, rerender) {
    Object.assign(n, patch);
    if (!n.title) delete n.title;
    const el = noteEls.get(n.id);
    if (el) { placeNote(n, el); el.querySelector('.ptitle').textContent = n.title || ''; const ta = el.querySelector('textarea'); if (ta.value !== (n.text || '')) ta.value = n.text || ''; }
    renderPalette();
    if (rerender) renderInspector();
    commitSoon();
  }
  function deleteNote(id) {
    meta.notes = notes().filter((n) => n.id !== id);
    if (selNote === id) selNote = null;
    drawNotes(); renderInspector(); renderPalette();
    commitSoon();
  }
  // New note at a canvas point (default: centre of the view). Returns the note.
  function addNote(pt) {
    if (notes().length >= 200) { toast('200 post-it au plus.', 'err'); return null; }
    if (!pt) { const st = $('#stage').getBoundingClientRect(); pt = canvasPoint(st.x + st.width / 2 - 110, st.y + st.height / 2 - 80); }
    const used = new Set(notes().map((n) => n.id));
    let k = 1; while (used.has('p' + k)) k++;
    const n = { id: 'p' + k, text: '', color: NOTE_COLORS[0][1], x: Math.round(pt.x), y: Math.round(pt.y), w: 220, h: 160 };
    notes().push(n);
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

  // What can follow a node (kinds valid after it, from the server's rules): start -> state; state -> trigger; trigger and
  // condition (true / false) -> condition, action, end (+ going to a state); action -> action, end (+ state; never a condition).
  function kindsAfter(kind) {
    switch (kind) {
      case 'start': return [];
      case 'state': return ['trigger'];
      case 'trigger': return ['condition', 'action', 'end'];
      case 'condition': return ['condition', 'action', 'end'];
      case 'action': return ['action', 'end'];
      default: return [];
    }
  }
  const canGoToState = (kind) => ['trigger', 'condition', 'action'].includes(kind);
  const KIND_ICON = (k) => KINDS[k].icon;
  // Node to create from a menu entry: {kind, preset} ; vocabulary entries pre-fill the node.
  function nodeChoices(kinds, withStates) {
    const out = kinds.map((k) => ({ label: KINDS[k].label, icon: KINDS[k].icon, color: KINDS[k].color, kind: k }));
    return withStates ? out.concat(V.states.map((s) => ({ label: 'État : ' + s.label, icon: stateIcon(s.id), kind: 'state', preset: { state: s.id } }))) : out;
  }
  // Submenu content "insert a node" with a search field; `make(choice)` performs the insertion.
  function insertSub(kinds, make, opts) {
    return (subEl, depth) => {
      const base = nodeChoices(kinds.filter((k) => k !== 'state'), false);
      const vocab = [];
      if (kinds.includes('trigger')) evs().forEach((e) => vocab.push({ label: e.label, icon: e.icon, kind: 'trigger', preset: { event: e.id }, hay: e.label + e.id }));
      if (kinds.includes('condition')) V.guards.forEach((g) => vocab.push({ label: g.label, icon: g.icon, kind: 'condition', preset: { guard: g.id }, hay: g.label + g.id }));
      if (kinds.includes('action')) V.actions.forEach((a) => vocab.push({ label: a.label, icon: a.icon, kind: 'action', preset: { action: a.id }, hay: a.label + a.id }));
      const stateRows = (opts && opts.states) ? V.states.map((s) => ({ label: 'Aller à : ' + s.label, icon: stateIcon(s.id), kind: 'state', preset: { state: s.id }, hay: s.label + s.id })) : [];
      const stateKind = kinds.includes('state') ? V.states.map((s) => ({ label: 'État : ' + s.label, icon: stateIcon(s.id), kind: 'state', preset: { state: s.id }, hay: s.label + s.id })) : [];
      const toItem = (c) => ({ label: c.label, icon: c.icon, color: c.color, fn: () => make(c) });
      const render = (q) => {
        const rows = q ? vocab.concat(stateRows, stateKind).filter((c) => c.hay.toLowerCase().includes(q)).slice(0, 14).concat(base.filter((c) => c.label.toLowerCase().includes(q))) : base.concat(stateKind);
        fillMenu(subEl, [{ search: { placeholder: 'Rechercher un nœud…', onInput: render } }].concat(rows.map(toItem), stateRows.length && !q ? [{ sep: true }].concat(stateRows.map(toItem)) : []), depth);
        const s = subEl.querySelector('.csearch'); if (s && q) { s.value = q; s.focus(); }
      };
      return [{ search: { placeholder: 'Rechercher un nœud…', onInput: render } }].concat(base.map(toItem), stateKind.map(toItem), stateRows.length ? [{ sep: true }].concat(stateRows.map(toItem)) : []);
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
    if (!clipboard) return;
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
    const m = model(dfid); if (!m || m.kind !== 'trigger' || (m.params || {}).type === 'enter') return;
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
  // Insert a new node after `dfid` (port = output class) and link it; for a state choice, link to the state's hub.
  function insertAfter(dfid, outCls, choice) {
    const d = dfNode(dfid);
    if (choice.kind === 'state') {
      let hub = [...nidToDf.values()].find((k) => model(k) && model(k).kind === 'state' && model(k).params.state === choice.preset.state);
      if (hub == null) { hub = addAt('state', choice.preset, { x: d.pos_x + 260, y: d.pos_y }, { select: false }); }
      if (hub != null) linkNodes(dfid, outCls, hub);
      return;
    }
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
        const ks = kinds.concat(m.kind === 'state' ? [] : []);
        after.push({ label: 'Insérer après' + suffix, icon: 'plus', disabled: !ks.length && !canGoToState(m.kind),
          sub: insertSub(ks.concat(canGoToState(m.kind) ? [] : []), (c) => insertAfter(dfid, cls, c), { states: canGoToState(m.kind) }) });
      });
      items = after.concat([{ sep: true },
        { label: 'Dupliquer', icon: 'plus', disabled: m.kind === 'state' || m.kind === 'start', fn: () => duplicateNode(dfid) },
        { label: 'Copier', icon: 'text-caption', disabled: m.kind === 'state' || m.kind === 'start', fn: () => copyNode(dfid) }]);
      if (m.kind === 'trigger' && (m.params || {}).type !== 'enter') items.push({ label: (m.params || {}).enabled === false ? 'Activer la chaîne' : 'Désactiver la chaîne', icon: 'power', fn: () => toggleChain(dfid) });
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
        { label: 'Insérer un nœud', icon: 'plus', sub: insertSub(NODE_KINDS.concat(['state']), (c) => addAt(c.kind, c.preset, pt, { exact: true })) },
        { label: 'Insérer un post-it', icon: 'message', fn: () => addNote(pt) },
        { label: 'Insérer un groupe', icon: 'square', fn: () => addFrame(pt) },
        { label: 'Coller', icon: 'text-caption', disabled: !clipboard, fn: () => pasteNode(pt) },
        { sep: true }, { label: 'Ajuster la vue', icon: 'eye', fn: fit }];
    }
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
      if (preset.action) { p.action = preset.action; p.args = {}; }
      if (preset.state) p.state = preset.state;
    }
    return m;
  }
  // Add a node of `kind`. Options: exact (place it exactly at `pt`, no nudging away from other nodes), select (default true).
  // A `state` node is unique per state: asking for an existing one just selects it. A trigger added while a state node is
  // selected is linked from it (state -> trigger). Returns the Drawflow id (or the existing hub's id), null if refused.
  function addAt(kind, preset, pt, opts) {
    opts = opts || {};
    if (kind === 'start' && Object.values(dfData()).some((d) => d.data.model.kind === 'start')) { toast('Il y a déjà un nœud Début.', 'err'); return null; }
    if (kind === 'state') {
      const sid = (preset && preset.state) || (V.states[0] || {}).id;
      const have = Object.keys(dfData()).find((k) => model(k).kind === 'state' && model(k).params.state === sid);
      if (have != null) { focusNode(model(have).id); return have; }
      preset = { state: sid };
    }
    const sel = selDf != null && dfNode(selDf) ? selDf : null;
    if (!pt) {
      // Preferred spot: right of the selected node, else the middle of the visible canvas.
      if (sel != null) pt = { x: dfNode(sel).pos_x + 260, y: dfNode(sel).pos_y };
      else { const st = $('#stage').getBoundingClientRect(); pt = canvasPoint(st.x + st.width / 2 - 100, st.y + st.height / 2 - 40); }
    }
    if (!opts.exact) pt = freeSpot(pt.x, pt.y);
    const m = defaultModel(kind, preset);
    if (kind === 'state') m.group = m.params.state;
    freshIds.add(m.id);
    const dfid = addNodeFromModel(m, Math.round(pt.x), Math.round(pt.y));
    if (kind === 'trigger' && sel != null && model(sel).kind === 'state' && m.params.type !== 'enter') editor.addConnection(sel, dfid, 'output_1', 'input_1');
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
    // one hub per state: clicking an existing one goes to it (addAt selects it), a missing one is created
    V.states.forEach((st) => items.push({ sec: 'États (un nœud par état)', kind: 'state', preset: { state: st.id }, label: st.label, sub: st.id, icon: stateIcon(st.id), hay: st.label + st.id }));
    if (rects.global) items.push({ sec: 'États (un nœud par état)', kind: 'band', band: true, id: 'global', label: 'Règles globales', sub: 'global', icon: 'git-branch', hay: 'global règles globales' });
    items.push({ sec: 'Groupes (cliquer pour y aller)', kind: 'frame', fn: () => addFrame(), label: 'Groupe', sub: 'nouveau (G)', icon: 'plus', color: '#e3b341', hay: 'groupe nouveau cadre commentaire' });
    frames().forEach((f) => items.push({ sec: 'Groupes (cliquer pour y aller)', kind: 'frame', fn: () => focusFrame(f.id), label: f.title || '(sans nom)', sub: '', icon: 'square', color: f.color, hay: 'groupe ' + f.title + ' ' + (f.note || '') }));
    items.push({ sec: 'Notes', kind: 'note', fn: () => addNote(), label: 'Post-it', sub: 'nouveau (N)', icon: 'plus', color: NOTE_COLORS[0][1], hay: 'note post-it postit nouveau' });
    notes().forEach((n) => items.push({ sec: 'Notes', kind: 'note', fn: () => focusNoteBox(n.id), label: n.title || (n.text || '').slice(0, 24) || '(vide)', sub: '', icon: 'message', color: n.color, hay: 'note post-it ' + (n.title || '') + ' ' + (n.text || '') }));
    NODE_KINDS.forEach((k) => items.push({ sec: 'Blocs', kind: k, label: KINDS[k].label, sub: '', icon: KINDS[k].icon, hay: KINDS[k].label + ' ' + k }));
    evs().forEach((e) => items.push({ sec: 'Événements', kind: 'trigger', preset: { event: e.id }, label: e.label, sub: e.id, icon: e.icon, hay: e.label + e.id + (e.help || '') }));
    V.guards.forEach((g) => items.push({ sec: 'Conditions', kind: 'condition', preset: { guard: g.id }, label: g.label, sub: g.id, icon: g.icon, hay: g.label + g.id + (g.help || '') }));
    V.actions.forEach((a) => items.push({ sec: 'Actions', kind: 'action', preset: { action: a.id }, label: a.label, sub: a.id, icon: a.icon, hay: a.label + a.id + (a.help || '') }));
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

  // States wired into the input of a trigger (Drawflow id), in link order.
  function linkedStates(dfid) {
    const n = dfNode(dfid); if (!n) return [];
    return [...new Set(((n.inputs.input_1 || {}).connections || []).map((c) => model(c.node)).filter((m) => m && m.kind === 'state').map((m) => m.params.state))];
  }
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
      box.append(field('Type', selectCtl([{ v: 'event', l: 'Un événement arrive' }, { v: 'after', l: 'Après un délai' }, { v: 'enter', l: "À l'entrée dans un état" }], p.type, (v) => edit((mm) => {
        const wasOff = mm.params.enabled === false, glob = mm.params.global;
        mm.params = { type: v };
        if (glob && v !== 'enter') mm.params.global = glob;
        if (v === 'event') mm.params.event = (V.events[0] || {}).id;
        if (v === 'after') { mm.params.delay = (V.delays[0] || {}).key || 5; mm.params.since = 'state'; }
        if (v === 'enter') mm.params.state = (V.states[0] || {}).id;
        else if (wasOff) mm.params.enabled = false;
      }, true))));
      if (p.type === 'event' || p.type === 'after') {
        // Scope = the state nodes wired into the trigger's input (none = global rule)
        const from = linkedStates(selDf);
        box.append(h('div', { class: 'fld' }, h('span', {}, "Valable dans l'état"),
          from.length ? h('div', {}, from.map((s) => h('span', { class: 'chip' }, ico(stateIcon(s), stateColor(s)), stateLabel(s)))) : h('div', { class: 'hint' }, 'Aucun état relié : règle globale (valable dans tous les états).'),
          h('div', { class: 'help' }, "Reliez la sortie d'un ou plusieurs nœuds État à l'entrée de ce déclencheur. Plusieurs états = la règle est valable dans chacun d'eux.")));
        if (from.length === 1 && p.type === 'event') box.append(checkCtl('Règle globale (évaluée avec les règles globales, limitée à cet état)', p.global, (c) => edit((mm) => { if (c) mm.params.global = true; else delete mm.params.global; }, true)));
        if (from.length > 1) box.append(h('p', { class: 'hint' }, 'Plusieurs états reliés : la règle est globale, limitée à ces états.'));
        if (from.length > 1 && p.type === 'after') box.append(h('div', { class: 'iss err' }, 'Un délai doit être rattaché à un seul état.'));
      }
      if (p.type === 'event') box.append(field('Événement', iconSelect(evs().map((e) => ({ v: e.id, l: e.label, icon: e.icon })), p.event, (v) => edit((mm) => { mm.params.event = v; }, true)), helpOf(evs(), p.event)));
      if (p.type !== 'enter') {
        box.append(h('p', { class: 'hint fannote' }, "Plusieurs branches : toutes celles qui ne changent pas d'état s'exécutent (dans l'ordre des numéros), puis une seule branche change d'état : la première qui correspond."));
        const fb = (fanInfo.fans || {})[m.id];
        if (fb && fb.length > 1) box.append(h('p', { class: 'hint' }, 'Ordre actuel : ' + fb.slice().sort((a, b) => a.rank - b.rank).map((b) => b.rank + ' → ' + b.target + (b.moves ? ' (change l\'état)' : '') + (b.ignored ? ' [ignorée]' : '')).join(' ; ')));
      }
      if (p.type === 'enter') box.append(h('p', { class: 'hint' }, "Un déclencheur « entrée dans l'état » ne peut pas être désactivé."));
      else {
        box.append(checkCtl('Chaîne activée', p.enabled !== false, (c) => edit((mm) => { mm.params.enabled = c; }, true), 'power'));
        if (p.enabled === false) box.append(h('p', { class: 'hint' }, "Désactivée : la chaîne reste dans le fichier mais le robot l'ignore (grisée sur le canvas)."));
      }
      if (p.type === 'after') {
        box.append(field('Délai (secondes, ou clé de réglage)', textCtl(p.delay, (v) => edit((mm) => { mm.params.delay = numOrKey(v); }, true), 'text', 'dl-delays'),
          'Clés : ' + V.delays.map((d) => `${d.key} = ${d.value} s`).join(' ; ')));
        box.append(h('datalist', { id: 'dl-delays' }, V.delays.map((d) => h('option', { value: d.key }))));
        box.append(field('Compté', selectCtl(V.since.map((s) => ({ v: s.id, l: s.label })), p.since || 'state', (v) => edit((mm) => { mm.params.since = v; }))));
      }
      if (p.type === 'enter') box.append(field('État', iconSelect(stateOpts, p.state, (v) => edit((mm) => { mm.params.state = v; }, true)), 'La chaîne doit finir par « Fin » et ne contenir que des actions.'));
    }
    if (m.kind === 'condition') {
      box.append(field('Type', selectCtl([{ v: 'guard', l: 'Une garde (réglage du robot)' }, { v: 'state', l: "L'état courant" }], p.type, (v) => edit((mm) => {
        mm.params = { type: v, negate: !!mm.params.negate };
        if (v === 'guard') mm.params.guard = (V.guards[0] || {}).id; else mm.params.states = [];
      }, true))));
      if (p.type === 'guard') box.append(field('Garde', iconSelect(V.guards.map((g) => ({ v: g.id, l: g.label, icon: g.icon })), p.guard, (v) => edit((mm) => { mm.params.guard = v; }, true)), helpOf(V.guards, p.guard)));
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
      box.append(field('Action', iconSelect(V.actions.map((a) => ({ v: a.id, l: a.label, icon: a.icon })), p.action, (v) => edit((mm) => { mm.params.action = v; mm.params.args = {}; }, true)), helpOf(V.actions, p.action)));
      const a = byId(V.actions, p.action);
      ((a && a.args) || []).forEach((arg, i) => {
        const cur = (p.args || {})[arg.name];
        const set = (v) => edit((mm) => {
          mm.params.args = mm.params.args || {};
          if (v === '' || v == null) delete mm.params.args[arg.name]; else mm.params.args[arg.name] = v;
        });
        const lab = arg.label || arg.name;
        if (arg.type === 'enum') {
          // `labels` (French text per option) comes from the vocabulary; event options reuse the event labels.
          const optLabel = (o) => (arg.labels && arg.labels[o]) || (byId(evs(), o) || {}).label || String(o);
          const required = ({ say_text: ['text'], set_expression: ['name', 'seconds'], wait: ['seconds'], gaze: ['mode'] }[p.action] || []).includes(arg.name);
          box.append(field(lab, selectCtl([{ v: '', l: required ? '(à choisir)' : '(aucun)' }].concat((arg.options || []).map((o) => ({ v: o, l: optLabel(o) }))), cur == null ? '' : cur, set),
            required ? 'Obligatoire : choisir une valeur.' : 'Facultatif.'));
        } else if (arg.type === 'number') {
          const lid = 'dl-arg' + i;
          const dl = (arg.options || []).length ? h('datalist', { id: lid }, (arg.options || []).map((o) => h('option', { value: o }))) : null;
          box.append(field(lab + ((arg.options || []).length && !/clé/.test(lab) ? ' (nombre, ou clé de réglage)' : ''), textCtl(cur, (v) => set(v === '' ? '' : numOrKey(v)), 'text', dl ? lid : null)));
          if (dl) box.append(dl);
        } else if (arg.max_len > 100) {
          box.append(field(lab, areaCtl(cur, set, arg.max_len), `${arg.max_len} caractères au plus.`));
        } else box.append(field(lab, textCtl(cur, set)));
      });
      box.append(field('Quand', selectCtl([{ v: 'do', l: "Avant le changement d'état" }, { v: 'then', l: "Après le changement d'état" }], p.phase || 'do', (v) => edit((mm) => { mm.params.phase = v; })),
        "« Avant » : exécutée avant le changement d'état de la chaîne ; « Après » : juste après (ex. phrase dite dans le nouvel état)."));
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
    const first = i >= 0 && sim.trace[i] ? idsOf(sim.trace[i])[0] : null;
    if (pan === 'fit') fitLit();
    else if (pan && first && !isVisible(first)) panTo(first, 0.45);
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
      h('button', { type: 'button', class: 'danger', onclick: () => { sim.steps = []; sim.note = ''; simRun(false); } }, ico('refresh'), 'Réinitialiser'),
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
      if (a && b && a.kind === 'state' && b.kind === 'trigger' && (b.params || {}).type === 'enter' && b.params.state !== a.params.state) {
        b.params.state = a.params.state; refreshNode(c.input_id);   // an "enter" trigger belongs to the state it is wired from
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
    installButtonGuards();

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
    document.addEventListener('mousemove', moveNoteDrag); document.addEventListener('mouseup', endNoteDrag);
    document.addEventListener('touchmove', moveNoteDrag, { passive: false }); document.addEventListener('touchend', endNoteDrag);
    // A press on the bare canvas or on a node unselects the frame / note (their own presses stop before here).
    dfEl.addEventListener('mousedown', (e) => { if (!e.target.closest('.drawflow-node')) { unselectFrame(); unselectNote(); } });
    dfEl.addEventListener('dragover', (e) => e.preventDefault());
    dfEl.addEventListener('drop', (e) => {
      e.preventDefault();
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
    meta: () => meta, journal: () => journal, loadJournal, loadVersions, selectTrace, toast };
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
      const g = doc.nodes.find((n) => n.kind === 'state');
      g.params.state = 'etat_inexistant';
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
