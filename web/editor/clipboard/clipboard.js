/**
 * Selection and fragment clipboard (lot L10).
 *
 * Purpose :  selection (node / chain / group / post-it), copy / cut / paste / duplicate as one undo step through one
 *            rebuild.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, inspector/property-picker.js, core/api.js, canvas/nodes.js, core/serialize.js,
 *            core/history.js, diagnostics/analysis.js, canvas/view.js, canvas/wires.js, frames/groups.js,
 *            frames/nesting.js, frames/notes.js, canvas/navigation.js, menu/context-menu.js, menu/node-menu.js,
 *            hierarchy/tree.js, inspector/inspector.js, core/ui.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, clone } from '../core/util.js';
import { S, KINDS, NODE_KINDS, NOTE_COLORS, freshIds, linkKey, linkProblem, nidToDf } from '../core/state.js';
import { isEnterTrig } from '../inspector/property-picker.js';
import { dfData, dfNode, model, nidOf } from '../core/api.js';
import { addNodeFromModel, nodeEl, refreshNode } from '../canvas/nodes.js';
import { rebuild, serialize } from '../core/serialize.js';
import { commit, commitSoon } from '../core/history.js';
import { analyze } from '../diagnostics/analysis.js';
import { nodeBox } from '../canvas/view.js';
import { paintWires } from '../canvas/wires.js';
import { FRAME_COLORS, frameById, frameEls, frames } from '../frames/groups.js';
import { FOLD_COL } from '../canvas/geometry.js';
import {
  addFrame, canvasPoint, deleteFrame, descendantFrames, drawFrames, dropTargetAt, editFrame, editFrameTitle,
  fitAncestors, selectFrame
} from '../frames/nesting.js';
import { addNote, deleteNote, editNote, noteById, noteEls, notes, selectNote } from '../frames/notes.js';
import { editBlocked, readOnlyMenu } from '../canvas/navigation.js';
import { catRows, filterRows, insertSub, kindsAfter, openCtx } from '../menu/context-menu.js';
import { addAt, defaultModel, selectDf } from '../menu/node-menu.js';
import { COL_TOP, chainRef, fileMenu, treeChains } from '../hierarchy/tree.js';
import { renderInspector } from '../inspector/inspector.js';
import { toast } from '../core/ui.js';

// ---------- selection and clipboard (lot L10) ----------
// The selection is ONE of: a node (selDf), a chain picked in the hierarchy (selChain: all its nodes, highlighted
// together), a group or a column (selFrame), a post-it (selNote). The clipboard holds a fragment {nodes, links, frames,
// notes} in canvas coordinates: links between copied nodes are kept, a group brings its sub-groups, the nodes whose
// centre is inside it and the post-its of its subtree (a column brings its content, never itself: columns are the
// server's). Paste = fresh ids, fragment top-left on the paste point, top-level items filed in the frame under that point.
// Paste, cut and duplicate are ONE undo step each: the document is edited as data, rebuilt once, then committed.
// shared state: S.clipboard (core/state.js)
// shared state: S.selChain (core/state.js)             // {tid, ids}: trigger id (null for a multi-node paste) + node ids, trigger first
export const hasSelection = () => S.selDf != null || !!S.selChain || !!S.selFrame || !!S.selNote;
export function paintChainSel() {
  if (!S.editor) return;
  const on = new Set(S.selChain ? S.selChain.ids : []);
  for (const dfid in dfData()) { const el = nodeEl(dfid); if (el) el.classList.toggle('chainsel', on.has(nidOf(dfid))); }
}
export function clearChainSel() { if (!S.selChain) return false; S.selChain = null; paintChainSel(); return true; }
// S2: a node hidden by a fold belongs to its own column (by its `group`) and to hidden frames only: a fold repack slides
// the neighbours over the folded column's former area, geometry alone would hand them its hidden nodes (and back). A
// folded column (card) holds what lies on its card, plus its hidden nodes.
export const inFrame = (f, dfid) => {
  const el = nodeEl(dfid), m = model(dfid), fe = frameEls.get(f.id);
  if (el && el.parentElement && el.parentElement.classList.contains('fold-hide') && m && m.group && frameById('auto-' + m.group)) {
    if (f.id === 'auto-' + m.group) return true;
    if (!(fe && fe.classList.contains('fold-hide'))) return false;
  }
  const b = nodeBox(dfid), cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2, card = !!(fe && fe.classList.contains('folded'));
  return cx >= f.x && cx <= f.x + (card ? FOLD_COL.w : f.w) && cy >= f.y && cy <= f.y + (card ? FOLD_COL.h : f.h);
};
// What belongs to frame `f` for a copy or a move: the frame and its descendant frames, the nodes whose centre is inside
// it, the post-its of the whole subtree (same membership as a title-bar drag).
export function frameMembers(f) {
  const sub = [f].concat(descendantFrames(f)), ids = new Set(sub.map((g) => g.id));
  return { frames: sub, dfids: Object.keys(dfData()).filter((dfid) => inFrame(f, dfid)), notes: notes().filter((n) => n.parent && ids.has(n.parent)) };
}
function selectionFragment() {
  const nids = new Set(), fids = new Set(), pids = new Set();
  if (S.selChain) S.selChain.ids.forEach((i) => nids.add(i));
  else if (S.selDf != null && model(S.selDf)) nids.add(nidOf(S.selDf));
  else if (S.selFrame && frameById(S.selFrame)) {
    const mb = frameMembers(frameById(S.selFrame));
    mb.frames.forEach((g) => { if (!g.auto) fids.add(g.id); });
    mb.dfids.forEach((d) => nids.add(nidOf(d)));
    mb.notes.forEach((n) => pids.add(n.id));
  } else if (S.selNote && noteById(S.selNote)) pids.add(S.selNote);
  const d = serialize();
  const nodes = d.nodes.filter((n) => nids.has(n.id) && n.kind !== 'state' && n.kind !== 'start'), keep = new Set(nodes.map((n) => n.id));
  const frag = { nodes, links: d.links.filter((l) => keep.has(l.from) && keep.has(l.to)),
    frames: clone(frames().filter((f) => fids.has(f.id))), notes: clone(notes().filter((n) => pids.has(n.id))) };
  return frag.nodes.length || frag.frames.length || frag.notes.length ? frag : null;
}
const fragSize = (c) => [c.nodes.length ? c.nodes.length + ' nœud(s)' : '', c.frames.length ? c.frames.length + ' groupe(s)' : '',
  c.notes.length ? c.notes.length + ' post-it' : ''].filter(Boolean).join(', ');
export function copySelection(quiet) {
  const m = S.selDf != null ? model(S.selDf) : null;
  if (m && (m.kind === 'state' || m.kind === 'start')) { toast('Un nœud ' + KINDS[m.kind].label + ' est unique : il ne se copie pas.', 'err'); return false; }
  const frag = selectionFragment();
  if (!frag) { if (!quiet) toast('Rien à copier : sélectionnez un nœud, une chaîne, un groupe ou un post-it.', 'err'); return false; }
  S.clipboard = frag;
  if (!quiet) toast('Copié : ' + fragSize(frag) + '.', 'ok');
  return true;
}
// Remove a fragment's items from a serialized document (wires touching a removed node go too).
function dropFragment(doc, frag) {
  const nids = new Set(frag.nodes.map((n) => n.id)), fids = new Set(frag.frames.map((f) => f.id)), pids = new Set(frag.notes.map((n) => n.id));
  doc.nodes = doc.nodes.filter((n) => !nids.has(n.id));
  doc.links = doc.links.filter((l) => !nids.has(l.from) && !nids.has(l.to));
  doc.frames = (doc.frames || []).filter((f) => !fids.has(f.id));
  doc.notes = (doc.notes || []).filter((n) => !pids.has(n.id));
}
const COL_NO_CUT = 'Une colonne d’état ne se coupe pas et ne se duplique pas : copiez-la, ou sélectionnez ses groupes et ses chaînes.';
export function cutSelection() {
  if (editBlocked()) return false;
  if (S.selFrame && (frameById(S.selFrame) || {}).auto) { toast(COL_NO_CUT, 'err'); return false; }
  if (!copySelection(true)) { toast('Rien à couper : sélectionnez un nœud, une chaîne, un groupe ou un post-it.', 'err'); return false; }
  const doc = serialize();
  dropFragment(doc, S.clipboard);
  S.selFrame = null; S.selNote = null; S.selChain = null;
  rebuild(doc, true); commit();
  toast('Coupé : ' + fragSize(S.clipboard) + ' (Ctrl+V pour coller, Ctrl+Z pour annuler).', 'ok');
  return true;
}
// A chain selected in the hierarchy: its nodes are deleted together (one undo step).
export function deleteSelection() {
  if (editBlocked() || !S.selChain) return false;
  const frag = selectionFragment(); if (!frag) return false;
  const doc = serialize();
  dropFragment(doc, frag); S.selChain = null;
  rebuild(doc, true); commit();
  return true;
}
// Paste fragment `c` with its top-left at canvas point `pt` (default: centre of the view). Returns the new ids.
export function pasteFragment(c, pt) {
  if (!c || editBlocked()) return null;
  if (!pt) { const st = $('#stage').getBoundingClientRect(); pt = canvasPoint(st.x + st.width / 2 - 100, st.y + st.height / 2 - 40); }
  const all = c.nodes.concat(c.frames, c.notes);
  const dx = Math.round(pt.x - Math.min(...all.map((o) => o.x || 0))), dy = Math.round(pt.y - Math.min(...all.map((o) => o.y || 0)));
  const host = dropTargetAt(pt);                       // the frame under the paste point owns the top-level pasted items
  const doc = serialize(), nmap = {}, fmap = {}, out = { nodes: [], frames: [], notes: [] };
  let k = S.idCounter;
  doc.nodes.forEach((n) => { const mm = /^n(\d+)$/.exec(n.id); if (mm) k = Math.max(k, +mm[1]); });
  c.nodes.forEach((n) => {
    const m = clone(n); m.id = 'n' + (++k); nmap[n.id] = m.id; m.x = n.x + dx; m.y = n.y + dy;
    if (m.kind === 'trigger' && m.params) delete m.params.fan;   // a pasted trigger is a fresh one
    doc.nodes.push(m); freshIds.add(m.id); out.nodes.push(m.id);
  });
  S.idCounter = k;
  c.links.forEach((l) => doc.links.push(Object.assign(clone(l), { from: nmap[l.from], to: nmap[l.to] })));
  const usedF = new Set((doc.frames || []).map((f) => f.id)), usedP = new Set((doc.notes || []).map((n) => n.id));
  const fresh = (used, p) => { let i = 1; while (used.has(p + i)) i++; used.add(p + i); return p + i; };
  c.frames.forEach((f) => { fmap[f.id] = fresh(usedF, 'f'); });
  const top = host ? host.id : null;
  doc.frames = (doc.frames || []).concat(c.frames.map((f) => {
    const g = Object.assign(clone(f), { id: fmap[f.id], x: f.x + dx, y: f.y + dy, parent: fmap[f.parent] || top }); delete g.auto;
    out.frames.push(g.id); return g;
  }));
  doc.notes = (doc.notes || []).concat(c.notes.map((n) => {
    const o = Object.assign(clone(n), { id: fresh(usedP, 'p'), x: n.x + dx, y: n.y + dy, parent: fmap[n.parent] || top }); delete o.auto;
    out.notes.push(o.id); return o;
  }));
  S.selFrame = null; S.selNote = null; S.selChain = null;
  rebuild(doc, true);
  const h2 = host && frameById(host.id); if (h2) { fitAncestors(h2); drawFrames(); }
  commit();
  // the pasted items become the selection: one node, else the top pasted group, else a post-it, else all the nodes
  const topFrame = c.frames.filter((f) => !fmap[f.parent]).map((f) => fmap[f.id])[0];
  if (out.nodes.length === 1 && !out.frames.length && !out.notes.length) selectDf(nidToDf.get(out.nodes[0]));
  else if (topFrame) selectFrame(topFrame);
  else if (!out.nodes.length && out.notes.length) selectNote(out.notes[0]);
  else if (out.nodes.length) {
    const trig = out.nodes.find((id) => { const d = nidToDf.get(id); return d != null && model(d).kind === 'trigger'; });
    S.selChain = { tid: trig || null, ids: out.nodes.slice() }; paintChainSel(); renderInspector();
  }
  return out;
}
export function duplicateSelection() {
  if (editBlocked()) return null;
  if (S.selFrame && (frameById(S.selFrame) || {}).auto) { toast(COL_NO_CUT, 'err'); return null; }
  const frag = selectionFragment(); if (!frag) return null;
  const all = frag.nodes.concat(frag.frames, frag.notes);
  return pasteFragment(frag, { x: Math.min(...all.map((o) => o.x || 0)) + 40, y: Math.min(...all.map((o) => o.y || 0)) + 40 });
}
// Older single-node entry points (test hooks, earlier scenarios): same clipboard.
export function copyNode(dfid) { if (String(S.selDf) !== String(dfid)) selectDf(dfid); return copySelection(true); }
export function pasteNode(pt) { return pasteFragment(S.clipboard, pt); }
function duplicateNode(dfid) { if (String(S.selDf) !== String(dfid)) selectDf(dfid); return duplicateSelection(); }
function toggleChain(dfid) {
  const m = model(dfid); if (!m || m.kind !== 'trigger' || isEnterTrig(m)) return;
  m.params.enabled = m.params.enabled === false;           // false -> true, true/undefined -> false
  if (m.params.enabled === true) delete m.params.enabled;
  refreshNode(dfid); if (S.selDf === dfid) renderInspector();
  analyze(); commitSoon();
}
// L10: "Désactiver la chaîne" on any node: the (non entry) triggers whose chains reach it, all switched together
// (any of them enabled -> all disabled, else all enabled again).
function chainTriggersOf(dfid) {
  const nid = nidOf(dfid);
  return treeChains().filter((c) => !c.orphan && c.ids.includes(nid)).map((c) => c.df).filter((d) => !isEnterTrig(model(d)));
}
export function toggleChains(dfids) {
  if (editBlocked() || !dfids.length) return;
  const off = dfids.some((d) => model(d).params.enabled !== false);
  dfids.forEach((d) => { const p = model(d).params; if (off) p.enabled = false; else delete p.enabled; refreshNode(d); });
  renderInspector(); analyze(); commitSoon();
}
// Link `fromDf` (output class) to `toDf`, honouring the same rules as a manual link.
export function linkNodes(fromDf, outCls, toDf) {
  const a = model(fromDf), b = model(toDf), why = a && b ? linkProblem(a, b) : 'Nœud introuvable.';
  if (why) { toast(why, 'err'); return false; }
  S.editor.addConnection(fromDf, toDf, outCls, 'input_1');
  return true;
}
// Insert a new node after `dfid` (port = output class) and link it.
function insertAfter(dfid, outCls, choice) {
  const d = dfNode(dfid);
  const nd = addAt(choice.kind, choice.preset, { x: d.pos_x + 260, y: d.pos_y }, { select: true });
  if (nd != null) linkNodes(dfid, outCls, nd);
}
// Split the wire (fromDf outCls -> toDf) into from -> new -> to.
function splitWire(w, choice) {
  const a = dfNode(w.out), b = dfNode(w.in);
  if (!a || !b) return;
  const ma = model(w.out), mb = model(w.in);
  const nm = defaultModel(choice.kind, choice.preset), probe = { kind: choice.kind };
  if (linkProblem(ma, probe) || linkProblem(probe, mb)) { toast('Ce nœud ne peut pas s’insérer ici.', 'err'); return; }
  const idx = +w.outCls.split('_')[1], port = ma.kind === 'condition' ? (idx === 1 ? 'true' : 'false') : 'out';
  const oldKey = linkKey(ma.id, port, mb.id), meta0 = S.linkMeta.get(oldKey);
  S.editor.removeSingleConnection(w.out, w.in, w.outCls, 'input_1');
  S.linkMeta.delete(oldKey);
  const x = Math.round((a.pos_x + b.pos_x) / 2), y = Math.round((a.pos_y + b.pos_y) / 2);
  freshIds.add(nm.id);
  const nd = addNodeFromModel(nm, x, y);
  S.editor.addConnection(w.out, nd, w.outCls, 'input_1');
  S.editor.addConnection(nd, w.in, 'output_1', 'input_1');
  if (meta0) S.linkMeta.set(linkKey(nm.id, 'out', mb.id), meta0);   // the hop into a state keeps its reason / description
  selectDf(nd); commitSoon(); analyze(); paintWires();
}
function colorMenu(list, cur, apply) {
  return list.map(([nm, c]) => ({ label: nm + (c === cur ? ' ✓' : ''), icon: 'square', color: c, fn: () => apply(c) }));
}
// Build and open the menu that matches what was right-clicked (lot L10 layout). Every menu but a wire's ends with the
// canvas part: Post-it, Groupe de nœuds, then Copier la sélection / Couper / Coller; on the bare canvas it starts with the
// three node categories (inserted at the click point). On a node, a group or a post-it it starts with what acts on that
// item: Copier, Couper, Dupliquer, Supprimer (+ Désactiver la chaîne on a node), Ranger dans le groupe ▸. A node keeps
// "Insérer après" (linked to its output); a wire keeps "Insérer un nœud au milieu" / "Supprimer le fil".
export function openContextFor(e) {
  const t = e.target, x = e.clientX, y = e.clientY, pt = canvasPoint(x, y);
  const noteEl = t.closest('.postit'), frameEl = t.closest('.frame'), nodeElm = t.closest('.drawflow-node'), pathEl = t.closest('path.main-path');
  const atPoint = (c) => addAt(c.kind, c.preset, pt, { exact: true });
  const tail = () => [
    { label: 'Post-it', icon: 'message', tip: 'Un post-it au point du clic (touche N : au centre de la vue).', fn: () => addNote(pt) },
    { label: 'Groupe de nœuds', icon: 'square', tip: 'Un groupe autour de la sélection ; sans nœud ni chaîne sélectionné, un groupe vide au point du clic (touche G).',
      fn: () => (S.selDf != null || S.selChain ? addFrame() : addFrame(pt)) },
    { sep: true },
    { label: 'Copier la sélection', icon: 'text-caption', key: 'Ctrl+C', disabled: !hasSelection(), fn: () => copySelection() },
    { label: 'Couper', icon: 'eraser', key: 'Ctrl+X', disabled: !hasSelection(), fn: cutSelection },
    { label: 'Coller', icon: 'arrow-right', key: 'Ctrl+V', disabled: !S.clipboard, tip: 'Colle au point du clic.', fn: () => pasteFragment(S.clipboard, pt) }];
  const acts = (o) => [
    { label: 'Copier', icon: 'text-caption', key: 'Ctrl+C', disabled: !o.copy, fn: () => copySelection() },
    { label: 'Couper', icon: 'eraser', key: 'Ctrl+X', disabled: !o.cut, tip: o.cutTip || null, fn: cutSelection },
    { label: 'Dupliquer', icon: 'plus', disabled: !o.cut, tip: o.cutTip || null, fn: duplicateSelection },
    { label: 'Supprimer', icon: 'x', key: 'Suppr', fn: o.del }]
    .concat(o.extra || [], [{ label: 'Ranger dans le groupe', icon: 'square', disabled: !o.file, tip: o.fileTip || null, sub: o.file ? () => fileMenu(o.file) : null }]);
  let items, filter = null;
  if (noteEl) {
    const n = noteById(noteEl.dataset.nid);
    if (n) selectNote(n.id, true);
    items = acts({ copy: true, cut: true, del: () => deleteNote(n.id), file: { what: 'note', id: n.id } }).concat([{ sep: true },
      { label: 'Modifier', icon: 'eraser', fn: () => { const ta = noteEls.get(n.id).querySelector('textarea'); ta.focus(); } },
      { label: 'Couleur', icon: 'square', sub: colorMenu(NOTE_COLORS, n.color, (c) => editNote(n, { color: c }, true)) },
      { sep: true }], tail());
  } else if (frameEl && frameEl.dataset.fid) {
    const f = frameById(frameEl.dataset.fid);
    selectFrame(f.id);
    items = acts({ copy: true, cut: !f.auto, cutTip: f.auto ? COL_NO_CUT : null, del: () => deleteFrame(f.id),
      file: f.auto ? null : { what: 'group', id: f.id }, fileTip: f.auto ? COL_TOP : null }).concat([{ sep: true },
      { label: 'Renommer', icon: 'eraser', fn: () => editFrameTitle(f) },
      { label: 'Couleur', icon: 'square', sub: colorMenu(FRAME_COLORS, f.color, (c) => editFrame(f, { color: c }, true)) },
      { sep: true }], tail());
  } else if (nodeElm) {
    const dfid = nodeElm.id.replace('node-', ''), m = model(dfid);
    selectDf(dfid);
    const own = m.kind !== 'state' && m.kind !== 'start';
    const trig = chainTriggersOf(dfid), anyOn = trig.some((d) => model(d).params.enabled !== false);
    const extra = trig.length ? [{ label: anyOn ? 'Désactiver la chaîne' : 'Activer la chaîne', icon: 'power', fn: () => toggleChains(trig) }] : [];
    items = acts({ copy: own, cut: own, del: () => S.editor.removeNodeId('node-' + dfid), extra, file: chainRef(m.id) });
    const kinds = kindsAfter(m.kind);
    const ports = m.kind === 'condition' ? [['output_1', ' (Vrai)'], ['output_2', ' (Faux)']] : [['output_1', '']];
    items.push({ sep: true });
    ports.forEach(([cls, suffix]) => items.push({ label: 'Insérer après' + suffix, icon: 'plus', disabled: !kinds.length,
      sub: kinds.length ? insertSub(kinds, (c) => insertAfter(dfid, cls, c)) : null }));
    items = items.concat([{ sep: true }], tail());
    if (kinds.length) filter = filterRows(kinds, (c) => insertAfter(dfid, 'output_1', c));
  } else if (pathEl && pathEl.parentElement.classList.length >= 5) {
    const cl = pathEl.parentElement.classList, w = { in: cl[1].slice(13), out: cl[2].slice(14), outCls: cl[3] };
    S.selConn = w;
    const ma = model(w.out), mb = model(w.in);
    const ok = ['condition', 'action'].filter((k) => !linkProblem(ma, { kind: k }) && !linkProblem({ kind: k }, mb) && !(k === 'condition' && ma.kind === 'action'));
    items = [
      { label: 'Insérer un nœud au milieu', icon: 'plus', disabled: !ok.length, sub: ok.length ? insertSub(ok, (c) => splitWire(w, c)) : null },
      { sep: true },
      { label: 'Supprimer le fil', icon: 'x', fn: () => { S.editor.removeSingleConnection(w.out, w.in, w.outCls, 'input_1'); S.selConn = null; renderInspector(); } }];
    if (ok.length) filter = filterRows(ok, (c) => splitWire(w, c));
  } else {
    items = catRows(NODE_KINDS, atPoint).concat([{ sep: true }], tail());
    filter = filterRows(NODE_KINDS, atPoint);
  }
  if (editBlocked(true)) { items = readOnlyMenu(items); filter = null; }
  openCtx(x, y, items, filter);
}
