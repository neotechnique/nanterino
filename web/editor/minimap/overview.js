/**
 * Overview (L7): zoom-scaled frame titles, semantic zoom, jump bar.
 *
 * Purpose :  semantic cards at low zoom, the state jump bar (lot S1: two levels, domain chip ▸ its column chips) and the
 *            minimap drawing.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, core/api.js, canvas/nodes.js, canvas/view.js, minimap/minimap.js,
 *            frames/nesting.js, canvas/navigation.js, domains/domains.js (S1)
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, h, ico } from '../core/util.js';
import { S, nidToDf, stateColor, stateIcon, stateLabel } from '../core/state.js';
import { dfData } from '../core/api.js';
import { nodeEl } from '../canvas/nodes.js';
import { bandRects, nodeBox } from '../canvas/view.js';
import { arithPoint, miniDown } from './minimap.js';
import { bbox, canvasPoint, setView } from '../frames/nesting.js';
import { zoomCentre } from '../canvas/navigation.js';
import { domainList, domainOfCol, focusDomain, hasDomains } from '../domains/domains.js';

// ---------- overview helpers (L7 fix round): zoom-scaled frame titles, semantic zoom, jump bar, minimap ----------
// --fts on precanvas = scale of the automatic frame titles so they never get smaller than ~14 px on screen;
// below SEM_ZOOM the container gets `semzoom`: each column shows a big card (state, chain count, in/out wires)
// and the nodes fade. Jump bar chips and the minimap live inside #drawflow but stop their own presses (no pan).
const SEM_ZOOM = 0.25;
// shared state: S.jumpEl, S.miniEl, S.miniRaf (core/state.js)
const MINI_KEY = 'nanterino.editor.minimap';
export function zoomVars() {
  if (!S.editor || !S.editor.precanvas) return;
  const z = S.editor.zoom || 1;
  S.editor.precanvas.style.setProperty('--fts', String(Math.max(1, 14 / (13 * z))));
  S.editor.container.classList.toggle('semzoom', z < SEM_ZOOM);
  scheduleMinimap();
}
const stopPress = (el) => ['mousedown', 'touchstart', 'pointerdown', 'wheel', 'dblclick'].forEach((t) => el.addEventListener(t, (e) => e.stopPropagation(), { passive: true }));
// Fit one state column (its band rect) at a readable zoom 0.6-0.8, top of the column (hub) in view.
function focusColumn(g) {
  const r = bandRects()[g], c = $('#drawflow'); if (!r) return false;
  const w = r.x1 - r.x0, hh = r.y1 - r.y0;
  const z = Math.max(0.6, Math.min(0.8, c.clientWidth / (w * 1.05), c.clientHeight / (hh * 1.05)));
  const cx = w * z <= c.clientWidth ? (c.clientWidth - w * z) / 2 - r.x0 * z : 20 - r.x0 * z;
  setView(z, cx, 50 - r.y0 * z);          // 50: below the jump bar (estimate; clearJumpbar() measures)
  clearJumpbar();
  return true;
}
// L6: an automatic column title (or any frame title) must never sit under the floating jump bar. The bar's height
// depends on fonts / chips, and the titles scale with --fts, so both are measured on screen, never hardcoded: every
// column title of a frame that shows on screen (or any title touching the bar) and starts above the bar's bottom is
// pushed below the bar by panning down. Frames entirely above or below the screen (other rows) never count.
// Returns the pan applied in screen px (0 when nothing overlapped).
export const JUMP_GAP = 6;
export function jumpbarBottom() {
  if (!S.editor || !S.jumpEl || !S.jumpEl.isConnected) return null;
  const jb = S.jumpEl.getBoundingClientRect();
  return jb.height ? jb.bottom : null;
}
export function clearJumpbar() {
  const bottom = jumpbarBottom(); if (bottom == null) return 0;
  const c = S.editor.container.getBoundingClientRect(), jb = S.jumpEl.getBoundingClientRect();
  let top = Infinity;
  // S1: a domain title (.dregion .dtitle) counts only when it is really under the bar (its region is not `auto`)
  S.editor.precanvas.querySelectorAll('.frame .ftitle, .dregion .dtitle').forEach((t) => {
    const r = t.getBoundingClientRect();
    if (!r.width || r.right <= c.left || r.left >= c.right || r.top >= bottom + JUMP_GAP) return;   // sideways / already clear
    const fr = t.parentElement.getBoundingClientRect();
    // a shown column whose title sits just above the screen edge counts; one scrolled far up (taller column of the row
    // above) does not, or panning to it would push the wanted column off screen
    const autoShown = t.parentElement.classList.contains('auto') && fr.bottom > bottom && fr.top < c.bottom && r.bottom > c.top - 2 * r.height;
    const underBar = r.bottom > jb.top && r.right > jb.left && r.left < jb.right;
    if (autoShown || underBar) top = Math.min(top, r.top);
  });
  const dy = top === Infinity ? 0 : bottom + JUMP_GAP - top;
  if (dy <= 0) return 0;
  S.editor.canvas_y += dy;
  S.editor.precanvas.style.transform = `translate(${S.editor.canvas_x}px, ${S.editor.canvas_y}px) scale(${S.editor.zoom})`;
  scheduleMinimap();
  return dy;
}
export function drawJumpbar() {
  if (!S.editor) return;
  if (!S.jumpEl || !S.jumpEl.isConnected) { S.jumpEl = h('div', { id: 'jumpbar', role: 'toolbar', 'aria-label': 'Aller à un état' }); stopPress(S.jumpEl); S.editor.container.append(S.jumpEl); }
  S.jumpEl.innerHTML = '';
  const groups = new Set(Object.values(dfData()).map((d) => d.data.model.group).filter(Boolean));
  const colChip = (g, lvl) => (g === 'global'
    ? h('button', { type: 'button', class: 'jchip', 'data-g': 'global', 'aria-level': lvl, title: 'Aller aux règles globales', style: '--c:#e0504d', onclick: () => focusColumn('global') }, ico('git-branch', '#e0504d'), 'Globales')
    : h('button', { type: 'button', class: 'jchip', 'data-g': g, 'aria-level': lvl, title: 'Aller à la colonne « ' + stateLabel(g) + ' »', style: '--c:' + stateColor(g),
      onclick: () => focusColumn(g) }, ico(stateIcon(g), stateColor(g)), stateLabel(g)));
  const order = (S.meta.states || []).map((s) => s.id).concat(['global']).filter((g) => groups.has(g));
  if (hasDomains()) {
    // lot S1: two levels, in reading order: a domain chip, then the chips of its columns (state order, globals last);
    // an empty domain keeps its chip (it shows where future content goes)
    domainList().forEach((d) => {
      S.jumpEl.append(h('button', { type: 'button', class: 'jdom' + (d.folded ? ' folded' : ''), 'data-d': d.id, 'aria-level': '1',
        title: 'Aller au domaine « ' + d.label + ' »' + (d.folded ? ' (replié)' : ''), style: '--c:' + d.color, onclick: () => focusDomain(d.id) },
      ico(d.icon || 'square', '#10141a'), d.label + ' ▸'));   // dark icon on the coloured chip
      order.filter((g) => domainOfCol(g) === d.id).forEach((g) => S.jumpEl.append(colChip(g, '2')));
    });
    return;
  }
  order.forEach((g) => S.jumpEl.append(colChip(g, '1')));
}
function miniOpen() { try { return localStorage.getItem(MINI_KEY) !== 'closed'; } catch (e) { return true; } }
export function scheduleMinimap() { if (!S.miniRaf) S.miniRaf = requestAnimationFrame(() => { S.miniRaf = 0; drawMinimap(); }); }
export function drawMinimap() {
  if (!S.editor || !S.editor.container) return;
  if (!S.miniEl || !S.miniEl.isConnected) {
    const cv = h('canvas', { width: 200, height: 130, 'aria-label': 'Carte du graphe (clic : y aller)' });
    const tog = h('button', { type: 'button', class: 'mtog', title: 'Afficher / masquer la carte' });
    S.miniEl = h('div', { id: 'minimap' }, tog, cv);
    stopPress(S.miniEl);
    tog.onclick = () => { const open = !S.miniEl.classList.contains('open'); try { localStorage.setItem(MINI_KEY, open ? 'open' : 'closed'); } catch (e) { /* per page */ } S.miniEl.classList.toggle('open', open); drawMinimap(); };
    // L8: press = centre the view there (or grab the viewport rectangle), drag = continuous pan (see miniDown)
    cv.addEventListener('pointerdown', miniDown);
    cv.addEventListener('wheel', (e) => { e.preventDefault(); zoomCentre(e.deltaY < 0 ? 1.15 : 1 / 1.15); }, { passive: false });
    S.miniEl.classList.toggle('open', miniOpen());
    S.editor.container.append(S.miniEl);
  }
  S.miniEl.querySelector('.mtog').textContent = S.miniEl.classList.contains('open') ? '▾ Carte' : '▸ Carte';
  if (!S.miniEl.classList.contains('open')) return;
  const cv = S.miniEl.querySelector('canvas'), ctx2 = cv.getContext('2d');
  const geo = (S.miniDrag && S.miniDrag.geo) || miniGeo(), rects = geo.rects, b = geo.b;   // L8: frozen while dragging
  if (!b) return;
  const pad = 30, x0 = b.x0 - pad, y0 = b.y0 - pad, s = Math.min(cv.width / (b.x1 - b.x0 + 2 * pad), cv.height / (b.y1 - b.y0 + 2 * pad));
  S.miniEl._map = { x0, y0, s };
  ctx2.clearRect(0, 0, cv.width, cv.height);
  ctx2.fillStyle = '#0d1117cc'; ctx2.fillRect(0, 0, cv.width, cv.height);
  rects.forEach(([g, r]) => { ctx2.fillStyle = stateColor(g) + '88'; ctx2.fillRect((r.x0 - x0) * s, (r.y0 - y0) * s, (r.x1 - r.x0) * s, (r.y1 - r.y0) * s); });
  // viewport frame first: the diagnostic dots are drawn on top of it
  let a, c;
  if (S.miniDrag) { a = arithPoint(S.miniDrag, S.miniDrag.st.x, S.miniDrag.st.y); c = arithPoint(S.miniDrag, S.miniDrag.st.right, S.miniDrag.st.bottom); }
  else { const st = S.editor.container.getBoundingClientRect(); a = canvasPoint(st.x, st.y); c = canvasPoint(st.right, st.bottom); }
  S.miniEl._view = { x0: a.x, y0: a.y, x1: c.x, y1: c.y };   // viewport in canvas coordinates (grab test, checks)
  ctx2.strokeStyle = '#ffffff'; ctx2.lineWidth = 1.5;
  ctx2.strokeRect((a.x - x0) * s, (a.y - y0) * s, (c.x - a.x) * s, (c.y - a.y) * s);
  // L6: one dot per node with a problem (same levels as the node badges): amber warnings first, red errors on top.
  // miniEl._dots keeps their canvas positions (tests, debugging); data-err / data-warn hold the counts.
  const dots = [];
  const cl = (v, max) => Math.max(4, Math.min(max - 4, v));   // a node on the graph's edge keeps a whole dot
  geo.marks.forEach((g) => dots.push({ nid: g.nid, level: g.level, x: cl((g.cx - x0) * s, cv.width), y: cl((g.cy - y0) * s, cv.height) }));
  ['warn', 'err'].forEach((lvl) => dots.filter((d) => d.level === lvl).forEach((d) => {
    ctx2.beginPath(); ctx2.arc(d.x, d.y, 3.5, 0, Math.PI * 2);
    ctx2.fillStyle = lvl === 'err' ? '#ff3b30' : '#ffb020'; ctx2.fill();
    ctx2.lineWidth = 1; ctx2.strokeStyle = '#0d1117'; ctx2.stroke();
  }));
  S.miniEl._dots = dots;
  S.miniEl.dataset.err = String(dots.filter((d) => d.level === 'err').length);
  S.miniEl.dataset.warn = String(dots.filter((d) => d.level === 'warn').length);
}
// Geometry the minimap draws: column rects, graph box, problem nodes (centre + level). Cached for a whole drag.
export function miniGeo() {
  const marks = [];
  S.issues.forEach((list, nid) => {
    const df = nidToDf.get(nid); if (df == null || !nodeEl(df)) return;
    const lvl = list.some((i) => i.level === 'err') ? 'err' : list.some((i) => i.level === 'warn') ? 'warn' : null;
    if (!lvl) return;
    const nb = nodeBox(df);
    marks.push({ nid, level: lvl, cx: (nb.x0 + nb.x1) / 2, cy: (nb.y0 + nb.y1) / 2 });
  });
  return { rects: Object.entries(bandRects()), b: bbox(), marks };
}
