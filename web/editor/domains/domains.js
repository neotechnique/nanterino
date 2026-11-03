/**
 * Domains (lot S1): the navigable level ABOVE the state columns (one graph for the whole robot).
 *
 * Purpose :  domain table / column -> domain map access (meta.domains, meta.columns), region rectangles (mirror of the
 *            server's graph_layout.region_rect), the #domains layer (one region per domain: title bar with icon, counts
 *            and fold button; an empty domain stays visible with its explanatory post-it), folding a domain or a column
 *            into a card (node count + error / warning badges; the folded content and the wires that touch it are
 *            HIDDEN, never redrawn to the card edge), moving a column to another domain (geometry follows), focusing a
 *            domain, the world box used by "Ajuster".
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Organisation only: meta.domains and
 *            meta.columns ride on the document (serialize copies meta), the server stores them in graph.layout.json and
 *            never compiles them (the robot's behaviour cannot change).
 * Depends :  core/util.js, core/state.js, core/api.js, canvas/nodes.js, canvas/view.js, canvas/wires.js,
 *            canvas/navigation.js, core/history.js, core/ui.js, frames/groups.js, frames/nesting.js, frames/notes.js,
 *            clipboard/clipboard.js, hierarchy/tree.js, minimap/overview.js
 * Invariant: a region is the bounding box of its column frames (auto-<group>) grown by REGION (same numbers as the
 *            server), or the stored x/y/w/h of the domain when it holds no column; a fold or a move is one commitSoon()
 *            (save-gated like every edit, undo / redo through the document snapshot); a document without `domains`
 *            (hub / go-to forms, very old undo entries) draws exactly as before S1.
 * Test    :  tests/web/domains.py (scenario `domains`) through the window.__editor hooks; server side
 *            tests/test_graph_domains.py.
 */
import { h, ico } from '../core/util.js';
import { S } from '../core/state.js';
import { dfData, dfNode, model } from '../core/api.js';
import { nodeEl } from '../canvas/nodes.js';
import { nodeBox } from '../canvas/view.js';
import { paintWires } from '../canvas/wires.js';
import { editBlocked } from '../canvas/navigation.js';
import { commitSoon } from '../core/history.js';
import { toast } from '../core/ui.js';
import { frameById, frameEls, frames } from '../frames/groups.js';
import { descendantFrames, drawFrames, focusRect } from '../frames/nesting.js';
import { drawNotes, noteEls, noteHeight, notes } from '../frames/notes.js';
import { frameMembers } from '../clipboard/clipboard.js';
import { scheduleTree } from '../hierarchy/tree.js';
import { clearJumpbar, drawJumpbar } from '../minimap/overview.js';

// Same numbers as nanterino/graph_layout.py (DOM_PAD, DOM_HEAD, COL_GAP, EMPTY_W / EMPTY_H): a region drawn by the
// editor and one drawn by the server around the same frames are the same rectangle.
export const REGION = { pad: 60, head: 240 };
const COL_GAP = 150;
const REGION_GAP = 260;                           // graph_layout.DOM_GAP: free space between two regions
export const FOLD_COL = { w: 340, h: 190 };       // a folded column: its frame shrinks to this card
export const FOLD_DOM = { w: 520, h: 250 };       // a folded domain: its region shrinks to this card
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
// Region rectangle {x, y, w, h} of a domain: its column frames grown by REGION, else its stored rectangle.
export function domainRect(d) {
  const cols = domainCols(d.id);
  if (cols.length) {
    const x0 = Math.min(...cols.map((f) => f.x)) - REGION.pad, y0 = Math.min(...cols.map((f) => f.y)) - REGION.head;
    const x1 = Math.max(...cols.map((f) => f.x + f.w)) + REGION.pad, y1 = Math.max(...cols.map((f) => f.y + f.h)) + REGION.pad;
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }
  return [d.x, d.y, d.w, d.h].every((v) => typeof v === 'number' && isFinite(v)) && d.w > 0 && d.h > 0 ? { x: d.x, y: d.y, w: d.w, h: d.h } : null;
}
// Domain whose region contains a canvas point (hierarchy: top-level groups, post-its and chains), else null.
export function domainAt(x, y) {
  return domainList().find((d) => { const r = domainRect(d); return r && x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h; }) || null;
}
// "Ajuster": the node box grown to every region (an empty region is part of the world the user should see).
export function worldBox(b) {
  let out = b ? { ...b } : null;
  domains().forEach((d) => {
    const r = domainRect(d); if (!r) return;
    out = out ? { x0: Math.min(out.x0, r.x), y0: Math.min(out.y0, r.y), x1: Math.max(out.x1, r.x + r.w), y1: Math.max(out.y1, r.y + r.h) }
      : { x0: r.x, y0: r.y, x1: r.x + r.w, y1: r.y + r.h };
  });
  return out;
}

// ---------- fold ----------
const centreIn = (b, r) => { const cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2; return cx >= r.x && cx <= r.x + r.w && cy >= r.y && cy <= r.y + r.h; };
// What a fold hides: {nodes: Set(dfid), frames: Set(id), notes: Set(id), byCol: {group: Set(dfid)}, byDom: {id: Set(dfid)}}.
// A folded column hides its sub-groups, its post-its and the nodes whose centre lies in its frame (the frame itself is
// drawn as a card); a folded domain hides its columns too, plus the top-level groups / post-its / nodes inside its region.
export function foldSets() {
  const out = { nodes: new Set(), frames: new Set(), notes: new Set(), byCol: {}, byDom: {} };
  if (!hasDomains() || !S.editor) return out;
  const data = dfData(), boxes = {};
  for (const df in data) boxes[df] = nodeBox(df);
  const hideFrame = (f, withSelf) => {
    const sub = descendantFrames(f), ids = new Set([f.id].concat(sub.map((g) => g.id)));
    if (withSelf) out.frames.add(f.id);
    sub.forEach((g) => out.frames.add(g.id));
    notes().forEach((n) => { if (n.parent && ids.has(n.parent)) out.notes.add(n.id); });
    const r = { x: f.x, y: f.y, w: f.w, h: f.h }, mine = new Set();
    for (const df in boxes) if (centreIn(boxes[df], r)) { mine.add(df); out.nodes.add(df); }
    return mine;
  };
  // a node inside a column frame belongs to that column (whatever region it overlaps); only the others are "loose"
  const inCol = new Set();
  frames().forEach((f) => { if (colGroup(f)) for (const df in boxes) if (centreIn(boxes[df], f)) inCol.add(df); });
  domainList().forEach((d) => {
    const dfold = !!d.folded, all = new Set();
    domainCols(d.id).forEach((f) => {
      const g = colGroup(f);
      if (!dfold && !isColFolded(g)) return;
      const mine = hideFrame(f, dfold);
      out.byCol[g] = mine; mine.forEach((x) => all.add(x));
    });
    if (dfold) {
      const r = domainRect(d);
      if (r) {
        frames().forEach((f) => { if (!f.auto && !f.parent && centreIn({ x0: f.x, y0: f.y, x1: f.x + f.w, y1: f.y + f.h }, r)) hideFrame(f, true).forEach((x) => all.add(x)); });
        notes().forEach((n) => { if (!n.parent && centreIn({ x0: n.x, y0: n.y, x1: n.x + n.w, y1: n.y + noteHeight(n) }, r)) out.notes.add(n.id); });
        for (const df in boxes) if (!inCol.has(df) && centreIn(boxes[df], r)) { all.add(df); out.nodes.add(df); }
      }
      out.byDom[d.id] = all;
    }
  });
  return out;
}
// Everything that moves with a region: its columns (frame, sub-groups, post-its, nodes) plus the top-level groups,
// post-its and loose nodes (in no column frame) inside its rectangle. {frames: Set, notes: Set, dfids: Set}.
function regionContent(d) {
  const out = { frames: new Set(), notes: new Set(), dfids: new Set() }, add = (mb) => {
    mb.frames.forEach((x) => out.frames.add(x)); mb.notes.forEach((x) => out.notes.add(x)); mb.dfids.forEach((x) => out.dfids.add(String(x)));
  };
  domainCols(d.id).forEach((f) => add(frameMembers(f)));
  const r = domainRect(d); if (!r) return out;
  const cols = frames().filter((f) => colGroup(f));
  frames().forEach((f) => { if (!f.auto && !f.parent && centreIn({ x0: f.x, y0: f.y, x1: f.x + f.w, y1: f.y + f.h }, r)) add(frameMembers(f)); });
  notes().forEach((n) => { if (!n.parent && centreIn({ x0: n.x, y0: n.y, x1: n.x + n.w, y1: n.y + noteHeight(n) }, r)) out.notes.add(n); });
  Object.keys(dfData()).forEach((df) => { const b = nodeBox(df); if (centreIn(b, r) && !cols.some((f) => centreIn(b, f))) out.dfids.add(String(df)); });
  return out;
}
function shiftContent(c, dx, dy) {
  c.frames.forEach((x) => { x.x += dx; x.y += dy; });
  c.notes.forEach((n) => { n.x += dx; n.y += dy; });
  c.dfids.forEach((df) => {
    const nd = dfNode(df), el = nodeEl(df); if (!nd) return;
    nd.pos_x += dx; nd.pos_y += dy;
    if (el) { el.style.left = nd.pos_x + 'px'; el.style.top = nd.pos_y + 'px'; }
  });
  c.dfids.forEach((df) => S.editor.updateConnectionNodes('node-' + df));
}
const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
// Regions never overlap after an edit of the editor: every region that overlaps the pusher (domain `id`, grown by a
// moved column) is moved right of it with its whole content, then pushes in turn (cascade, bounded). `content`:
// {domain id: regionContent measured before the edit} (else measured now).
function separate(id, content) {
  const todo = [id];
  let guard = 0;
  while (todo.length && guard++ < 60) {
    const p = domainById(todo.shift()), pr = p && domainRect(p); if (!pr) continue;
    domainList().forEach((o) => {
      if (o.id === p.id) return;
      const or = domainRect(o); if (!or || !overlap(pr, or)) return;
      const dx = Math.round(pr.x + pr.w + REGION_GAP - or.x), c = (content && content[o.id]) || regionContent(o);
      shiftContent(c, dx, 0);
      if (!domainCols(o.id).length) o.x = Math.round(or.x + dx);     // an empty region moves by its stored rectangle
      todo.push(o.id);
    });
  }
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
export function drawDomains() {
  if (!S.editor || !S.editor.precanvas) return;
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
    const w = folded ? FOLD_DOM.w : r.w, hh = folded ? FOLD_DOM.h : r.h;
    el.style.cssText = `--c:${d.color};left:${r.x}px;top:${r.y}px;width:${w}px;height:${hh}px`;
    if (folded) {
      const s = foldStats(fs.byDom[d.id]), open = h('button', { type: 'button', class: 'funfold', onclick: (e) => { e.stopPropagation(); foldDomain(d.id, false); } }, 'Déplier');
      stopBtn(open);
      el.append(h('div', { class: 'dcard' }, h('div', { class: 'fcstat' }, h('span', {}, cols.length + ' colonne' + (cols.length > 1 ? 's' : '')), ...statLine(s)), open));
    }
    root.append(el);
  });
  applyFold();
}

// ---------- edits (one undo step each, save-gated) ----------
export function foldDomain(id, on) {
  const d = domainById(id); if (!d || editBlocked()) return false;
  if (!!d.folded === !!on) return false;
  if (on) d.folded = true; else delete d.folded;
  drawFrames(); drawJumpbar(); scheduleTree(); commitSoon();
  return true;
}
export function foldColumn(g, on) {
  if (!hasDomains() || editBlocked()) return false;
  const cols = colMap(), e = Object.assign({ domain: domainOfCol(g) }, cols[g] || {});
  if (!!e.folded === !!on) return false;
  if (on) e.folded = true; else delete e.folded;
  cols[g] = e;
  drawFrames(); scheduleTree(); commitSoon();
  return true;
}
// Move the column `g` (its frame, sub-groups, post-its and nodes) into domain `id`: right of that domain's columns
// (top aligned), or at the top-left of an empty region. A domain left empty keeps its current rectangle; regions the
// grown target now overlaps are pushed right with their content (separate), so regions never overlap.
export function moveColumnToDomain(g, id) {
  const d = domainById(id); if (!d || editBlocked()) return false;
  const cur = domainOfCol(g), f = frameById('auto-' + g), content = {};
  if (cur === id) { toast('La colonne est déjà dans le domaine « ' + d.label + ' ».', ''); return false; }
  if (f) {
    const src = domainById(cur);
    if (src && domainCols(cur).length === 1) { const r = domainRect(src); if (r) Object.assign(src, { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.w), h: Math.round(r.h) }); }
    const mine = domainCols(id), tr = domainRect(d);
    const tx = mine.length ? Math.max(...mine.map((c) => c.x + c.w)) + COL_GAP : (tr ? tr.x + REGION.pad : f.x);
    const ty = mine.length ? Math.min(...mine.map((c) => c.y)) : (tr ? tr.y + REGION.head : f.y);
    const mb = frameMembers(f), mv = { frames: new Set(mb.frames), notes: new Set(mb.notes), dfids: new Set(mb.dfids.map(String)) };
    // what each region holds is measured BEFORE the column lands: once placed it may overlap another region's column
    // frame for a moment, and geometry alone would then hand its nodes to that region
    domainList().forEach((o) => {
      const c = regionContent(o);
      mv.frames.forEach((x) => c.frames.delete(x)); mv.notes.forEach((x) => c.notes.delete(x)); mv.dfids.forEach((x) => c.dfids.delete(x));
      content[o.id] = c;
    });
    shiftContent(mv, Math.round(tx - f.x), Math.round(ty - f.y));
  }
  const cols = colMap();
  cols[g] = Object.assign({}, cols[g] || {}, { domain: id });
  if (f) separate(id, content);     // the grown region pushes the regions it now overlaps (to the right, cascading)
  drawFrames(); drawNotes(); paintWires(); drawJumpbar(); scheduleTree();
  commitSoon();
  toast('Colonne « ' + ((f && f.title) || g) + ' » rangée dans le domaine « ' + d.label + ' ».', '');
  return true;
}
export function focusDomain(id) {
  const d = domainById(id), r = d && domainRect(d); if (!r) return false;
  const w = d.folded ? FOLD_DOM.w : r.w, hh = d.folded ? FOLD_DOM.h : r.h;
  focusRect({ x0: r.x, y0: r.y, x1: r.x + w, y1: r.y + hh });
  clearJumpbar();
  return true;
}
