/**
 * Menus: adding nodes and the node menu tree (lot L5).
 *
 * Purpose :  addAt / linkNodes, Category (node kind) > Theme > item tree from the vocabulary (menuItems, menuTree).
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, core/api.js, canvas/nodes.js, core/history.js, core/chains.js,
 *            diagnostics/analysis.js, canvas/view.js, frames/nesting.js, canvas/navigation.js, menu/context-menu.js,
 *            core/ui.js, panels/live.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, clone } from '../core/util.js';
import { S, CATS, KINDS, KIND_TIP, byId, evs, freshIds, stateIcon } from '../core/state.js';
import { dfData, dfNode, nextNid } from '../core/api.js';
import { addNodeFromModel, nodeEl } from '../canvas/nodes.js';
import { commitSoon } from '../core/history.js';
import { panTo } from '../core/chains.js';
import { analyze } from '../diagnostics/analysis.js';
import { nodeBox } from '../canvas/view.js';
import { canvasPoint } from '../frames/nesting.js';
import { editBlocked } from '../canvas/navigation.js';
import { moveChoices } from './context-menu.js';
import { toast } from '../core/ui.js';
import { isVisible } from '../panels/live.js';

// ---------- adding nodes ----------
export function defaultModel(kind, preset) {
  const m = { id: nextNid(), kind, description: '', params: {} };
  const p = m.params;
  const firstState = (S.V.states[0] || {}).id || '';
  if (kind === 'trigger') { p.type = 'event'; p.event = (S.V.events[0] || {}).id || ''; }
  if (kind === 'condition') { p.type = 'guard'; p.guard = (S.V.guards[0] || {}).id || ''; p.negate = false; }
  if (kind === 'action') { p.action = (S.V.actions[0] || {}).id || ''; p.args = {}; p.phase = 'do'; }
  if (kind === 'goto' || kind === 'state') p.state = firstState;
  if (kind === 'start') p.state = 'veille';
  if (preset) {
    if (preset.event) { p.type = 'event'; p.event = preset.event; }
    if (preset.type === 'after') { p.type = 'after'; delete p.event; p.delay = (S.V.delays[0] || {}).key || 5; p.since = 'state'; }
    if (preset.params) Object.assign(p, clone(preset.params));   // e.g. var_changed on etat = X (state entry)
    if (preset.guard) { p.guard = preset.guard; if (preset.args) p.args = clone(preset.args); }
    if (preset.action) { p.action = preset.action; p.args = preset.args ? clone(preset.args) : {}; }
    if (preset.state) p.state = preset.state;
  }
  return m;
}
// Add a node of `kind`. Options: exact (place it exactly at `pt`, no nudging away from other nodes), select (default true).
// Returns the Drawflow id, null if refused. (Vars L2: no State hubs any more; a trigger is never linked on creation.)
export function addAt(kind, preset, pt, opts) {
  opts = opts || {};
  if (kind === 'start') { toast("Le nœud Début n'existe plus : un déclencheur démarre sa chaîne tout seul.", 'err'); return null; }   // L4
  if (kind === 'state' || kind === 'goto') { toast("Les nœuds État / Aller à n'existent plus : utilisez l'action « Changer d'état ».", 'err'); return null; }
  if (editBlocked()) return null;
  const sel = S.selDf != null && dfNode(S.selDf) ? S.selDf : null;
  if (!pt) {
    // Preferred spot: right of the selected node, else the middle of the visible canvas.
    if (sel != null) pt = { x: dfNode(sel).pos_x + 260, y: dfNode(sel).pos_y };
    else { const st = $('#stage').getBoundingClientRect(); pt = canvasPoint(st.x + st.width / 2 - 100, st.y + st.height / 2 - 40); }
  }
  if (!opts.exact) pt = freeSpot(pt.x, pt.y);
  const m = defaultModel(kind, preset);
  freshIds.add(m.id);
  const dfid = addNodeFromModel(m, Math.round(pt.x), Math.round(pt.y));
  commitSoon();
  if (opts.select !== false) selectDf(dfid);
  if (!isVisible(m.id)) panTo(m.id, 0.6);
  analyze();
  return dfid;
}
// Nearest position (on a 250 x 130 grid around the wanted one) where a new 214 x 120 node touches no other node.
function freeSpot(x, y) {
  const boxes = Object.keys(dfData()).map((id) => nodeBox(id));
  const free = (px, py) => boxes.every((b) => px + 230 < b.x0 || px > b.x1 + 16 || py + 130 < b.y0 || py > b.y1 + 16);
  const cand = [];
  for (let i = -8; i <= 8; i++) for (let j = -8; j <= 8; j++) cand.push([i * 250 * 0.5, j * 130 * 0.5, Math.hypot(i * 1.2, j)]);
  cand.sort((a, b) => a[2] - b[2]);
  for (const [dx, dy] of cand) if (free(x + dx, y + dy)) return { x: Math.round(x + dx), y: Math.round(y + dy) };
  return { x, y };
}
export function selectDf(dfid) {
  // Drawflow has no public "select"; emulate the click it listens to.
  const el = nodeEl(dfid);
  if (el) { el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true })); }
}

// ---------- node menu: Category (node kind) > Theme > item (lot L5) ----------
// Themes and each entry's theme come from the vocabulary (`theme`, `themes`, `theme_slots`); the editor never picks a
// theme itself. Entries built from data (intents, delay trigger, per-state entries) use the vocabulary's theme slots.
export const themeById = (id) => byId(S.V.themes, id) || { id: id || 'autres', label: 'Autres', icon: 'circle-dot', help: '', order: 999 };
export const slotTheme = (slot) => (S.V.theme_slots || {})[slot] || '';
export function menuItems() {
  const out = [];
  // `hay` (search text) = label, id, help and the theme name: searching "micro" lists the whole Micro theme too
  const add = (cat, theme, label, icon, preset, help, extra, slot) => out.push({ cat, kind: cat, theme, label, icon, preset, help: help || '', slot: slot || '',
    hay: (label + ' ' + (extra || '') + ' ' + (help || '') + ' ' + themeById(theme).label).toLowerCase() });
  evs().forEach((e) => {
    const intent = String(e.id).startsWith('intent.');
    add('trigger', intent ? slotTheme('intent') : e.theme, e.label, e.icon, { event: e.id }, e.help, e.id, intent ? 'intent' : '');
  });
  add('trigger', slotTheme('after'), 'Après un délai', 'clock', { type: 'after' },
    'Démarre la chaîne après un délai, compté depuis l’entrée dans l’état ou depuis la dernière parole. À rattacher à un état (condition « etat = … »).', 'after délai attendre', 'after');
  S.V.states.forEach((st) => add('trigger', slotTheme('state_enter'), 'Entrée dans « ' + st.label + ' »', stateIcon(st.id),
    { event: 'var_changed', params: { name: 'etat', value: st.id } }, 'Quand etat devient ' + st.id + ' : des actions à l’entrée dans l’état (ni condition, ni changement d’état).', 'etat entrée ' + st.id, 'state_enter'));
  S.V.guards.forEach((g) => add('condition', g.theme, g.label, g.icon, { guard: g.id }, g.help, g.id));
  S.V.states.forEach((st) => add('condition', slotTheme('state_test'), 'etat = ' + st.label, stateIcon(st.id),
    { guard: 'var_compare', args: { name: 'etat', op: '=', value: st.id } }, 'Vrai quand le robot est dans l’état « ' + st.label + ' » : range la chaîne dans sa colonne.', 'etat état ' + st.id, 'state_test'));
  S.V.actions.forEach((a) => add('action', a.theme, a.label, a.icon, { action: a.id }, a.help, a.id));
  moveChoices().forEach((c) => add('action', slotTheme('state_move'), c.label, c.icon, c.preset, 'Le robot passe dans cet état (action « Changer une variable » sur etat).', c.hay, 'state_move'));
  // L10: "Fin" (end of chain, no state change) is an `end` node filed under Actions › État, beside "Changer d'état → X"
  out.push({ cat: 'action', kind: 'end', theme: slotTheme('state_move'), label: KINDS.end.label, icon: KINDS.end.icon, preset: null, help: KIND_TIP.end, slot: 'end',
    hay: (KINDS.end.label + ' end fin de chaîne ' + KIND_TIP.end + ' ' + themeById(slotTheme('state_move')).label).toLowerCase() });
  return out;
}
// [{cat, themes: [{theme, items}]}] for the allowed kinds; themes in vocabulary order; a theme without item is dropped.
export function menuTree(kinds, opts) {
  // L10: an entry is kept when its node KIND is allowed ("Fin" = an end filed under the Actions category)
  const items = menuItems().filter((i) => kinds.includes(i.kind) && (!(opts && opts.noMoves) || i.slot !== 'state_move'));
  return CATS.filter((c) => items.some((i) => i.cat === c.id)).map((c) => {
    const mine = items.filter((i) => i.cat === c.id), ids = [...new Set(mine.map((i) => i.theme))];
    ids.sort((a, b) => themeById(a).order - themeById(b).order);
    return { cat: c, themes: ids.map((t) => ({ theme: themeById(t), items: mine.filter((i) => i.theme === t) })) };
  }).filter((c) => c.themes.length);
}
export const itemPath = (i) => ((CATS.find((c) => c.id === i.cat) || {}).label || '') + ' › ' + themeById(i.theme).label;
