/**
 * Canvas: geometry cache (lot S2, plan "espace sans limite" A3).
 *
 * Purpose :  node box sizes and the viewport geometry WITHOUT a layout read per frame. Node sizes are measured once
 *            (offsetWidth / offsetHeight, the only read), then kept up to date by a ResizeObserver (edit of a node's
 *            text, font load, unfold); the container / precanvas sizes and the untransformed precanvas offset are
 *            measured once and invalidated by the same observer (window resize, side panels toggled). viewRect() and
 *            fastCanvasPoint() turn the Drawflow transform into canvas coordinates arithmetically.
 * S3:       portRel(): offset of a port inside its node (measured once, then arithmetic; canvas/wiredraw.js draws the wires
 *            from it); viewRect() accepts a translation / zoom override.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Never writes the document.
 * Invariant: a node hidden by a fold (display:none, 0 x 0) keeps its last known size (or the default card size when it
 *            was never shown), so a fold never invalidates the boxes of the content it hides; `ver` increases on every
 *            geometry change (bumpGeo: edits, frame / domain redraws, node moves; observer: size changes), so a cache
 *            keyed on it (minimap world, zoom range) is never stale. `reads` counts the layout reads made here (cache
 *            misses only): a pan / zoom frame must not add any (scenario `minimap2`).
 * Depends :  core/state.js
 * Test    :  tests/web/space.py (scenarios `zoom3`, `minimap2`) through window.__editor.geoStats / nodeBoxOf.
 */
import { S } from '../core/state.js';

export const NODE_DEFAULT = { w: 214, h: 80 };   // size of a node never measured (hidden from the start)
export const FOLD_COL = { w: 340, h: 190 };     // a folded column: its frame shrinks to this card (graph_layout.FOLD_COL_*)
export const FOLD_DOM = { w: 520, h: 250 };     // a folded domain: its region shrinks to this card (graph_layout.FOLD_DOM_*)

const G = { ver: 1, sizes: new Map(), ports: new Map(), ro: null, reads: 0, misses: 0, view: null, viewEls: [], listener: null };
export const geoVer = () => G.ver;
export function bumpGeo() { G.ver++; }
export const geoStats = () => ({ ver: G.ver, reads: G.reads, misses: G.misses, cached: G.sizes.size, view: !!G.view });
// Called (once per animation frame at most, by the caller) when the observer saw a size change.
export function setGeoListener(fn) { G.listener = fn; }

function observer() {
  if (!G.ro && typeof ResizeObserver !== 'undefined') G.ro = new ResizeObserver(onResize);
  return G.ro;
}
function onResize(entries) {
  let changed = false;
  for (const e of entries) {
    const t = e.target;
    if (G.viewEls.includes(t)) { G.view = null; changed = true; continue; }
    const c = t._geoDf != null ? G.sizes.get(t._geoDf) : null; if (!c || c.el !== t) continue;
    const bs = e.borderBoxSize && (e.borderBoxSize[0] || e.borderBoxSize);
    const w = bs ? bs.inlineSize : e.contentRect.width, hh = bs ? bs.blockSize : e.contentRect.height;
    if (!w || !hh) continue;                 // hidden by a fold: keep the last known size
    if (Math.abs(c.w - w) > 0.5 || Math.abs(c.h - hh) > 0.5) { c.w = w; c.h = hh; c.hidden = false; changed = true; G.ports.delete(t._geoDf); }   // S3: ports move with the box
  }
  if (changed) { G.ver++; if (G.listener) G.listener(); }
}
// {w, h} of a node element (cached). The first call per element reads the layout once.
export function nodeSize(dfid, el) {
  const key = String(dfid), c = G.sizes.get(key);
  if (c && c.el === el) return c;
  if (c && G.ro) G.ro.unobserve(c.el);       // the element was replaced (rebuild): forget the old one
  G.misses++; G.reads++;
  const w = el.offsetWidth, hh = el.offsetHeight;
  const n = w || hh ? { el, w, h: hh, hidden: false } : { el, w: NODE_DEFAULT.w, h: NODE_DEFAULT.h, hidden: true };
  G.sizes.set(key, n); el._geoDf = key;
  const ro = observer(); if (ro) ro.observe(el);
  return n;
}
// Drop the cached size of a node (refreshNode: its content changed; the observer would catch it a frame later).
export function forgetNode(dfid) {
  const c = G.sizes.get(String(dfid)); if (!c) return;
  if (G.ro) G.ro.unobserve(c.el);
  G.sizes.delete(String(dfid)); G.ports.delete(String(dfid)); G.ver++;
}
// S3: offset of a port (`cls` = "output_1" / "input_1") from the node's top-left corner, to the port's centre, in canvas
// units. Measured once per node and port (two rectangle reads), then arithmetic: port centre = node position + this.
// Returns null when the node is not displayed (nothing is cached then). Dropped when the node's size changes.
export function portRel(dfid, el, cls) {
  const key = String(dfid);
  let m = G.ports.get(key);
  if (!m || m.el !== el) { m = { el, p: {} }; G.ports.set(key, m); }
  if (m.p[cls]) return m.p[cls];
  const port = el.querySelector('.' + cls);
  if (!port) return null;
  nodeSize(dfid, el);                    // observed from now on: a size change drops the cached ports (onResize)
  G.reads++;
  const nr = el.getBoundingClientRect(), pr = port.getBoundingClientRect(), z = S.editor.zoom || 1;
  if (!nr.width) return null;
  return (m.p[cls] = { x: (pr.x - nr.x) / z + port.offsetWidth / 2, y: (pr.y - nr.y) / z + port.offsetHeight / 2 });
}
// Container / precanvas geometry, measured once (two rect reads) and kept until the observer or a window resize.
function viewGeo() {
  if (G.view) return G.view;
  const c = S.editor.container, p = S.editor.precanvas, z = S.editor.zoom;
  G.reads++;
  const cr = c.getBoundingClientRect(), pr = p.getBoundingClientRect();
  const ox = p.clientWidth / 2, oy = p.clientHeight / 2;
  // untransformed precanvas origin relative to the container: screen x of canvas point q = left + offX + cx + ox(1 - z) + z q
  G.view = { left: cr.left, top: cr.top, w: cr.width, h: cr.height, ox, oy,
    offX: pr.left - cr.left - S.editor.canvas_x - ox * (1 - z), offY: pr.top - cr.top - S.editor.canvas_y - oy * (1 - z) };
  if (!G.viewEls.length) {
    G.viewEls = [c, p];
    const ro = observer(); if (ro) { ro.observe(c); ro.observe(p); }
    window.addEventListener('resize', () => { G.view = null; });
  }
  return G.view;
}
export function invalidateView() { G.view = null; }
// Visible part of the canvas in canvas coordinates (no layout read once measured).
// S3: optional translation / zoom override (cx, cy, z): Drawflow dispatches `translate` before it stores canvas_x / y.
export function viewRect(cx = S.editor.canvas_x, cy = S.editor.canvas_y, z = S.editor.zoom) {
  const v = viewGeo();
  const sx = v.offX + cx + v.ox * (1 - z), sy = v.offY + cy + v.oy * (1 - z);
  return { x0: -sx / z, y0: -sy / z, x1: (v.w - sx) / z, y1: (v.h - sy) / z, w: v.w, h: v.h };
}
// Canvas point under a client point (same result as frames/nesting.js canvasPoint, without its rect read).
export function fastCanvasPoint(clientX, clientY) {
  const v = viewGeo(), z = S.editor.zoom;
  return { x: (clientX - v.left - v.offX - S.editor.canvas_x - v.ox * (1 - z)) / z,
    y: (clientY - v.top - v.offY - S.editor.canvas_y - v.oy * (1 - z)) / z };
}
// Precanvas half size (Drawflow scales around it), from the cache.
export const viewOrigin = () => { const v = viewGeo(); return { ox: v.ox, oy: v.oy, left: v.left + v.offX, top: v.top + v.offY, cl: v.left, ct: v.top, w: v.w, h: v.h }; };
