/**
 * Editor core: network calls and model access over the Drawflow data.
 *
 * Purpose :  api / postJson (fetch JSON), dfData / dfNode / model / nidOf / nextNid.
 * Boundary:  the only fetch() wrapper of the editor (JSON in / out); model access reads the Drawflow document of
 *            S.editor. Moved unchanged out of the former single-file editor.js (lot M6).
 *            L22: every call registers an automatic progress task (core/progress.js) shown only if it lasts more than
 *            AUTO_DELAY_MS, so fast calls never flash the bar; pollers pass { progress: false }; a call made while an
 *            explicit covering task runs (save, validate…) adds no task of its own. A 5xx / network failure turns the
 *            bar red briefly (the caller keeps its own toast); a 4xx is an answer, not a failure.
 * Depends :  core/state.js, core/progress.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { S } from './state.js';
import { covered, startTask } from './progress.js';

// ---------- network ----------
export const AUTO_DELAY_MS = 300;
// French label of an automatic task, from the route (the chip shows it when the call is slow).
const LABELS = [
  [/^\/api\/graph\/visual/, 'GET', 'Chargement du graphe'], [/^\/api\/graph\/visual/, 'POST', 'Enregistrement du graphe'],
  [/^\/api\/graph\/vocab/, '', 'Chargement du vocabulaire'], [/^\/api\/graph\/check/, '', 'Vérification du graphe'],
  [/^\/api\/graph\/simulate/, '', 'Simulation'], [/^\/api\/graph\/versions\/.+\/restore/, '', 'Restauration de la version'],
  [/^\/api\/graph\/versions/, '', 'Chargement des versions'], [/^\/api\/graph\/trace/, '', 'Chargement du journal'],
  [/^\/api\/graph\/vars\/reset/, '', 'Réinitialisation de la variable'], [/^\/api\/graph\/vars/, '', 'Lecture des variables'],
  [/^\/api\/graph\/reset/, '', 'Retour au graphe par défaut'], [/^\/api\/graph\/snapshot/, '', "Export de l'image"],
  [/^\/api\/graph$/, '', 'Lecture du graphe actif'],
];
function labelOf(path, method) {
  const p = String(path).split('?')[0];
  const hit = LABELS.find(([re, m]) => re.test(p) && (!m || m === method));
  return hit ? hit[2] : 'Chargement';
}
// opts.progress: false = no automatic task (pollers), a string = its label. Other opts go to fetch() unchanged.
export async function api(path, opts) {
  const { progress, ...fo } = opts || {};
  const method = (fo.method || 'GET').toUpperCase();
  const task = progress === false || covered() ? null
    : startTask(typeof progress === 'string' ? progress : labelOf(path, method), { delay: AUTO_DELAY_MS, auto: true });
  let r;
  try { r = await fetch(path, fo); } catch (e) { if (task) task.fail(); throw e; }
  let j = null;
  try { j = await r.json(); } catch (e) { /* non JSON */ }
  if (task) { if (r.status >= 500) task.fail(); else task.done(); }
  return { status: r.status, ok: r.ok, json: j };
}
export const postJson = (path, body, opts) => api(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body == null ? {} : body), ...(opts || {}),
});

// ---------- model access ----------
export function dfData() { return S.editor.drawflow.drawflow[S.editor.module].data; }
export function dfNode(dfid) { return dfData()[dfid]; }
export function model(dfid) { const n = dfNode(dfid); return n ? n.data.model : null; }
export function nidOf(dfid) { const m = model(dfid); return m ? m.id : null; }

export function nextNid() {
  let mx = S.idCounter;
  for (const id in dfData()) { const m = /^n(\d+)$/.exec(model(id).id); if (m) mx = Math.max(mx, +m[1]); }
  S.idCounter = mx + 1;
  return 'n' + S.idCounter;
}
