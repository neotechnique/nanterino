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
    start:     { label: 'Début',            cls: 'start',     ins: 0, outs: 1, color: 'var(--grey)',    icon: 'flag' },
    trigger:   { label: 'Déclencheur',      cls: 'trigger',   ins: 0, outs: 1, color: 'var(--trigger)', icon: 'bolt' },
    condition: { label: 'Condition',        cls: 'condition', ins: 1, outs: 2, color: 'var(--cond)',    icon: 'git-branch' },
    action:    { label: 'Action',           cls: 'action',    ins: 1, outs: 1, color: 'var(--action)',  icon: 'player-play' },
    goto:      { label: "Aller à l'état",   cls: 'goto',      ins: 1, outs: 0, color: 'var(--goto)',    icon: 'arrow-right' },
    end:       { label: 'Fin',              cls: 'end',       ins: 1, outs: 0, color: 'var(--grey)',    icon: 'square' },
  };

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
  let globalIssues = [];           // issues without a node
  let liveState = null;
  let lastWs = 0, lastAge = null;
  let idCounter = 0;
  let addJitter = 0;

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
    }
    return '';
  }
  function nodeHtml(m) {
    const k = KINDS[m.kind];
    const tag = m.group === 'global' ? `<span class="ntag" style="background:${esc(stateColor(m.group))}">${esc(m.group === 'global' ? 'global' : stateLabel(m.group))}</span>` : '';
    const off = m.kind === 'trigger' && (m.params || {}).enabled === false ? '<span class="ntag off">désactivée</span>' : '';
    const desc = m.description ? `<div class="nsum" style="color:var(--mut)">${esc(m.description)}</div>` : '';
    return `<div class="nhead">${icoHtml(iconOf(m), k.color)}<span class="ntitle">${esc(k.label)}</span>${off}${tag}</div><div class="nsum">${esc(summary(m))}</div>${desc}<div class="nmsg"></div>`;
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
        for (const c of d.outputs[key].connections) links.push({ from: m.id, port, to: nidOf(c.node) });
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
    selDf = null;
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
    analyze();
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
    const adj = new Map();
    (doc.links || []).forEach((l) => { const k = l.from + '|' + l.port; if (!adj.has(k)) adj.set(k, []); adj.get(k).push(l.to); });
    const trig = (doc.nodes || []).filter((n) => n.kind === 'trigger').map((n) => n.id);
    let ordered = [...new Set((doc.order || []).filter((i) => nodes[i] && nodes[i].kind === 'trigger'))];
    const seen = new Set(ordered);
    ordered = ordered.concat(trig.filter((i) => !seen.has(i)).sort((a, b) => (nodes[a].y || 0) - (nodes[b].y || 0) || (nodes[a].x || 0) - (nodes[b].x || 0)));
    const paths = (tid) => {
      const out = [];
      const rec = (nid, chain) => {
        if (chain.some((c) => c[0] === nid)) return;
        const n = nodes[nid]; if (!n) return;
        if (n.kind === 'goto' || n.kind === 'end') { out.push(chain.concat([[nid, false]])); return; }
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
      paths(tid).forEach((path) => {
        const ids = path.map((x) => x[0]);
        if (p.type === 'enter') { const k = p.state + '/enter'; if (!keys.has(k)) { keys.set(k, ids); mine.push(k); } return; }
        const pos = [], neg = []; let force = false;
        path.slice(1, -1).forEach(([nid, inv]) => {
          const n = nodes[nid]; if (n.kind !== 'condition') return;
          const q = n.params || {}, isNeg = !!q.negate !== inv;
          if (q.type === 'state') { (isNeg ? neg : pos).push(q.states || []); force = force || (!isNeg && !!q.global); }
        });
        let key;
        if (pos.length === 1 && pos[0].length === 1 && !neg.length && !force) {
          const st = pos[0][0]; counts[st] = counts[st] || 0; key = st + '/t' + counts[st]++;
        } else {
          if (p.type === 'after') return;
          if (pos.length && !pos[0].filter((s) => pos.slice(1).every((o) => o.includes(s))).length) return;
          key = 'global/t' + gcount++;
        }
        keys.set(key, ids); mine.push(key);
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
    off.forEach((d) => { if (!on.has(d) && data[d]) out.add(data[d].data.model.id); });
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
    const incoming = {}, outgoing = {};
    for (const dfid in data) { incoming[dfid] = 0; outgoing[dfid] = 0; }
    for (const dfid in data) {
      for (const key in data[dfid].outputs) for (const c of data[dfid].outputs[key].connections) {
        outgoing[dfid]++; incoming[c.node] = (incoming[c.node] || 0) + 1;
      }
    }
    const stateIds = new Set(V.states.map((s) => s.id));
    const targeted = new Set();
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
        else targeted.add(p.state);
      }
      if (!['start', 'trigger'].includes(m.kind) && !incoming[dfid]) add(id, 'warn', "Nœud non relié : il serait perdu à l'enregistrement.");
      if (['condition', 'action'].includes(m.kind)) {
        // dead end: a chain must finish on Aller à / Fin (the false branch of a condition may stay empty)
        const o1 = data[dfid].outputs.output_1;
        if (!o1 || !o1.connections.length) add(id, 'warn', "La chaîne ne se termine pas par « Aller à l'état » ou « Fin ».");
      }
      if (m.kind === 'condition') {
        for (const c of (data[dfid].inputs.input_1 || { connections: [] }).connections) {
          const src = data[c.node];
          if (src && src.data.model.kind === 'action') add(id, 'err', 'Une condition ne peut pas suivre une action.');
        }
      }
    }
    globalIssues = [];
    if (startState) targeted.add(startState);
    V.states.forEach((s) => { if (!targeted.has(s.id) && Object.keys(data).length) globalIssues.push({ level: 'warn', message: `L'état « ${s.label} » n'est la destination d'aucun « Aller à l'état ».` }); });
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
    issues = out;
    for (const dfid in data) markNode(dfid);
    paintChains();
    drawBands();
    renderMsgs();
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
  // State bands: one translucent labelled frame per state, drawn in a layer inside Drawflow's canvas so it
  // follows pan/zoom; recomputed from node positions after every change (analyze()).
  let bandsEl = null;
  function ensureBands() {
    if (!bandsEl || !bandsEl.isConnected) { bandsEl = h('div', { id: 'bands' }); editor.precanvas.insertBefore(bandsEl, editor.precanvas.firstChild); }
    return bandsEl;
  }
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
  function drawBands() {
    if (!editor) return;
    const root = ensureBands(); root.innerHTML = '';
    const rects = bandRects();
    for (const gid in rects) {
      const r = rects[gid];
      const live = gid === liveState;
      const sim = gid === simState;
      root.append(h('div', { class: 'band' + (live ? ' live' : '') + (sim ? ' sim' : ''), style: `--c:${stateColor(gid)};left:${r.x0}px;top:${r.y0}px;width:${r.x1 - r.x0}px;height:${r.y1 - r.y0}px` },
        h('div', { class: 'btitle' }, ico(gid === 'global' ? 'git-branch' : stateIcon(gid)),
          (gid === 'global' ? 'Règles globales' : stateLabel(gid)) + (live ? '  ● état courant du robot' : '') + (sim ? '  ▶ état simulé' : ''))));
    }
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
  function focusBand(gid, zoom) {
    const r = bandRects()[gid], c = $('#drawflow');
    if (!r) return false;
    const w = r.x1 - r.x0, hh = r.y1 - r.y0;
    const z = zoom || Math.max(0.1, Math.min(1, c.clientWidth / (w * 1.05), c.clientHeight / (hh * 1.05)));
    const cx = w * z <= c.clientWidth ? (c.clientWidth - w * z) / 2 - r.x0 * z : 20 - r.x0 * z;
    const cy = hh * z <= c.clientHeight ? (c.clientHeight - hh * z) / 2 - r.y0 * z : 20 - r.y0 * z;
    setView(z, cx, cy);
    return true;
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

  // ---------- adding nodes ----------
  function defaultModel(kind, preset) {
    const m = { id: nextNid(), kind, description: '', params: {} };
    const p = m.params;
    const firstState = (V.states[0] || {}).id || '';
    if (kind === 'trigger') { p.type = 'event'; p.event = (V.events[0] || {}).id || ''; }
    if (kind === 'condition') { p.type = 'guard'; p.guard = (V.guards[0] || {}).id || ''; p.negate = false; }
    if (kind === 'action') { p.action = (V.actions[0] || {}).id || ''; p.args = {}; p.phase = 'do'; }
    if (kind === 'goto') p.state = firstState;
    if (kind === 'start') p.state = 'veille';
    if (preset) {
      if (preset.event) { p.type = 'event'; p.event = preset.event; }
      if (preset.guard) p.guard = preset.guard;
      if (preset.action) { p.action = preset.action; p.args = {}; }
      if (preset.state) p.state = preset.state;
    }
    return m;
  }
  function addAt(kind, preset, pt) {
    if (kind === 'start' && Object.values(dfData()).some((d) => d.data.model.kind === 'start')) { toast('Il y a déjà un nœud Début.', 'err'); return; }
    if (!pt) {
      // Preferred spot: right of the selected node, else the middle of the visible canvas.
      if (selDf != null && dfNode(selDf)) pt = { x: dfNode(selDf).pos_x + 260, y: dfNode(selDf).pos_y };
      else { const st = $('#stage').getBoundingClientRect(); pt = canvasPoint(st.x + st.width / 2 - 100, st.y + st.height / 2 - 40); }
    }
    pt = freeSpot(pt.x, pt.y);
    const m = defaultModel(kind, preset);
    freshIds.add(m.id);
    const dfid = addNodeFromModel(m, pt.x, pt.y);
    commitSoon();
    selectDf(dfid);
    if (!isVisible(m.id)) panTo(m.id, 0.6);
    analyze();
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
    V.states.forEach((st) => { if (rects[st.id]) items.push({ sec: 'États (cliquer pour y aller)', kind: 'band', band: true, id: st.id, label: st.label, sub: st.id, icon: stateIcon(st.id), hay: st.label + st.id }); });
    if (rects.global) items.push({ sec: 'États (cliquer pour y aller)', kind: 'band', band: true, id: 'global', label: 'Règles globales', sub: 'global', icon: 'git-branch', hay: 'global règles globales' });
    Object.keys(KINDS).forEach((k) => items.push({ sec: 'Blocs', kind: k, label: KINDS[k].label, sub: '', icon: KINDS[k].icon, hay: KINDS[k].label + ' ' + k }));
    evs().forEach((e) => items.push({ sec: 'Événements', kind: 'trigger', preset: { event: e.id }, label: e.label, sub: e.id, icon: e.icon, hay: e.label + e.id + (e.help || '') }));
    V.guards.forEach((g) => items.push({ sec: 'Conditions', kind: 'condition', preset: { guard: g.id }, label: g.label, sub: g.id, icon: g.icon, hay: g.label + g.id + (g.help || '') }));
    V.actions.forEach((a) => items.push({ sec: 'Actions', kind: 'action', preset: { action: a.id }, label: a.label, sub: a.id, icon: a.icon, hay: a.label + a.id + (a.help || '') }));
    V.states.forEach((s) => items.push({ sec: 'Aller à un état', kind: 'goto', preset: { state: s.id }, label: s.label, sub: s.id, icon: stateIcon(s.id), hay: s.label + s.id }));
    let sec = '';
    items.filter((i) => !q || i.hay.toLowerCase().includes(q)).forEach((i) => {
      if (i.sec !== sec) { sec = i.sec; box.append(h('div', { class: 'psec' }, sec)); }
      const el = h('div', { class: 'pitem', draggable: i.band ? null : 'true', title: i.hay },
        ico(i.icon, i.band ? stateColor(i.id) : KINDS[i.kind].color), i.label, h('small', {}, i.sub));
      el.addEventListener('click', () => { if (i.band) focusBand(i.id); else addAt(i.kind, i.preset); if (innerWidth <= 900) document.body.classList.add('hide-left'); });
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

  function renderInspector() {
    const box = $('#inspector'); box.innerHTML = '';
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
        const wasOff = mm.params.enabled === false;
        mm.params = { type: v };
        if (v === 'event') mm.params.event = (V.events[0] || {}).id;
        if (v === 'after') { mm.params.delay = (V.delays[0] || {}).key || 5; mm.params.since = 'state'; }
        if (v === 'enter') mm.params.state = (V.states[0] || {}).id;
        else if (wasOff) mm.params.enabled = false;
      }, true))));
      if (p.type === 'event') box.append(field('Événement', iconSelect(evs().map((e) => ({ v: e.id, l: e.label, icon: e.icon })), p.event, (v) => edit((mm) => { mm.params.event = v; }, true)), helpOf(evs(), p.event)));
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
    if (m.kind === 'goto') {
      box.append(field("État d'arrivée", iconSelect(stateOpts, p.state, (v) => edit((mm) => { mm.params.state = v; }, true)), (byId(V.states, p.state) || {}).description || ''));
      box.append(field('Raison (journal)', textCtl(p.reason, (v) => edit((mm) => { if (v) mm.params.reason = v; else delete mm.params.reason; }))));
    }
    if (m.kind === 'end') box.append(h('p', { class: 'hint' }, "Fin de chaîne : aucun changement d'état."));

    const ta = h('textarea', {}); ta.value = m.description || '';
    ta.addEventListener('change', () => edit((mm) => { mm.description = ta.value; }));
    box.append(field('Description', ta));
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
    editor.on('nodeSelected', (id) => { selDf = id; renderInspector(); if (innerWidth <= 900) document.body.classList.remove('hide-right'); });
    editor.on('nodeUnselected', () => { selDf = null; renderInspector(); });
    editor.on('nodeMoved', commitSoon);
    editor.on('nodeRemoved', (id) => { if (loading) return; for (const [k, v] of nidToDf) if (String(v) === String(id)) nidToDf.delete(k); selDf = null; renderInspector(); commitSoon(); });
    editor.on('connectionCreated', commitSoon);
    editor.on('connectionRemoved', commitSoon);

    // Keys typed in inspector fields must never reach Drawflow (its Delete handler would remove the selected node).
    window.addEventListener('keydown', (e) => {
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) { e.stopPropagation(); return; }
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); }
      else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) { e.preventDefault(); redo(); }
    }, true);

    const dfEl = $('#drawflow');
    dfEl.addEventListener('dragover', (e) => e.preventDefault());
    dfEl.addEventListener('drop', (e) => {
      e.preventDefault();
      try { const d = JSON.parse(e.dataTransfer.getData('text/plain')); addAt(d.kind, d.preset, canvasPoint(e.clientX, e.clientY)); } catch (err) { /* foreign drop */ }
    });

    $('#search').addEventListener('input', renderPalette);
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
      const g = doc.nodes.find((n) => n.kind === 'goto');
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
