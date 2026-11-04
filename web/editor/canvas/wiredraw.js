/**
 * Canvas: wire index and arithmetic wire drawing (lot S3, plan "espace sans limite" A4 + A5).
 *
 * Purpose :  Drawflow redraws the wires of a node (updateConnectionNodes) by searching the whole container for the
 *            wires (querySelectorAll, O(DOM)) and by reading 4 bounding rectangles per wire: for a graph ten times the
 *            shipped one that was the load time (62 s) and the fold / unfold time (33 s / 9 s). This module keeps a
 *            wire index (node -> its wires, built once per change of the wire set) and draws a wire from the cached
 *            geometry: port centre = node position + the port offset inside the node (canvas/geometry.js portRel,
 *            measured once per node, no layout read afterwards), then Drawflow's own createCurvature().
 * Boundary:  DOM of the editor page and the shared state S only, no network call, never writes the document. It
 *            replaces the work of Drawflow.updateConnectionNodes for plain wires (no reroute point; the editor sets
 *            `reroute = false`); a wire with a `.point` still goes through Drawflow's own code.
 * Invariants: (1) the path of a wire is `createCurvature(out port centre, in port centre, curvature, 'openclose')`, the
 *            same call, with the same centres, as Drawflow makes (the wire tests compare the ends with the port
 *            rectangles). (2) a culled (display:none) node still gets exact wires: its ports are measured while it is
 *            shown (always the case at load) and cached, the rest is arithmetic. (3) while the document loads
 *            (S.loading) nothing is drawn per link; a wire is drawn when it first comes into view (culling.js), in one
 *            batch with the others, and again after a move of one of its nodes.
 * Depends :  core/state.js, canvas/geometry.js
 * Test    :  tests/web/bigworld.py (scenario `bigworld`: load time, wires equal to the port rectangles after a fold),
 *            the wire scenarios (`wires`, `wiredrag`, `foldpack`).
 */
import { S } from '../core/state.js';
import { dfData, dfNode } from '../core/api.js';
import { portRel } from './geometry.js';

const W = { list: null, by: new Map(), dirty: true, n: -1, rev: 0 };
export const wireRev = () => W.rev;      // changes with the wire set (the cull pass keys on it)

// ---------- wire index ----------
export function resetWires() { W.list = null; W.by = new Map(); W.dirty = true; W.rev++; }
export function markWiresDirty() { W.dirty = true; W.rev++; }
export function wireList() {
  const live = S.editor.container.getElementsByClassName('connection');
  if (W.list && !W.dirty && W.n === live.length) return W.list;
  const list = [], by = new Map();
  for (const svg of live) {
    const cl = svg.classList;
    if (cl.length < 5) continue;                       // the wire being dragged has no ends yet
    const w = { svg, a: cl[2].slice(14), b: cl[1].slice(13), outCls: cl[3], inCls: cl[4], off: cl.contains('cull') };
    list.push(w);
    for (const k of [w.a, w.b]) { if (!by.has(k)) by.set(k, []); by.get(k).push(w); }
  }
  W.list = list; W.by = by; W.dirty = false; W.n = live.length; W.rev++;
  return list;
}
export function wiresOf(dfid) { wireList(); return W.by.get(String(dfid)) || []; }

// ---------- drawing ----------
// A wire is DRAWN once it has a path computed from the current positions. A culled wire is not drawn (nobody can see
// it): it is drawn when it comes into view (canvas/culling.js), and a move of one of its nodes makes it undrawn again.
const drawn = new WeakSet();
export const isDrawn = (w) => drawn.has(w.svg);
// Correctness beats speed on graphs of the shipped size: up to EAGER_MAX nodes EVERY wire is drawn and painted (path +
// gradient), culled or not, so a wire is never stale or unpainted whatever the view; the deferred drawing above only
// applies to bigger graphs (the 10x bigworld). Visibility (the `cull` class) is still decided by canvas/culling.js.
export const EAGER_MAX = 600;
export const eagerWires = () => !!(S.editor && S.editor.drawflow) && Object.keys(dfData()).length <= EAGER_MAX;
// Port centre of node `dfid` in canvas coordinates, or null when it cannot be measured (never shown).
function centre(dfid, cls) {
  const nd = dfNode(dfid), el = document.getElementById('node-' + dfid);
  if (!nd || !el) return null;
  let r = portRel(dfid, el, cls);
  if (!r) {                                            // hidden and never measured: show it for the measure only
    const wrap = el.parentElement, was = wrap && wrap.classList.contains('cull');
    if (was) wrap.classList.remove('cull');
    r = portRel(dfid, el, cls);
    if (was) wrap.classList.add('cull');
    if (!r) return null;
  }
  // Drawflow moves the element during a drag and stores pos_x / pos_y only when the drag ends: the live position is the style
  const lx = parseFloat(el.style.left), ly = parseFloat(el.style.top);
  return { x: (Number.isFinite(lx) ? lx : nd.pos_x) + r.x, y: (Number.isFinite(ly) ? ly : nd.pos_y) + r.y };
}
// Draw `ws` in two passes (all the centres are measured first, then all the paths are written: one layout flush at
// most). Returns the svg elements that were drawn (a wire with reroute points is left to Drawflow's own code).
export function drawBatch(ws) {
  const todo = [];
  for (const w of ws) {
    if (w.svg.querySelector('.point')) { todo.push({ w, own: true }); continue; }
    const s = centre(w.a, w.outCls), e = centre(w.b, w.inCls);
    if (s && e) todo.push({ w, s, e });
  }
  const out = [];
  for (const t of todo) {
    if (t.own) continue;
    t.w.svg.children[0].setAttributeNS(null, 'd', S.editor.createCurvature(t.s.x, t.s.y, t.e.x, t.e.y, S.editor.curvature, 'openclose'));
    drawn.add(t.w.svg); out.push(t.w.svg);
  }
  return { svgs: out, own: todo.filter((t) => t.own).length };
}
// Redraw the wires of node `dfid` (both directions): the visible ones now, the culled ones when they come back.
// Returns false when Drawflow's own code must do it (reroute points).
export function drawNodeWires(dfid) {
  const live = [], eager = eagerWires();
  for (const w of wiresOf(dfid)) { if (w.off && !eager) drawn.delete(w.svg); else live.push(w); }
  return drawBatch(live).own === 0;
}
// Many nodes at once (a repack moved them): every wire touching one of them is drawn in ONE batch, each wire once.
// Returns {svgs, own}: the drawn elements (for the gradient pass) and how many wires need Drawflow's own code.
export function drawNodesWires(dfids) {
  const live = [], seen = new Set(), eager = eagerWires();
  for (const d of dfids) {
    for (const w of wiresOf(d)) {
      if (seen.has(w.svg)) continue;
      seen.add(w.svg);
      if (w.off && !eager) drawn.delete(w.svg); else live.push(w);
    }
  }
  return drawBatch(live);
}
// Replacement of Drawflow.updateConnectionNodes (installed in core/boot.js): `orig` is Drawflow's version.
export function fastUpdate(orig, id) {
  if (S.loading) return;                               // rebuild(): the wires are drawn when they first come into view
  const dfid = String(id).replace(/^node-/, '');
  if (!drawNodeWires(dfid)) orig(id);
}
