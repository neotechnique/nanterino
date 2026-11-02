/**
 * Frames: post-it notes.
 *
 * Purpose :  meta.notes drawing, editing, display modes (compact / full), drag and nesting into groups.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, core/api.js, core/history.js, canvas/view.js, frames/groups.js,
 *            frames/nesting.js, canvas/navigation.js, hierarchy/tree.js, inspector/fields.js, inspector/inspector.js,
 *            core/ui.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, h, ico } from '../core/util.js';
import { S, NOTE_COLORS } from '../core/state.js';
import { dfData } from '../core/api.js';
import { commitSoon } from '../core/history.js';
import { bandRects, nodeBox } from '../canvas/view.js';
import { ensureFrames } from './groups.js';
import {
  canvasPoint, clearNodeSelection, drawFrames, dropTarget, dropTargetAt, evPoint, fitAncestors, focusRect,
  markDrop, noteBox, parentOf, reparent
} from './nesting.js';
import { editBlocked } from '../canvas/navigation.js';
import { scheduleTree } from '../hierarchy/tree.js';
import { areaCtl, field, selectCtl, textCtl } from '../inspector/fields.js';
import { renderInspector } from '../inspector/inspector.js';
import { toast } from '../core/ui.js';

// ---------- post-it notes ----------
// meta.notes = [{id, text, color, x, y, w, h, title?}] lives in the document (serialize() copies meta), so undo/redo, the
// dirty flag and "Enregistrer" cover it. The server keeps it only in graph.layout.json: never compiled. Drawn in a #notes
// layer inside precanvas (pan/zoom apply), above the frames and wires, below the nodes. Only the left button/primary touch
// drags or resizes (header = move, corner = resize); the text area edits in place.
// shared state: S.selNote, S.notesEl, S.noteDrag (core/state.js)
export const noteEls = new Map();
export const notes = () => (S.meta.notes = Array.isArray(S.meta.notes) ? S.meta.notes : []);
export const noteById = (id) => notes().find((n) => n.id === id);
function ensureNotes() {
  if (!S.notesEl || !S.notesEl.isConnected) { S.notesEl = h('div', { id: 'notes' }); S.editor.precanvas.insertBefore(S.notesEl, ensureFrames().nextSibling); }
  return S.notesEl;
}
// Lot L5 display modes (n.display, stored only when 'compact'): full = the whole text, the note grows with it (h is
// its minimum height); compact = title bar + first line, the full text in the note's tooltip.
const noteCompact = (n) => n.display === 'compact';
export const noteFirstLine = (n) => ((n.text || '').split('\n').find((l) => l.trim()) || '').trim();
const noteTip = (n) => [n.title, n.text].filter((x) => x && String(x).trim()).join('\n') || 'Post-it vide';
export function placeNote(n, el) {
  el.style.cssText = `--c:${n.color};left:${n.x}px;top:${n.y}px;width:${n.w}px;` + (noteCompact(n) ? '' : `min-height:${n.h}px`);
  el.classList.toggle('compact', noteCompact(n)); el.classList.toggle('full', !noteCompact(n));
}
function growNote(el) {   // full mode: the text area takes the height of its text (wraps, no inner scroll bar)
  const ta = el && el.querySelector('.ptext');
  if (!ta || el.classList.contains('compact')) return;
  ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 'px';
}
function refreshNoteText(n, el) {
  const pl = el.querySelector('.pline'); if (pl) pl.textContent = noteFirstLine(n) || '(vide)';
  if (noteCompact(n)) el.setAttribute('data-tip', noteTip(n)); else el.removeAttribute('data-tip');
  growNote(el);
}
// Height of a note as drawn (full notes grow, compact ones shrink), in canvas px.
export function noteHeight(n) { const el = noteEls.get(n.id); return el && el.offsetHeight ? el.offsetHeight : n.h; }
export function setNoteDisplay(n, mode) {
  if (!n || editBlocked()) return;
  if (mode === 'compact') n.display = 'compact'; else delete n.display;
  drawNotes(); if (S.selNote === n.id) renderInspector();
  commitSoon();
}
export function drawNotes() {
  if (!S.editor) return;
  const root = ensureNotes(); root.innerHTML = ''; noteEls.clear();
  notes().forEach((n) => {
    const ta = h('textarea', { class: 'ptext', maxlength: 2000, placeholder: 'Écrivez ici…', 'aria-label': 'Texte du post-it' });
    ta.value = n.text || '';
    ta.addEventListener('input', () => { n.text = ta.value; refreshNoteText(n, ta.closest('.postit')); });
    ta.addEventListener('change', () => { n.text = ta.value; commitSoon(); if (S.selNote === n.id) renderInspector(); });
    ta.addEventListener('focus', () => selectNote(n.id, true));
    const compact = noteCompact(n);
    const head = h('div', { class: 'phead', title: 'Glisser pour déplacer le post-it' }, ico('message'), h('span', { class: 'ptitle' + (n.title ? '' : ' empty') }, n.title || 'Post-it'),
      h('button', { type: 'button', class: 'pmode', 'data-tip': compact ? 'Afficher tout le texte' : 'Compact : seulement le titre et la première ligne (le texte complet en info-bulle)',
        'aria-label': compact ? 'Afficher tout le texte' : 'Réduire le post-it', 'aria-pressed': String(compact),
        onclick: (e) => { e.stopPropagation(); setNoteDisplay(n, compact ? 'full' : 'compact'); } }, compact ? '▾' : '▴'),
      h('button', { type: 'button', class: 'pdel', title: 'Supprimer le post-it', 'aria-label': 'Supprimer le post-it',
        onclick: (e) => { e.stopPropagation(); deleteNote(n.id); } }, '×'));
    const line = h('div', { class: 'pline' }, noteFirstLine(n) || '(vide)');
    const grip = h('div', { class: 'presize', title: 'Redimensionner' });
    const el = h('div', { class: 'postit' + (n.id === S.selNote ? ' sel' : ''), 'data-nid': n.id }, head, ta, line, grip);
    placeNote(n, el);
    if (compact) el.setAttribute('data-tip', noteTip(n));
    el.addEventListener('mousedown', (e) => { e.stopPropagation(); if (e.button === 0) selectNote(n.id, true); });   // no canvas pan from a note
    // L7: pointer events + pointer capture (mouse, pen and touch alike): the drag keeps receiving its moves
    // even when the pointer leaves the note, and one document-level pointermove/up pair (boot) drives it.
    for (const part of [head, grip]) part.addEventListener('pointerdown', (e) => startNoteDrag(e, n, part === grip ? 'resize' : 'move'));
    head.addEventListener('dblclick', () => { selectNote(n.id); const t = $('#inspector input.ntitleinp'); if (t) t.focus(); });
    noteEls.set(n.id, el);
    root.append(el);
    growNote(el);
  });
}
export function selectNote(id, keepFocus) {
  if (S.selNote === id) return;
  clearNodeSelection();
  if (S.selFrame) { S.selFrame = null; drawFrames(); }
  S.selNote = id;
  noteEls.forEach((el, k) => el.classList.toggle('sel', k === id));
  renderInspector();
  if (id && innerWidth <= 900 && !keepFocus) document.body.classList.remove('hide-right');
}
export function unselectNote() { if (S.selNote) { S.selNote = null; noteEls.forEach((el) => el.classList.remove('sel')); renderInspector(); } }
function startNoteDrag(e, n, mode) {
  if (e.button || e.isPrimary === false) return;          // left button / primary touch only
  if (e.target.closest && e.target.closest('.pdel,.pmode')) return;   // the × / mode buttons keep their own click
  e.stopPropagation(); e.preventDefault();
  selectNote(n.id, true);
  try { e.currentTarget.setPointerCapture(e.pointerId); } catch (err) { /* synthetic event without a live pointer */ }
  S.noteDrag = { n, mode, pid: e.pointerId, cx: e.clientX, cy: e.clientY, ox: n.x, oy: n.y, ow: n.w, oh: n.h, moved: false, nh: noteHeight(n) };
}
export function moveNoteDrag(e) {
  const d = S.noteDrag; if (!d || (d.pid != null && e.pointerId !== d.pid)) return;
  if (e.cancelable) e.preventDefault();
  const p = evPoint(e), dx = (p.clientX - d.cx) / S.editor.zoom, dy = (p.clientY - d.cy) / S.editor.zoom;
  if (!d.moved && Math.hypot(p.clientX - d.cx, p.clientY - d.cy) < 3) return;
  d.moved = true;
  if (d.mode === 'resize') { d.n.w = Math.max(120, Math.round(d.ow + dx)); d.n.h = Math.max(90, Math.round(d.oh + dy)); }
  else { d.n.x = Math.round(d.ox + dx); d.n.y = Math.round(d.oy + dy); d.pt = canvasPoint(p.clientX, p.clientY); markDrop(dropTargetAt(d.pt)); }   // L8 outline, L9 pointer
  const el = noteEls.get(d.n.id); if (el) { placeNote(d.n, el); if (d.mode === 'resize') growNote(el); }
}
export function endNoteDrag(e) {
  const d = S.noteDrag; if (!d || (e && d.pid != null && e.pointerId !== d.pid)) return;
  S.noteDrag = null;
  markDrop(null);
  if (!d.moved) return;
  {                                 // a note never covers a node: moved or grown onto one, it slides to the nearest free spot
    const p = noteSpot(d.n.x, d.n.y, d.n.w, noteHeight(d.n), d.n.id);
    d.n.x = p.x; d.n.y = p.y;
    const el = noteEls.get(d.n.id); if (el) placeNote(d.n, el);
  }
  // L9: the group under the POINTER at release owns the note (L8 used its centre); a resize grows its parents
  if (d.mode === 'move') reparent(d.n, true, dropTargetAt(d.pt));
  else fitAncestors(parentOf(d.n));
  if (d.n.parent || d.mode === 'move') drawFrames();
  commitSoon();
}
// Nearest position (spiral on a 40 px grid around x, y) where a w x h note touches no node, badge or other note.
function noteSpot(x, y, w, hh, selfId, okFn) {   // okFn(x, y): extra constraint on a candidate (L4: visible spot)
  const boxes = Object.keys(dfData()).map((id) => nodeBox(id));
  notes().forEach((o) => { if (o.id !== selfId) boxes.push({ x0: o.x, y0: o.y, x1: o.x + o.w, y1: o.y + noteHeight(o) }); });
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
export function editNote(n, patch, rerender) {
  Object.assign(n, patch);
  if (!n.title) delete n.title;
  const el = noteEls.get(n.id);
  if (el) { placeNote(n, el); const pt = el.querySelector('.ptitle'); pt.textContent = n.title || 'Post-it'; pt.classList.toggle('empty', !n.title); const ta = el.querySelector('textarea'); if (ta.value !== (n.text || '')) ta.value = n.text || ''; refreshNoteText(n, el); }
  scheduleTree();
  if (rerender) renderInspector();
  commitSoon();
}
export function deleteNote(id) {
  if (editBlocked()) return;
  S.meta.notes = notes().filter((n) => n.id !== id);
  if (S.selNote === id) S.selNote = null;
  drawNotes(); renderInspector(); scheduleTree();
  commitSoon();
}
// New note at a canvas point (default: centre of the view). Returns the note.
export function addNote(pt) {
  if (editBlocked()) return null;
  if (notes().length >= 200) { toast('200 post-it au plus.', 'err'); return null; }
  if (!pt) { const st = $('#stage').getBoundingClientRect(); pt = canvasPoint(st.x + st.width / 2 - 110, st.y + st.height / 2 - 80); }
  const used = new Set(notes().map((n) => n.id));
  let k = 1; while (used.has('p' + k)) k++;
  // L7: auto-placed where it covers no node. L4: preferably where its header can be grabbed (inside the visible
  // stage, below the jump bar); without such a spot the nearest free one is used and the view is panned to it (the
  // default view now starts flush with the first column, so that spot used to sit under the jump bar).
  const stR = $('#stage').getBoundingClientRect(), jb = $('#jumpbar'), pr = S.editor.precanvas.getBoundingClientRect();
  const top = Math.max(stR.y, jb ? jb.getBoundingClientRect().bottom : stR.y) + 8, z = S.editor.zoom;
  const visible = (px, py) => { const sx = pr.x + px * z, sy = pr.y + py * z;
    return sx >= stR.x + 8 && sy >= top && sx + 220 * z <= stR.right - 8 && sy + 40 * z <= stR.bottom - 8; };
  const vs = noteSpot(pt.x, pt.y, 220, 160, null, visible);
  const spot = vs.free !== false ? vs : noteSpot(pt.x, pt.y, 220, 160);
  const pan = !visible(spot.x, spot.y);
  const n = { id: 'p' + k, text: '', color: NOTE_COLORS[0][1], x: spot.x, y: spot.y, w: 220, h: 160 };
  const host = dropTarget(noteBox(n, n.h));   // L8: a post-it created inside a group belongs to it
  if (host) n.parent = host.id;
  notes().push(n);
  if (host) { fitAncestors(host); drawFrames(); }
  if (pan) focusRect({ x0: n.x, y0: n.y, x1: n.x + n.w, y1: n.y + n.h }, S.editor.zoom);   // same zoom, note centred
  S.selNote = null; drawNotes(); selectNote(n.id);
  scheduleTree(); commitSoon();
  const ta = noteEls.get(n.id) && noteEls.get(n.id).querySelector('textarea'); if (ta) ta.focus();
  return n;
}
export function focusNoteBox(id) {
  const n = noteById(id); if (!n) return;
  focusRect({ x0: n.x, y0: n.y, x1: n.x + n.w, y1: n.y + n.h }, Math.max(S.editor.zoom, 0.6));
  selectNote(id);
}
export function renderNoteInspector(box, n) {
  box.append(h('div', { class: 'insttitle' }, ico('message', n.color), 'Post-it', h('small', { class: 'hint' }, n.id)));
  const t = textCtl(n.title || '', (v) => editNote(n, { title: v.slice(0, 60) }));
  t.maxLength = 60; t.classList.add('ntitleinp');
  box.append(field('Titre (facultatif)', t));
  box.append(field('Texte', areaCtl(n.text || '', (v) => editNote(n, { text: v }), 2000), '2000 caractères au plus. Le robot ne lit jamais les post-it.'));
  const disp = selectCtl([{ v: 'full', l: 'Texte complet' }, { v: 'compact', l: 'Compact : titre et première ligne' }], noteCompact(n) ? 'compact' : 'full', (v) => setNoteDisplay(n, v));
  disp.classList.add('ndisp');
  box.append(field('Affichage', disp, 'Compact : le texte complet s’affiche en info-bulle au survol du post-it.'));
  const sw = h('div', { class: 'swatches' });
  NOTE_COLORS.forEach(([nm, c]) => sw.append(h('button', { type: 'button', class: 'sw' + (c === n.color ? ' on' : ''), title: nm, 'aria-label': nm, style: 'background:' + c, onclick: () => editNote(n, { color: c }, true) })));
  box.append(h('div', { class: 'fld' }, h('span', {}, 'Couleur'), sw));
  box.append(h('button', { type: 'button', class: 'danger', onclick: () => deleteNote(n.id) }, 'Supprimer le post-it'));
}
