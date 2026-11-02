/**
 * Canvas: no wire into a trigger (Vars L2).
 *
 * Purpose :  drop guard that refuses (and toasts) a connection into a trigger.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/state.js, core/api.js, canvas/nodes.js, core/ui.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { S, NO_TRIGGER_INPUT } from '../core/state.js';
import { dfData } from '../core/api.js';
import { nodeEl } from './nodes.js';
import { toast } from '../core/ui.js';

// ---------- no wire into a trigger (Vars L2) ----------
// A trigger has no input port, so Drawflow silently drops a wire released on it. Tell the user why: when a wire drag
// (editor.connection) ends over a trigger card, toast the rule. Hit-test by card rectangles (the dragged path may be
// the topmost element under the pointer). Nothing is linked either way.
export function installTriggerDropGuard() {
  const onUp = (e) => {
    if (!S.editor || !S.editor.connection) return;
    const pt = e.changedTouches ? e.changedTouches[0] : e;
    if (!pt) return;
    const data = dfData();
    for (const dfid in data) {
      if (data[dfid].data.model.kind !== 'trigger') continue;
      const el = nodeEl(dfid); if (!el) continue;
      const r = el.getBoundingClientRect();
      if (pt.clientX >= r.left && pt.clientX <= r.right && pt.clientY >= r.top && pt.clientY <= r.bottom) {
        S.noInputRefusals++; toast(NO_TRIGGER_INPUT, 'err'); return;
      }
    }
  };
  S.editor.container.addEventListener('mouseup', onUp, true);
  S.editor.container.addEventListener('touchend', onUp, true);
}
// shared state: S.noInputRefusals (core/state.js)   // test hook: wires refused because they ended on a trigger
