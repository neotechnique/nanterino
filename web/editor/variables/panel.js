/**
 * Variables panel (Vars L2): state, renames, live values.
 *
 * Purpose :  varsUi, name checks, renameUses / deleteVarOrList, live column polling (<= 1 Hz while the tab is open),
 *            store refresh.
 * Boundary:  network through core/api.js: GET /api/graph/vars (<= 1 Hz, only while the Variables tab is open). Moved
 *            unchanged out of the former single-file editor.js (lot M6).
 * Depends :  core/state.js, variables/model.js, inspector/property-picker.js, core/api.js, canvas/nodes.js,
 *            core/history.js, diagnostics/analysis.js, inspector/inspector.js, variables/tables.js, core/ui.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { S } from '../core/state.js';
import { VAR_NAME, docVars, listDefs, varDefs } from './model.js';
import { isSrcObj, srcRename, varUses, vtype } from '../inspector/property-picker.js';
import { api, dfData, model } from '../core/api.js';
import { refreshNode } from '../canvas/nodes.js';
import { commitSoon } from '../core/history.js';
import { analyze } from '../diagnostics/analysis.js';
import { renderInspector } from '../inspector/inspector.js';
import { renderVars } from './tables.js';
import { toast } from '../core/ui.js';

// ---------- Variables panel (Vars L2: Game Creator 2 style Local Variables, tabs Noms / Listes) ----------
// Edits the document's `variables` block (meta.variables) like the intents panel edits meta.intents: every change goes
// through commitSoon() (undo / dirty / save), the server validates at save time (a deleted variable that a node still
// uses = 400, located on that node). System variables (etat, tours, ...) and source-bound lists are read-only and
// marked with a lock. The live column reads GET /api/graph/vars once a second, only while this tab is open.
export const varsUi = { tab: 'names', sel: null, list: null, live: null, timer: null, uses: null };
export function varsChanged(rerender) {
  commitSoon();
  analyze();
  if (rerender) renderVars();
  if (S.selDf != null && S.curTab === 'node') renderInspector();
}
const takenName = (id) => varDefs().some((v) => v.id === id) || listDefs().some((l) => l.id === id);
export function checkNewName(id, old) {
  if (!VAR_NAME.test(id)) return 'Nom invalide : minuscules, chiffres et _, commence par une lettre, 32 caractères au plus.';
  if (id !== old && takenName(id)) return 'Ce nom est déjà pris (les variables et les listes partagent les noms).';
  return null;
}
// Rename a variable or list everywhere in the canvas (args name / list, trigger name, "$name" values).
export function renameUses(old, nu) {
  const swap = (v) => (v === '$' + old ? '$' + nu : Array.isArray(v) ? v.map(swap) : v);
  for (const dfid in dfData()) {
    const m = model(dfid), p = m.params || {}, a = p.args || {};
    let hit = false;
    if (m.kind === 'trigger' && p.name === old) { p.name = nu; hit = true; }
    if (a.name === old) { a.name = nu; hit = true; }
    if (a.list === old) { a.list = nu; hit = true; }
    if (a.dict === old) { a.dict = nu; hit = true; }
    if (a.key === '$' + old) { a.key = '$' + nu; hit = true; }
    ['value'].forEach((k) => { if (a[k] !== undefined && swap(a[k]) !== a[k]) { a[k] = swap(a[k]); hit = true; } if (p[k] !== undefined && m.kind === 'trigger' && swap(p[k]) !== p[k]) { p[k] = swap(p[k]); hit = true; } });
    // lot M5: value sources (any argument, any depth) reading the renamed variable / list
    Object.keys(a).forEach((k) => {
      if (!isSrcObj(a[k])) return;
      const r = srcRename(a[k], old, nu);
      if (JSON.stringify(r) !== JSON.stringify(a[k])) { a[k] = r; hit = true; }
    });
    if (hit) refreshNode(dfid);
  }
}
// Delete only when nothing uses it; otherwise list the users (clickable) and refuse.
export function deleteVarOrList(id, isList) {
  const uses = varUses(id);
  if (uses.length) {
    varsUi.uses = { id, nodes: uses };
    toast(`« ${id} » est utilisée par ${uses.length} nœud(s) : ${uses.join(', ')}. Retirez-la de ces nœuds d'abord.`, 'err');
    renderVars(); return false;
  }
  delete docVars()[isList ? 'lists' : 'names'][id];
  if (isList) varsUi.list = null; else varsUi.sel = null;
  varsUi.uses = null;
  toast(`« ${id} » supprimée.`, 'ok');
  varsChanged(true); return true;
}
// A value as shown in the panel / Tester. `type` (L12, optional) refines it: chrono = elapsed m:ss (null = stopped),
// vector = (x, y), date = "AAAA-MM-JJ HH:MM"; a list shows [count], a dict {count}.
export function liveText(v, type) {
  if (v === undefined) return '—';
  const c = type ? vtype(type).control : '';
  if (c === 'timer') {
    if (v == null) return 'arrêté';
    const n = Math.max(0, Math.floor(Number(v)) || 0);
    return Math.floor(n / 60) + ':' + String(n % 60).padStart(2, '0');
  }
  if (Array.isArray(v)) return c === 'vector' ? '(' + v.join(', ') + ')' : '[' + v.length + ']';
  if (v && typeof v === 'object') return '{' + Object.keys(v).length + '}';
  if (v === true) return 'vrai';
  if (v === false) return 'faux';
  if (v == null) return c ? '(vide)' : 'null';
  if (c === 'datetime') return String(v).replace('T', ' ').slice(0, 16);
  return String(v);
}
function paintLive() {
  const j = varsUi.live || {};
  document.querySelectorAll('#vars [data-live]').forEach((el) => {
    const [kind, id] = el.dataset.live.split(':');
    el.textContent = liveText(((j[kind] || {})[id]), el.dataset.ltype || '');
  });
}
async function pollVars() {
  if (S.curTab !== 'vars') return;
  const r = await api('/api/graph/vars', { progress: false });   // L22: 1 Hz poller, never on the progress bar
  if (!r.ok || !r.json) return;
  const conflicts = (x) => JSON.stringify((((x || {}).store) || {}).ignored || []);
  const was = conflicts(varsUi.live);
  varsUi.live = r.json;
  paintLive();               // the chrono "ticks": the robot sends its elapsed seconds on every poll
  if (conflicts(r.json) !== was) { analyze(); renderVars(); }
}
// L12: one read of GET /api/graph/vars outside the panel (load / after save): the persisted-value conflicts
// (store.ignored) become global warnings even when the Variables tab is closed.
export async function refreshVarStore() {
  let r;
  try { r = await api('/api/graph/vars'); } catch (e) { return; }
  if (!r || !r.ok || !r.json) return;
  varsUi.live = r.json;
  analyze();
  if (S.curTab === 'vars') renderVars();
}
export function startVarsPoll() {
  if (varsUi.timer) return;
  pollVars();
  varsUi.timer = setInterval(pollVars, 1000);       // <= 1 Hz, only while the tab is open
}
export function stopVarsPoll() { clearInterval(varsUi.timer); varsUi.timer = null; }
