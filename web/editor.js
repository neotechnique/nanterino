/**
 * Nanterino visual graph editor (Game Creator 2 style node editor).
 *
 * Purpose : draw / edit the robot dialogue graph as nodes (Start, Trigger, Condition, Action, Goto, End) and
 *           round-trip it through the node-document contract (Notes/graph-visual-format.md).
 * Boundary: talks only to GET /api/graph/visual, /api/graph/vocab, /api/graph, POST /api/graph/visual,
 *           POST /api/graph/reset and WS /ws (live state + heartbeat). graph.yaml stays the only executed
 *           artifact; the server compiles and validates, this page never decides what is valid on its own
 *           (client checks below are structural hints only).
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
  const errLog = [];
  window.addEventListener('error', (e) => { errLog.push(String(e.message)); dbg('ERR ' + e.message); });
  window.addEventListener('unhandledrejection', (e) => { errLog.push(String(e.reason)); dbg('REJ ' + e.reason); });
  function dbg(msg) {
    if (!location.hash.includes('debug') || location.hash.includes('quiet')) return;
    let d = $('#dbg');
    if (!d) { d = h('div', { id: 'dbg' }); document.body.append(d); }
    d.textContent += msg + '\n';
  }

  const KINDS = {
    start:     { label: 'Début',            cls: 'start',     ins: 0, outs: 1, color: 'var(--grey)' },
    trigger:   { label: 'Déclencheur',      cls: 'trigger',   ins: 0, outs: 1, color: 'var(--trigger)' },
    condition: { label: 'Condition',        cls: 'condition', ins: 1, outs: 2, color: 'var(--cond)' },
    action:    { label: 'Action',           cls: 'action',    ins: 1, outs: 1, color: 'var(--action)' },
    goto:      { label: "Aller à l'état",   cls: 'goto',      ins: 1, outs: 0, color: 'var(--goto)' },
    end:       { label: 'Fin',              cls: 'end',       ins: 1, outs: 0, color: 'var(--grey)' },
  };

  // ---------- state ----------
  let V = { events: [], actions: [], guards: [], delays: [], since: [], states: [], intents: [] };
  let meta = { version: 1, states: [], intents: {}, order: [] };   // top-level doc fields other than nodes/links
  let editor = null;
  const nidToDf = new Map();       // our node id -> Drawflow id
  let loading = false;
  let selDf = null;
  let hist = [], histIdx = -1, savedSnap = '';
  let serverErrors = [];           // [{node,message}] from the last POST
  let issues = new Map();          // nid -> [{level,message}] (client analysis + server errors)
  let globalIssues = [];           // issues without a node
  let liveState = null;
  let lastWs = 0, lastAge = null;
  let idCounter = 0;
  let addJitter = 0;

  const byId = (list, id) => (list || []).find((x) => x.id === id);
  // Triggerable events = vocabulary events + one `intent.<id>` event per recognised intent.
  const evs = () => V.events.concat(V.intents.map((i) => ({ id: i.event || 'intent.' + i.id, label: 'Intention « ' + i.id + ' »', help: i.label })));
  const stateLabel = (id) => { const s = byId(V.states, id); return s ? s.label : id; };
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
    const desc = m.description ? `<div class="nsum" style="color:var(--mut)">${esc(m.description)}</div>` : '';
    return `<div class="nhead">${esc(k.label)}${tag}</div><div class="nsum">${esc(summary(m))}</div>${desc}<div class="nmsg"></div>`;
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

  // ---------- analysis (structural hints, not the validator) ----------
  function analyze() {
    const data = dfData();
    const out = new Map();
    const add = (nid, level, message) => { if (!out.has(nid)) out.set(nid, []); out.get(nid).push({ level, message }); };
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
    serverErrors.forEach((e) => {
      if (e.node && nidToDf.has(e.node)) add(e.node, 'err', e.message);
      else globalIssues.push({ level: 'err', message: e.message });
    });
    issues = out;
    for (const dfid in data) markNode(dfid);
    drawBands();
    renderMsgs();
  }
  function markNode(dfid) {
    const el = nodeEl(dfid), m = model(dfid);
    if (!el || !m) return;
    const list = issues.get(m.id) || [];
    const hasErr = list.some((i) => i.level === 'err');
    el.classList.toggle('err', hasErr);
    el.classList.toggle('warn', !hasErr && list.length > 0);
    const msg = el.querySelector('.nmsg');
    if (msg) msg.textContent = list.map((i) => i.message).join(' ');
    el.title = list.map((i) => (i.level === 'err' ? 'Erreur : ' : 'Attention : ') + i.message).join('\n');
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
      root.append(h('div', { class: 'band' + (live ? ' live' : ''), style: `--c:${stateColor(gid)};left:${r.x0}px;top:${r.y0}px;width:${r.x1 - r.x0}px;height:${r.y1 - r.y0}px` },
        h('div', { class: 'btitle' }, (gid === 'global' ? 'Règles globales' : stateLabel(gid)) + (live ? '  ● état courant du robot' : ''))));
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
    if (!focusBand((st && st.data.model.params.state) || 'veille', 0.55)) fit();
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
      const st = $('#stage').getBoundingClientRect();
      pt = canvasPoint(st.x + st.width / 2 - 100, st.y + st.height / 2 - 40);
      addJitter = (addJitter + 1) % 6; pt.x += addJitter * 24; pt.y += addJitter * 24;
    }
    const dfid = addNodeFromModel(defaultModel(kind, preset), pt.x, pt.y);
    commitSoon();
    selectDf(dfid);
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
    V.states.forEach((st) => { if (rects[st.id]) items.push({ sec: 'États (cliquer pour y aller)', kind: 'band', band: true, id: st.id, label: st.label, sub: st.id, hay: st.label + st.id }); });
    if (rects.global) items.push({ sec: 'États (cliquer pour y aller)', kind: 'band', band: true, id: 'global', label: 'Règles globales', sub: 'global', hay: 'global règles globales' });
    Object.keys(KINDS).forEach((k) => items.push({ sec: 'Blocs', kind: k, label: KINDS[k].label, sub: '', hay: KINDS[k].label + ' ' + k }));
    evs().forEach((e) => items.push({ sec: 'Événements', kind: 'trigger', preset: { event: e.id }, label: e.label, sub: e.id, hay: e.label + e.id + (e.help || '') }));
    V.guards.forEach((g) => items.push({ sec: 'Conditions', kind: 'condition', preset: { guard: g.id }, label: g.label, sub: g.id, hay: g.label + g.id + (g.help || '') }));
    V.actions.forEach((a) => items.push({ sec: 'Actions', kind: 'action', preset: { action: a.id }, label: a.label, sub: a.id, hay: a.label + a.id + (a.help || '') }));
    V.states.forEach((s) => items.push({ sec: 'Aller à un état', kind: 'goto', preset: { state: s.id }, label: s.label, sub: s.id, hay: s.label + s.id }));
    let sec = '';
    items.filter((i) => !q || i.hay.toLowerCase().includes(q)).forEach((i) => {
      if (i.sec !== sec) { sec = i.sec; box.append(h('div', { class: 'psec' }, sec)); }
      const el = h('div', { class: 'pitem', draggable: i.band ? null : 'true', title: i.hay },
        h('span', { class: 'dot', style: 'background:' + (i.band ? stateColor(i.id) : KINDS[i.kind].color) }), i.label, h('small', {}, i.sub));
      el.addEventListener('click', () => { if (i.band) focusBand(i.id); else addAt(i.kind, i.preset); if (innerWidth <= 900) document.body.classList.add('hide-left'); });
      el.addEventListener('dragstart', (ev) => { ev.dataTransfer.setData('text/plain', JSON.stringify({ kind: i.kind, preset: i.preset || null })); });
      box.append(el);
    });
  }

  // ---------- inspector ----------
  function field(label, control, help) {
    return h('label', { class: 'fld' }, h('span', {}, label), control, help ? h('div', { class: 'help' }, help) : null);
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
  function checkCtl(label, value, onchange) {
    const c = h('input', { type: 'checkbox' }); c.checked = !!value;
    c.addEventListener('change', () => onchange(c.checked));
    return h('label', { class: 'chk' }, c, label);
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
    box.append(h('div', { class: 'insttitle' }, h('span', { class: 'dot', style: 'background:' + KINDS[m.kind].color }),
      KINDS[m.kind].label, h('small', { class: 'hint' }, m.id + (m.group ? ' · ' + (m.group === 'global' ? 'global' : stateLabel(m.group)) : ''))));
    const helpOf = (list, id) => (byId(list, id) || {}).help || '';
    const stateOpts = V.states.map((s) => ({ v: s.id, l: s.label }));

    if (m.kind === 'start') {
      box.append(field('État de départ (fixé par le code)', h('input', { type: 'text', disabled: true, value: stateLabel(p.state) })));
    }
    if (m.kind === 'trigger') {
      box.append(field('Type', selectCtl([{ v: 'event', l: 'Un événement arrive' }, { v: 'after', l: 'Après un délai' }, { v: 'enter', l: "À l'entrée dans un état" }], p.type, (v) => edit((mm) => {
        mm.params = { type: v };
        if (v === 'event') mm.params.event = (V.events[0] || {}).id;
        if (v === 'after') { mm.params.delay = (V.delays[0] || {}).key || 5; mm.params.since = 'state'; }
        if (v === 'enter') mm.params.state = (V.states[0] || {}).id;
      }, true))));
      if (p.type === 'event') box.append(field('Événement', selectCtl(evs().map((e) => ({ v: e.id, l: e.label })), p.event, (v) => edit((mm) => { mm.params.event = v; }, true)), helpOf(evs(), p.event)));
      if (p.type === 'after') {
        box.append(field('Délai (secondes, ou clé de réglage)', textCtl(p.delay, (v) => edit((mm) => { mm.params.delay = numOrKey(v); }, true), 'text', 'dl-delays'),
          'Clés : ' + V.delays.map((d) => `${d.key} = ${d.value} s`).join(' ; ')));
        box.append(h('datalist', { id: 'dl-delays' }, V.delays.map((d) => h('option', { value: d.key }))));
        box.append(field('Compté', selectCtl(V.since.map((s) => ({ v: s.id, l: s.label })), p.since || 'state', (v) => edit((mm) => { mm.params.since = v; }))));
      }
      if (p.type === 'enter') box.append(field('État', selectCtl(stateOpts, p.state, (v) => edit((mm) => { mm.params.state = v; }, true)), 'La chaîne doit finir par « Fin » et ne contenir que des actions.'));
    }
    if (m.kind === 'condition') {
      box.append(field('Type', selectCtl([{ v: 'guard', l: 'Une garde (réglage du robot)' }, { v: 'state', l: "L'état courant" }], p.type, (v) => edit((mm) => {
        mm.params = { type: v, negate: !!mm.params.negate };
        if (v === 'guard') mm.params.guard = (V.guards[0] || {}).id; else mm.params.states = [];
      }, true))));
      if (p.type === 'guard') box.append(field('Garde', selectCtl(V.guards.map((g) => ({ v: g.id, l: g.label })), p.guard, (v) => edit((mm) => { mm.params.guard = v; }, true)), helpOf(V.guards, p.guard)));
      if (p.type === 'state') {
        const wrap = h('div', { class: 'fld' }, h('span', {}, 'États'));
        V.states.forEach((s) => wrap.append(checkCtl(s.label, (p.states || []).includes(s.id), (c) => edit((mm) => {
          const set = new Set(mm.params.states || []); c ? set.add(s.id) : set.delete(s.id); mm.params.states = [...set];
        }))));
        box.append(wrap);
        box.append(checkCtl('Règle globale (limitée à ces états)', p.global, (c) => edit((mm) => { if (c) mm.params.global = true; else delete mm.params.global; })));
      }
      box.append(checkCtl('Inverser (non)', p.negate, (c) => edit((mm) => { mm.params.negate = c; })));
      box.append(h('p', { class: 'hint' }, 'Sorties : « Vrai » continue la chaîne ; « Faux » démarre la branche suivante.'));
    }
    if (m.kind === 'action') {
      box.append(field('Action', selectCtl(V.actions.map((a) => ({ v: a.id, l: a.label })), p.action, (v) => edit((mm) => { mm.params.action = v; mm.params.args = {}; }, true)), helpOf(V.actions, p.action)));
      const a = byId(V.actions, p.action);
      ((a && a.args) || []).forEach((arg, i) => {
        const cur = (p.args || {})[arg.name];
        const set = (v) => edit((mm) => {
          mm.params.args = mm.params.args || {};
          if (v === '' || v == null) delete mm.params.args[arg.name]; else mm.params.args[arg.name] = v;
        });
        const lab = arg.label || arg.name;
        if (arg.type === 'enum') {
          box.append(field(lab, selectCtl([{ v: '', l: '(aucun)' }].concat((arg.options || []).map((o) => ({ v: o, l: String(o) }))), cur == null ? '' : cur, set)));
        } else if (arg.type === 'number') {
          const lid = 'dl-arg' + i;
          const dl = (arg.options || []).length ? h('datalist', { id: lid }, (arg.options || []).map((o) => h('option', { value: o }))) : null;
          box.append(field(lab + ' (nombre, ou clé de réglage)', textCtl(cur, (v) => set(v === '' ? '' : numOrKey(v)), 'text', dl ? lid : null)));
          if (dl) box.append(dl);
        } else box.append(field(lab, textCtl(cur, set)));
      });
      box.append(field('Quand', selectCtl([{ v: 'do', l: "Avant le changement d'état" }, { v: 'then', l: "Après le changement d'état" }], p.phase || 'do', (v) => edit((mm) => { mm.params.phase = v; }))));
    }
    if (m.kind === 'goto') {
      box.append(field("État d'arrivée", selectCtl(stateOpts, p.state, (v) => edit((mm) => { mm.params.state = v; }, true)), (byId(V.states, p.state) || {}).description || ''));
      box.append(field('Raison (journal)', textCtl(p.reason, (v) => edit((mm) => { if (v) mm.params.reason = v; else delete mm.params.reason; }))));
    }
    if (m.kind === 'end') box.append(h('p', { class: 'hint' }, "Fin de chaîne : aucun changement d'état."));

    const ta = h('textarea', {}); ta.value = m.description || '';
    ta.addEventListener('change', () => edit((mm) => { mm.description = ta.value; }));
    box.append(field('Description', ta));
    (issues.get(m.id) || []).forEach((i) => box.append(h('div', { class: 'iss ' + i.level }, i.message)));
    box.append(h('button', { class: 'danger', onclick: () => { editor.removeNodeId('node-' + selDf); } }, 'Supprimer ce nœud'));
  }

  function renderIntents() {
    const box = $('#intents'); box.innerHTML = '';
    box.append(h('p', { class: 'hint' }, 'Phrases que le robot reconnaît et transforme en événement « intent.… ». Les mots viennent du graphe ou de la configuration.'));
    V.intents.forEach((it) => {
      const cfg = (meta.intents || {})[it.id] || {};
      const ta = h('textarea', {}); ta.value = cfg.description || '';
      ta.addEventListener('change', () => { meta.intents = meta.intents || {}; (meta.intents[it.id] = meta.intents[it.id] || {}).description = ta.value; commitSoon(); });
      box.append(h('div', { class: 'intent' },
        h('div', {}, h('code', {}, it.event || it.id)),
        h('div', { class: 'words' }, [cfg.words ? 'Mots : ' + cfg.words.join(', ') : '', cfg.words_from ? 'Mots : clé « ' + cfg.words_from + ' » de la configuration' : '',
          cfg.only_in ? ' · seulement en : ' + cfg.only_in.map(stateLabel).join(', ') : ''].join('')),
        field('Description', ta)));
    });
    if (!V.intents.length) box.append(h('p', { class: 'hint' }, 'Aucune intention.'));
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
    return r;
  }
  async function save() {
    if (validate(false)) { validate(true); return; }
    await postDoc(serialize());
  }
  async function loadAll() {
    const [vocab, vis] = await Promise.all([api('/api/graph/vocab'), api('/api/graph/visual')]);
    if (!vocab.ok || !vis.ok) { toast('Impossible de charger le graphe (' + (vocab.status || vis.status) + ').', 'err'); return; }
    V = vocab.json; serverErrors = [];
    renderPalette();
    rebuild(vis.json, false);
    renderPalette();
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
    $('#tabNode').onclick = () => { $('#tabNode').className = 'on'; $('#tabIntents').className = ''; $('#inspector').hidden = false; $('#intents').hidden = true; };
    $('#tabIntents').onclick = () => { $('#tabIntents').className = 'on'; $('#tabNode').className = ''; $('#inspector').hidden = true; $('#intents').hidden = false; };
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
    connectWs();
    setInterval(paintHeart, 500);
    setInterval(pollLive, 500);
    window.addEventListener('beforeunload', (e) => { if (hist[histIdx] !== savedSnap) { e.preventDefault(); e.returnValue = ''; } });
    runDebug();
  }

  // ---------- test hooks (used by the verification scenarios; harmless in normal use) ----------
  window.__editor = { serialize, postDoc, loadAll, errors: errLog, nodeCount: () => Object.keys(dfData()).length };

  async function runDebug() {
    const mode = (location.hash.match(/debug=(\w+)/) || [])[1];
    if (!mode) return;
    await new Promise((r) => setTimeout(r, 800));
    if (mode === 'band') { focusBand('veille'); dbg('band'); }
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
