/**
 * Overview (L7, S2): zoom-scaled frame titles, semantic zoom on three levels, jump bar, minimap drawing.
 *
 * Purpose :  semantic cards at low zoom (S2: three levels: normal; below SEM_ZOOM column cards; below DOM_ZOOM domain
 *            cards, see domains/domains.js), the state jump bar (lot S1: two levels, domain chip ▸ its column chips),
 *            column focus (S2: fit-to-target, readable) and the minimap drawing (S2: it scales with the world: domains
 *            then columns then aggregated error / warning dots, resizable and collapsible, its own zoom / pan).
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved out of the former single-file
 *            editor.js (lot M6).
 * Invariant: drawing a minimap frame makes NO layout read: the world (regions, columns, box) is cached on the geometry
 *            version (canvas/geometry.js geoVer), the viewport comes from viewRect() (arithmetic on the transform), the
 *            canvas size from S.miniSize (scenario `minimap2` counts the reads). The minimap view at zoom 1 shows the
 *            whole world anchored at its top-left (as before S2); zoomed in (wheel over the minimap, never the main
 *            canvas), it follows the main view when the main view moves out of it, and stays inside the world.
 * Depends :  core/util.js, core/state.js, core/api.js, canvas/view.js, canvas/geometry.js, minimap/minimap.js,
 *            frames/nesting.js, domains/domains.js (S1)
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks; tests/web/space.py
 *            (scenarios `zoom3`, `minimap2`).
 */
import { $, h, ico } from '../core/util.js';
import { S, nidToDf, stateColor, stateIcon, stateLabel } from '../core/state.js';
import { dfData, model } from '../core/api.js';
import { bandRects, nodeBox } from '../canvas/view.js';
import { geoVer, viewRect } from '../canvas/geometry.js';
import { applyCull } from '../canvas/culling.js';
import { arithPoint, miniDown, miniResizeDown } from './minimap.js';
import { setView } from '../frames/nesting.js';
import {
  domainById, domainCols, domainList, domainOfCol, domainRect, focusDomain, hasDomains, isColFolded, worldBounds
} from '../domains/domains.js';
import { frameById } from '../frames/groups.js';

// ---------- overview helpers (L7 fix round): zoom-scaled frame titles, semantic zoom, jump bar, minimap ----------
// --fts on precanvas = scale of the automatic frame titles so they never get smaller than ~14 px on screen; --zinv =
// 1 / zoom (S2 domain cards keep a constant screen size). Below SEM_ZOOM the container gets `semzoom`: each column
// shows a big card (state, chain count, in/out wires) and the nodes fade; below DOM_ZOOM (S2) it also gets `domzoom`:
// each domain region shows its card (label, icon, colour, column / node counts, badges; click = zoom into it).
// Jump bar chips and the minimap live inside #drawflow but stop their own presses (no pan).
export const SEM_ZOOM = 0.25;
export const DOM_ZOOM = 0.1;
// S2: lowest zoom a column / chain focus uses when the target does not fit: node texts stay readable (was a fixed
// 0.6-0.8 range for columns, 0.3-0.75 for chains; now fit-to-target between READABLE and 1).
export const READABLE = 0.5;
// shared state: S.jumpEl, S.miniEl, S.miniRaf, S.miniSize, S.miniView, S.miniGeoC (core/state.js)
const MINI_KEY = 'nanterino.editor.minimap';
const MINI_SIZE_KEY = 'nanterino.editor.minimap.size';
export const MINI_DEFAULT = { w: 170, h: 110 };         // CSS size before S2 (the canvas was 200 x 130 drawn at 170 x 110)
export const MINI_LIMITS = { w0: 120, h0: 80, w1: 640, h1: 480 };
export const MINI_ZOOM_MAX = 32;
export function zoomVars() {
  if (!S.editor || !S.editor.precanvas) return;
  const z = S.editor.zoom || 1;
  S.editor.precanvas.style.setProperty('--fts', String(Math.max(1, 14 / (13 * z))));
  S.editor.precanvas.style.setProperty('--zinv', String(1 / z));
  S.editor.container.classList.toggle('semzoom', z < SEM_ZOOM);
  S.editor.container.classList.toggle('domzoom', z < DOM_ZOOM && hasDomains());
  applyCull();          // S3: every view change (setView / setRawView / zoom) ends here, the transform is stored
  scheduleMinimap();
}
const stopPress = (el) => ['mousedown', 'touchstart', 'pointerdown', 'wheel', 'dblclick'].forEach((t) => el.addEventListener(t, (e) => e.stopPropagation(), { passive: true }));
// S2: fit-to-target. The whole column when it fits at READABLE or more (never above 1); else its width at READABLE or
// more, the top of the column (its first chains) in view below the jump bar.
function focusColumn(g) {
  const r = bandRects()[g], c = $('#drawflow'); if (!r) return false;
  const w = r.x1 - r.x0, hh = r.y1 - r.y0, top = 50;          // 50: below the jump bar (estimate; clearJumpbar() measures)
  const fit = Math.min(c.clientWidth / (w * 1.05), (c.clientHeight - top) / (hh * 1.05));
  const z = fit >= READABLE ? Math.min(1, fit) : Math.max(READABLE, Math.min(1, c.clientWidth / (w * 1.05)));
  const cx = w * z <= c.clientWidth ? (c.clientWidth - w * z) / 2 - r.x0 * z : 20 - r.x0 * z;
  setView(z, cx, top - r.y0 * z);
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
  // S1: a domain title (.dregion .dtitle) counts only when it is really under the bar (its region is not `auto`);
  // S2: not at the domain zoom level, where the domain card replaces it
  const sel = S.editor.container.classList.contains('domzoom') ? '.frame .ftitle' : '.frame .ftitle, .dregion .dtitle';
  S.editor.precanvas.querySelectorAll(sel).forEach((t) => {
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

// ---------- minimap (S2: scales with the world) ----------
function miniOpen() { try { return localStorage.getItem(MINI_KEY) !== 'closed'; } catch (e) { return true; } }
export function clampMiniSize(v) {
  return { w: Math.round(Math.max(MINI_LIMITS.w0, Math.min(MINI_LIMITS.w1, +v.w || MINI_DEFAULT.w))),
    h: Math.round(Math.max(MINI_LIMITS.h0, Math.min(MINI_LIMITS.h1, +v.h || MINI_DEFAULT.h))) };
}
function storedMiniSize() {
  try { const v = JSON.parse(localStorage.getItem(MINI_SIZE_KEY) || 'null'); if (v && typeof v === 'object') return clampMiniSize(v); } catch (e) { /* default */ }
  return { ...MINI_DEFAULT };
}
// CSS size of the minimap canvas (persisted per browser when `persist`); the intrinsic size follows the device pixels.
export function setMiniSize(v, persist) {
  S.miniSize = clampMiniSize(v);
  const cv = S.miniEl && S.miniEl.querySelector('canvas');
  if (cv) {
    const k = Math.min(2, Math.max(1, (typeof devicePixelRatio === 'number' && devicePixelRatio) || 1));
    cv.style.width = S.miniSize.w + 'px'; cv.style.height = S.miniSize.h + 'px';
    cv.width = Math.round(S.miniSize.w * k); cv.height = Math.round(S.miniSize.h * k);
  }
  if (persist) { try { localStorage.setItem(MINI_SIZE_KEY, JSON.stringify(S.miniSize)); } catch (e) { /* per page */ } }
  drawMinimap();
  return S.miniSize;
}
// Minimap's own zoom (factor `f` around the client point), never the main canvas. Zoom 1 = the whole world.
export function miniZoomAt(clientX, clientY, f) {
  const cv = S.miniEl && S.miniEl.querySelector('canvas'), m = S.miniEl && S.miniEl._map; if (!cv || !m || S.miniDrag) return false;
  const mv = S.miniView, mz = Math.max(1, Math.min(MINI_ZOOM_MAX, mv.mz * f)); if (Math.abs(mz - mv.mz) < 1e-6) return false;
  const cr = cv.getBoundingClientRect(), px = (clientX - cr.x) * cv.width / (cr.width || cv.width), py = (clientY - cr.y) * cv.height / (cr.height || cv.height);
  const p = { x: m.x0 + px / m.s, y: m.y0 + py / m.s }, s = m.s * mz / mv.mz;        // canvas point under the pointer stays there
  S.miniView = mz <= 1 ? { mz: 1, cx: null, cy: null, vc: mv.vc } : { mz, cx: p.x - px / s + cv.width / (2 * s), cy: p.y - py / s + cv.height / (2 * s), vc: mv.vc };
  drawMinimap();
  return true;
}
export function resetMiniZoom() { S.miniView = { mz: 1, cx: null, cy: null, vc: null }; drawMinimap(); }
function buildMinimap() {
  const cv = h('canvas', { width: MINI_DEFAULT.w, height: MINI_DEFAULT.h, 'aria-label': 'Carte du graphe (clic : y aller, molette : zoom de la carte)' });
  const tog = h('button', { type: 'button', class: 'mtog', title: 'Afficher / masquer la carte' });
  const mz = h('button', { type: 'button', class: 'mzreset', hidden: true, title: 'Carte : revenir à tout le graphe', onclick: resetMiniZoom });
  const grip = h('div', { class: 'mresize', title: 'Redimensionner la carte (glisser)', 'aria-label': 'Redimensionner la carte' });
  S.miniEl = h('div', { id: 'minimap' }, h('div', { class: 'mhead' }, mz, tog), h('div', { class: 'mwrap' }, cv, grip));
  stopPress(S.miniEl);
  tog.onclick = () => { const open = !S.miniEl.classList.contains('open'); try { localStorage.setItem(MINI_KEY, open ? 'open' : 'closed'); } catch (e) { /* per page */ } S.miniEl.classList.toggle('open', open); drawMinimap(); };
  // L8: press = centre the view there (or grab the viewport rectangle), drag = continuous pan (see miniDown)
  cv.addEventListener('pointerdown', miniDown);
  grip.addEventListener('pointerdown', miniResizeDown);
  // S2: the wheel over the minimap zooms the MINIMAP view (around the pointer), the main canvas keeps its zoom
  cv.addEventListener('wheel', (e) => { e.preventDefault(); miniZoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.25 : 1 / 1.25); }, { passive: false });
  S.miniEl.classList.toggle('open', miniOpen());
  S.editor.container.append(S.miniEl);
  setMiniSize(S.miniSize || storedMiniSize(), false);
}
export function scheduleMinimap() { if (!S.miniRaf) S.miniRaf = requestAnimationFrame(() => { S.miniRaf = 0; drawMinimap(); }); }
// Map of the minimap: {x0, y0, s} (canvas point -> minimap px = (p - x0) * s). Zoom 1: whole world, top-left anchored.
function miniMapFor(b, W, H, vr) {
  const pad = 30, s0 = Math.min(W / (b.x1 - b.x0 + 2 * pad), H / (b.y1 - b.y0 + 2 * pad)), mv = S.miniView;
  if (!(mv.mz > 1)) return { x0: b.x0 - pad, y0: b.y0 - pad, s: s0 };
  const s = s0 * mv.mz, hw = W / (2 * s), hh = H / (2 * s);
  let cx = mv.cx == null ? (b.x0 + b.x1) / 2 : mv.cx, cy = mv.cy == null ? (b.y0 + b.y1) / 2 : mv.cy;
  if (vr) {      // follow: only when the MAIN view moved, and its centre left the minimap view
    const vx = (vr.x0 + vr.x1) / 2, vy = (vr.y0 + vr.y1) / 2, last = mv.vc;
    if (last && (Math.abs(last.x - vx) > 0.5 || Math.abs(last.y - vy) > 0.5) && (vx < cx - hw || vx > cx + hw || vy < cy - hh || vy > cy + hh)) { cx = vx; cy = vy; }
    mv.vc = { x: vx, y: vy };
  }
  const lim = (v, lo, hi) => (lo > hi ? (lo + hi) / 2 : Math.max(lo, Math.min(hi, v)));   // stay inside the world
  cx = lim(cx, b.x0 - pad + hw, b.x1 + pad - hw); cy = lim(cy, b.y0 - pad + hh, b.y1 + pad - hh);
  mv.cx = cx; mv.cy = cy;
  return { x0: cx - hw, y0: cy - hh, s };
}
export function drawMinimap() {
  if (!S.editor || !S.editor.container) return;
  if (!S.miniEl || !S.miniEl.isConnected) buildMinimap();
  S.miniEl.querySelector('.mtog').textContent = S.miniEl.classList.contains('open') ? '▾ Carte' : '▸ Carte';
  const zb = S.miniEl.querySelector('.mzreset');
  zb.hidden = !(S.miniView.mz > 1); zb.textContent = '×' + (Math.round(S.miniView.mz * 10) / 10) + ' ⤢';
  if (!S.miniEl.classList.contains('open')) return;
  const cv = S.miniEl.querySelector('canvas'), ctx2 = cv.getContext('2d'), W = cv.width, H = cv.height;
  const geo = (S.miniDrag && S.miniDrag.geo) || miniGeo(), b = geo.b;   // L8: frozen while dragging
  if (!b) return;
  // viewport in canvas coordinates: arithmetic (S2: no rect read per frame); while dragging from the press snapshot
  let a, c;
  if (S.miniDrag) { a = arithPoint(S.miniDrag, S.miniDrag.st.x, S.miniDrag.st.y); c = arithPoint(S.miniDrag, S.miniDrag.st.right, S.miniDrag.st.bottom); }
  else { const v = viewRect(); a = { x: v.x0, y: v.y0 }; c = { x: v.x1, y: v.y1 }; }
  const map = S.miniDrag ? S.miniDrag.map : miniMapFor(b, W, H, { x0: a.x, y0: a.y, x1: c.x, y1: c.y });
  const { x0, y0, s } = map, X = (x) => (x - x0) * s, Y = (y) => (y - y0) * s;
  S.miniEl._map = { x0, y0, s };
  ctx2.clearRect(0, 0, W, H);
  ctx2.fillStyle = '#0d1117cc'; ctx2.fillRect(0, 0, W, H);
  // 1. domain regions (empty ones dashed), label when there is room
  const k = W / (S.miniSize ? S.miniSize.w : W);
  geo.doms.forEach((r) => {
    const rx = X(r.x), ry = Y(r.y), rw = r.w * s, rh = r.h * s;
    ctx2.fillStyle = r.color + (r.folded ? '55' : '1f'); ctx2.fillRect(rx, ry, rw, rh);
    ctx2.setLineDash(r.cols ? [] : [4 * k, 3 * k]); ctx2.lineWidth = 1.2 * k; ctx2.strokeStyle = r.color; ctx2.strokeRect(rx, ry, rw, rh);
    ctx2.setLineDash([]);
    if (rw > 46 * k && rh > 14 * k) { ctx2.fillStyle = r.color; ctx2.font = Math.round(9 * k) + 'px sans-serif'; ctx2.fillText(r.label, rx + 3 * k, ry + 10 * k, rw - 6 * k); }
  });
  // 2. columns
  geo.rects.forEach(([g, r]) => { ctx2.fillStyle = stateColor(g) + '88'; ctx2.fillRect(X(r.x0), Y(r.y0), (r.x1 - r.x0) * s, (r.y1 - r.y0) * s); });
  // viewport frame first: the diagnostic dots are drawn on top of it
  S.miniEl._view = { x0: a.x, y0: a.y, x1: c.x, y1: c.y };   // viewport in canvas coordinates (grab test, checks)
  ctx2.strokeStyle = '#ffffff'; ctx2.lineWidth = 1.5 * k;
  ctx2.strokeRect(X(a.x), Y(a.y), (c.x - a.x) * s, (c.y - a.y) * s);
  // 3. L6 diagnostics, S2 aggregated: the problem nodes falling in the same minimap cell (per level) make ONE dot (size
  // and count grow); amber warnings first, red errors on top. miniEl._dots keeps one entry per node at its dot's
  // position (tests), miniEl._agg the drawn dots; data-err / data-warn hold the node counts.
  const cl = (v, max) => Math.max(4 * k, Math.min(max - 4 * k, v)), cell = 9 * k, buckets = new Map(), dots = [];
  geo.marks.forEach((g) => {
    const x = cl(X(g.cx), W), y = cl(Y(g.cy), H), key = g.level + ':' + Math.floor(x / cell) + ':' + Math.floor(y / cell);
    const bk = buckets.get(key) || { level: g.level, sx: 0, sy: 0, n: 0, nids: [] };
    bk.sx += x; bk.sy += y; bk.n++; bk.nids.push(g.nid); buckets.set(key, bk);
  });
  const agg = [...buckets.values()].map((bk) => ({ level: bk.level, x: bk.sx / bk.n, y: bk.sy / bk.n, n: bk.n, nids: bk.nids }));
  ['warn', 'err'].forEach((lvl) => agg.filter((d) => d.level === lvl).forEach((d) => {
    const rad = (d.n > 1 ? Math.min(8, 3.5 + Math.log2(d.n) * 1.5) : 3.5) * k;
    ctx2.beginPath(); ctx2.arc(d.x, d.y, rad, 0, Math.PI * 2);
    ctx2.fillStyle = lvl === 'err' ? '#ff3b30' : '#ffb020'; ctx2.fill();
    ctx2.lineWidth = 1 * k; ctx2.strokeStyle = '#0d1117'; ctx2.stroke();
    // the count sits right of the dot (outlined), so the dot's centre keeps its pure colour (pixel checks, readability)
    if (d.n > 1) {
      const tx = d.x + rad + 1 * k, ty = d.y + 3 * k;
      ctx2.font = 'bold ' + Math.round(8 * k) + 'px sans-serif'; ctx2.lineWidth = 2.5 * k; ctx2.strokeStyle = '#0d1117';
      ctx2.strokeText(String(d.n), tx, ty); ctx2.fillStyle = '#ffffff'; ctx2.fillText(String(d.n), tx, ty);
    }
    d.nids.forEach((nid) => dots.push({ nid, level: lvl, x: d.x, y: d.y }));
  }));
  S.miniEl._dots = dots; S.miniEl._agg = agg; S.miniEl._doms = geo.doms.map((r) => r.id);
  S.miniEl.dataset.err = String(dots.filter((d) => d.level === 'err').length);
  S.miniEl.dataset.warn = String(dots.filter((d) => d.level === 'warn').length);
}
// Where a problem node shows on the minimap: its own centre, or the centre of the card that folds it (S2).
function markCentre(df, bands) {
  const m = model(df), g = m && m.group;
  if (g && hasDomains()) {
    const d = domainById(domainOfCol(g)), f = frameById('auto-' + g);
    if (d && d.folded && f) { const r = domainRect(d); if (r) return [r.x + r.w / 2, r.y + r.h / 2]; }
    if (f && isColFolded(g)) { const r = bands[g]; if (r) return [(r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2]; }
  }
  const nb = nodeBox(df);
  return [(nb.x0 + nb.x1) / 2, (nb.y0 + nb.y1) / 2];
}
// Geometry the minimap draws: domain regions, column rects, world box (cached on the geometry version: no work and no
// layout read while only the view moves), problem nodes (centre + level, recomputed: badges change on their own).
export function miniGeo() {
  const ver = geoVer();
  if (!S.miniGeoC || S.miniGeoC.ver !== ver) {
    const doms = hasDomains() ? domainList().map((d) => { const r = domainRect(d); return r ? { id: d.id, label: d.label, color: d.color || '#888888', folded: !!d.folded, cols: domainCols(d.id).length, ...r } : null; }).filter(Boolean) : [];
    const hidden = (g) => hasDomains() && !!(domainById(domainOfCol(g)) || {}).folded;
    S.miniGeoC = { ver, doms, rects: Object.entries(bandRects()).filter(([g]) => !hidden(g)), b: worldBounds() };
  }
  const marks = [], bands = S.miniGeoC.bands || (S.miniGeoC.bands = Object.fromEntries(S.miniGeoC.rects));
  S.issues.forEach((list, nid) => {
    const df = nidToDf.get(nid); if (df == null || !dfData()[df]) return;
    const lvl = list.some((i) => i.level === 'err') ? 'err' : list.some((i) => i.level === 'warn') ? 'warn' : null;
    if (!lvl) return;
    const [cx, cy] = markCentre(df, bands);
    marks.push({ nid, level: lvl, cx, cy });
  });
  return { doms: S.miniGeoC.doms, rects: S.miniGeoC.rects, b: S.miniGeoC.b, marks };
}
