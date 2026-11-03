/**
 * Menus: the right-click context menu (L10 flat menu).
 *
 * Purpose :  openContextFor / closeCtx, cascading Déclencheurs / Actions / Conditions submenus, typing filter.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, menu/node-menu.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { h, ico } from '../core/util.js';
import { S, KINDS, stateIcon } from '../core/state.js';
import { itemPath, menuTree } from './node-menu.js';

// ---------- context menu (right click) ----------
// A floating menu at the cursor: French labels, icons, arrow keys / Enter / Esc, submenus on hover or Right arrow,
// kept inside the viewport. Items: [{label, icon, fn, sub, search, disabled, sep, key, path, tip}] ; `sub` is a list or a
// function returning one; `key` = shortcut hint on the right. L10: openCtx(x, y, items, filter) - `filter` = flat rows
// [{label, hay, fn, ...}] that typing filters (ctxFilter), no visible search field until a key is typed.
// shared state: S.ctx (core/state.js)
export function closeCtx() { if (S.ctx) { S.ctx.menus.forEach((m) => m.remove()); S.ctx.el.remove(); S.ctx = null; } }
// Esc: close the innermost submenu (focus goes back to its parent row), else the whole menu.
function escMenu() {
  if (!S.ctx) return;
  if (S.ctx.menus.length > 1) {
    closeSubsFrom(S.ctx.menus.length - 2);
    const parent = S.ctx.menus[S.ctx.menus.length - 1], rows = parent.querySelectorAll('.cit:not(.dis)');
    const open = [...rows].find((r) => r.querySelector('.carr'));
    (open || rows[0] || parent).focus();
  } else closeCtx();
}
export function openCtx(x, y, items, filter) {
  closeCtx();
  const root = h('div', { class: 'ctx', role: 'menu', tabindex: '-1' });
  S.ctx = { el: root, menus: [root], base: items, filter: filter || null, q: '', x, y };
  document.body.append(root);
  fillMenu(root, items, 0);
  placeMenu(root, x, y);
  const first = root.querySelector('.cit:not(.dis)'); if (first) first.focus(); else root.focus();
}
function placeMenu(el, x, y) {
  // L7: never taller than the viewport (the menu scrolls inside), so every entry stays reachable
  el.style.maxHeight = Math.max(120, innerHeight - 8) + 'px';
  el.style.left = '0px'; el.style.top = '0px';
  const r = el.getBoundingClientRect(), W = innerWidth, H = innerHeight;
  el.style.left = Math.max(4, Math.min(x, W - r.width - 4)) + 'px';
  el.style.top = Math.max(4, Math.min(y, H - r.height - 4)) + 'px';
}
function fillMenu(el, items, depth) {
  el.innerHTML = '';
  items.forEach((it) => {
    if (it.sep) { el.append(h('div', { class: 'csep' })); return; }
    if (it.search) {
      const inp = h('input', { type: 'search', class: 'csearch', placeholder: it.search.placeholder || 'Rechercher…', 'aria-label': 'Rechercher' });
      inp.addEventListener('input', () => { it.search.onInput(inp.value.trim().toLowerCase()); });
      inp.addEventListener('keydown', (e) => { e.stopPropagation(); if (S.ctx) S.ctx.kbd = Date.now(); if (e.key === 'Escape') escMenu(); else if (e.key === 'ArrowDown') { e.preventDefault(); focusNext(el, 1, inp); } else if (e.key === 'Enter') { const f = el.querySelector('.cit:not(.dis)'); if (f) f.click(); } });
      el.append(inp); return;
    }
    const row = h('div', { class: 'cit' + (it.disabled ? ' dis' : ''), role: 'menuitem', tabindex: '-1', 'aria-disabled': it.disabled ? 'true' : null,
      'aria-haspopup': it.sub ? 'menu' : null, 'data-tip': it.tip || null, 'data-tip-side': it.tip ? '1' : null },
      it.icon ? ico(it.icon, it.color) : h('span', { class: 'ico-sp' }), h('span', { class: 'clab' }, it.label), it.path ? h('span', { class: 'cpath' }, it.path) : null,
      it.key ? h('span', { class: 'ckey' }, it.key) : null, it.sub ? h('span', { class: 'carr' }, '▸') : null);
    if (!it.disabled) {
      row.addEventListener('click', (e) => {
        e.stopPropagation();
        if (it.sub) { openSub(row, it, depth); return; }
        closeCtx(); if (it.fn) it.fn();
      });
      // a stationary pointer re-fires mouseenter when the menu re-lays out after a key press: ignore it for a moment
      if (it.sub) row.addEventListener('mouseenter', () => { if (!S.ctx || (S.ctx.kbd && Date.now() - S.ctx.kbd < 800)) return; openSub(row, it, depth); });
      else row.addEventListener('mouseenter', () => { closeSubsFrom(depth); row.focus(); });
    }
    el.append(row);
  });
}
function closeSubsFrom(depth) {
  if (!S.ctx) return;
  while (S.ctx.menus.length > depth + 1) S.ctx.menus.pop().remove();
}
// L10 type-to-filter: no search field is shown; the first printable key typed while a menu is open puts a filter line at
// the top of the ROOT menu and lists the matching node entries (with their "Catégorie › Thème" path) in place of its
// rows; Backspace edits the text, Esc clears it (a second Esc closes as usual), arrows / Enter pick a row.
function ctxFilter(q) {
  if (!S.ctx || !S.ctx.filter) return;
  S.ctx.q = q;
  closeSubsFrom(0);
  const root = S.ctx.menus[0];
  if (!q) fillMenu(root, S.ctx.base, 0);
  else {
    const ql = q.toLowerCase(), hits = S.ctx.filter.filter((r) => (r.hay || r.label.toLowerCase()).includes(ql)).slice(0, 20);
    fillMenu(root, hits.length ? hits : [{ label: 'Aucun nœud ne correspond', disabled: true }], 0);
    root.prepend(h('div', { class: 'cfilter', 'aria-live': 'polite' }, ico('eye'), h('span', {}, 'Filtre : ' + q)));
  }
  placeMenu(root, S.ctx.x, S.ctx.y);
  const first = root.querySelector('.cit:not(.dis)'); (first || root).focus();
}
function openSub(row, it, depth) {
  closeSubsFrom(depth);          // keep the menus up to this row's own level, drop any submenu already open under it
  const sub = h('div', { class: 'ctx csub', role: 'menu', tabindex: '-1' });
  document.body.append(sub); S.ctx.menus.push(sub);
  const list = typeof it.sub === 'function' ? it.sub(sub, depth + 1) : it.sub;
  fillMenu(sub, list, depth + 1);
  const pr = row.getBoundingClientRect();
  sub.style.left = '0px'; sub.style.top = '0px';
  const r = sub.getBoundingClientRect();
  let x = pr.right - 2; if (x + r.width > innerWidth - 4) x = Math.max(4, pr.left - r.width + 2);
  placeMenu(sub, x, pr.top - 4);
  const first = sub.querySelector('.csearch') || sub.querySelector('.cit:not(.dis)'); if (first) first.focus();
}
function focusNext(menu, dir, cur) {
  const rows = [...menu.querySelectorAll(':scope > .cit:not(.dis), :scope > .csearch')];
  if (!rows.length) return;
  let i = rows.indexOf(cur || document.activeElement);
  i = i < 0 ? (dir > 0 ? 0 : rows.length - 1) : (i + dir + rows.length) % rows.length;
  rows[i].focus();
}
export function ctxKey(e) {
  if (!S.ctx) return false;
  const menu = S.ctx.menus[S.ctx.menus.length - 1];
  S.ctx.kbd = Date.now();
  // L10: printable keys filter the node entries (a space only once some text is typed: alone it activates the row)
  const plain = !e.ctrlKey && !e.metaKey && !e.altKey;
  if (S.ctx.filter && plain && e.key.length === 1 && (e.key !== ' ' || S.ctx.q)) ctxFilter(S.ctx.q + e.key);
  else if (S.ctx.q && e.key === 'Backspace') ctxFilter(S.ctx.q.slice(0, -1));
  else if (S.ctx.q && e.key === 'Escape') ctxFilter('');
  else if (e.key === 'Escape') escMenu();
  else if (e.key === 'ArrowDown') focusNext(menu, 1);
  else if (e.key === 'ArrowUp') focusNext(menu, -1);
  else if (e.key === 'ArrowRight') { const a = document.activeElement; if (a && a.classList.contains('cit') && a.querySelector('.carr')) a.click(); }
  else if (e.key === 'ArrowLeft') { if (S.ctx.menus.length > 1) { closeSubsFrom(S.ctx.menus.length - 2); const rows = S.ctx.menus[S.ctx.menus.length - 1].querySelectorAll('.cit:not(.dis)'); if (rows[0]) rows[0].focus(); } }
  else if (e.key === 'Enter' || e.key === ' ') { const a = document.activeElement; if (a && a.classList.contains('cit')) a.click(); }
  else if (e.key === 'Tab') { /* keep focus inside the menu */ }
  else return false;
  e.preventDefault(); e.stopPropagation();
  return true;
}

// What can follow a node (kinds valid after it, from the server's rules): start -> nothing (display only); trigger and
// condition (true / false) -> condition, action, end (+ changing the state); action -> action, end (+ changing the state;
// never a condition). Nothing ever leads INTO a trigger.
export function kindsAfter(kind) {
  switch (kind) {
    case 'start': return [];
    case 'trigger': return ['condition', 'action', 'end'];
    case 'condition': return ['condition', 'action', 'end'];
    case 'action': return ['action', 'end'];
    default: return [];
  }
}
const canGoToState = (kind) => ['trigger', 'condition', 'action'].includes(kind);
const KIND_ICON = (k) => KINDS[k].icon;
// Node to create from a menu entry: {kind, preset} ; vocabulary entries pre-fill the node.
function nodeChoices(kinds) {
  return kinds.map((k) => ({ label: KINDS[k].label, icon: KINDS[k].icon, color: KINDS[k].color, kind: k }));
}
// Vars L2 shortcut rows: "Changer d'état → X" = an action set_var(etat, X) (replaces the old "État : X" / "Aller à : X").
export const moveChoices = () => S.V.states.map((s) => ({ label: "Changer d'état → " + s.label, icon: stateIcon(s.id), kind: 'action',
  preset: { action: 'set_var', args: { name: 'etat', value: s.id } }, hay: "changer d'état " + s.label + ' ' + s.id }));
// Lot L10: the node part of every menu = Catégorie ▸ Thème ▸ entrée only (no search field, no empty blocks, no
// "Changer d'état → X" rows at the root: they live with "Fin" in Actions › État). Typing while a menu is open filters
// (filterRows + ctxFilter). `make(choice)` performs the insertion.
export function catRows(kinds, make) {
  const toItem = (c) => ({ label: c.label, icon: c.icon, color: c.color, tip: c.help || null, fn: () => make(c) });
  return menuTree(kinds).map(({ cat, themes }) => ({ label: cat.label, icon: cat.icon, color: KINDS[cat.id].color, tip: cat.tip,
    sub: themes.map(({ theme, items }) => ({ label: theme.label, icon: theme.icon, tip: theme.help || null, sub: items.map(toItem) })) }));
}
// The same entries as flat rows for type-to-filter: each with its "Catégorie › Thème" path and its search text.
export function filterRows(kinds, make) {
  return menuTree(kinds).flatMap((c) => c.themes.flatMap((t) => t.items))
    .map((c) => ({ label: c.label, icon: c.icon, color: c.color, tip: c.help || null, path: itemPath(c), hay: c.hay, fn: () => make(c) }));
}
export const insertSub = (kinds, make) => () => catRows(kinds, make);
