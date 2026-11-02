/**
 * Frames: groups (cosmetic frames, "Groupe").
 *
 * Purpose :  meta.frames list access, colours, frame element placement.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { h } from '../core/util.js';
import { S } from '../core/state.js';

// ---------- groups (cosmetic frames, "Groupe") ----------
// meta.frames = [{id, title, color, x, y, w, h, note?}] lives in the document (serialize() copies meta), so undo/redo,
// dirty tracking and Enregistrer cover it for free. The server stores it only in graph.layout.json: it is never
// compiled into graph.yaml. Drawn in a #frames layer inside precanvas (so pan/zoom apply), after #bands and before
// the nodes; only the title bar and the resize handle take pointer events, the rest lets clicks reach the canvas.
export const FRAME_COLORS = [['Jaune', '#e3b341'], ['Bleu', '#4f8ef7'], ['Vert', '#56d364'], ['Rouge', '#e5534b'],
  ['Violet', '#a371f7'], ['Orange', '#f0883e'], ['Gris', '#8b949e'], ['Cyan', '#39c5cf']];
export const FRAME_PAD = { l: 32, r: 32, t: 72, b: 32 };      // around a node box; t leaves room for the 30 px title bar and the band title
// shared state: S.selFrame (core/state.js)
// shared state: S.framesEl (core/state.js)
// shared state: S.frameDrag (core/state.js)
export const frameEls = new Map();
export const frames = () => (S.meta.frames = Array.isArray(S.meta.frames) ? S.meta.frames : []);
export const frameById = (id) => frames().find((f) => f.id === id);
export function ensureFrames() {
  if (!S.framesEl || !S.framesEl.isConnected) { S.framesEl = h('div', { id: 'frames' }); S.editor.precanvas.insertBefore(S.framesEl, S.editor.precanvas.firstChild); }
  return S.framesEl;
}
// Readable text colour on a frame colour (#rrggbb).
function inkOn(hex) {
  const n = parseInt(hex.slice(1), 16), lum = 0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255);
  return lum > 150 ? '#10141a' : '#ffffff';
}
export function placeFrame(f, el) {
  el.style.cssText = `--c:${f.color};--ink:${inkOn(f.color)};left:${f.x}px;top:${f.y}px;width:${f.w}px;height:${f.h}px`;
}
