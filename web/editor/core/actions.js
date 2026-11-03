/**
 * Editor core: toolbar actions.
 *
 * Purpose :  validate, postDoc, save, loadAll.
 * Boundary:  network through core/api.js: GET /api/graph/vocab + /api/graph/visual, POST /api/graph/visual (save); the
 *            server validates. Moved unchanged out of the former single-file editor.js (lot M6). L22: save() is one
 *            covering progress task (fresh check + POST), red on refusal.
 * Depends :  core/util.js, core/state.js, core/api.js, core/serialize.js, core/history.js, core/chains.js,
 *            diagnostics/analysis.js, diagnostics/check.js, hierarchy/tree.js, panels/intents.js, variables/panel.js,
 *            core/ui.js, panels/history-panels.js, core/progress.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $ } from './util.js';
import { S, KINDS, freshIds } from './state.js';
import { AUTO_DELAY_MS, api, postJson } from './api.js';
import { rebuild, serialize } from './serialize.js';
import { snap, updateBar } from './history.js';
import { computeChains } from './chains.js';
import { analyze } from '../diagnostics/analysis.js';
import { freshCheck } from '../diagnostics/check.js';
import { scheduleTree } from '../hierarchy/tree.js';
import { renderIntents } from '../panels/intents.js';
import { refreshVarStore } from '../variables/panel.js';
import { toast } from './ui.js';
import { loadVersions } from '../panels/history-panels.js';
import { startTask } from './progress.js';

// ---------- toolbar actions ----------
export function validate(showToast) {
  freshIds.clear();          // from here on, empty required fields count as real errors
  analyze();
  let ne = 0, nw = 0;
  S.issues.forEach((l) => l.forEach((i) => (i.level === 'err' ? ne++ : i.level === 'info' ? 0 : nw++)));
  S.globalIssues.forEach((i) => (i.level === 'err' ? ne++ : nw++));
  if (showToast) {
    toast(ne ? `${ne} erreur(s) à corriger, ${nw} avertissement(s).` : nw ? `Aucune erreur, ${nw} avertissement(s).` : "Structure correcte. Le robot fait la validation finale à l'enregistrement.", ne ? 'err' : 'ok');
    if (ne + nw) $('#msgs').hidden = false;
  }
  return ne;
}
export async function postDoc(doc) {
  const r = await postJson('/api/graph/visual', doc);
  if (r.ok) {
    S.serverErrors = [];
    S.savedSnap = snap();
    S.liveChains = computeChains(doc);
    if (S.curTab === 'versions') loadVersions();
    setTimeout(refreshVarStore, 1500);    // L12: the robot reloads the graph, then reads its saved values again
    toast(r.json.message || 'Enregistré.', r.json.applied ? 'ok' : '');
    const b = $('#banner');
    b.hidden = r.json.applied !== false;
    if (r.json.applied === false) { b.className = ''; b.textContent = 'Graphe enregistré : il sera appliqué à la prochaine veille.'; }
  } else {
    S.serverErrors = (r.json && r.json.errors) || [{ node: null, message: 'Erreur ' + r.status }];
    toast(S.serverErrors.length + " erreur(s) refusée(s) par le robot : rien n'a été écrit.", 'err');
    $('#msgs').hidden = false;
  }
  analyze(); updateBar();
  if (!r.ok && S.curTab === 'intents') renderIntents();     // show the per-intent server message
  return r;
}
export async function save() {
  if (S.navLocked) { toast('Verrouillé — lecture seule : enregistrement désactivé (L pour déverrouiller).', 'err'); return; }
  // L22: one progress task for the whole save (its fetches add none of their own); the page stays usable meanwhile
  const task = startTask('Enregistrement et application', { delay: AUTO_DELAY_MS, covers: true });
  try {
    const r = await saveSteps();
    if (r && r.ok) task.done(); else task.fail();      // refused (local or robot): red bar, the toast says why
    return r;
  } catch (e) { task.fail(); throw e; }
}
async function saveSteps() {
  // L6: decide on a fresh dry run, not on badges up to 0.5 s old (debounce) or from an earlier refused save: a click
  // right after a fix used to be blocked by the stale error. The server re-validates on POST anyway.
  let doc = null;
  for (let i = 0; i < 3 && !doc; i++) {
    const ok = await freshCheck(), cur = serialize();
    if (ok && JSON.stringify(cur) !== S.checkOkKey) continue;   // edited while waiting: check that version
    if (ok) { S.serverErrors = []; S.simErrors = []; analyze(); }   // the fresh check supersedes older refusals
    doc = cur;             // check unavailable (network / 5xx): fall back to the badges, the POST validates anyway
  }
  if (!doc || validate(false)) { validate(true); return null; }
  return postDoc(doc);
}
export async function loadAll() {
  const [vocab, vis] = await Promise.all([api('/api/graph/vocab'), api('/api/graph/visual')]);
  if (!vocab.ok || !vis.ok) { toast('Impossible de charger le graphe (' + (vocab.status || vis.status) + ').', 'err'); return; }
  S.V = vocab.json; S.serverErrors = []; S.simErrors = [];
  (S.V.kinds || []).forEach((k) => { if (KINDS[k.id] && k.icon) KINDS[k.id].icon = k.icon; });
  scheduleTree();
  rebuild(vis.json, false);
  S.liveChains = computeChains(vis.json);
  scheduleTree();
  if (S.curTab === 'versions') loadVersions();
  S.hist = [snap()]; S.histIdx = 0; S.savedSnap = S.hist[0];
  const b = $('#banner');
  if (vis.json.error) { b.hidden = false; b.className = 'bad'; b.textContent = 'Le fichier du graphe a été refusé au démarrage : ' + vis.json.error; }
  else if (vis.json.pending) { b.hidden = false; b.className = ''; b.textContent = "Un graphe enregistré attend la prochaine veille pour s'appliquer."; }
  else b.hidden = true;
  updateBar();
  refreshVarStore();          // L12: persisted-value conflicts (store.ignored) become global warnings
  return vis.json;
}
