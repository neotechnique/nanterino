/**
 * Editor core: network calls and model access over the Drawflow data.
 *
 * Purpose :  api / postJson (fetch JSON), dfData / dfNode / model / nidOf / nextNid.
 * Boundary:  the only fetch() wrapper of the editor (JSON in / out); model access reads the Drawflow document of
 *            S.editor. Moved unchanged out of the former single-file editor.js (lot M6).
 * Depends :  core/state.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { S } from './state.js';

// ---------- network ----------
export async function api(path, opts) {
  const r = await fetch(path, opts);
  let j = null;
  try { j = await r.json(); } catch (e) { /* non JSON */ }
  return { status: r.status, ok: r.ok, json: j };
}
export const postJson = (path, body) => api(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body == null ? {} : body),
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
