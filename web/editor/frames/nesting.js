/**
 * Frames: nested groups (lot L8 / L9), frame drawing and editing.
 *
 * Purpose :  parent links, drop target under the pointer (dropTargetAt), grow-to-fit, frame drag / resize / edit /
 *            delete.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, core/api.js, canvas/nodes.js, core/serialize.js, core/history.js,
 *            core/chains.js, canvas/view.js, minimap/overview.js, minimap/minimap.js, frames/groups.js, frames/notes.js,
 *            canvas/navigation.js, clipboard/clipboard.js, menu/node-menu.js, hierarchy/tree.js, inspector/fields.js,
 *            inspector/inspector.js, core/ui.js, domains/domains.js (S1)
 *            S2: frames hidden by a fold are never drop targets (a repack may slide neighbours over them); a column drag
 *            takes the nodes of clipboard.inFrame (hidden nodes by their column, never by geometry); "Ajuster" and the
 *            minimum zoom use the whole world (worldBounds: nodes + frames + regions); zoom_min = half the fit zoom of
 *            the world (no fixed floor), refreshed on every redraw of the frames; focusRect takes {min, max}.
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, h, ico } from '../core/util.js';
import { S, nidToDf } from '../core/state.js';
import { applyCull, updateWires } from '../canvas/culling.js';
import { dfData, dfNode, model, nidOf } from '../core/api.js';
import { nodeEl, stateDesc } from '../canvas/nodes.js';
import { serialize } from '../core/serialize.js';
import { commitSoon } from '../core/history.js';
import { computeChains } from '../core/chains.js';
import { bandRects, drawBands, nodeBox } from '../canvas/view.js';
import { JUMP_GAP, clearJumpbar, jumpbarBottom, zoomVars } from '../minimap/overview.js';
import { frameCard } from '../minimap/minimap.js';
import { FRAME_COLORS, FRAME_PAD, ensureFrames, frameById, frameEls, frames, placeFrame } from './groups.js';
import { noteEls, noteHeight, notes, placeNote } from './notes.js';
import { editBlocked } from '../canvas/navigation.js';
import { clearChainSel, inFrame } from '../clipboard/clipboard.js';
import { selectDf } from '../menu/node-menu.js';
import { colColor, colIcon, colState, scheduleTree, treeStats } from '../hierarchy/tree.js';
import { areaCtl, checkCtl, field, textCtl } from '../inspector/fields.js';
import { renderInspector } from '../inspector/inspector.js';
import { toast } from '../core/ui.js';
import { domainById, domainList, domainOfCol, drawDomains, foldColumn, isColFolded, moveColumnToDomain, worldBounds } from '../domains/domains.js';

// ---------- nested groups (lot L8) ----------
// f.parent / note.parent = id of the enclosing frame (absent = top level), saved in graph.layout.json (the server's
// clean_parents drops dangling / cyclic links and any parent of an automatic column). Frames and post-its belong by
// that link; nodes still follow a frame by geometry (centre inside it when its drag starts). A drop decides the link.
// L9 (2026-11-01, user report "je ne peux pas mettre un groupe dans un groupe"): the target is the innermost frame
// under the POINTER at release (dropTargetAt), never the item itself or one of its descendants (so no cycle), whatever
// the sizes: a person drags by the title and lets go where the pointer is, often with a group as big as or bigger than
// the target (the L8 rule, "the dragged item's centre inside a LARGER frame", refused exactly that). A user group may
// enter a state column (`auto`); a column itself stays top level: dropped onto a group it goes back where it was, with
// a red outline while held and a toast. A user frame always encloses its children: a drop grows the parent chain to
// fit (automatic columns are never grown: they are the state columns), and a resize cannot shrink any frame below its
// children. Deleting a frame hands its children to its own parent.
// Legacy layouts (no `parent` anywhere) get their membership from geometry once, at load (adoptLegacy). L9: the first
// time the user nests or un-nests anything, every user frame and post-it gets an explicit `parent` (null = top level,
// kept by the server), so that adoption can never run again and redo a choice the user made.
export const NEST_PAD = { l: 16, r: 16, t: 40, b: 16 };   // t: room for the child's title bar under the parent's
export const parentOf = (it) => (it && it.parent ? frameById(it.parent) || null : null);
function frameDepth(f) { let d = 0, p = parentOf(f), guard = 0; while (p && guard++ < 200) { d++; p = parentOf(p); } return d; }
export function descendantFrames(f) {
  const out = [], todo = [f.id], seen = new Set([f.id]);
  while (todo.length) {
    const id = todo.pop();
    frames().forEach((g) => { if (g.parent === id && !seen.has(g.id)) { seen.add(g.id); out.push(g); todo.push(g.id); } });
  }
  return out;
}
export const frameBox = (f) => ({ x0: f.x, y0: f.y, x1: f.x + f.w, y1: f.y + f.h });
export const noteBox = (n, hh) => ({ x0: n.x, y0: n.y, x1: n.x + n.w, y1: n.y + (hh == null ? noteHeight(n) : hh) });
// Frame that would receive an item whose box is `b`: deepest frame containing its centre (then smallest), skipping
// `skip` ids. opts.frame: the item is a frame (only enters a larger one); opts.smallest: smallest area wins (legacy).
// S2: a frame hidden by a fold (class fold-hide) is never a target.
const foldHidden = (g) => { const el = frameEls.get(g.id); return !!(el && el.classList.contains('fold-hide')); };
export function dropTarget(b, skip, opts) {
  const o = opts || {}, cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2, area = (b.x1 - b.x0) * (b.y1 - b.y0);
  let best = null, bd = -1, ba = 0;
  frames().forEach((g) => {
    if ((skip && skip.has(g.id)) || foldHidden(g) || cx < g.x || cx > g.x + g.w || cy < g.y || cy > g.y + g.h) return;
    const ga = g.w * g.h; if (o.frame && ga <= area) return;
    const d = o.smallest ? 0 : frameDepth(g);
    if (!best || d > bd || (d === bd && ga < ba)) { best = g; bd = d; ba = ga; }
  });
  return best;
}
// L9: frame that receives a drop: the deepest frame under the POINTER (canvas point `pt`), then the smallest, skipping
// `skip` ids (the dragged frame and its descendants). Size never matters: the receiving chain grows to fit.
// S2: frames hidden by a fold are skipped, unless `only` (Set of ids) restricts the candidates (hierarchy of hidden chains).
export function dropTargetAt(pt, skip, only) {
  if (!pt) return null;
  let best = null, bd = -1, ba = 0;
  frames().forEach((g) => {
    if ((skip && skip.has(g.id)) || (only ? !only.has(g.id) : foldHidden(g)) || pt.x < g.x || pt.x > g.x + g.w || pt.y < g.y || pt.y > g.y + g.h) return;
    const d = frameDepth(g), ga = g.w * g.h;
    if (!best || d > bd || (d === bd && ga < ba)) { best = g; bd = d; ba = ga; }
  });
  return best;
}
// L9: after the user's first nesting choice every user frame / post-it carries `parent` (null = top level): adoptLegacy
// only runs on a layout where no item has the key, so it can never undo that choice on a later reload.
function explicitParents() {
  frames().forEach((f) => { if (!f.auto && !('parent' in f)) f.parent = null; });
  notes().forEach((n) => { if (!('parent' in n)) n.parent = null; });
}
function childBoxes(f) {
  return frames().filter((g) => g.parent === f.id).map(frameBox).concat(notes().filter((n) => n.parent === f.id).map((n) => noteBox(n)));
}
// Grow `f` and its user-frame ancestors so they enclose their children (NEST_PAD margins).
export function fitAncestors(f) {
  let guard = 0;
  while (f && guard++ < 200) {
    const kids = f.auto ? [] : childBoxes(f);
    if (kids.length) {
      const x0 = Math.min(f.x, ...kids.map((k) => k.x0 - NEST_PAD.l)), y0 = Math.min(f.y, ...kids.map((k) => k.y0 - NEST_PAD.t));
      const x1 = Math.max(f.x + f.w, ...kids.map((k) => k.x1 + NEST_PAD.r)), y1 = Math.max(f.y + f.h, ...kids.map((k) => k.y1 + NEST_PAD.b));
      f.x = Math.round(x0); f.y = Math.round(y0); f.w = Math.round(x1 - x0); f.h = Math.round(y1 - y0);
    }
    f = parentOf(f);
  }
}
// Smallest size the bottom-right grip may give `f` (its children stay inside).
function minFrameSize(f) {
  let w = 0, hh = 0;
  childBoxes(f).forEach((k) => { w = Math.max(w, k.x1 + NEST_PAD.r - f.x); hh = Math.max(hh, k.y1 + NEST_PAD.b - f.y); });
  return { w, h: hh };
}
// Link a dropped frame / note to `target` (null = top level); grows the new parent chain. Toast when the link changed.
export function reparent(it, isNote, target) {
  const old = it.parent || null, now = target ? target.id : null;
  it.parent = now;                            // L9: null = top level, written explicitly (see explicitParents)
  if (target) fitAncestors(target);
  if (old === now) return false;
  explicitParents();
  const what = isNote ? 'Post-it' : 'Groupe', name = (g) => '« ' + ((g && g.title) || (g && g.id) || old) + ' »';
  toast(now ? what + ' rangé dans ' + name(target) + '.' : what + ' sorti de ' + name(frameById(old)) + '.', '');
  return true;
}
// shared state: S.dropEl, S.dropCls (core/state.js)            // frame element outlined as the drop target of the current drag
// deny: L9 red outline (a state column held over a group: it will not enter it)
export function markDrop(f, deny) {
  const el = f ? frameEls.get(f.id) || null : null, cls = deny ? 'dropdeny' : 'droptarget';
  if (el === S.dropEl && cls === S.dropCls) return;
  if (S.dropEl) S.dropEl.classList.remove(S.dropCls);
  S.dropEl = el; S.dropCls = cls;
  if (el) el.classList.add(cls);
}
// Old layout without any `parent`: frames and post-its join the smallest frame around their centre, once at load.
export function adoptLegacy() {
  const fr = frames(), ns = notes();
  if (fr.some((f) => 'parent' in f) || ns.some((n) => 'parent' in n)) return false;
  let changed = false;
  fr.forEach((f) => { if (f.auto) return; const t = dropTarget(frameBox(f), new Set([f.id]), { frame: true, smallest: true }); if (t) { f.parent = t.id; changed = true; } });
  ns.forEach((n) => { const t = dropTarget(noteBox(n), null, { smallest: true }); if (t) { n.parent = t.id; changed = true; } });
  return changed;
}
export function drawFrames() {
  if (!S.editor) return;
  const root = ensureFrames(); root.innerHTML = ''; frameEls.clear(); S.dropEl = null;
  // L8 z-order: parents first, children after (drawn above); list order inside one depth
  frames().map((f, i) => [f, frameDepth(f), i]).sort((a, b) => a[1] - b[1] || a[2] - b[2]).forEach(([f]) => {
    const text = h('span', { class: 'ftext' }, f.title || '(sans nom)');
    if (!f.title) text.classList.add('empty');
    const tip = f.auto ? 'Glisser pour déplacer la colonne avec ses nœuds, ses groupes et ses post-it (une colonne reste au premier niveau). Double-clic pour renommer.'
      : 'Glisser pour déplacer le groupe avec ses nœuds, ses groupes et ses post-it ; lâché avec le pointeur sur un autre groupe ou une colonne, il en fait partie. Double-clic pour renommer.';
    const title = h('div', { class: 'ftitle', title: tip }, ico('square'), text);
    const grip = h('div', { class: 'fresize', title: 'Redimensionner' });
    const el = h('div', { class: 'frame' + (f.auto ? ' auto' : '') + (f.id === S.selFrame ? ' sel' : ''), 'data-fid': f.id, 'data-parent': f.parent || false }, title, grip);
    placeFrame(f, el);
    if (f.auto) { const card = frameCard(f); if (card) el.append(card); }   // semantic-zoom card (CSS shows it below 0.25)
    for (const part of [title, grip]) {
      part.addEventListener('mousedown', (e) => startFrameDrag(e, f, part === grip ? 'resize' : 'move'));
      part.addEventListener('touchstart', (e) => startFrameDrag(e, f, part === grip ? 'resize' : 'move'), { passive: false });
    }
    title.addEventListener('dblclick', (e) => { e.stopPropagation(); editFrameTitle(f); });
    frameEls.set(f.id, el);
    root.append(el);
  });
  drawBands();             // live / simulated state glow on the auto column frames
  drawDomains();           // lot S1: domain regions follow their columns; fold cards / hidden content re-applied
  updateZoomMin();         // S2: the zoom range follows the size of the world
  applyCull(true);         // S3: the new frame elements are culled by the same rule as the nodes
}
// S2: lowest zoom = half the zoom that fits the whole world (no fixed floor: a 10x graph zooms out 10x further).
export function updateZoomMin() {
  if (!S.editor) return;
  S.editor.zoom_min = Math.max(1e-4, Math.min(0.5, fitZoom() * 0.5));
}
export function clearNodeSelection() {
  if (S.editor.node_selected) { S.editor.node_selected.classList.remove('selected'); S.editor.node_selected = null; }
  S.selDf = null;
  clearChainSel();                     // L10: one selection at a time (node | chain | group | post-it)
}
export function selectFrame(id) {
  if (S.selFrame === id) return;
  clearNodeSelection();
  if (S.selNote) { S.selNote = null; noteEls.forEach((el) => el.classList.remove('sel')); }
  S.selFrame = id;
  drawFrames(); renderInspector();
  if (id && innerWidth <= 900) document.body.classList.remove('hide-right');
}
export function unselectFrame() { if (S.selFrame) { S.selFrame = null; drawFrames(); renderInspector(); } }
export const evPoint = (e) => (e.touches && e.touches[0]) || (e.changedTouches && e.changedTouches[0]) || e;
function startFrameDrag(e, f, mode) {
  if (e.button) return;                 // left button / touch only
  e.stopPropagation(); e.preventDefault();   // Drawflow must not pan the canvas or select a node
  selectFrame(f.id);
  const p = evPoint(e);
  S.frameDrag = { f, mode, cx: p.clientX, cy: p.clientY, ox: f.x, oy: f.y, ow: f.w, oh: f.h, moved: false, nodes: [], frames: [], notes: [],
    skip: new Set([f.id]), min: mode === 'resize' ? minFrameSize(f) : null };
  if (mode === 'move') {
    // Nodes whose centre lies in the frame at drag start follow it; L8: so do all descendant frames and their post-its.
    // S2: clipboard.inFrame: a node hidden by a fold follows its own column only (a repack may slide it under this frame)
    S.frameDrag.nodes = Object.keys(dfData()).filter((dfid) => inFrame(f, dfid))
      .map((dfid) => ({ dfid, x: dfNode(dfid).pos_x, y: dfNode(dfid).pos_y }));
    const kids = descendantFrames(f);
    kids.forEach((g) => S.frameDrag.skip.add(g.id));
    S.frameDrag.frames = kids.map((g) => ({ g, x: g.x, y: g.y }));
    S.frameDrag.notes = notes().filter((n) => n.parent && S.frameDrag.skip.has(n.parent)).map((n) => ({ n, x: n.x, y: n.y }));
  }
}
export function moveFrameDrag(e) {
  const d = S.frameDrag; if (!d) return;
  if (e.cancelable) e.preventDefault();
  const p = evPoint(e), dx = (p.clientX - d.cx) / S.editor.zoom, dy = (p.clientY - d.cy) / S.editor.zoom;
  if (!d.moved && Math.hypot(p.clientX - d.cx, p.clientY - d.cy) < 3) return;   // a click is not a move
  d.moved = true;
  const f = d.f;
  if (d.mode === 'resize') { f.w = Math.max(80, d.min.w, Math.round(d.ow + dx)); f.h = Math.max(60, d.min.h, Math.round(d.oh + dy)); }
  else {
    f.x = Math.round(d.ox + dx); f.y = Math.round(d.oy + dy);
    d.nodes.forEach((n) => {
      const nd = dfNode(n.dfid), el = nodeEl(n.dfid);
      nd.pos_x = n.x + dx; nd.pos_y = n.y + dy;
      if (el) { el.style.left = nd.pos_x + 'px'; el.style.top = nd.pos_y + 'px'; }
    });
    updateWires(d.nodes.map((n) => n.dfid));          // S3: positions first, then ONE redraw pass of their wires
    d.frames.forEach((o) => { o.g.x = Math.round(o.x + dx); o.g.y = Math.round(o.y + dy); const el = frameEls.get(o.g.id); if (el) placeFrame(o.g, el); });
    d.notes.forEach((o) => { o.n.x = Math.round(o.x + dx); o.n.y = Math.round(o.y + dy); const el = noteEls.get(o.n.id); if (el) placeNote(o.n, el); });
    d.pt = canvasPoint(p.clientX, p.clientY);
    markDrop(dropTargetAt(d.pt, d.skip), f.auto);   // L8 outline; L9: under the pointer, red for a column (refused)
  }
  const el = frameEls.get(f.id); if (el) placeFrame(f, el);
}
export function endFrameDrag() {
  const d = S.frameDrag; if (!d) return;
  S.frameDrag = null;
  markDrop(null);
  if (!d.moved) return;
  if (d.mode === 'move') {
    const t = dropTargetAt(d.pt, d.skip);
    if (!d.f.auto) reparent(d.f, false, t);
    else if (t) {                     // L9: a state column stays top level: back where it was, and say so
      undoFrameMove(d);
      toast('Une colonne d\u2019état reste au premier niveau : « ' + (d.f.title || d.f.id) + ' » revient à sa place. Pour ranger « '
        + (t.title || t.id) + ' » dans la colonne, glissez plutôt ce groupe dans la colonne.', 'err');
    }
  } else if (d.mode === 'resize') fitAncestors(parentOf(d.f));   // a grown child grows its parents
  drawBands(); drawFrames(); renderInspector();
  commitSoon();
}
// L9: put a frame drag back (the frame, the nodes, frames and post-its that followed it), wires redrawn.
function undoFrameMove(d) {
  d.f.x = d.ox; d.f.y = d.oy;
  d.nodes.forEach((n) => {
    const nd = dfNode(n.dfid), el = nodeEl(n.dfid);
    nd.pos_x = n.x; nd.pos_y = n.y;
    if (el) { el.style.left = n.x + 'px'; el.style.top = n.y + 'px'; }
  });
  updateWires(d.nodes.map((n) => n.dfid));
  d.frames.forEach((o) => { o.g.x = o.x; o.g.y = o.y; });
  d.notes.forEach((o) => { o.n.x = o.x; o.n.y = o.y; const el = noteEls.get(o.n.id); if (el) placeNote(o.n, el); });
}
export function editFrameTitle(f) {
  const el = frameEls.get(f.id), t = el && el.querySelector('.ftext'); if (!t) return;
  const inp = h('input', { class: 'finput', type: 'text', maxlength: 60 });
  inp.value = f.title;
  t.replaceWith(inp); inp.focus(); inp.select();
  let done = false;
  const fin = (ok) => {
    if (done) return; done = true;
    if (ok && inp.value !== f.title) { f.title = inp.value.slice(0, 60); commitSoon(); }
    drawFrames(); renderInspector(); scheduleTree();
  };
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') fin(true); else if (e.key === 'Escape') fin(false); });
  inp.addEventListener('blur', () => fin(true));
  for (const ev of ['mousedown', 'dblclick']) inp.addEventListener(ev, (e) => e.stopPropagation());
}
export function editFrame(f, patch, rerender) {
  Object.assign(f, patch);
  if (f.note === '' || f.note == null) delete f.note;
  drawFrames(); scheduleTree();
  if (rerender) renderInspector();
  commitSoon();
}
export function deleteFrame(id) {
  if (editBlocked()) return;
  // L8: the children of a deleted group go to its parent (or the top level); they are never deleted
  const gone = frameById(id), up = gone && gone.parent ? gone.parent : null;
  frames().concat(notes()).forEach((it) => { if (it.parent === id) it.parent = up; });   // L9: null = explicit top level
  S.meta.frames = frames().filter((f) => f.id !== id);
  if (S.selFrame === id) S.selFrame = null;
  drawFrames(); renderInspector(); scheduleTree();
  commitSoon();
}
// "Groupe" / key G: a frame around the selected node's chain(s) (Drawflow selects one node at a time, so the
// whole rule it belongs to is wrapped), else a default box at the visible centre.
export function addFrame(at) {
  if (editBlocked()) return null;
  let b = null;
  if (!at && S.selDf != null && dfNode(S.selDf)) {
    const nid = nidOf(S.selDf), ids = new Set([nid]);
    try { computeChains(serialize()).keys.forEach((arr) => { if (arr.includes(nid)) arr.forEach((i) => ids.add(i)); }); } catch (e) { /* keep the single node */ }
    ids.forEach((i) => {
      const dfid = nidToDf.get(i); if (dfid == null) return;
      if (i !== nid && model(dfid).kind === 'state') return;   // a chain's source / target state hubs stay outside its group
      const nb = nodeBox(dfid);
      b = b ? { x0: Math.min(b.x0, nb.x0), y0: Math.min(b.y0, nb.y0), x1: Math.max(b.x1, nb.x1), y1: Math.max(b.y1, nb.y1) } : nb;
    });
  }
  let x, y, w, hh;
  if (b) { x = b.x0 - FRAME_PAD.l; y = b.y0 - FRAME_PAD.t; w = b.x1 - b.x0 + FRAME_PAD.l + FRAME_PAD.r; hh = b.y1 - b.y0 + FRAME_PAD.t + FRAME_PAD.b; }
  else {
    const st = $('#stage').getBoundingClientRect(), c = at && typeof at.x === 'number' && !at.target ? at : canvasPoint(st.x + st.width / 2, st.y + st.height / 2);
    w = 420; hh = 260; x = at ? c.x : c.x - w / 2; y = at ? c.y : c.y - hh / 2;   // at a given point: top-left corner there
  }
  const used = new Set(frames().map((f) => f.id));
  let k = 1; while (used.has('f' + k)) k++;
  const f = { id: 'f' + k, title: 'Groupe ' + (frames().length + 1), color: FRAME_COLORS[frames().length % FRAME_COLORS.length][1],
    x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(hh) };
  // L8: a new group inside another one (or a column) is its child
  const host = dropTarget(frameBox(f), null, { frame: true });
  if (host) { f.parent = host.id; frames().push(f); fitAncestors(host); } else frames().push(f);
  S.selFrame = null; selectFrame(f.id);
  scheduleTree(); commitSoon();
}
export function focusFrame(id) {
  const f = frameById(id); if (!f) return;
  focusRect({ x0: f.x, y0: f.y, x1: f.x + f.w, y1: f.y + f.h });
  selectFrame(id);
}
export function renderFrameInspector(box, f) {
  // L10: a column (auto frame of a state) says which state it holds, how many chains and problems it contains
  const st = f.auto ? colState(f) : null;
  box.append(h('div', { class: 'insttitle' }, ico(f.auto ? colIcon(st) : 'square', f.auto ? colColor(st) : f.color), f.auto ? 'Colonne' : 'Groupe', h('small', { class: 'hint' }, f.id)));
  if (f.auto) {
    const desc = st === 'global' ? 'Règles globales : valables dans tous les états, évaluées avant celles de l’état courant.' : stateDesc(st);
    if (desc) box.append(h('p', { class: 'hint' }, desc));
    const s = treeStats('col:' + f.id);
    box.append(h('p', { class: 'hint colstat' }, s.chains + ' chaîne(s) · ✖ ' + s.err + ' · ⚠ ' + s.warn + ' (nœuds en erreur / avertissement)'));
    if (domainList().length) {     // lot S1: the domain of the column (organisation only) and its fold
      const sel = h('select', { class: 'coldomain', 'aria-label': 'Domaine de la colonne' });
      domainList().forEach((d) => sel.append(h('option', { value: d.id }, d.label)));
      sel.value = domainOfCol(st);
      sel.addEventListener('change', () => { if (!moveColumnToDomain(st, sel.value)) sel.value = domainOfCol(st); renderInspector(); });
      box.append(field('Domaine', sel, 'Range la colonne (et tout son contenu) dans un autre domaine. Le comportement du robot ne change pas.'));
      box.append(checkCtl('Repliée en carte', isColFolded(st), () => foldColumn(st, !isColFolded(st)), 'square'));
      const dm = domainById(domainOfCol(st));
      if (dm && dm.note) box.append(h('p', { class: 'hint coldomnote' }, dm.note));
    }
  }
  const name = textCtl(f.title, (v) => editFrame(f, { title: v.slice(0, 60) }));
  name.maxLength = 60;
  box.append(field('Nom', name));
  const sw = h('div', { class: 'swatches' });
  FRAME_COLORS.forEach(([n, c]) => sw.append(h('button', { type: 'button', class: 'sw' + (c === f.color ? ' on' : ''), title: n, 'aria-label': n,
    style: 'background:' + c, onclick: () => editFrame(f, { color: c }, true) })));
  const custom = h('input', { type: 'color', class: 'swc', title: 'Couleur personnalisée' });
  custom.value = f.color;
  custom.addEventListener('change', () => editFrame(f, { color: custom.value.toLowerCase() }, true));
  sw.append(custom);
  box.append(h('div', { class: 'fld' }, h('span', {}, 'Couleur'), sw));
  box.append(field('Note', areaCtl(f.note || '', (v) => editFrame(f, { note: v }), 2000), 'Texte libre, purement décoratif : le robot ne le lit pas.'));
  if (parentOf(f)) box.append(h('p', { class: 'hint fparent' }, 'Dans le groupe « ' + (parentOf(f).title || parentOf(f).id) + ' » (glisser ce groupe hors de lui pour l’en sortir).'));
  box.append(h('p', { class: 'hint' }, 'Un groupe ne change rien au comportement du robot : il sert seulement à ranger le graphe. Glisser la barre de titre déplace aussi les nœuds, les groupes et les post-it qu’il contient ; un groupe ou un post-it lâché avec le pointeur sur un groupe ou une colonne en fait partie, quelle que soit sa taille (une colonne d’état, elle, reste au premier niveau).'));
  box.append(h('button', { type: 'button', class: 'danger', onclick: () => deleteFrame(f.id) }, 'Supprimer le groupe (son contenu reste)'));
}

export function bbox() {
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  for (const dfid in dfData()) { const b = nodeBox(dfid); x0 = Math.min(x0, b.x0); y0 = Math.min(y0, b.y0); x1 = Math.max(x1, b.x1); y1 = Math.max(y1, b.y1); }
  return x0 > x1 ? null : { x0, y0, x1, y1 };
}
function fitZoom() {
  const b = worldBounds(), c = $('#drawflow');   // S1: the domain regions (even empty ones) are part of the world; S2: + frames
  if (!b) return 1;
  // L7: the column layout is wide (~14 000 px): allow a smaller zoom so "Ajuster" really shows everything; S2: no floor
  return Math.max(1e-4, Math.min(1, c.clientWidth / ((b.x1 - b.x0) * 1.1), c.clientHeight / ((b.y1 - b.y0) * 1.1)));
}
// "Ajuster": whole graph, centred, ~5 % padding each side.
export function fit() {
  const b = worldBounds(), c = $('#drawflow');
  if (!b) return;
  // L6: leave the measured jump bar row plus one column-title row (titles never draw smaller than ~14 px) free
  const jbb = jumpbarBottom(), jbH = jbb == null ? 38 : jbb - c.getBoundingClientRect().top;
  const t0 = S.editor.precanvas.querySelector('.frame.auto .ftitle'), titleH = t0 ? t0.offsetHeight * (14 / 13) : 22;
  const w = b.x1 - b.x0, hh = b.y1 - b.y0, top = jbH + JUMP_GAP + titleH;
  const z = Math.min(fitZoom(), (c.clientHeight - top) / (hh * 1.08));
  setView(z, (c.clientWidth - w * z) / 2 - b.x0 * z, top + (c.clientHeight - top - hh * z) / 2 - b.y0 * z);
  clearJumpbar();
}
// Jump to a state band: fit it to the canvas (or use a fixed readable zoom when given). S2: opts {min, max} bound the
// fit (default: the world-derived zoom_min .. 1, no fixed 0.1 floor).
export function focusRect(r, zoom, opts) {
  const c = $('#drawflow'), o = opts || {};
  const w = r.x1 - r.x0, hh = r.y1 - r.y0;
  const lo = o.min != null ? o.min : S.editor.zoom_min, hi = o.max != null ? o.max : 1;
  const z = zoom || Math.max(lo, Math.min(hi, c.clientWidth / (w * 1.05), c.clientHeight / (hh * 1.05)));
  const cx = w * z <= c.clientWidth ? (c.clientWidth - w * z) / 2 - r.x0 * z : 20 - r.x0 * z;
  const cy = hh * z <= c.clientHeight ? (c.clientHeight - hh * z) / 2 - r.y0 * z : 20 - r.y0 * z;
  setView(z, cx, cy);
  return true;
}
export function focusBand(gid, zoom) {
  const r = bandRects()[gid];
  return r ? focusRect(r, zoom) : false;
}
// First view: the true fit when readable, else a readable zoom on the start state's band.
export function initialView() {
  if (fitZoom() >= 0.5) { fit(); return; }
  // L7 / Vars L2: open on the top-left corner of the start state's column (its first chains) at a readable
  // zoom, so the column titles run along the top of the screen. L4: no Start node, the start state is veille.
  const r = bandRects().veille;
  if (!r) { fit(); return; }
  const x0 = r.x0, z = 0.75;
  setView(z, 16 - x0 * z, 16 - (r.y0 - 30) * z);
  clearJumpbar();
}
export function setView(z, cx, cy) {
  // Drawflow scales around the centre of its canvas (no transform-origin), so convert the wanted
  // top-left based translation: screen = tx + O + z*(p - O)  =>  tx = cx - O*(1 - z).
  const ox = S.editor.precanvas.clientWidth / 2, oy = S.editor.precanvas.clientHeight / 2;
  cx -= ox * (1 - z); cy -= oy * (1 - z);
  S.editor.zoom = z; S.editor.zoom_last_value = z; S.editor.canvas_x = cx; S.editor.canvas_y = cy;
  S.editor.precanvas.style.transform = `translate(${cx}px, ${cy}px) scale(${z})`;
  zoomVars();
}
export function focusNode(nid) {
  const dfid = nidToDf.get(nid);
  if (dfid == null) return;
  const d = dfNode(dfid), st = $('#drawflow'), z = Math.max(S.editor.zoom, 0.6);
  setView(z, st.clientWidth / 2 - (d.pos_x + 107) * z, st.clientHeight / 2 - (d.pos_y + 40) * z);
  selectDf(dfid);
}
export function canvasPoint(clientX, clientY) {
  const r = S.editor.precanvas.getBoundingClientRect();
  return { x: (clientX - r.x) / S.editor.zoom, y: (clientY - r.y) / S.editor.zoom };
}
