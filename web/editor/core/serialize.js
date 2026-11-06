/**
 * Editor core: (de)serialization of the node document.
 *
 * Purpose :  serialize() (the single exit point of the document) and rebuild() from a server document.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, variables/model.js, inspector/property-picker.js, core/api.js, canvas/nodes.js,
 *            diagnostics/analysis.js, canvas/wires.js, minimap/overview.js, frames/groups.js, frames/nesting.js,
 *            frames/notes.js, hierarchy/tree.js, inspector/inspector.js, panels/intents.js, variables/tables.js,
 *            tester/tester.js, canvas/culling.js, canvas/wiredraw.js (S3)
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { clone, dbg } from './util.js';
import { S, KINDS, linkKey, nidToDf } from './state.js';
import { docVars } from '../variables/model.js';
import { isEnterTrig } from '../inspector/property-picker.js';
import { dfData, model, nidOf } from './api.js';
import { addNodeFromModel } from '../canvas/nodes.js';
import { analyze } from '../diagnostics/analysis.js';
import { paintWires } from '../canvas/wires.js';
import { cullAll, resetCull } from '../canvas/culling.js';
import { resetWires } from '../canvas/wiredraw.js';
import { clearJumpbar, drawJumpbar, zoomVars } from '../minimap/overview.js';
import { frameById } from '../frames/groups.js';
import { adoptLegacy, drawFrames, initialView } from '../frames/nesting.js';
import { drawNotes, noteById } from '../frames/notes.js';
import { scheduleTree } from '../hierarchy/tree.js';
import { renderInspector } from '../inspector/inspector.js';
import { renderIntents } from '../panels/intents.js';
import { renderVars } from '../variables/tables.js';
import { renderTester } from '../tester/tester.js';

// ---------- (de)serialization ----------
export function serialize() {
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
        const lk = { from: m.id, port, to: nidOf(c.node) }, mt = S.linkMeta.get(linkKey(lk.from, port, lk.to));
        if (mt) Object.assign(lk, mt);          // reason / description of a hop into a state node
        links.push(lk);
      }
    }
  }
  // Trigger order: keep the server order, drop deleted ones, append new non-"enter" triggers by (y, x).
  const present = new Set(nodes.filter((n) => n.kind === 'trigger').map((n) => n.id));
  const order = (S.meta.order || []).filter((id) => present.has(id));
  const inOrder = new Set(order);
  nodes.filter((n) => n.kind === 'trigger' && !inOrder.has(n.id) && !isEnterTrig(n))
    .sort((a, b) => a.y - b.y || a.x - b.x).forEach((n) => order.push(n.id));
  const doc = {};
  for (const k in S.meta) if (!['nodes', 'links', 'order', 'error', 'pending'].includes(k)) doc[k] = clone(S.meta[k]);
  doc.nodes = nodes; doc.links = links; doc.order = order;
  return doc;
}

export function rebuild(doc, keepView) {
  const T = (S.perf = { t0: performance.now(), marks: [] }), mark = (k) => T.marks.push([k, Math.round(performance.now() - T.t0)]);   // S3: phase timings (scenario bigworld prints them)
  S.loading = true;
  S.meta = {};
  for (const k in doc) if (!['nodes', 'links', 'error', 'pending'].includes(k)) S.meta[k] = clone(doc[k]);
  if (!S.meta.version) S.meta.version = 1;
  nidToDf.clear();
  // L4: an interaction still in progress refers to DOM nodes that clear() is about to drop (undo/redo during a drag)
  S.editor.drag = false; S.editor.drag_point = false; S.editor.connection = false; S.editor.editor_selected = false;
  S.editor.ele_selected = null; S.editor.node_selected = null; S.editor.connection_selected = null; S.editor.connection_ele = null;
  S.editor.clear();
  resetCull(); resetWires();   // S3: every element of the culling pass / wire index is gone (culling is applied again by zoomVars() at the end)
  S.selDf = null; S.selConn = null; S.selChain = null;   // L10: a hierarchy chain selection refers to the old nodes
  S.linkMeta = new Map();
  mark('clear');
  (doc.links || []).forEach((l) => {
    const mt = {};
    if (l.reason) mt.reason = l.reason;
    if (l.description) mt.description = l.description;
    if (Object.keys(mt).length) S.linkMeta.set(linkKey(l.from, l.port, l.to), mt);
  });
  (doc.nodes || []).forEach((n) => {
    // Lot L4: a legacy Start node (old saved document / undo entry) is dropped silently: triggers start their chains
    // and the start state is fixed by the code. Its wires are skipped below (no Drawflow id), the server ignores it.
    if (n.kind === 'start') { dbg('legacy start node dropped ' + n.id); return; }
    const m = clone(n); delete m.x; delete m.y;
    m.params = m.params || {}; m.description = m.description || '';
    addNodeFromModel(m, n.x || 0, n.y || 0);
  });
  mark('nodes');
  (doc.links || []).forEach((l) => {
    const a = nidToDf.get(l.from), b = nidToDf.get(l.to);
    if (a == null || b == null) return;
    // Vars L2: a port the kind no longer has (wire into a trigger, legacy hub / Start wires) is not drawn
    // (Drawflow would throw on a missing input); the server refuses such wires anyway.
    const ka = KINDS[model(a).kind], kb = KINDS[model(b).kind];
    if (!kb || !kb.ins || !ka || !ka.outs || (l.port === 'false' && ka.outs < 2)) { dbg('wire skipped ' + l.from + '>' + l.to); return; }
    S.editor.addConnection(a, b, l.port === 'false' ? 'output_2' : 'output_1', 'input_1');
  });
  mark('links');
  cullAll();               // S3: hide everything before the first layout; the first view shows (and draws) what it needs
  docVars();               // the variables block always exists from here on (stable dirty snapshot)
  S.loading = false;
  if (!keepView) initialView();
  if (S.selFrame && !frameById(S.selFrame)) S.selFrame = null;
  if (S.selNote && !noteById(S.selNote)) S.selNote = null;
  mark('docVars');
  analyze(); mark('analyze');
  paintWires(); mark('paintWires');
  drawFrames(); mark('drawFrames');
  drawNotes(); mark('drawNotes');
  if (!keepView && adoptLegacy()) drawFrames();   // L8: old flat layout -> membership from geometry, once
  drawJumpbar(); mark('jumpbar'); zoomVars(); mark('zoomVars');
  if (!keepView) clearJumpbar();   // L6: the jump bar exists only now: measure it and free the column titles
  scheduleTree();
  renderInspector();
  renderIntents();
  if (S.curTab === 'vars') renderVars();
  if (S.curTab === 'tester') renderTester();
  mark('end');
}
