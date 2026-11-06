/**
 * Editor core: undo / redo history.
 *
 * Purpose :  snapshot list of serialized documents (snap, commitSoon, commitTyping, undo, redo, dirty mark, isDirty).
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Invariant: L23 save rule: every edit (nodes, wires, groups, post-its, hierarchy actions) only changes the in-page
 *            document and this history; nothing is written before "Enregistrer et appliquer" (core/actions.js save).
 * Depends :  core/util.js, core/state.js, core/serialize.js, diagnostics/analysis.js, canvas/navigation.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $ } from './util.js';
import { S } from './state.js';
import { rebuild, serialize } from './serialize.js';
import { analyze } from '../diagnostics/analysis.js';
import { editBlocked } from '../canvas/navigation.js';
import { bumpGeo } from '../canvas/geometry.js';

// ---------- history ----------
export const snap = () => JSON.stringify(serialize());
// shared state: S.commitTimer (core/state.js)
export function commitSoon() {
  if (S.loading) return;
  clearTimeout(S.commitTimer);
  S.commitTimer = setTimeout(commit, 0);   // coalesce the several events of one gesture (e.g. node removal)
}
// L23: typing in a post-it commits after a short pause, so the "modifié" mark shows while the user types and one undo
// step covers one burst of typing (the textarea's change event still commits at once on blur).
let typeTimer = 0;
export const TYPE_COMMIT_MS = 600;
export function commitTyping() {
  if (S.loading) return;
  clearTimeout(typeTimer);
  typeTimer = setTimeout(commit, TYPE_COMMIT_MS);
}
// L23: true when the document differs from the last saved one, including an edit not yet in the history (pending
// typing). Used by the beforeunload prompt: post-its, groups and the hierarchy obey the same save rule as nodes.
export function isDirty() {
  if (!S.editor || S.savedSnap == null) return false;
  if (S.hist[S.histIdx] !== S.savedSnap) return true;
  try { return snap() !== S.savedSnap; } catch (e) { return false; }
}
export function commit() {
  if (S.loading) return;
  clearTimeout(typeTimer);
  const s = snap();
  if (s !== S.hist[S.histIdx]) {
    S.hist = S.hist.slice(0, S.histIdx + 1); S.hist.push(s);
    if (S.hist.length > 100) S.hist.shift();
    S.histIdx = S.hist.length - 1;
  }
  bumpGeo();                 // S2: an edit may move / add / remove nodes: the cached minimap world is stale
  analyze(); updateBar();
}
export function undo() { if (editBlocked()) return; if (S.histIdx > 0) { S.histIdx--; rebuild(JSON.parse(S.hist[S.histIdx]), true); updateBar(); } }
export function redo() { if (editBlocked()) return; if (S.histIdx < S.hist.length - 1) { S.histIdx++; rebuild(JSON.parse(S.hist[S.histIdx]), true); updateBar(); } }
export function updateBar() {
  $('#btnUndo').disabled = S.histIdx <= 0;
  $('#btnRedo').disabled = S.histIdx >= S.hist.length - 1;
  $('#dirty').hidden = S.hist[S.histIdx] === S.savedSnap;
}
