/**
 * Domains (lot S1, S2): the navigable level ABOVE the state columns (one graph for the whole robot).
 *
 * Purpose :  domain table / column -> domain map access (meta.domains, meta.columns), region rectangles (mirror of the
 *            server's graph_layout.region_rect / region_boxes), the #domains layer (one region per domain: title bar
 *            with icon, counts and fold button; an empty domain stays visible with its explanatory post-it; S2: a
 *            domain card shown below DOM_ZOOM, click = zoom into the domain), folding a domain or a column into a card
 *            (node count + error / warning badges; the folded content and the wires that touch it are HIDDEN, never
 *            redrawn to the card edge), moving a column to another domain (geometry follows), focusing a domain, the
 *            world box used by "Ajuster" and the minimap (worldBounds).
 *            S2: folding RECLAIMS space: a folded column pulls the columns right of it (same row of its domain) left by
 *            the width it gave up, and every fold / unfold repacks the regions on their grid (packRegions: rows kept,
 *            REGION_GAP between regions, top-left anchored), so unfolding restores the packed layout exactly.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Organisation only: meta.domains and
 *            meta.columns ride on the document (serialize copies meta), the server stores them in graph.layout.json and
 *            never compiles them (the robot's behaviour cannot change).
 * Depends :  core/util.js, core/state.js, core/api.js, canvas/nodes.js, canvas/view.js, canvas/wires.js,
 *            canvas/navigation.js, canvas/geometry.js, core/history.js, core/ui.js, frames/groups.js, frames/nesting.js,
 *            frames/notes.js, clipboard/clipboard.js, hierarchy/tree.js, minimap/overview.js
 * Invariant: a region is the bounding box of its column frames (auto-<group>, a folded column counts as its FOLD_COL
 *            card) and of its explanatory post-it (`auto: "domain:<id>"`, S2: it sits right of the columns, never under
 *            a column title) grown by REGION (same numbers as the server), or the stored x/y/w/h of the domain when it
 *            holds no column; a folded domain's region is its FOLD_DOM card at the region's top-left. Regions never
 *            overlap after an edit of this module. What a region / a fold owns is decided by DATA where data exists
 *            (column = node `group`, frames / post-its = `parent` links), by geometry only for loose top-level items, so
 *            hidden content that a repack slid under a neighbour is never captured by it. A fold or a move is one
 *            commitSoon() (save-gated like every edit, undo / redo through the document snapshot); a document without
 *            `domains` (hub / go-to forms, very old undo entries) draws exactly as before S1.
 * Test    :  tests/web/domains.py (scenario `domains`), tests/web/space.py (scenarios `zoom3`, `minimap2`, `foldpack`)
 *            through the window.__editor hooks; server side tests/test_graph_domains.py, tests/test_graph_repack.py.
 */
import { h, ico } from '../core/util.js';
import { S } from '../core/state.js';
import { updateWires } from '../canvas/culling.js';
import { dfData, dfNode, model } from '../core/api.js';
import { nodeEl } from '../canvas/nodes.js';
import { nodeBox } from '../canvas/view.js';
import { paintWires } from '../canvas/wires.js';
import { editBlocked } from '../canvas/navigation.js';
import { FOLD_COL, FOLD_DOM, bumpGeo } from '../canvas/geometry.js';
import { commitSoon } from '../core/history.js';
import { toast } from '../core/ui.js';
import { frameById, frameEls, frames } from '../frames/groups.js';
import { bbox, descendantFrames, drawFrames, focusRect } from '../frames/nesting.js';
import { drawNotes, noteEls, noteHeight, notes } from '../frames/notes.js';
import { frameMembers } from '../clipboard/clipboard.js';
import { scheduleTree } from '../hierarchy/tree.js';
import { DOM_ZOOM, clearJumpbar, drawJumpbar } from '../minimap/overview.js';

// Same numbers as nanterino/graph_layout.py (DOM_PAD, DOM_HEAD, COL_GAP, DOM_GAP, FOLD_*): a region drawn by the
// editor and one drawn by the server around the same frames are the same rectangle.
export const REGION = { pad: 60, head: 240 };
const COL_GAP = 150;
export const REGION_GAP = 260;                   // graph_layout.DOM_GAP: free space between two regions
const ROW_TOL = REGION_GAP;                      // packRegions: same row when the tops differ by less (see packPositions)
const defaultDomain = (g) => (g === 'global' ? 'systeme' : 'dialogue');

export const domains = () => (Array.isArray(S.meta.domains) ? S.meta.domains : []);
export const hasDomains = () => domains().length > 0;
export const domainById = (id) => domains().find((d) => d.id === id) || null;
// Domains in display order (`order`, then list order): jump bar, hierarchy, layer.
export const domainList = () => domains().map((d, i) => [d, i]).sort((a, b) => (a[0].order - b[0].order) || (a[1] - b[1])).map((x) => x[0]);
const colMap = () => (S.meta.columns && typeof S.meta.columns === 'object' ? S.meta.columns : (S.meta.columns = {}));
export const colGroup = (f) => (f && f.auto && String(f.id).startsWith('auto-') ? String(f.id).slice(5) : null);
export function domainOfCol(g) {
  const e = (S.meta.columns || {})[g], id = e && e.domain;
  return id && domainById(id) ? id : defaultDomain(g);
}
export const domainCols = (id) => frames().filter((f) => colGroup(f) && domainOfCol(colGroup(f)) === id);
export const isColFolded = (g) => !!((S.meta.columns || {})[g] || {}).folded;
export const isDomFolded = (id) => !!(domainById(id) || {}).folded;
// S2: the explanatory post-it of a domain (server domain_notes), top level only.
export const domainNote = (d) => notes().find((n) => n.auto === 'domain:' + d.id && !n.parent) || null;
// Drawn box of a column frame: its FOLD_COL card when folded (unless `full`).
export function colBox(f, full) {
  const fold = !full && isColFolded(colGroup(f));
  return { x0: f.x, y0: f.y, x1: f.x + (fold ? FOLD_COL.w : f.w), y1: f.y + (fold ? FOLD_COL.h : f.h) };
}
// Region rectangle {x, y, w, h} of a domain: its column boxes (+ its post-it) grown by REGION, else its stored
// rectangle; folded = the FOLD_DOM card at the same top-left. `full`: as if nothing were folded (what the region owns).
export function domainRect(d, full) {
  const cols = domainCols(d.id);
  let r = null;
  if (cols.length) {
    const boxes = cols.map((f) => colBox(f, full)), n = domainNote(d);
    if (n) boxes.push({ x0: n.x, y0: n.y, x1: n.x + n.w, y1: n.y + noteHeight(n) });
    const x0 = Math.min(...boxes.map((b) => b.x0)) - REGION.pad, y0 = Math.min(...boxes.map((b) => b.y0)) - REGION.head;
    const x1 = Math.max(...boxes.map((b) => b.x1)) + REGION.pad, y1 = Math.max(...boxes.map((b) => b.y1)) + REGION.pad;
    r = { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  } else if ([d.x, d.y, d.w, d.h].every((v) => typeof v === 'number' && isFinite(v)) && d.w > 0 && d.h > 0) r = { x: d.x, y: d.y, w: d.w, h: d.h };
  if (r && d.folded && !full) r = { x: r.x, y: r.y, w: FOLD_DOM.w, h: FOLD_DOM.h };
  return r;
}
// Domain whose region contains a canvas point (hierarchy: top-level groups, post-its and chains), else null.
export function domainAt(x, y) {
  return domainList().find((d) => { const r = domainRect(d); return r && x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h; }) || null;
}
// "Ajuster": the node box grown to every region (an empty region is part of the world the user should see).
export function worldBox(b) {
  let out = b ? { ...b } : null;
  const grow = (x0, y0, x1, y1) => { out = out ? { x0: Math.min(out.x0, x0), y0: Math.min(out.y0, y0), x1: Math.max(out.x1, x1), y1: Math.max(out.y1, y1) } : { x0, y0, x1, y1 }; };
  domains().forEach((d) => { const r = domainRect(d); if (r) grow(r.x, r.y, r.x + r.w, r.y + r.h); });
  return out;
}
// S2: the whole world (Ajuster, minimap, minimum zoom): nodes + frames (drawn size) + domain regions (empty ones too).
export function worldBounds() {
  let out = worldBox(bbox());
  frames().forEach((f) => {
    const b = colGroup(f) ? colBox(f) : { x0: f.x, y0: f.y, x1: f.x + f.w, y1: f.y + f.h };
    out = out ? { x0: Math.min(out.x0, b.x0), y0: Math.min(out.y0, b.y0), x1: Math.max(out.x1, b.x1), y1: Math.max(out.y1, b.y1) } : b;
  });
  return out;
}

// ---------- ownership (S2: data first) ----------
const centreIn = (b, r) => { const cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2; return cx >= r.x && cx <= r.x + r.w && cy >= r.y && cy <= r.y + r.h; };
// Group of a node whose column frame exists (it belongs to that column whatever its position), else null (loose).
function nodeCol(df) { const m = model(df), g = m && m.group; return g && frameById('auto-' + g) ? g : null; }
// Everything a domain owns, measured BEFORE an edit moves anything: its columns (frame, sub-groups, post-its, the nodes
// of their groups), its post-it, plus the loose top-level groups / post-its / nodes inside its FULL region rectangle.
// `claimed` (Set of objects / dfids) makes a shared item go to the first domain that claims it (domain order).
function domainContent(d, claimed) {
  const out = { frames: new Set(), notes: new Set(), dfids: new Set() };
  const take = (set, it) => { if (!claimed.has(it)) { claimed.add(it); set.add(it); } };
  const groups = new Set();
  domainCols(d.id).forEach((f) => {
    groups.add(colGroup(f));
    const sub = [f].concat(descendantFrames(f)), ids = new Set(sub.map((g) => g.id));
    sub.forEach((g) => take(out.frames, g));
    notes().forEach((n) => { if (n.parent && ids.has(n.parent)) take(out.notes, n); });
  });
  Object.keys(dfData()).forEach((df) => { const g = nodeCol(df); if (g && groups.has(g)) take(out.dfids, String(df)); });
  const dn = domainNote(d); if (dn) take(out.notes, dn);
  const r = domainRect(d, true); if (!r) return out;
  frames().forEach((f) => {
    if (f.auto || f.parent || claimed.has(f) || !centreIn({ x0: f.x, y0: f.y, x1: f.x + f.w, y1: f.y + f.h }, r)) return;
    const mb = frameMembers(f);
    mb.frames.forEach((g) => take(out.frames, g)); mb.notes.forEach((n) => take(out.notes, n));
  });
  notes().forEach((n) => { if (!n.parent && !claimed.has(n) && centreIn({ x0: n.x, y0: n.y, x1: n.x + n.w, y1: n.y + noteHeight(n) }, r)) take(out.notes, n); });
  Object.keys(dfData()).forEach((df) => { if (!nodeCol(df) && centreIn(nodeBox(df), r)) take(out.dfids, String(df)); });
  return out;
}
// {domain id: content} of every domain, in domain order (no item twice).
function allContent() {
  const claimed = new Set(), out = {};
  domainList().forEach((d) => { out[d.id] = domainContent(d, claimed); });
  return out;
}

// ---------- fold ----------
// What a fold hides: {nodes: Set(dfid), frames: Set(id), notes: Set(id), byCol: {group: Set(dfid)}, byDom: {id: Set(dfid)}}.
// A folded column hides its sub-groups, its post-its and the nodes of its group (S2: by data, see the invariant); a
// folded domain hides its columns too, plus the top-level groups / post-its / loose nodes inside its full region.
export function foldSets() {
  const out = { nodes: new Set(), frames: new Set(), notes: new Set(), byCol: {}, byDom: {} };
  if (!hasDomains() || !S.editor) return out;
  const data = dfData(), byGroup = {};
  for (const df in data) { const g = nodeCol(df); if (g) (byGroup[g] || (byGroup[g] = new Set())).add(df); }
  const hideFrame = (f, withSelf) => {
    const sub = descendantFrames(f), ids = new Set([f.id].concat(sub.map((g) => g.id)));
    if (withSelf) out.frames.add(f.id);
    sub.forEach((g) => out.frames.add(g.id));
    notes().forEach((n) => { if (n.parent && ids.has(n.parent)) out.notes.add(n.id); });
  };
  domainList().forEach((d) => {
    const dfold = !!d.folded, all = new Set();
    domainCols(d.id).forEach((f) => {
      const g = colGroup(f);
      if (!dfold && !isColFolded(g)) return;
      hideFrame(f, dfold);
      const mine = byGroup[g] || new Set();
      mine.forEach((x) => { out.nodes.add(x); all.add(x); });
      out.byCol[g] = mine;
    });
    if (dfold) {
      const r = domainRect(d, true);
      if (r) {
        frames().forEach((f) => {
          if (f.auto || f.parent || !centreIn({ x0: f.x, y0: f.y, x1: f.x + f.w, y1: f.y + f.h }, r)) return;
          hideFrame(f, true);
          for (const df in data) if (!nodeCol(df) && centreIn(nodeBox(df), f)) { out.nodes.add(df); all.add(df); }
        });
        notes().forEach((n) => { if (!n.parent && centreIn({ x0: n.x, y0: n.y, x1: n.x + n.w, y1: n.y + noteHeight(n) }, r)) out.notes.add(n.id); });
        for (const df in data) if (!nodeCol(df) && centreIn(nodeBox(df), r)) { all.add(df); out.nodes.add(df); }
      }
      out.byDom[d.id] = all;
    }
  });
  return out;
}
function shiftContent(c, dx, dy) {
  if (!dx && !dy) return;
  c.frames.forEach((x) => { x.x += dx; x.y += dy; });
  c.notes.forEach((n) => { n.x += dx; n.y += dy; });
  c.dfids.forEach((df) => {
    const nd = dfNode(df), el = nodeEl(df); if (!nd) return;
    nd.pos_x += dx; nd.pos_y += dy;
    if (el) { el.style.left = nd.pos_x + 'px'; el.style.top = nd.pos_y + 'px'; }
  });
  updateWires(c.dfids);          // S3: one pass (and the culled ends shown meanwhile)
}
const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
// Regions never overlap after an edit of the editor: every region that overlaps the pusher (domain `id`, grown by a
// moved column) is moved right of it with its whole content, then pushes in turn (cascade, bounded). `content`:
// {domain id: content measured before the edit} (else measured now).
function separate(id, content) {
  const todo = [id], cont = content || allContent();
  let guard = 0;
  while (todo.length && guard++ < 60) {
    const p = domainById(todo.shift()), pr = p && domainRect(p); if (!pr) continue;
    domainList().forEach((o) => {
      if (o.id === p.id) return;
      const or = domainRect(o); if (!or || !overlap(pr, or)) return;
      const dx = Math.round(pr.x + pr.w + REGION_GAP - or.x);
      shiftContent(cont[o.id], dx, 0);
      if (!domainCols(o.id).length) o.x = Math.round(or.x + dx);     // an empty region moves by its stored rectangle
      todo.push(o.id);
    });
  }
}
// S2: grid positions of region rectangles [{id, x, y, w, h, i}] -> Map(id -> {x, y}). Mirror of
// graph_layout.pack_positions: sorted by top then left (then domain order i), a region starts a new row when its top is
// ROW_TOL or more below the row's first top; rows are stacked from the top-left corner of all regions with REGION_GAP
// between rows (row height = its tallest region) and between the regions of a row. A packed layout (the server's
// default grid) packs to itself, so a fold followed by an unfold puts everything back.
export function packPositions(items) {
  const out = new Map(); if (!items.length) return out;
  const X0 = Math.min(...items.map((r) => r.x)), Y0 = Math.min(...items.map((r) => r.y));
  const rows = [];
  items.slice().sort((a, b) => (a.y - b.y) || (a.x - b.x) || (a.i - b.i)).forEach((r) => {
    const cur = rows[rows.length - 1];
    if (cur && r.y - cur.top < ROW_TOL) cur.items.push(r); else rows.push({ top: r.y, items: [r] });
  });
  let y = Y0;
  rows.forEach((row) => {
    let x = X0;
    row.items.sort((a, b) => (a.x - b.x) || (a.i - b.i)).forEach((r) => { out.set(r.id, { x, y }); x += r.w + REGION_GAP; });
    y += Math.max(...row.items.map((r) => r.h)) + REGION_GAP;
  });
  return out;
}
// Repack every region on its grid (packPositions) with its content (`content` measured before the edit, else now).
// Returns the number of regions moved.
export function packRegions(content) {
  const ds = domainList(), items = [];
  ds.forEach((d, i) => { const r = domainRect(d); if (r) items.push({ id: d.id, x: r.x, y: r.y, w: r.w, h: r.h, i }); });
  const pos = packPositions(items), cont = content || allContent();
  let moved = 0;
  items.forEach((r) => {
    const p = pos.get(r.id), dx = Math.round(p.x - r.x), dy = Math.round(p.y - r.y); if (!dx && !dy) return;
    const d = domainById(r.id);
    shiftContent(cont[r.id], dx, dy);
    if (!domainCols(r.id).length) { d.x = Math.round(d.x + dx); d.y = Math.round(d.y + dy); }
    moved++;
  });
  return moved;
}
// S2: a column folding (on) or unfolding pulls / pushes the columns right of it in the same row of its domain (vertical
// overlap with its FULL frame, which a fold never changes) by the width the card gives up, with their content. The
// rows are told apart by the same full frame, so fold then unfold moves the same columns back by the same amount.
function shiftRowNeighbours(g, on) {
  const f = frameById('auto-' + g); if (!f) return;
  const dw = f.w - FOLD_COL.w; if (dw <= 0) return;
  const from = f.x + (on ? f.w : FOLD_COL.w) - 1, claimed = new Set(), moved = { frames: new Set(), notes: new Set(), dfids: new Set() };
  const rowOf = (y0, y1) => y0 < f.y + f.h && y1 > f.y;
  const cols = domainCols(domainOfCol(g)).filter((c) => c !== f && c.x >= from && rowOf(c.y, c.y + c.h));
  const byGroup = new Set(cols.map(colGroup));
  cols.forEach((c) => {
    [c].concat(descendantFrames(c)).forEach((x) => moved.frames.add(x));
    notes().forEach((n) => { if (n.parent && [...moved.frames].some((x) => x.id === n.parent)) moved.notes.add(n); });
  });
  Object.keys(dfData()).forEach((df) => { const k = nodeCol(df); if (k && byGroup.has(k) && !claimed.has(df)) { claimed.add(df); moved.dfids.add(String(df)); } });
  const dn = domainNote(domainById(domainOfCol(g)) || {});
  if (dn && dn.x >= from && rowOf(dn.y, dn.y + noteHeight(dn))) moved.notes.add(dn);
  shiftContent(moved, on ? -dw : dw, 0);
}
// Rolled-up diagnostics of a set of Drawflow ids: {n, err, warn} (same levels as the node badges).
export function foldStats(dfids) {
  let err = 0, warn = 0;
  (dfids || new Set()).forEach((df) => {
    const m = model(df), l = (m && S.issues.get(m.id)) || [];
    if (l.some((x) => x.level === 'err')) err++; else if (l.some((x) => x.level === 'warn')) warn++;
  });
  return { n: (dfids || new Set()).size, err, warn };
}
const statLine = (s) => [h('span', { class: 'fcount' }, s.n + ' nœud' + (s.n > 1 ? 's' : '')),
  s.err ? h('span', { class: 'fbadge err', title: s.err + ' nœud(s) en erreur' }, '✖ ' + s.err) : null,
  s.warn ? h('span', { class: 'fbadge warn', title: s.warn + ' nœud(s) avec un avertissement' }, '⚠ ' + s.warn) : null].filter(Boolean);
const stopBtn = (el) => ['mousedown', 'touchstart', 'pointerdown', 'dblclick'].forEach((t) => el.addEventListener(t, (e) => e.stopPropagation(), { passive: true }));
// Apply the fold state to the drawn canvas: hide nodes / wires / frames / post-its, draw the column cards, add the
// column fold buttons. Called after every frame / post-it redraw (drawDomains) and after a rebuild.
export function applyFold() {
  if (!S.editor || !S.editor.precanvas) return;
  const pc = S.editor.precanvas;
  pc.querySelectorAll('.fold-hide').forEach((el) => el.classList.remove('fold-hide'));
  if (!hasDomains()) return;
  const fs = foldSets();
  fs.nodes.forEach((df) => { const el = nodeEl(df); if (el) (el.parentElement || el).classList.add('fold-hide'); });
  if (fs.nodes.size) {
    S.editor.container.querySelectorAll('svg.connection').forEach((svg) => {
      const cl = svg.classList; if (cl.length < 5) return;
      if (fs.nodes.has(cl[1].slice(13)) || fs.nodes.has(cl[2].slice(14))) svg.classList.add('fold-hide');
    });
  }
  fs.frames.forEach((id) => { const el = frameEls.get(id); if (el) el.classList.add('fold-hide'); });
  fs.notes.forEach((id) => { const el = noteEls.get(id); if (el) el.classList.add('fold-hide'); });
  frameEls.forEach((el, id) => {
    const f = frameById(id), g = colGroup(f); if (!g) return;
    const title = el.querySelector('.ftitle');
    if (title && !title.querySelector('.ffold')) {
      const b = h('button', { type: 'button', class: 'ffold', title: isColFolded(g) ? 'Déplier la colonne' : 'Replier la colonne en carte',
        'aria-label': isColFolded(g) ? 'Déplier la colonne' : 'Replier la colonne', onclick: (e) => { e.stopPropagation(); foldColumn(g, !isColFolded(g)); } }, isColFolded(g) ? '▸' : '▾');
      stopBtn(b); title.append(b);
    }
    el.classList.toggle('folded', isColFolded(g));
    if (isColFolded(g) && !fs.frames.has(id)) {
      el.style.width = FOLD_COL.w + 'px'; el.style.height = FOLD_COL.h + 'px';
      const s = foldStats(fs.byCol[g]), open = h('button', { type: 'button', class: 'funfold', onclick: (e) => { e.stopPropagation(); foldColumn(g, false); } }, 'Déplier');
      stopBtn(open);
      el.append(h('div', { class: 'foldcard', 'data-g': g }, h('div', { class: 'fcname' }, f.title || g), h('div', { class: 'fcstat' }, ...statLine(s)), open));
    }
  });
}

// ---------- the #domains layer ----------
function ensureLayer() {
  if (!S.domainsEl || !S.domainsEl.isConnected) {
    S.domainsEl = h('div', { id: 'domains' });
    const pc = S.editor.precanvas, fr = pc.querySelector('#frames');
    pc.insertBefore(S.domainsEl, fr || pc.firstChild);    // below the column frames, the post-its and the nodes
  }
  return S.domainsEl;
}
// S2: rolled-up stats of a whole domain (its columns + loose content): {cols, n, err, warn}.
export function domainStats(d) {
  const c = domainContent(d, new Set()), s = foldStats(c.dfids);
  return { cols: domainCols(d.id).length, n: s.n, err: s.err, warn: s.warn };
}
// S2: the domain card of the domain zoom level (below DOM_ZOOM, CSS shows it over the whole region; its text scales
// with 1/zoom through --zinv). Click = zoom into that domain (focusDomain).
function domainCard(d) {
  const s = domainStats(d), open = () => focusDomain(d.id);
  const card = h('div', { class: 'dzcard', role: 'button', tabindex: '-1', 'data-dom': d.id, title: 'Domaine « ' + d.label + ' » : clic pour y entrer.', onclick: open },
    h('div', { class: 'dzname' }, ico(d.icon || 'square'), h('span', {}, d.label)),
    h('div', { class: 'dzstat' }, h('span', { class: 'dzcols' }, s.cols ? s.cols + ' colonne' + (s.cols > 1 ? 's' : '') : 'vide'), ...statLine(s)));
  stopBtn(card);
  return card;
}
// Refresh the domain cards' badges after a diagnostics pass (analyze), without redrawing the regions.
export function refreshDomainCards() {
  if (!S.domainsEl || !S.domainsEl.isConnected || !hasDomains()) return;
  S.domainsEl.querySelectorAll('.dzcard').forEach((el) => { const d = domainById(el.dataset.dom); if (d) el.replaceWith(domainCard(d)); });
}
export function drawDomains() {
  if (!S.editor || !S.editor.precanvas) return;
  bumpGeo();                                     // S2: regions / folds changed: minimap world and zoom range follow
  const root = ensureLayer(); root.innerHTML = '';
  if (!hasDomains()) { applyFold(); return; }
  const fs = foldSets();
  domainList().forEach((d) => {
    const r = domainRect(d); if (!r) return;
    const cols = domainCols(d.id), folded = !!d.folded;
    const fb = h('button', { type: 'button', class: 'dfold', title: folded ? 'Déplier le domaine' : 'Replier le domaine en carte',
      'aria-label': folded ? 'Déplier le domaine' : 'Replier le domaine', onclick: (e) => { e.stopPropagation(); foldDomain(d.id, !folded); } }, folded ? '▸' : '▾');
    stopBtn(fb);
    const title = h('div', { class: 'dtitle', title: 'Domaine « ' + d.label + ' » : clic pour y aller.' + (d.note ? ' ' + d.note : ''),
      onclick: () => focusDomain(d.id) }, ico(d.icon || 'square'), h('span', { class: 'dlabel' }, d.label),
    h('span', { class: 'dcount' }, cols.length ? cols.length + ' colonne' + (cols.length > 1 ? 's' : '') : 'vide'), fb);
    stopBtn(title);
    const el = h('div', { class: 'dregion' + (cols.length ? '' : ' empty') + (folded ? ' folded' : ''), 'data-dom': d.id }, title);
    el.style.cssText = `--c:${d.color};left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px`;
    if (folded) {
      const s = foldStats(fs.byDom[d.id]), open = h('button', { type: 'button', class: 'funfold', onclick: (e) => { e.stopPropagation(); foldDomain(d.id, false); } }, 'Déplier');
      stopBtn(open);
      el.append(h('div', { class: 'dcard' }, h('div', { class: 'fcstat' }, h('span', {}, cols.length + ' colonne' + (cols.length > 1 ? 's' : '')), ...statLine(s)), open));
    }
    el.append(domainCard(d));
    root.append(el);
  });
  applyFold();
}

// ---------- edits (one undo step each, save-gated) ----------
// S2: every fold / unfold repacks: content measured first (ownership before anything moves), then the flag, then the
// grid; nodes, wires, frames and post-its are redrawn once.
function afterRepack() { drawFrames(); drawNotes(); paintWires(); drawJumpbar(); scheduleTree(); commitSoon(); }
export function foldDomain(id, on) {
  const d = domainById(id); if (!d || editBlocked()) return false;
  if (!!d.folded === !!on) return false;
  const content = allContent();
  if (on) d.folded = true; else delete d.folded;
  packRegions(content);
  afterRepack();
  return true;
}
export function foldColumn(g, on) {
  if (!hasDomains() || editBlocked()) return false;
  const cols = colMap(), e = Object.assign({ domain: domainOfCol(g) }, cols[g] || {});
  if (!!e.folded === !!on) return false;
  const content = allContent();
  shiftRowNeighbours(g, !!on);
  if (on) e.folded = true; else delete e.folded;
  cols[g] = e;
  packRegions(content);
  afterRepack();
  return true;
}
// Move the column `g` (its frame, sub-groups, post-its and nodes) into domain `id`: right of that domain's columns
// (top aligned), or at the top-left of an empty region. A domain left empty keeps its current rectangle; regions the
// grown target now overlaps are pushed right with their content (separate), so regions never overlap. S2: the target's
// explanatory post-it then sits right of its columns, top aligned (never under a column title, still in the region).
export function moveColumnToDomain(g, id) {
  const d = domainById(id); if (!d || editBlocked()) return false;
  const cur = domainOfCol(g), f = frameById('auto-' + g);
  if (cur === id) { toast('La colonne est déjà dans le domaine « ' + d.label + ' ».', ''); return false; }
  let content = null;
  if (f) {
    const src = domainById(cur);
    if (src && domainCols(cur).length === 1) { const r = domainRect(src, true); if (r) Object.assign(src, { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.w), h: Math.round(r.h) }); }
    const mine = domainCols(id), tr = domainRect(d, true);
    const tx = mine.length ? Math.max(...mine.map((c) => colBox(c).x1)) + COL_GAP : (tr ? tr.x + REGION.pad : f.x);
    const ty = mine.length ? Math.min(...mine.map((c) => c.y)) : (tr ? tr.y + REGION.head : f.y);
    const mb = frameMembers(f), mv = { frames: new Set(mb.frames), notes: new Set(mb.notes), dfids: new Set(mb.dfids.map(String)) };
    Object.keys(dfData()).forEach((df) => { if (nodeCol(df) === g) mv.dfids.add(String(df)); });   // hidden ones too (folded)
    // what each region holds is measured BEFORE the column lands: once placed it may overlap another region's column
    // frame for a moment, and geometry alone would then hand its loose items to that region
    content = allContent();
    Object.values(content).forEach((c) => { mv.frames.forEach((x) => c.frames.delete(x)); mv.notes.forEach((x) => c.notes.delete(x)); mv.dfids.forEach((x) => c.dfids.delete(x)); });
    shiftContent(mv, Math.round(tx - f.x), Math.round(ty - f.y));
  }
  const cols = colMap();
  cols[g] = Object.assign({}, cols[g] || {}, { domain: id });
  if (f) {
    const dn = domainNote(d), mine = domainCols(id);
    if (dn && mine.length) { dn.x = Math.round(Math.max(...mine.map((c) => colBox(c).x1)) + COL_GAP); dn.y = Math.round(Math.min(...mine.map((c) => c.y))); }
    separate(id, content);     // the grown region pushes the regions it now overlaps (to the right, cascading)
  }
  drawFrames(); drawNotes(); paintWires(); drawJumpbar(); scheduleTree();
  commitSoon();
  toast('Colonne « ' + ((f && f.title) || g) + ' » rangée dans le domaine « ' + d.label + ' ».', '');
  return true;
}
// Frame a domain: its whole region when that is readable, else its top-left part at the zoom just above the domain
// cards (S2: fit-to-target, never stuck at the domain zoom level, so a click on a domain card really enters it).
export function focusDomain(id) {
  const d = domainById(id), r = d && domainRect(d); if (!r) return false;
  focusRect({ x0: r.x, y0: r.y, x1: r.x + r.w, y1: r.y + r.h }, null, { min: DOM_ZOOM * 1.25, max: 1 });
  clearJumpbar();
  return true;
}
