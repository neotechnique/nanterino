/**
 * Editor tooltips (lot L5): one lightweight component for the whole page.
 *
 * Purpose :  data-tip / borrowed title bubbles in #tip, hover delay, long press and the "i" icon on touch screens (tipi).
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, canvas/nodes.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { h } from '../core/util.js';
import { S } from '../core/state.js';
import { nodeTipOf } from '../canvas/nodes.js';

// ---------- tooltips (lot L5): one lightweight component for the whole page ----------
// Any element with `data-tip` (or a native `title`, taken over while hovered so the browser bubble never shows, then
// put back) gets a styled bubble after TIP_DELAY ms. The bubble lives in <body> (never clipped by a panel), has
// pointer-events none (never steals a click, a drag or an elementFromPoint) and hides on press / key / wheel / scroll.
// Touch: a long press (500 ms) shows it; a `.tipi` info icon toggles it on tap. `data-tip-side` = beside the target.
const TIP_DELAY = 400;
// shared state: S.tipEl, S.tipTimer, S.tipFor, S.tipTouch, S.tipOpenAt (core/state.js)
function tipTarget(el) {
  // L8: a node is a tip target as a whole (its bubble text is built at hover time: diagnostics change)
  el = el && el.closest ? el.closest('[data-tip],[title],.drawflow-node') : null;
  if (!el || el.id === 'tip') return null;
  if (el.classList.contains('drawflow-node')) el.setAttribute('data-tip', nodeTipOf(el) || '');
  if (el.hasAttribute('title')) {
    const t = el.getAttribute('title');
    el.removeAttribute('title');
    if (t) { el.setAttribute('data-tip', t); el.setAttribute('data-tip-own', '1'); }
  }
  return el.getAttribute('data-tip') ? el : null;
}
function restoreTitle(el) {   // a borrowed `title` goes back (selectors and code that read it keep working)
  if (!el || !el.getAttribute('data-tip-own')) return;
  if (!el.hasAttribute('title')) el.setAttribute('title', el.getAttribute('data-tip') || '');
  el.removeAttribute('data-tip'); el.removeAttribute('data-tip-own');
}
// L8: no bubble while something is being dragged, wired or panned (the timer may fire mid-gesture).
function tipBusy() {
  return !!(S.editor && (S.editor.drag || S.editor.connection || S.editor.drag_point)) || !!S.frameDrag || !!S.noteDrag || !!S.miniDrag
    || document.body.classList.contains('nav-panning');
}
// Same Drawflow node (a node and its badge / ports / tags): moving between them swaps the bubble without a gap.
function sameNode(a, b) {
  const n = a && a.closest ? a.closest('.drawflow-node') : null;
  return !!n && !!b && !!b.closest && n === b.closest('.drawflow-node');
}
function showTip(el) {
  if (!S.tipEl || !el.isConnected || tipBusy()) return;
  const txt = el.getAttribute('data-tip'); if (!txt) return;
  S.tipEl.textContent = txt; S.tipEl.hidden = false;
  const r = el.getBoundingClientRect(), t = S.tipEl.getBoundingClientRect(), W = innerWidth, H = innerHeight, g = 8;
  let x, y;
  if (el.hasAttribute('data-tip-side')) { x = r.right + g; if (x + t.width > W - 4) x = r.left - t.width - g; y = r.top; }
  else { x = r.left + r.width / 2 - t.width / 2; y = r.bottom + g; if (y + t.height > H - 4) y = r.top - t.height - g; }
  S.tipEl.style.left = Math.round(Math.max(4, Math.min(x, W - t.width - 4))) + 'px';
  S.tipEl.style.top = Math.round(Math.max(4, Math.min(y, H - t.height - 4))) + 'px';
  S.tipEl.classList.add('on');
  S.tipFor = el;
}
export function hideTip() {
  clearTimeout(S.tipTimer); S.tipTimer = 0;
  if (S.tipEl) { S.tipEl.hidden = true; S.tipEl.classList.remove('on'); }
  if (S.tipFor) { restoreTitle(S.tipFor); S.tipFor = null; }
}
// Small "i" button carrying a help text (inspector fields): hover = bubble, tap = bubble (touch screens).
export const tipi = (text) => (text ? h('span', { class: 'tipi', 'data-tip': text, role: 'button', tabindex: '0', 'aria-label': 'Aide' }, 'i') : null);
export function installTips() {
  S.tipEl = h('div', { id: 'tip', role: 'tooltip', hidden: true });
  document.body.append(S.tipEl);
  document.addEventListener('mouseover', (e) => {
    if (Date.now() - S.tipTouch < 800) return;            // compatibility mouse events right after a touch
    const t = e.buttons ? null : tipTarget(e.target);    // never while a button is held (drags, wires)
    if (t === S.tipFor) return;
    const warm = !!(t && S.tipFor && S.tipEl && !S.tipEl.hidden && sameNode(t, S.tipFor));   // L8: shown bubble, same node
    hideTip();
    if (!t) return;
    if (warm) { showTip(t); return; }
    S.tipFor = t; S.tipTimer = setTimeout(() => showTip(t), TIP_DELAY);
  }, true);
  // leaving for another part of the same node is decided by the next mouseover (no hide / re-show flicker)
  document.addEventListener('mouseout', (e) => { if (S.tipFor && !(e.relatedTarget && (S.tipFor.contains(e.relatedTarget) || sameNode(S.tipFor, e.relatedTarget)))) hideTip(); }, true);
  ['mousedown', 'keydown', 'wheel', 'dragstart'].forEach((ev) => document.addEventListener(ev, () => hideTip(), true));
  document.addEventListener('scroll', () => hideTip(), true);
  let lp = 0;                                            // touch: long press shows, the next touch hides
  document.addEventListener('touchstart', (e) => {
    S.tipTouch = Date.now(); clearTimeout(lp);
    S.tipOpenAt = S.tipFor && S.tipEl && !S.tipEl.hidden ? S.tipFor : null;   // remembered: touchstart hides it before the click toggles
    hideTip();
    const t = tipTarget(e.target); if (!t) return;
    S.tipFor = t; lp = setTimeout(() => showTip(t), 500);
  }, { capture: true, passive: true });
  ['touchmove', 'touchend', 'touchcancel'].forEach((ev) => document.addEventListener(ev, () => { S.tipTouch = Date.now(); clearTimeout(lp); }, { capture: true, passive: true }));
  document.addEventListener('click', (e) => {           // info icons: a tap / click toggles their bubble at once
    const i = e.target.closest && e.target.closest('.tipi'); if (!i) return;
    e.preventDefault(); e.stopPropagation();
    // A real touch tap: touchstart already hid the bubble, so "was open" comes from what touchstart remembered.
    const was = (S.tipFor === i && S.tipEl && !S.tipEl.hidden) || (S.tipOpenAt === i && Date.now() - S.tipTouch < 800);
    S.tipOpenAt = null;
    hideTip(); if (!was) showTip(i);
  }, true);
}
