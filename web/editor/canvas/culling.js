/**
 * Canvas: off-screen culling (lot S3, plan "espace sans limite" A4).
 *
 * Purpose :  keep the editor fluid on a graph ten times the shipped one (~2,300 nodes): the nodes (and the wires) that
 *            are outside the view plus a margin get `display:none` (class `cull` on the node wrapper `.parent-node` /
 *            on the wire svg), so the browser neither styles, lays out nor paints them. Under the semantic zoom
 *            (column / domain cards, zoom < 0.25) the cards hide every node anyway: all nodes and wires are culled.
 * Boundary:  DOM of the editor page and the shared state S only, no network call, never writes the document (a cull
 *            class is a display state, not data: serialize() / undo never see it). The geometry comes from the cache
 *            of canvas/geometry.js (node sizes by ResizeObserver, view by arithmetic): a pan / zoom frame makes NO
 *            layout read. The wire index is canvas/wiredraw.js.
 * Invariants: (1) wires are drawn from cached geometry (canvas/wiredraw.js), so a culled node still gets exact wires and
 *            nothing has to be shown for a redraw; when a node comes back its wires are already right.
 *            (2) the selected node, the node being dragged and the ends of the selected wire are never culled.
 *            (3) culling is a pure function of (view, zoom, node boxes, selection): applyCull(true) recomputes every
 *            state from scratch; a rebuild of the document resets it (resetCull). (4) a wire is culled only when both
 *            ends are, and the box spanned by its two ends misses the view.
 * Depends :  core/state.js, core/api.js, canvas/geometry.js, canvas/wiredraw.js, canvas/wires.js
 * Test    :  tests/web/bigworld.py (scenario `bigworld`: culled counts, nothing missing once shown, frame times).
 */
import { S } from '../core/state.js';
import { dfData } from '../core/api.js';
import { NODE_DEFAULT, geoVer, nodeSize, viewRect } from './geometry.js';
import { drawBatch, drawNodesWires, eagerWires, isDrawn, wireList, wireRev } from './wiredraw.js';
import { paintSvgs } from './wires.js';

const C = { arr: null, byId: new Map(), geo: -1, count: -1, key: '', applies: 0, skipped: 0, ms: 0, on: true };

// Forget every cached entry (rebuild of the document: all elements are new and visible).
export function resetCull() { C.arr = null; C.key = ''; }
// Right after the nodes and wires of a freshly built document exist, BEFORE anything measures them: hide them all, so
// the first layout of the page only lays out what the first view needs (applyCull shows that, at the end of rebuild).
export function cullAll() {
  if (!C.on || !S.editor || !S.editor.precanvas) return;
  // small graph (eager wires): leave everything shown so the first pass measures every port in one layout
  if (eagerWires()) { C.arr = null; C.key = ''; return; }
  S.editor.precanvas.querySelectorAll('.parent-node').forEach((n) => n.classList.add('cull'));
  S.editor.container.querySelectorAll('svg.connection').forEach((n) => n.classList.add('cull'));
  C.arr = null; C.key = '';
}
export function setCullEnabled(on) { C.on = !!on; C.key = ''; if (!on) showAll(); else applyCull(true); }
export const cullStats = () => {
  const w = S.editor && S.editor.container ? wireList() : [];
  return { on: C.on, nodes: C.arr ? C.arr.length : 0, culled: C.arr ? C.arr.filter((e) => e.off).length : 0,
    wires: w.length, wiresCulled: w.filter((x) => x.off).length, applies: C.applies, skipped: C.skipped, ms: Math.round(C.ms * 100) / 100 };
};

// ---------- entries: one per node (box in canvas coordinates, wrapper element) ----------
function entries() {
  const data = dfData(), keys = Object.keys(data);
  if (C.arr && C.geo === geoVer() && C.count === keys.length) return C.arr;
  const byId = new Map(), arr = [];
  // reads first (nodeSize measures a never-seen element once), class toggles later: no layout thrash
  for (const df of keys) {
    const nd = data[df], el = document.getElementById('node-' + df);
    if (!el) continue;
    const wrap = el.parentElement || el, sz = nodeSize(df, el) || NODE_DEFAULT;
    const e = { df, el, wrap, x0: nd.pos_x, y0: nd.pos_y, x1: nd.pos_x + sz.w, y1: nd.pos_y + sz.h, off: wrap.classList.contains('cull') };
    byId.set(df, e); arr.push(e);
  }
  C.arr = arr; C.byId = byId; C.geo = geoVer(); C.count = keys.length;
  return arr;
}

// ---------- the cull pass ----------
const hit = (e, v) => e.x0 < v.x1 && e.x1 > v.x0 && e.y0 < v.y1 && e.y1 > v.y0;
function keepSet() {
  const keep = new Set();
  const add = (el) => { const n = el && el.closest && el.closest('.drawflow-node'); if (n && n.id) keep.add(n.id.slice(5)); };
  if (S.selDf != null) keep.add(String(S.selDf));
  add(S.editor.node_selected); add(S.editor.ele_selected);
  const cs = S.editor.connection_selected, svg = cs && cs.closest && cs.closest('svg.connection');
  if (svg && svg.classList.length >= 5) { keep.add(svg.classList[2].slice(14)); keep.add(svg.classList[1].slice(13)); }
  return keep;
}
// Recompute which nodes / wires are shown. `force` = ignore the "same view, same geometry" shortcut. `ov` = {x, y}
// canvas translation to use instead of S.editor.canvas_x/y (Drawflow dispatches `translate` before it stores them).
export function applyCull(force, ov) {
  if (!S.editor || !S.editor.precanvas || !S.editor.container || S.loading) return;
  const t0 = performance.now();
  const z = S.editor.zoom, cx = ov && ov.x != null ? ov.x : S.editor.canvas_x, cy = ov && ov.y != null ? ov.y : S.editor.canvas_y;
  const sem = S.editor.container.classList.contains('semzoom');
  const wires0 = wireList();                                      // (rebuilds the index when the wire set changed)
  const key = [cx, cy, z, sem, geoVer(), C.on, wireRev()].join('|') + '|' + S.selDf;
  if (!force && key === C.key) { C.skipped++; return; }
  C.key = key;
  const arr = entries(), wires = wires0;
  const vr = viewRect(cx, cy, z), m = Math.max(vr.x1 - vr.x0, vr.y1 - vr.y0) * 0.5 + 300;
  const view = { x0: vr.x0 - m, y0: vr.y0 - m, x1: vr.x1 + m, y1: vr.y1 + m };
  const keep = keepSet();
  const flips = [];
  for (const e of arr) {
    const shown = !C.on || (!sem && hit(e, view)) || keep.has(e.df);
    if (shown === e.off) flips.push([e, !shown]);
  }
  const wflips = [];
  for (const w of wires) {
    const ea = C.byId.get(w.a), eb = C.byId.get(w.b);
    let shown = true;                                              // a wire to an unknown node is left alone
    if (C.on && ea && eb) {
      shown = keep.has(w.a) || keep.has(w.b)
        || (!sem && (hit(ea, view) || hit(eb, view)
          || hit({ x0: Math.min(ea.x0, eb.x0), y0: Math.min(ea.y0, eb.y0), x1: Math.max(ea.x1, eb.x1), y1: Math.max(ea.y1, eb.y1) }, view)));
    }
    if (shown === w.off) wflips.push([w, !shown]);
  }
  cullItems(view, sem);                                            // groups and post-its (same rule, their own boxes)
  // eager (small graph): every wire gets its path + gradient, culled or not, BEFORE nodes are hidden (ports measured
  // while shown, one layout flush)
  const eager = eagerWires();
  if (eager) { const all = wires.filter((w) => !isDrawn(w)); if (all.length) paintSvgs(drawBatch(all).svgs); }
  for (const [e, off] of flips) { e.off = off; e.wrap.classList.toggle('cull', off); }
  for (const [w, off] of wflips) { w.off = off; w.svg.classList.toggle('cull', off); }
  // wires that are shown but have no path yet (first view of a loaded document, or moved while culled): draw them in one
  // batch from the cached geometry, then paint their gradient
  const todo = wires.filter((w) => !w.off && !isDrawn(w));
  if (todo.length) paintSvgs(drawBatch(todo).svgs);
  C.applies++; C.ms += performance.now() - t0;
}

// ---------- groups (frames) and post-its ----------
// Same view test on their data boxes (meta.frames / meta.notes: x, y, w, h; a post-it grows with its text, the margin
// covers it). Under the semantic zoom the column cards cover what a column holds: its sub-groups and post-its are culled.
// Elements are found through the layer children (data-fid / data-nid), so this module imports neither frames/ nor notes.
function rootOf(f, byId) { let g = f, n = 0; while (g && g.parent && n++ < 50) g = byId.get(g.parent); return g; }
function cullItems(view, sem) {
  const fl = (S.meta && S.meta.frames) || [], nl = (S.meta && S.meta.notes) || [];
  const byId = new Map(fl.map((f) => [f.id, f]));
  const inColumn = (it) => { const r = it.parent ? rootOf(it, byId) : null; return !!(r && r.auto); };
  const sel = new Set([S.selFrame, S.selNote, S.frameDrag && S.frameDrag.f && S.frameDrag.f.id]);
  const layer = (el, attr) => { const m = new Map(); if (el) for (const c of el.children) m.set(c.getAttribute(attr), c); return m; };
  const fe = layer(S.framesEl, 'data-fid'), ne = layer(S.notesEl, 'data-nid');
  const toggle = (list, els) => {
    for (const it of list) {
      const el = els.get(it.id); if (!el) continue;
      const box = { x0: it.x, y0: it.y, x1: it.x + (it.w || 0), y1: it.y + (it.h || 0) };
      const shown = !C.on || sel.has(it.id) || (hit(box, view) && !(sem && it.parent && inColumn(it)));
      if (shown === el.classList.contains('cull')) el.classList.toggle('cull', !shown);
    }
  };
  toggle(fl, fe); toggle(nl, ne);
}
// Show every node and wire again (culling switched off).
function showAll() {
  document.querySelectorAll('.cull').forEach((x) => x.classList.remove('cull'));
  if (C.arr) C.arr.forEach((e) => { e.off = false; });
  if (S.editor && S.editor.container) wireList().forEach((w) => { w.off = false; });
}
// Redraw the wires of many moved nodes in ONE pass (a fold repack, a column or frame drag, a hierarchy move): the
// positions are already set; the wires are drawn from the cached geometry, then the cull pass sees the new boxes.
export function updateWires(dfids) {
  if (S.loading) return;
  const r = drawNodesWires(dfids);
  paintSvgs(r.svgs);
  if (r.own) for (const d of dfids) S.editor.updateConnectionNodes('node-' + d);   // reroute points: Drawflow's own code
  C.arr = null; applyCull(true);
}
