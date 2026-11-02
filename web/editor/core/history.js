/**
 * Editor core: undo / redo history.
 *
 * Purpose :  snapshot list of serialized documents (snap, commitSoon, undo, redo, dirty mark).
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, core/serialize.js, diagnostics/analysis.js, canvas/navigation.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $ } from './util.js';
import { S } from './state.js';
import { rebuild, serialize } from './serialize.js';
import { analyze } from '../diagnostics/analysis.js';
import { editBlocked } from '../canvas/navigation.js';

// ---------- history ----------
export const snap = () => JSON.stringify(serialize());
// shared state: S.commitTimer (core/state.js)
export function commitSoon() {
  if (S.loading) return;
  clearTimeout(S.commitTimer);
  S.commitTimer = setTimeout(commit, 0);   // coalesce the several events of one gesture (e.g. node removal)
}
export function commit() {
  if (S.loading) return;
  const s = snap();
  if (s !== S.hist[S.histIdx]) {
    S.hist = S.hist.slice(0, S.histIdx + 1); S.hist.push(s);
    if (S.hist.length > 100) S.hist.shift();
    S.histIdx = S.hist.length - 1;
  }
  analyze(); updateBar();
}
export function undo() { if (editBlocked()) return; if (S.histIdx > 0) { S.histIdx--; rebuild(JSON.parse(S.hist[S.histIdx]), true); updateBar(); } }
export function redo() { if (editBlocked()) return; if (S.histIdx < S.hist.length - 1) { S.histIdx++; rebuild(JSON.parse(S.hist[S.histIdx]), true); updateBar(); } }
export function updateBar() {
  $('#btnUndo').disabled = S.histIdx <= 0;
  $('#btnRedo').disabled = S.histIdx >= S.hist.length - 1;
  $('#dirty').hidden = S.hist[S.histIdx] === S.savedSnap;
}
