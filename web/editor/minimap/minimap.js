/**
 * Minimap navigation (lot L8).
 *
 * Purpose :  press-and-drag on the minimap (pointer capture, one rAF per frame, wheel = zoom).
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, tooltips/tooltips.js, core/state.js, core/api.js, core/chains.js, canvas/view.js,
 *            minimap/overview.js, frames/nesting.js, canvas/navigation.js, menu/context-menu.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, h } from '../core/util.js';
import { hideTip } from '../tooltips/tooltips.js';
import { S, nidToDf } from '../core/state.js';
import { dfData, model } from '../core/api.js';
import { panTo } from '../core/chains.js';
import { nodeBox } from '../canvas/view.js';
import { drawMinimap, miniGeo, scheduleMinimap } from './overview.js';
import { setView } from '../frames/nesting.js';
import { setRawView } from '../canvas/navigation.js';
import { closeCtx } from '../menu/context-menu.js';

// ---------- minimap navigation (lot L8) ----------
// Pointer events + pointer capture on the minimap canvas (mouse, pen and touch alike; the release may happen anywhere,
// even outside the minimap). The press never reaches the canvas (stopPress: no Drawflow pan). Moves only record the
// pointer; one requestAnimationFrame per frame pans arithmetically (no layout read per move) and redraws the minimap from
// geometry cached at press time, so the viewport rectangle follows live. A press inside the viewport rectangle grabs it
// (offset kept; released without moving it is a click, which still centres the view there); a press elsewhere first
// centres the view on that point (a plain click = jump there).
// shared state: S.miniDrag (core/state.js)
function miniCanvasPoint(d, clientX, clientY) {   // client px over the minimap -> graph canvas coordinates
  return { x: d.map.x0 + (clientX - d.cr.x) * d.kx / d.map.s, y: d.map.y0 + (clientY - d.cr.y) * d.ky / d.map.s };
}
// Canvas point under a client point from the current transform: precanvas screen x = B + cx + o(1 - z) + z * p.
export function arithPoint(d, clientX, clientY) {
  const z = S.editor.zoom;
  return { x: (clientX - d.bx - S.editor.canvas_x - d.ox * (1 - z)) / z, y: (clientY - d.by - S.editor.canvas_y - d.oy * (1 - z)) / z };
}
function miniApply() {
  const d = S.miniDrag; if (!d) return;
  d.raf = 0;
  const p = miniCanvasPoint(d, d.px, d.py), c = arithPoint(d, d.vc.x, d.vc.y), z = S.editor.zoom;
  const dx = (c.x - p.x - d.off.x) * z, dy = (c.y - p.y - d.off.y) * z;
  if (Math.abs(dx) + Math.abs(dy) > 0.01) setRawView(z, S.editor.canvas_x + dx, S.editor.canvas_y + dy);
  if (S.miniRaf) { cancelAnimationFrame(S.miniRaf); S.miniRaf = 0; }
  drawMinimap();                           // same frame: the rectangle follows the pan at once
}
export function miniDown(e) {
  const cv = e.currentTarget, m = S.miniEl && S.miniEl._map;
  if (!m || e.button || e.isPrimary === false || S.miniDrag) return;
  e.preventDefault(); e.stopPropagation();
  hideTip(); closeCtx();
  try { cv.setPointerCapture(e.pointerId); } catch (err) { /* synthetic event without a live pointer */ }
  const cr = cv.getBoundingClientRect(), st = S.editor.container.getBoundingClientRect(), pr = S.editor.precanvas.getBoundingClientRect();
  const ox = S.editor.precanvas.clientWidth / 2, oy = S.editor.precanvas.clientHeight / 2, z = S.editor.zoom;
  // kx / ky: the canvas is drawn at its intrinsic size but shown at its CSS size (the old click handler ignored that)
  const d = { pid: e.pointerId, map: { x0: m.x0, y0: m.y0, s: m.s }, cr, kx: cv.width / (cr.width || cv.width), ky: cv.height / (cr.height || cv.height),
    st, vc: { x: st.x + st.width / 2, y: st.y + st.height / 2 }, ox, oy,
    bx: pr.x - S.editor.canvas_x - ox * (1 - z), by: pr.y - S.editor.canvas_y - oy * (1 - z),
    geo: miniGeo(), off: { x: 0, y: 0 }, px: e.clientX, py: e.clientY, x0: e.clientX, y0: e.clientY, raf: 0, grab: false, moved: false };
  const p = miniCanvasPoint(d, e.clientX, e.clientY), v = S.miniEl._view, c = arithPoint(d, d.vc.x, d.vc.y);
  if (v && p.x >= v.x0 && p.x <= v.x1 && p.y >= v.y0 && p.y <= v.y1) { d.off = { x: c.x - p.x, y: c.y - p.y }; d.grab = true; }   // grab
  S.miniDrag = d;
  S.miniEl.classList.add('dragging');
  document.body.classList.add('mini-drag');   // no text selection over the jump bar / panels while dragging
  miniApply();
}
export function miniMove(e) {
  const d = S.miniDrag; if (!d || e.pointerId !== d.pid) return;
  if (e.cancelable) e.preventDefault();
  d.px = e.clientX; d.py = e.clientY;
  if (!d.moved && Math.hypot(d.px - d.x0, d.py - d.y0) >= 3) d.moved = true;   // below 3 px it is still a click
  if (!d.raf) d.raf = requestAnimationFrame(miniApply);
}
export function miniUp(e) {
  const d = S.miniDrag; if (!d || (e && e.pointerId !== d.pid)) return;
  if (d.raf) cancelAnimationFrame(d.raf);
  if (e && e.type === 'pointerup') { d.px = e.clientX; d.py = e.clientY; }
  if (d.grab && !d.moved) d.off = { x: 0, y: 0 };   // a click inside the viewport rectangle centres there too
  if (e && e.type !== 'lostpointercapture') miniApply();
  S.miniDrag = null;
  if (S.miniEl) S.miniEl.classList.remove('dragging');
  document.body.classList.remove('mini-drag');
  try { const sel = window.getSelection(); if (sel && !sel.isCollapsed) sel.removeAllRanges(); } catch (err) { /* nothing selected */ }
  scheduleMinimap();
}
// Semantic-zoom card of an automatic frame: state name, chain count, wires in / out of the column.
export function frameCard(f) {
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
export function focusChainIds(ids) {
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  (ids || []).forEach((nid) => { const d = nidToDf.get(nid); const m = d == null ? null : model(d); if (!m || m.kind === 'state') return; const b = nodeBox(d); x0 = Math.min(x0, b.x0); y0 = Math.min(y0, b.y0); x1 = Math.max(x1, b.x1 + 120); y1 = Math.max(y1, b.y1); });
  if (x0 > x1) { const first = (ids || [])[0]; if (first) panTo(first, 0.75); return; }
  const c = $('#drawflow'), w = x1 - x0, hh = y1 - y0;
  const z = Math.max(0.3, Math.min(0.75, c.clientWidth / (w * 1.15), (c.clientHeight - 50) / (hh * 1.15)));
  setView(z, c.clientWidth / 2 - ((x0 + x1) / 2) * z, 25 + c.clientHeight / 2 - ((y0 + y1) / 2) * z);
}
