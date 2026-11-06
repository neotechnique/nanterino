/**
 * Canvas: view helpers.
 *
 * Purpose :  node boxes, state column rectangles (bandRects) and the live / simulated column glow (drawBands).
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 *            S2: node sizes come from the geometry cache (canvas/geometry.js, no layout read per call); a folded
 *            column's rectangle is its card (FOLD_COL), so jumping to it / the minimap show what is drawn.
 * Depends :  core/state.js, core/api.js, canvas/nodes.js, frames/groups.js, canvas/geometry.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { S } from '../core/state.js';
import { dfData, dfNode, model } from '../core/api.js';
import { nodeEl } from './nodes.js';
import { frameEls, frames } from '../frames/groups.js';
import { FOLD_COL, NODE_DEFAULT, nodeSize } from './geometry.js';

// ---------- view ----------
// Vars L2: a state is a column (automatic frame `auto-<state>`, no hub node). The helpers below keep the old "band"
// vocabulary for navigation: bandRects() = the column frame when present, else the bounding box of every node whose
// `group` is that state; used to jump to a state, the minimap and the first view.
export function nodeBox(dfid) {
  const d = dfNode(dfid), el = nodeEl(dfid), sz = el ? nodeSize(dfid, el) : NODE_DEFAULT;
  return { x0: d.pos_x, y0: d.pos_y, x1: d.pos_x + sz.w, y1: d.pos_y + sz.h };
}
export function bandRects() {
  const g = {};
  for (const dfid in dfData()) {
    const m = model(dfid); if (!m.group) continue;
    const b = nodeBox(dfid), r = g[m.group] || (g[m.group] = { x0: 1e9, y0: 1e9, x1: -1e9, y1: -1e9 });
    r.x0 = Math.min(r.x0, b.x0); r.y0 = Math.min(r.y0, b.y0); r.x1 = Math.max(r.x1, b.x1); r.y1 = Math.max(r.y1, b.y1);
  }
  for (const k in g) { g[k].x0 -= 24; g[k].x1 += 24; g[k].y0 -= 48; g[k].y1 += 24; }
  // Vars L2: the automatic column frame of a state (auto-<state>) is the column when the user kept it
  // S2: a folded column (meta.columns[g].folded) is drawn as its card: that card is the column's rectangle
  const cols = S.meta.columns || {};
  frames().forEach((f) => {
    if (!f.id.startsWith('auto-')) return;
    const k = f.id.slice(5), fold = !!(cols[k] && cols[k].folded);
    g[k] = { x0: f.x, y0: f.y, x1: f.x + (fold ? FOLD_COL.w : f.w), y1: f.y + (fold ? FOLD_COL.h : f.h) };
  });
  return g;
}
// Live robot state / simulated state: the matching automatic column frame `auto-<state>` glows (class live / sim);
// a legacy state node too.
export function drawBands() {
  if (!S.editor) return;
  frameEls.forEach((el, fid) => {
    const g = fid.startsWith('auto-') ? fid.slice(5) : null;
    el.classList.toggle('live', !!g && g === S.liveState);
    el.classList.toggle('sim', !!g && g === S.simState);
  });
  const data = dfData();
  for (const dfid in data) {
    const m = data[dfid].data.model; if (m.kind !== 'state') continue;
    const el = nodeEl(dfid); if (!el) continue;
    el.classList.toggle('live', m.params.state === S.liveState);
    el.classList.toggle('sim', m.params.state === S.simState);
  }
}
