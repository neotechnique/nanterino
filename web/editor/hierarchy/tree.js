/**
 * Hierarchy (lot L10): Unity-style tree of the left column.
 *
 * Purpose :  buildTree / renderTree (columns > nested groups > chains > post-its), fold state, rename, drag a row into a
 *            group (moveInto).
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, inspector/property-picker.js, core/api.js, canvas/nodes.js, core/history.js,
 *            diagnostics/check.js, canvas/view.js, canvas/wires.js, minimap/minimap.js, frames/groups.js,
 *            frames/nesting.js, frames/notes.js, canvas/navigation.js, clipboard/clipboard.js, menu/node-menu.js,
 *            inspector/fields.js, inspector/inspector.js, core/ui.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, h, ico } from '../core/util.js';
import { S, KINDS, iconOf, nidToDf, stateColor, stateIcon } from '../core/state.js';
import { isEnterTrig } from '../inspector/property-picker.js';
import { dfData, dfNode, model, nidOf } from '../core/api.js';
import { nodeEl, nodeTheme, summary } from '../canvas/nodes.js';
import { commitSoon } from '../core/history.js';
import { ISSUE_PREFIX } from '../diagnostics/check.js';
import { nodeBox } from '../canvas/view.js';
import { paintWires } from '../canvas/wires.js';
import { focusChainIds } from '../minimap/minimap.js';
import { FRAME_PAD, frameById, frames } from '../frames/groups.js';
import {
  NEST_PAD, clearNodeSelection, descendantFrames, drawFrames, dropTargetAt, editFrame, focusFrame, focusNode,
  frameBox, noteBox, parentOf, reparent
} from '../frames/nesting.js';
import {
  drawNotes, editNote, focusNoteBox, noteById, noteEls, noteFirstLine, noteHeight, notes
} from '../frames/notes.js';
import { editBlocked } from '../canvas/navigation.js';
import {
  copySelection, cutSelection, deleteSelection, frameMembers, inFrame, paintChainSel, toggleChains
} from '../clipboard/clipboard.js';
import { themeById } from '../menu/node-menu.js';
import { checkCtl } from '../inspector/fields.js';
import { renderInspector } from '../inspector/inspector.js';
import { toast } from '../core/ui.js';

// ---------- hierarchy (lot L10): Unity-style tree of the left column (replaces the palette and the COLONNES / GROUPES lists) ----------
// Rows: columns (auto frames, top level) > nested groups (frame.parent, any depth) > chains > post-its (note.parent).
// A chain = one trigger + every node its outputs reach (a fan shared by several compiled chains is ONE row); nodes carry
// no parent, so a chain sits in the deepest frame under its trigger's centre (dropTargetAt, the canvas drop rule). Nodes
// reached by no trigger get a row of their own. Siblings: groups, then chains, then post-its, each by (y, then x).
// Rebuilt (debounced: scheduleTree) after every edit and diagnostics pass, keeping the fold state (per browser) and the
// scroll; never rebuilt under a rename or a drag. The filter keeps the matching rows and their ancestors (unfolded).
// Click = select + centre (a chain selects all its nodes), double-click / F2 = rename a group, column or post-it, a
// pointer drag of a row onto a column / group row = moveInto (same rules as a canvas drop). The selected item's row is
// highlighted (syncTreeSel, called by renderInspector), or its nearest visible ancestor when folded away.
const TREE_KEY = 'nanterino.editor.tree';
export const COL_TOP = 'Une colonne d’état reste au premier niveau : elle ne se range pas dans un groupe.';
// shared state: S.treeFold, S.treeTimer, S.treeDrag, S.treeRename, S.treeJustDragged (core/state.js)
// shared state: S.treeOwner, S.treeUp (core/state.js)   // last build: node id -> its row key ; row key -> parent row key
export function treeFolded() {
  if (!S.treeFold) {
    S.treeFold = new Set();
    try { const v = JSON.parse(localStorage.getItem(TREE_KEY) || 'null'); if (Array.isArray(v)) S.treeFold = new Set(v); } catch (e) { /* storage off */ }
  }
  return S.treeFold;
}
function setFold(key, folded) {
  const s = treeFolded();
  if (folded) s.add(key); else s.delete(key);
  try { localStorage.setItem(TREE_KEY, JSON.stringify([...s])); } catch (e) { /* storage off: still works for this page */ }
  renderTree();
  const back = document.querySelector('#tree .hrow[data-key="' + CSS.escape(key) + '"]'); if (back) back.focus({ preventScroll: true });
}
export function scheduleTree() { if (!S.treeTimer) S.treeTimer = setTimeout(() => { S.treeTimer = 0; renderTree(); }, 120); }
export const colState = (f) => String(f.id).replace(/^auto-/, '');
export const colIcon = (st) => (st === 'global' ? 'git-branch' : stateIcon(st));
export const colColor = (st) => (st === 'global' ? null : stateColor(st));
// Chains of the canvas: [{df, tid, ids}] (ids in breadth-first order from the trigger, true branch before false) plus the
// nodes no trigger reaches [{df, nid, ids, orphan: true}].
export function treeChains() {
  if (!S.editor) return [];
  const data = dfData(), reached = new Set(), out = [];
  const trig = Object.keys(data).filter((d) => data[d].data.model.kind === 'trigger')
    .sort((a, b) => data[a].pos_y - data[b].pos_y || data[a].pos_x - data[b].pos_x);
  trig.forEach((df) => {
    const seen = new Set(), queue = [df];
    while (queue.length) {
      const d = queue.shift(); if (seen.has(d) || !data[d]) continue; seen.add(d);
      if (d !== df && data[d].data.model.kind === 'state') continue;     // a legacy hub ends the chain
      Object.keys(data[d].outputs).sort().forEach((k) => data[d].outputs[k].connections.forEach((c) => queue.push(String(c.node))));
    }
    const ids = [...seen].map((d) => data[d].data.model.id);
    ids.forEach((i) => reached.add(i));
    out.push({ df, tid: data[df].data.model.id, ids });
  });
  Object.keys(data).forEach((df) => { const id = data[df].data.model.id; if (!reached.has(id)) out.push({ df, nid: id, ids: [id], orphan: true }); });
  return out;
}
function chainHost(df) { const b = nodeBox(df); return dropTargetAt({ x: (b.x0 + b.x1) / 2, y: (b.y0 + b.y1) / 2 }); }
// Reference of the chain a node belongs to (first chain reaching it, else the node alone), for moveInto / fileMenu.
export function chainRef(nid) {
  const all = treeChains(), c = all.find((x) => !x.orphan && x.ids.includes(nid)) || all.find((x) => x.ids.includes(nid));
  return c ? { what: 'chain', id: c.tid || c.nid, ids: c.ids.slice(), df: c.df } : null;
}
// The tree: rows {key, type: col | group | chain | node | note, id, label, icon, color, x, y, ids (own node ids), off, kids}.
export function buildTree() {
  const root = { key: 'root', type: 'root', ids: [], kids: [] }, rowOf = new Map();
  if (!S.editor) return root;
  frames().forEach((f) => {
    const st = f.auto ? colState(f) : null;
    rowOf.set(f.id, { key: (f.auto ? 'col:' : 'g:') + f.id, type: f.auto ? 'col' : 'group', id: f.id, label: f.title || '(sans nom)',
      icon: f.auto ? colIcon(st) : 'square', color: f.auto ? colColor(st) : f.color, x: f.x, y: f.y, ids: [], kids: [] });
  });
  const into = (pid) => (pid && rowOf.get(pid)) || root;
  frames().forEach((f) => (f.auto ? root : into(f.parent)).kids.push(rowOf.get(f.id)));
  S.treeOwner = new Map();
  treeChains().forEach((c) => {
    const m = model(c.df), d = dfNode(c.df), host = chainHost(c.df), key = c.orphan ? 'n:' + c.nid : 'c:' + c.tid;
    const row = c.orphan
      ? { key, type: 'node', id: c.nid, label: KINDS[m.kind].label + ' : ' + summary(m), icon: iconOf(m), color: KINDS[m.kind].color, x: d.pos_x, y: d.pos_y, ids: c.ids, kids: [] }
      : { key, type: 'chain', id: c.tid, label: summary(m), icon: themeById(nodeTheme(m)).icon || iconOf(m), color: KINDS.trigger.color,
        x: d.pos_x, y: d.pos_y, ids: c.ids, off: (m.params || {}).enabled === false, kids: [] };
    c.ids.forEach((i) => { if (!S.treeOwner.has(i)) S.treeOwner.set(i, key); });
    into(host && host.id).kids.push(row);
  });
  notes().forEach((n) => into(n.parent).kids.push({ key: 'p:' + n.id, type: 'note', id: n.id, label: n.title || noteFirstLine(n) || '(vide)',
    icon: 'message', color: n.color, x: n.x, y: n.y, ids: [], kids: [] }));
  const rank = { col: 0, group: 1, chain: 2, node: 2, note: 3 };
  const sortRec = (row, depth) => { if (depth > 200) return; row.kids.sort((a, b) => rank[a.type] - rank[b.type] || a.y - b.y || a.x - b.x); row.kids.forEach((k) => sortRec(k, depth + 1)); };
  sortRec(root, 0);
  return root;
}
// Post-order pass: rolled-up node ids (diagnostics: nodes in error / warning, chains below) and filter matches.
function treeStat(row, q, depth) {
  const all = new Set(row.ids);
  let hit = false, chains = row.type === 'chain' ? 1 : 0;
  if ((depth || 0) < 200) row.kids.forEach((k) => { treeStat(k, q, (depth || 0) + 1).forEach((i) => all.add(i)); if (k.hit) hit = true; chains += k.chains; });
  row.self = !!q && String(row.label || '').toLowerCase().includes(q);
  row.hit = row.self || hit;
  row.chains = chains; row.err = 0; row.warn = 0;
  all.forEach((i) => {
    const l = S.issues.get(i) || [];
    if (l.some((x) => x.level === 'err')) row.err++; else if (l.some((x) => x.level === 'warn')) row.warn++;
  });
  return all;
}
export function treeStats(key) {
  const root = buildTree(); treeStat(root, '');
  let found = null;
  const find = (r) => { if (found) return; if (r.key === key) { found = r; return; } r.kids.forEach(find); };
  find(root);
  return found || { chains: 0, err: 0, warn: 0 };
}
export function renderTree() {
  const box = $('#tree'); if (!box || !S.editor) return;
  if (S.treeRename || S.treeDrag) { scheduleTree(); return; }
  clearTimeout(S.treeTimer); S.treeTimer = 0;
  const q = (($('#treeFilter') || {}).value || '').trim().toLowerCase();
  const root = buildTree(), fold = treeFolded();
  treeStat(root, q);
  S.treeUp = new Map();
  const up = (row, pk, depth) => { S.treeUp.set(row.key, pk); if (depth < 200) row.kids.forEach((k) => up(k, row.key, depth + 1)); };
  up(root, null, 0);
  const out = document.createDocumentFragment();
  const emit = (row, depth) => {
    if (depth > 200 || (q && !row.hit)) return;
    const hasKids = row.kids.length > 0, open = hasKids && (q ? true : !fold.has(row.key));
    const roll = !hasKids || !open;      // an open container lets its children carry their own badges
    const badges = [];
    if (roll && row.err) badges.push(h('span', { class: 'hb err', 'data-tip': row.err + ' nœud(s) en erreur' + (hasKids ? ' dans ce qui est replié' : '') }, '✖ ' + row.err));
    if (roll && row.warn) badges.push(h('span', { class: 'hb warn', 'data-tip': row.warn + ' nœud(s) avec un avertissement' + (hasKids ? ' dans ce qui est replié' : '') }, '⚠ ' + row.warn));
    const tip = row.off ? 'Chaîne désactivée : elle reste dans le fichier mais le robot l’ignore.' : (String(row.label).length > 26 ? row.label : null);
    out.append(h('div', { class: 'hrow h-' + row.type + (row.off ? ' off' : '') + (row.self ? ' hit' : ''), role: 'treeitem', tabindex: '-1',
      'data-key': row.key, 'data-type': row.type, 'data-id': row.id, 'aria-level': String(depth + 1), 'aria-expanded': hasKids ? String(open) : null,
      style: '--d:' + depth, 'data-tip': tip, 'data-tip-side': tip ? '1' : null },
      h('span', { class: 'hcar' + (hasKids ? '' : ' sp'), 'aria-hidden': 'true' }, hasKids ? (open ? '▾' : '▸') : ''),
      ico(row.icon, row.color), h('span', { class: 'hlab' }, row.label), badges));
    if (open) row.kids.forEach((k) => emit(k, depth + 1));
  };
  root.kids.forEach((k) => emit(k, 0));
  const top = box.scrollTop;
  box.innerHTML = '';
  box.append(out);
  if (!box.children.length) box.append(h('p', { class: 'hint' }, q ? 'Rien ne correspond au filtre.' : 'Graphe vide : clic droit sur le graphe pour ajouter un nœud.'));
  box.scrollTop = top;
  syncTreeSel(true);
}
// Row key of the current selection (a node -> the chain row it belongs to).
function selKey() {
  if (S.selChain && S.selChain.tid) return 'c:' + S.selChain.tid;
  if (S.selFrame) { const f = frameById(S.selFrame); return f ? (f.auto ? 'col:' : 'g:') + f.id : null; }
  if (S.selNote) return 'p:' + S.selNote;
  if (S.selDf != null) return S.treeOwner.get(nidOf(S.selDf)) || null;
  return null;
}
export function syncTreeSel(noScroll) {
  const box = $('#tree'); if (!box) return;
  let k = selKey(), el = null, guard = 0;
  while (k && guard++ < 300 && !(el = box.querySelector('.hrow[data-key="' + CSS.escape(k) + '"]'))) k = S.treeUp.get(k);
  box.querySelectorAll('.hrow.sel').forEach((r) => { if (r !== el) r.classList.remove('sel'); });
  if (!el) return;
  el.classList.add('sel');
  if (noScroll) return;
  // scroll the tree box only (scrollIntoView could also scroll overflow-hidden ancestors of the page)
  const r = el.getBoundingClientRect(), b = box.getBoundingClientRect();
  if (r.top < b.top) box.scrollTop -= b.top - r.top + 4; else if (r.bottom > b.bottom) box.scrollTop += r.bottom - b.bottom + 4;
}
// A chain picked in the hierarchy: every node of it selected (highlighted) at once, view centred on it.
export function selectChain(tid, centre) {
  const c = treeChains().find((x) => x.tid === tid); if (!c) return false;
  clearNodeSelection();
  if (S.selFrame) { S.selFrame = null; drawFrames(); }
  if (S.selNote) { S.selNote = null; noteEls.forEach((el) => el.classList.remove('sel')); }
  S.selConn = null;
  S.selChain = { tid, ids: c.ids.slice() };
  paintChainSel();
  if (centre) focusChainIds(c.ids);
  renderInspector();
  if (innerWidth <= 900) document.body.classList.remove('hide-right');
  return true;
}
function treeActivate(r) {
  const type = r.dataset.type, id = r.dataset.id;
  if (type === 'col' || type === 'group') focusFrame(id);
  else if (type === 'note') focusNoteBox(id);
  else if (type === 'chain') selectChain(id, true);
  else if (type === 'node') focusNode(id);
  if (innerWidth <= 900) document.body.classList.add('hide-left');
}
function treeRenameRow(r) {
  const type = r.dataset.type, id = r.dataset.id;
  const it = type === 'note' ? noteById(id) : (type === 'group' || type === 'col') ? frameById(id) : null;
  if (!it || editBlocked()) return;
  const lab = r.querySelector('.hlab'); if (!lab) return;
  const inp = h('input', { class: 'hrename', type: 'text', maxlength: 60, 'aria-label': type === 'note' ? 'Titre du post-it' : 'Nom du groupe' });
  inp.value = it.title || '';
  S.treeRename = true;
  lab.replaceWith(inp); inp.focus(); inp.select();
  let done = false;
  inp._fin = (ok) => {
    if (done) return; done = true; S.treeRename = false;
    const v = inp.value.slice(0, 60);
    if (ok && v !== (it.title || '')) { if (type === 'note') editNote(it, { title: v }, true); else editFrame(it, { title: v }, true); }
    renderTree();
  };
  inp.addEventListener('blur', () => inp._fin(true));
  ['pointerdown', 'mousedown', 'click', 'dblclick'].forEach((t) => inp.addEventListener(t, (e) => e.stopPropagation()));
}
export function treeFilterKey(e) {
  const flt = e.target;
  if (e.key === 'Escape' && flt.value) { e.preventDefault(); flt.value = ''; renderTree(); }
  else if (e.key === 'ArrowDown' || e.key === 'Enter') { const r = document.querySelector('#tree .hrow'); if (r) { e.preventDefault(); r.focus(); } }
}
// Keys on a focused row: arrows move / fold, Enter selects, F2 renames. Returns true when handled.
export function treeKey(e) {
  const r = e.target, rows = [...document.querySelectorAll('#tree .hrow')], i = rows.indexOf(r), k = e.key, open = r.getAttribute('aria-expanded');
  if (e.ctrlKey || e.metaKey || e.altKey) return false;
  if (k === 'ArrowDown' || k === 'ArrowUp') { const n = rows[i + (k === 'ArrowDown' ? 1 : -1)]; if (n) n.focus(); }
  else if (k === 'ArrowRight' && open === 'false') setFold(r.dataset.key, false);
  else if (k === 'ArrowLeft' && open === 'true') setFold(r.dataset.key, true);
  else if (k === 'ArrowLeft') { const p = S.treeUp.get(r.dataset.key), pr = p && document.querySelector('#tree .hrow[data-key="' + CSS.escape(p) + '"]'); if (pr) pr.focus(); }
  else if (k === 'Enter') treeActivate(r);
  else if (k === 'F2') treeRenameRow(r);
  else return false;
  e.preventDefault(); e.stopPropagation();
  return true;
}
const rowRef = (r) => {
  const type = r.dataset.type, id = r.dataset.id;
  if (type === 'group') return { what: 'group', id };
  if (type === 'note') return { what: 'note', id };
  if (type === 'chain' || type === 'node') return chainRef(type === 'chain' ? id : id);
  return { what: 'col', id };
};
// May the dragged row `d` be dropped on row `over`? (a column never moves; a group never into itself / its subtree)
function treeDropOk(d, over) {
  if (!over || over === d.row || !/^(col|group)$/.test(over.dataset.type) || d.type === 'col') return false;
  const t = frameById(over.dataset.id); if (!t) return false;
  if (d.type === 'group') { const f = frameById(d.id); if (!f || f.id === t.id || descendantFrames(f).some((g) => g.id === t.id)) return false; }
  return true;
}
export function installTree() {
  const box = $('#tree'), flt = $('#treeFilter');
  if (!box || !flt) return;
  flt.addEventListener('input', renderTree);
  box.addEventListener('click', (e) => {
    if (S.treeJustDragged) { S.treeJustDragged = false; return; }
    const r = e.target.closest && e.target.closest('.hrow'); if (!r || S.treeRename) return;
    if (e.target.closest('.hcar') && r.getAttribute('aria-expanded') != null) { setFold(r.dataset.key, r.getAttribute('aria-expanded') === 'true'); return; }
    treeActivate(r);
    const again = box.querySelector('.hrow[data-key="' + CSS.escape(r.dataset.key) + '"]'); if (again) again.focus({ preventScroll: true });
  });
  box.addEventListener('dblclick', (e) => {
    const r = e.target.closest && e.target.closest('.hrow');
    if (r && /^(group|col|note)$/.test(r.dataset.type)) { e.preventDefault(); treeRenameRow(r); }
  });
  // Drag and drop of rows: pointer events (mouse, pen, touch), the pointer is captured only once the drag has started so
  // that a plain click keeps its row as the click target. The drop target is the row under the POINTER.
  box.addEventListener('pointerdown', (e) => {
    const r = e.target.closest && e.target.closest('.hrow');
    if (!r || e.button !== 0 || S.treeRename || e.target.closest('.hcar:not(.sp)')) return;
    S.treeDrag = { row: r, type: r.dataset.type, id: r.dataset.id, x: e.clientX, y: e.clientY, pid: e.pointerId, on: false, over: null, ghost: null };
  });
  box.addEventListener('pointermove', (e) => {
    const d = S.treeDrag; if (!d || e.pointerId !== d.pid) return;
    if (!d.on) {
      if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < 6) return;
      d.on = true;
      try { box.setPointerCapture(d.pid); } catch (err) { /* synthetic pointer */ }
      document.body.classList.add('tree-drag');
      try { const s = window.getSelection(); if (s && !s.isCollapsed) s.removeAllRanges(); } catch (err) { /* nothing selected */ }
      d.row.classList.add('hdragged');
      d.ghost = h('div', { class: 'hghost' }, (d.row.querySelector('.hlab') || {}).textContent || '');
      document.body.append(d.ghost);
    }
    if (e.cancelable) e.preventDefault();
    d.ghost.style.left = (e.clientX + 14) + 'px'; d.ghost.style.top = (e.clientY + 10) + 'px';
    const el = document.elementFromPoint(e.clientX, e.clientY), over = el && el.closest ? el.closest('#tree .hrow') : null;
    const target = over && over !== d.row && /^(col|group)$/.test(over.dataset.type) ? over : null;
    if (d.over && d.over !== target) d.over.classList.remove('hdrop', 'hdeny');
    d.over = target;
    if (target) { const ok = treeDropOk(d, target); target.classList.toggle('hdrop', ok); target.classList.toggle('hdeny', !ok); }
  });
  const end = (e) => {
    const d = S.treeDrag; if (!d || (e.pointerId != null && e.pointerId !== d.pid)) return;
    S.treeDrag = null;
    if (!d.on) return;                                   // a plain click: the click handler selects
    S.treeJustDragged = true; setTimeout(() => { S.treeJustDragged = false; }, 0);
    document.body.classList.remove('tree-drag');
    d.row.classList.remove('hdragged');
    if (d.ghost) d.ghost.remove();
    if (d.over) d.over.classList.remove('hdrop', 'hdeny');
    if (e.type === 'pointerup' && d.over) {
      if (d.type === 'col') toast(COL_TOP, 'err');
      else if (!treeDropOk(d, d.over)) toast('Un groupe ne peut pas entrer dans lui-même ni dans un de ses sous-groupes.', 'err');
      else moveInto(rowRef(d.row), frameById(d.over.dataset.id));
    }
    scheduleTree();
  };
  box.addEventListener('pointerup', end);
  box.addEventListener('pointercancel', end);
  renderTree();
}
// "Ranger dans le groupe ▸": every column and group in hierarchy order (indented by depth); the current host is ticked
// and off, a moved group's own subtree is left out.
export function fileMenu(ref) {
  if (!ref) return [{ label: 'Rien à ranger', disabled: true }];
  const skip = new Set();
  if (ref.what === 'group') { const f = frameById(ref.id); if (f) [f].concat(descendantFrames(f)).forEach((g) => skip.add(g.id)); }
  let cur = null;
  if (ref.what === 'group') cur = (frameById(ref.id) || {}).parent || null;
  else if (ref.what === 'note') cur = (noteById(ref.id) || {}).parent || null;
  else if (ref.df != null) { const hst = chainHost(ref.df); cur = hst ? hst.id : null; }
  const rows = [];
  const walk = (row, depth) => row.kids.forEach((k) => {
    if (!/^(col|group)$/.test(k.type) || skip.has(k.id) || depth > 50) return;
    rows.push({ label: ' '.repeat(depth) + k.label + (k.id === cur ? ' ✓' : ''), icon: k.icon, color: k.color, disabled: k.id === cur,
      fn: () => moveInto(ref, frameById(k.id)) });
    walk(k, depth + 1);
  });
  walk(buildTree(), 0);
  return rows.length ? rows : [{ label: 'Aucun groupe', disabled: true }];
}
// L10: file a group, a post-it or a chain (its nodes) in `target` (a column or a group), from the hierarchy (drag a row)
// or the menu (Ranger dans le groupe ▸). The item moves just below what the target already holds, on its inner left
// margin; the target and its parents grow to enclose it (they never shrink); then, like a canvas drop, dropTargetAt at
// the item's anchor decides the parent (the explicit target wins when the anchor also falls in an overlapping outsider).
// A column never moves into anything (same refusal as on the canvas). One undo step.
export function moveInto(ref, target) {
  if (editBlocked() || !ref || !target) return false;
  if (ref.what === 'col') { toast(COL_TOP, 'err'); return false; }
  let box = null, it = null;
  const mv = { frames: [], notes: [], dfids: [] };
  if (ref.what === 'group') {
    it = frameById(ref.id); if (!it) return false;
    if (it.auto) { toast(COL_TOP, 'err'); return false; }
    if (it.id === target.id || descendantFrames(it).some((g) => g.id === target.id)) { toast('Un groupe ne peut pas entrer dans lui-même ni dans un de ses sous-groupes.', 'err'); return false; }
    Object.assign(mv, frameMembers(it)); box = frameBox(it);
  } else if (ref.what === 'note') {
    it = noteById(ref.id); if (!it) return false;
    mv.notes = [it]; box = noteBox(it);
  } else {
    mv.dfids = (ref.ids || []).map((i) => nidToDf.get(i)).filter((d) => d != null && dfNode(d)).map(String);
    if (!mv.dfids.length) return false;
    mv.dfids.forEach((d) => { const b = nodeBox(d); box = box ? { x0: Math.min(box.x0, b.x0), y0: Math.min(box.y0, b.y0), x1: Math.max(box.x1, b.x1), y1: Math.max(box.y1, b.y1) } : b; });
  }
  // lowest point of what the target already holds (the moved item itself excluded)
  const mf = new Set(mv.frames.map((g) => g.id)), mn = new Set(mv.notes.map((n) => n.id)), md = new Set(mv.dfids.map(String));
  let bottom = target.y + FRAME_PAD.t - 24;
  frames().forEach((g) => { if (g.parent === target.id && !mf.has(g.id)) bottom = Math.max(bottom, g.y + g.h); });
  notes().forEach((n) => { if (n.parent === target.id && !mn.has(n.id)) bottom = Math.max(bottom, n.y + noteHeight(n)); });
  Object.keys(dfData()).forEach((d) => { if (!md.has(String(d)) && inFrame(target, d)) bottom = Math.max(bottom, nodeBox(d).y1); });
  const dx = Math.round(target.x + FRAME_PAD.l - box.x0), dy = Math.round(bottom + 24 - box.y0);
  mv.frames.forEach((g) => { g.x += dx; g.y += dy; });
  mv.notes.forEach((n) => { n.x += dx; n.y += dy; });
  mv.dfids.forEach((d) => {
    const nd = dfNode(d), el = nodeEl(d);
    nd.pos_x += dx; nd.pos_y += dy;
    if (el) { el.style.left = nd.pos_x + 'px'; el.style.top = nd.pos_y + 'px'; }
  });
  mv.dfids.forEach((d) => S.editor.updateConnectionNodes('node-' + d));
  const moved = { x0: box.x0 + dx, y0: box.y0 + dy, x1: box.x1 + dx, y1: box.y1 + dy };
  let nb = moved, f = target, guard = 0;
  while (f && guard++ < 200) {          // the target (then each parent) encloses the moved box, columns included
    const pad = f === target ? FRAME_PAD : NEST_PAD;
    const x0 = Math.min(f.x, nb.x0 - pad.l), y0 = Math.min(f.y, nb.y0 - pad.t), x1 = Math.max(f.x + f.w, nb.x1 + pad.r), y1 = Math.max(f.y + f.h, nb.y1 + pad.b);
    f.x = Math.round(x0); f.y = Math.round(y0); f.w = Math.round(x1 - x0); f.h = Math.round(y1 - y0);
    nb = frameBox(f); f = parentOf(f);
  }
  if (ref.what === 'group' || ref.what === 'note') {
    let t = dropTargetAt({ x: moved.x0 + 12, y: moved.y0 + 12 }, mf);
    if (!t || (t.id !== target.id && !descendantFrames(target).some((g) => g.id === t.id))) t = target;
    reparent(it, ref.what === 'note', t);
  } else toast('Chaîne rangée dans « ' + (target.title || target.id) + ' ».', '');
  drawFrames(); drawNotes(); paintWires();
  commitSoon(); scheduleTree();
  return true;
}
// Inspector of a chain picked in the hierarchy (or of several pasted nodes): where it lives, its problems, its steps.
export function renderChainInspector(box) {
  const df = S.selChain.tid ? nidToDf.get(S.selChain.tid) : null, m = df != null ? model(df) : null;
  const ids = S.selChain.ids.filter((i) => nidToDf.has(i));
  if (m) {
    box.append(h('div', { class: 'insttitle' }, ico(themeById(nodeTheme(m)).icon || iconOf(m), KINDS.trigger.color), 'Chaîne', h('small', { class: 'hint' }, ids.length + ' nœud(s)')));
    box.append(h('div', { class: 'chname' }, summary(m)));
    const path = []; let f = chainHost(df), g = 0;
    while (f && g++ < 50) { path.unshift(f.title || f.id); f = parentOf(f); }
    box.append(h('p', { class: 'hint chpath' }, 'Dans : ' + (path.length ? path.join(' › ') : 'hors des colonnes')));
  } else box.append(h('div', { class: 'insttitle' }, ico('git-branch'), 'Sélection', h('small', { class: 'hint' }, ids.length + ' nœud(s)')));
  const iss = [];
  ids.forEach((i) => (S.issues.get(i) || []).forEach((x) => { if (x.level === 'err' || x.level === 'warn') iss.push(Object.assign({ nid: i }, x)); }));
  if (iss.length) box.append(h('div', { class: 'isslist' }, iss.map((i) => h('div', { class: 'iss ' + i.level, role: 'button', tabindex: '0', onclick: () => focusNode(i.nid) },
    (ISSUE_PREFIX[i.level] || '') + i.message))));
  else box.append(h('p', { class: 'hint chok' }, '✔ Aucune erreur ni avertissement dans cette chaîne.'));
  box.append(h('div', { class: 'sect' }, 'Étapes'));
  ids.forEach((i, k) => {
    const mm = model(nidToDf.get(i));
    box.append(h('div', { class: 'trow cstep', 'data-nid': i, onclick: () => focusNode(i) }, ico(iconOf(mm), KINDS[mm.kind].color), ' ',
      (k + 1) + '. ', h('b', {}, KINDS[mm.kind].label), ' : ' + summary(mm)));
  });
  if (m && !isEnterTrig(m)) {
    box.append(checkCtl('Chaîne activée', m.params.enabled !== false, () => toggleChains([df]), 'power'));
    if (m.params.enabled === false) box.append(h('p', { class: 'hint' }, 'Désactivée : la chaîne reste dans le fichier mais le robot l’ignore (grisée).'));
  }
  box.append(h('div', { class: 'chbtns' }, h('button', { type: 'button', onclick: () => copySelection() }, 'Copier'),
    h('button', { type: 'button', onclick: cutSelection }, 'Couper'),
    h('button', { type: 'button', class: 'danger', onclick: deleteSelection }, m ? 'Supprimer la chaîne' : 'Supprimer ces nœuds')));
}
