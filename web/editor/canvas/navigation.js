/**
 * Canvas: mouse button guards and safe navigation (L8).
 *
 * Purpose :  left-button-only grabbing, Space+drag / hand tool (H) panning, wheel pan / Ctrl+wheel zoom, read-only lock
 *            (L), keyboard pan, help popover.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, minimap/overview.js, frames/nesting.js, frames/notes.js, menu/context-menu.js,
 *            clipboard/clipboard.js, menu/node-menu.js, core/ui.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, h, ico, icoUrl } from '../core/util.js';
import { S } from '../core/state.js';
import { zoomVars } from '../minimap/overview.js';
import { fit } from '../frames/nesting.js';
import { fastCanvasPoint, viewOrigin } from './geometry.js';
import { selectNote } from '../frames/notes.js';
import { closeCtx } from '../menu/context-menu.js';
import { openContextFor } from '../clipboard/clipboard.js';
import { selectDf } from '../menu/node-menu.js';
import { toast } from '../core/ui.js';

// ---------- mouse buttons: only the LEFT button grabs anything ----------
// Middle and right buttons must never start a Drawflow drag (node, wire, canvas pan). A capture listener on window
// swallows them before Drawflow sees them; the native context menu is replaced by ours (see openCtx).
export function installButtonGuards() {
  const inCanvas = (e) => e.target && e.target.closest && e.target.closest('#drawflow');
  // registered first so it runs before the guard below: any press outside the menu closes it
  window.addEventListener('mousedown', (e) => { if (S.ctx && !(e.target.closest && e.target.closest('.ctx'))) closeCtx(); }, true);
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

// ---------- safe navigation (L8): Space+drag, wheel pan, hand tool (H), lock mode (L), keyboard pan ----------
// Ways to move the view that can never edit anything, plus a persisted read-only lock:
//  - Space held (focus not in a text field), the hand tool or the lock: every trusted left press inside the canvas is
//    taken in the WINDOW CAPTURE phase, before Drawflow / node / frame / post-it / wire handlers, and becomes a plain
//    view pan (setRawView). The press never reaches them, so nothing can be selected, moved, linked or resized.
//  - Lock only: a press released without moving still selects the node / wire / post-it under it (replayed as a
//    synthetic, untrusted press that this interceptor lets through) so the inspector can be READ; inputs are disabled.
//  - Wheel = pan (Shift = horizontal, trackpad deltaX/deltaY both), Ctrl+wheel / pinch = zoom around the cursor.
//    Drawflow's own wheel zoom never runs (stopped in the capture phase).
// Invariants: only trusted events are intercepted (internal helpers such as selectDf() dispatch synthetic presses);
// every edit entry point (addAt, addFrame, addNote, pasteNode, undo, redo, delete*, palette drop, keys, context menu,
// inspector inputs) checks editBlocked(); save() checks navLocked only (saving is not an edit of the canvas).
const LOCK_KEY = 'nanterino.editor.locked';
const NAV_SKIP = '#jumpbar, #minimap, .ctx, .rbadge';          // overlays that handle their own presses (navigation)
const RO_PANELS = '#inspector, #intents, #versions, #vars';    // Tester and Journal stay usable (viewing, simulating)
// shared state: S.navLocked, S.navHand, S.navSpace, S.navPan, S.helpEl (core/state.js)
export function editBlocked(quiet) {
  if (!S.navLocked && !S.navHand) return false;
  if (!quiet) toast(S.navLocked ? 'Verrouillé — lecture seule (L pour déverrouiller).' : 'Outil main actif — H pour éditer.', 'err');
  return true;
}
const isTyping = (t) => !!(t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable));
const inCanvasEv = (e) => !!(e.target && e.target.closest && e.target.closest('#drawflow'));
// Drawflow coordinates (translate is applied around the precanvas centre; see setView for the top-left variant).
export function setRawView(z, cx, cy) {
  S.editor.zoom = z; S.editor.zoom_last_value = z; S.editor.canvas_x = cx; S.editor.canvas_y = cy;
  S.editor.precanvas.style.transform = `translate(${cx}px, ${cy}px) scale(${z})`;
  S.editor.dispatch('translate', { x: cx, y: cy });
  zoomVars();
}
function panBy(dx, dy) { setRawView(S.editor.zoom, S.editor.canvas_x + dx, S.editor.canvas_y + dy); }
// Zoom keeping the canvas point under (clientX, clientY) fixed: precanvas left = B + cx + ox(1 - z), so
// cx' = cx + clientX - p.x*z' - rect.x + ox(z' - z) (same for y).
function zoomAt(clientX, clientY, factor) {
  const z = S.editor.zoom, z2 = Math.min(S.editor.zoom_max, Math.max(S.editor.zoom_min, z * factor));
  if (Math.abs(z2 - z) < 1e-6) return;
  // S2: arithmetic (canvas/geometry.js), no rect read per wheel tick: precanvas left = origin left + cx + ox(1 - z)
  const o = viewOrigin(), p = fastCanvasPoint(clientX, clientY), ox = o.ox, oy = o.oy;
  const rx = o.left + S.editor.canvas_x + ox * (1 - z), ry = o.top + S.editor.canvas_y + oy * (1 - z);
  setRawView(z2, S.editor.canvas_x + clientX - p.x * z2 - rx + ox * (z2 - z), S.editor.canvas_y + clientY - p.y * z2 - ry + oy * (z2 - z));
}
export function zoomCentre(factor) { const o = viewOrigin(); zoomAt(o.cl + o.w / 2, o.ct + o.h / 2, factor); }
function onNavWheel(e) {
  if (!inCanvasEv(e) || e.target.closest(NAV_SKIP)) return;
  const zoom = e.ctrlKey || e.metaKey;                       // trackpad pinch arrives as ctrlKey wheel
  if (!zoom && e.target.closest('textarea')) return;         // a long post-it text scrolls itself
  e.preventDefault(); e.stopImmediatePropagation();
  closeCtx();
  const k = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
  let dx = e.deltaX * k, dy = e.deltaY * k;
  if (zoom) { zoomAt(e.clientX, e.clientY, Math.exp(-Math.max(-300, Math.min(300, dy)) * 0.002)); return; }
  if (e.shiftKey && !dx) { dx = dy; dy = 0; }
  panBy(-dx, -dy);
}
const navMode = () => S.navSpace || S.navHand || S.navLocked;
function evPt(e) { return e.touches ? (e.touches[0] || e.changedTouches[0]) : e; }
function onNavDown(e) {
  if (!e.isTrusted || !inCanvasEv(e)) return;
  if (S.navPan) { if (e.cancelable) e.preventDefault(); e.stopImmediatePropagation(); return; }   // same press, other event type
  if (!navMode() || e.target.closest(NAV_SKIP)) return;
  if (e.type === 'touchstart' ? e.touches.length !== 1 : e.button !== 0) return;          // other buttons: installButtonGuards
  if (e.cancelable) e.preventDefault();
  e.stopImmediatePropagation();
  const p = evPt(e);
  S.navPan = { x: p.clientX, y: p.clientY, cx: S.editor.canvas_x, cy: S.editor.canvas_y, moved: false, target: e.target, select: S.navLocked && !S.navHand && !S.navSpace };
  document.body.classList.add('nav-panning');
  $('#drawflow').focus({ preventScroll: true });
}
function onNavMove(e) {
  if (!S.navPan) return;
  const p = evPt(e); if (!p) return;
  const dx = p.clientX - S.navPan.x, dy = p.clientY - S.navPan.y;
  if (Math.abs(dx) + Math.abs(dy) > 3) S.navPan.moved = true;
  if (S.navPan.moved) setRawView(S.editor.zoom, S.navPan.cx + dx, S.navPan.cy + dy);
  if (e.cancelable) e.preventDefault();
  e.stopImmediatePropagation();
}
function onNavUp(e) {
  if (!S.navPan) return;
  if (e.cancelable) e.preventDefault();
  e.stopImmediatePropagation();
  const pan = S.navPan; S.navPan = null;
  document.body.classList.remove('nav-panning');
  if (!pan.moved && pan.select && e.type !== 'pointercancel') lockSelect(pan.target);
}
// Lock: a click (no drag) shows what is under it in the inspector. Synthetic presses are untrusted, so onNavDown lets them through.
function lockSelect(t) {
  if (!t || !t.isConnected) return;
  const note = t.closest('.postit'), node = t.closest('.drawflow-node'), wire = t.closest('path.main-path');
  const press = (el) => { el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true })); };
  if (note) selectNote(note.dataset.nid);
  else if (node) selectDf(node.id.replace('node-', ''));
  else if (wire) press(wire);
  else press(S.editor.precanvas);                     // bare canvas: Drawflow unselects
}
// Clicks / double-clicks that follow an intercepted press must not reach node, frame-title or post-it handlers.
function onNavClick(e) {
  if (!e.isTrusted || !navMode() || !inCanvasEv(e) || e.target.closest(NAV_SKIP)) return;
  e.preventDefault(); e.stopImmediatePropagation();
}
function onNavKey(e) {
  const free = !isTyping(e.target) && !S.ctx && $('#modal').hidden;
  if (e.key === ' ' || e.code === 'Space') {
    if (!free) return;
    e.preventDefault(); e.stopImmediatePropagation();          // no page scroll, no button activation
    if (e.type === 'keydown' && !S.navSpace) { S.navSpace = true; updateNavUi(); }
    else if (e.type === 'keyup' && S.navSpace) { S.navSpace = false; updateNavUi(); }
    return;
  }
  if (e.type !== 'keydown' || !free) return;
  const plain = !e.ctrlKey && !e.metaKey && !e.altKey, k = e.key;
  if (plain && (k === 'h' || k === 'H')) { e.preventDefault(); e.stopImmediatePropagation(); setHand(!S.navHand); return; }
  if (plain && (k === 'l' || k === 'L')) { e.preventDefault(); e.stopImmediatePropagation(); setLock(!S.navLocked); return; }
  if (plain && k === '?') { e.preventDefault(); e.stopImmediatePropagation(); toggleHelp(); return; }
  if (k === 'Escape' && S.helpEl && !S.helpEl.hidden) { toggleHelp(false); return; }
  // read-only: editing keys stop here (Drawflow's own Delete handler included)
  const mod = e.ctrlKey || e.metaKey;
  if (editBlocked(true) && (k === 'Delete' || k === 'Backspace' || (plain && /^[gnGN]$/.test(k)) || (mod && /^[vzyxVZYX]$/.test(k)))) {
    e.preventDefault(); e.stopImmediatePropagation(); editBlocked(); return;
  }
  // view keys: only while the canvas itself has the focus
  const dfEl = $('#drawflow'), a = document.activeElement;
  if (!(a === dfEl || (dfEl.contains(a) && !isTyping(a))) || mod || e.altKey) return;
  const step = e.shiftKey ? 240 : 60;
  const arrows = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
  if (arrows[k]) { e.preventDefault(); e.stopImmediatePropagation(); panBy(arrows[k][0], arrows[k][1]); }
  else if (k === '+' || k === '=') { e.preventDefault(); e.stopImmediatePropagation(); zoomCentre(1.2); }
  else if (k === '-' || k === '_') { e.preventDefault(); e.stopImmediatePropagation(); zoomCentre(1 / 1.2); }
  else if (k === '0') { e.preventDefault(); e.stopImmediatePropagation(); fit(); }
}
export function setHand(on) { S.navHand = !!on; updateNavUi(); }
export function setLock(on) {
  S.navLocked = !!on;
  try { if (S.navLocked) localStorage.setItem(LOCK_KEY, '1'); else localStorage.removeItem(LOCK_KEY); } catch (e) { /* per page only */ }
  updateNavUi();
}
// Read-only panels and canvas text fields; buttons/inputs this code disabled are marked so unlocking restores only them.
function applyReadOnly() {
  const on = S.navLocked || S.navHand;
  document.querySelectorAll(RO_PANELS).forEach((p) => p.querySelectorAll('input, textarea, select, button').forEach((el) => {
    if (el.classList.contains('navok')) return;          // navigation inside a panel (sub-tabs, list picker) stays usable
    if (on && !el.disabled) { el.disabled = true; el.dataset.navro = '1'; }
    else if (!on && el.dataset.navro) { el.disabled = false; delete el.dataset.navro; }
  }));
  document.querySelectorAll('#drawflow textarea, #drawflow input').forEach((el) => {
    if (on && !el.readOnly) { el.readOnly = true; el.dataset.navro = '1'; }
    else if (!on && el.dataset.navro) { el.readOnly = false; delete el.dataset.navro; }
  });
}
export function readOnlyMenu(items) {
  const keep = new Set(['Ajuster la vue', 'Copier', 'Copier la sélection']);   // copying never edits
  return [{ label: S.navLocked ? 'Verrouillé — lecture seule' : 'Outil main — lecture seule', icon: S.navLocked ? 'lock' : 'hand-stop', disabled: true }, { sep: true }]
    .concat(items.map((it) => (it.sep || (keep.has(it.label) && !it.disabled) ? it : { label: it.label, icon: it.icon, disabled: true })));
}
function updateNavUi() {
  const b = document.body;
  b.classList.toggle('nav-grab', S.navSpace || S.navHand);
  b.classList.toggle('nav-hand', S.navHand);
  b.classList.toggle('nav-locked', S.navLocked);
  b.classList.toggle('nav-ro', S.navHand || S.navLocked);
  const bh = $('#btnHand'), bl = $('#btnLock');
  if (bh) { bh.classList.toggle('on', S.navHand); bh.setAttribute('aria-pressed', String(S.navHand)); }
  if (bl) {
    bl.classList.toggle('on', S.navLocked); bl.setAttribute('aria-pressed', String(S.navLocked));
    const i = bl.querySelector('.ico'); if (i) i.style.setProperty('--ic', icoUrl(S.navLocked ? 'lock' : 'lock-open'));
    bl.title = S.navLocked ? 'Déverrouiller (L)' : 'Verrouiller : lecture seule (L)';
  }
  const ban = $('#navBanner');
  if (ban) {
    ban.innerHTML = '';
    if (S.navLocked) ban.append(h('span', { class: 'nb-lock' }, ico('lock'), 'Verrouillé — lecture seule'), h('small', {}, 'L pour déverrouiller'));
    if (S.navHand) ban.append(h('span', { class: 'nb-hand' }, ico('hand-stop'), 'Outil main — H pour éditer'));
    ban.hidden = !S.navLocked && !S.navHand;
  }
  applyReadOnly();
}
export function toggleHelp(force) {
  if (!S.helpEl) return;
  S.helpEl.hidden = force === undefined ? !S.helpEl.hidden : !force;
  const b = $('#btnHelp'); if (b) b.classList.toggle('on', !S.helpEl.hidden);
}
function buildHelp() {
  const rows = [
    ['Espace + glisser', 'déplacer la vue (rien ne peut être sélectionné ni modifié)'],
    ['Molette', 'défiler haut / bas'], ['Maj + molette', 'défiler gauche / droite'],
    ['Ctrl + molette, pincer', 'zoom autour du curseur'],
    ['H', 'outil main : chaque glisser déplace la vue, aucun clic n’édite'],
    ['L', 'verrouiller : lecture seule (mémorisé)'],
    ['Flèches (Maj = vite)', 'déplacer la vue — canevas actif'], ['+ / −', 'zoom — canevas actif'], ['0', 'ajuster — canevas actif'],
    ['Glisser à gauche', 'sur le vide : déplacer la vue ; sur un nœud : le déplacer'],
    ['Clic droit', 'menu'], ['?', 'cette aide']];
  S.helpEl = h('div', { id: 'navHelp', class: 'navhelp', role: 'dialog', 'aria-label': 'Commandes de navigation', hidden: true },
    h('div', { class: 'nhtitle' }, ico('question-mark'), 'Navigation', h('button', { type: 'button', class: 'nhclose', title: 'Fermer', onclick: () => toggleHelp(false) }, '×')),
    h('dl', {}, rows.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)])));   // h() flattens one level only
  ['mousedown', 'pointerdown', 'wheel'].forEach((t) => S.helpEl.addEventListener(t, (e) => e.stopPropagation(), { passive: true }));
  $('#stage').append(S.helpEl);
}
export function installSafeNav() {
  const dfEl = $('#drawflow');
  dfEl.tabIndex = 0;                                         // the canvas can hold the focus (arrow / + / - / 0 keys)
  S.navLocked = (() => { try { return localStorage.getItem(LOCK_KEY) === '1'; } catch (e) { return false; } })();
  // focus the canvas on any press in it (not on its text fields), so the view keys work right after a click
  window.addEventListener('pointerdown', (e) => { if (e.isTrusted && inCanvasEv(e) && !isTyping(e.target) && !e.target.closest(NAV_SKIP)) dfEl.focus({ preventScroll: true }); }, true);
  ['pointerdown', 'mousedown', 'touchstart'].forEach((t) => window.addEventListener(t, onNavDown, { capture: true, passive: false }));
  ['pointermove', 'mousemove', 'touchmove'].forEach((t) => window.addEventListener(t, onNavMove, { capture: true, passive: false }));
  ['pointerup', 'mouseup', 'touchend', 'pointercancel', 'touchcancel'].forEach((t) => window.addEventListener(t, onNavUp, { capture: true, passive: false }));
  ['click', 'dblclick'].forEach((t) => window.addEventListener(t, onNavClick, true));
  window.addEventListener('wheel', onNavWheel, { capture: true, passive: false });
  window.addEventListener('keydown', onNavKey, true);
  window.addEventListener('keyup', onNavKey, true);
  window.addEventListener('blur', () => { if (S.navSpace) { S.navSpace = false; updateNavUi(); } });
  buildHelp();
  $('#btnHand').onclick = () => setHand(!S.navHand);
  $('#btnLock').onclick = () => setLock(!S.navLocked);
  $('#btnHelp').onclick = (e) => { e.stopPropagation(); toggleHelp(); };
  document.addEventListener('click', (e) => { if (S.helpEl && !S.helpEl.hidden && !S.helpEl.contains(e.target)) toggleHelp(false); });
  // re-render of the inspector / panels / post-its: keep the read-only state on the new inputs
  const mo = new MutationObserver(() => { if (S.navLocked || S.navHand) applyReadOnly(); });
  mo.observe($('#right'), { childList: true, subtree: true });
  mo.observe(S.editor.precanvas, { childList: true, subtree: true });
  updateNavUi();
}
