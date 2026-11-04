/**
 * Editor core: boot.
 *
 * Purpose :  boot(): Drawflow creation, Drawflow hooks, toolbar wiring, first load.
 * Boundary:  creates the Drawflow editor (vendored, MIT) and wires the page; network through core/api.js: GET /api/graph,
 *            POST /api/graph/reset. Moved unchanged out of the former single-file editor.js (lot M6).
 *            L22: the boot is a progress task: editor.html shows the bar (indeterminate) from the first paint, boot()
 *            takes it over (modules loaded = 40 %, Drawflow ready, graph loaded) and ends it; « Valider » is a covering
 *            task (fresh server dry run, then the client summary).
 * Depends :  core/util.js, tooltips/tooltips.js, core/state.js, core/api.js, core/history.js, diagnostics/check.js,
 *            canvas/wires.js, minimap/overview.js, minimap/minimap.js, frames/nesting.js, frames/notes.js,
 *            canvas/navigation.js, menu/context-menu.js, clipboard/clipboard.js, menu/node-menu.js, hierarchy/tree.js,
 *            inspector/inspector.js, core/ui.js, core/actions.js, panels/live.js, panels/history-panels.js,
 *            canvas/trigger-guard.js, export/export.js, core/debug.js, core/progress.js, canvas/culling.js, canvas/wiredraw.js (S3)
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, h } from './util.js';
import { installTips } from '../tooltips/tooltips.js';
import { S, linkKey, linkProblem, nidToDf } from './state.js';
import { AUTO_DELAY_MS, api, dfData, model, postJson } from './api.js';
import { commitSoon, isDirty, redo, undo } from './history.js';
import { diagCycle, freshCheck } from '../diagnostics/check.js';
import { installRetHover, paintDragWire, paintWires, retVisible, setRetVisible } from '../canvas/wires.js';
import { scheduleMinimap, zoomVars } from '../minimap/overview.js';
import { miniMove, miniUp } from '../minimap/minimap.js';
import {
  addFrame, canvasPoint, deleteFrame, drawFrames, endFrameDrag, fit, moveFrameDrag, unselectFrame
} from '../frames/nesting.js';
import { addNote, deleteNote, endNoteDrag, moveNoteDrag, noteEls, unselectNote } from '../frames/notes.js';
import { editBlocked, installButtonGuards, installSafeNav } from '../canvas/navigation.js';
import { ctxKey } from '../menu/context-menu.js';
import {
  clearChainSel, copySelection, cutSelection, deleteSelection, hasSelection, pasteFragment
} from '../clipboard/clipboard.js';
import { addAt } from '../menu/node-menu.js';
import { installTree, treeFilterKey, treeKey } from '../hierarchy/tree.js';
import { renderInspector } from '../inspector/inspector.js';
import { modal, toYaml, toast } from './ui.js';
import { loadAll, save, validate } from './actions.js';
import { activateTab, connectWs, paintHeart, pollLive } from '../panels/live.js';
import { loadJournal } from '../panels/history-panels.js';
import { installTriggerDropGuard } from '../canvas/trigger-guard.js';
import { toggleExport } from '../export/export.js';
import { runDebug } from './debug.js';
import { startTask, track } from './progress.js';
import { bumpGeo, setGeoListener } from '../canvas/geometry.js';
import { applyCull } from '../canvas/culling.js';
import { fastUpdate, markWiresDirty } from '../canvas/wiredraw.js';

// ---------- boot ----------
export async function boot() {
  // L22: every module is loaded when this runs; the rest of the boot is the graph load
  const task = startTask("Chargement de l'éditeur", { progress: 0.4, covers: true });
  try {
    await bootSteps(task);
    task.done();
  } catch (e) { task.fail(); throw e; }       // main.js toasts the boot error
}
async function bootSteps(task) {
  // Test hook: `#hold=<port>` keeps the page "loading" until a slow local image answers, so a headless
  // `firefox --screenshot` (taken at the load event) sees the finished async rendering.
  const hold = (location.hash.match(/hold=(\d+)/) || [])[1];
  if (hold) document.body.append(h('img', { src: 'http://127.0.0.1:' + hold + '/hold.gif', width: 1, height: 1 }));
  S.editor = new Drawflow($('#drawflow'));
  S.editor.reroute = false;
  // S2: zoom_min is derived from the world (frames/nesting.js updateZoomMin, after every frame redraw); 0.01 until then
  S.editor.zoom_min = 0.01; S.editor.zoom_max = 1.6;
  S.editor.start();
  S.editor.on('nodeSelected', (id) => {
    clearChainSel();
    S.selDf = id; S.selConn = null;
    applyCull();                                // S3: a node selected from the hierarchy / a search may be culled
    if (S.selFrame) { S.selFrame = null; drawFrames(); }
    if (S.selNote) { S.selNote = null; noteEls.forEach((el) => el.classList.remove('sel')); }
    renderInspector(); if (innerWidth <= 900) document.body.classList.remove('hide-right');
  });
  S.editor.on('nodeUnselected', () => { S.selDf = null; renderInspector(); });
  S.editor.on('connectionSelected', (c) => {
    S.selConn = { out: c.output_id, in: c.input_id, outCls: c.output_class }; S.selDf = null;
    if (S.selNote) { S.selNote = null; noteEls.forEach((el) => el.classList.remove('sel')); }
    renderInspector(); if (innerWidth <= 900) document.body.classList.remove('hide-right');
  });
  S.editor.on('connectionUnselected', () => { S.selConn = null; renderInspector(); });
  S.editor.on('nodeMoved', () => { bumpGeo(); commitSoon(); });   // S2: node boxes moved: cached world stale
  S.editor.on('nodeRemoved', (id) => { markWiresDirty(); if (S.loading) return; for (const [k, v] of nidToDf) if (String(v) === String(id)) nidToDf.delete(k); S.selDf = null; renderInspector(); commitSoon(); });
  S.editor.on('connectionCreated', (c) => {
    markWiresDirty();                           // S3: the wire list of the culling pass
    if (S.loading) return;
    const a = model(c.output_id), b = model(c.input_id), why = a && b ? linkProblem(a, b) : null;
    if (why) {                                  // same rules as the server; the wire is dropped at once
      S.editor.removeSingleConnection(c.output_id, c.input_id, c.output_class, c.input_class);
      toast(why, 'err'); return;
    }
    commitSoon();
  });
  S.editor.on('connectionRemoved', (c) => {
    markWiresDirty();
    const a = model(c.output_id), b = model(c.input_id);
    if (a && b) { const idx = +c.output_class.split('_')[1]; S.linkMeta.delete(linkKey(a.id, a.kind === 'condition' ? (idx === 1 ? 'true' : 'false') : 'out', b.id)); }
    if (S.selConn && String(S.selConn.out) === String(c.output_id) && String(S.selConn.in) === String(c.input_id)) S.selConn = null;
    commitSoon();
  });
  // Wires are repainted (gradient from the source kind colour to the target kind colour) whenever Drawflow redraws them.
  const origUpdate = S.editor.updateConnectionNodes.bind(S.editor);
  // S3: Drawflow's getModuleFromNodeId walks EVERY node of every module, twice per addConnection: the load of a 10x graph
  // was quadratic (8 s for 1,800 wires). The editor has a single module, so a node of the current one answers at once.
  const origModule = S.editor.getModuleFromNodeId.bind(S.editor);
  S.editor.getModuleFromNodeId = (id) => (dfData()[id] ? S.editor.module : origModule(id));
  // S3: wires are drawn from the cached geometry (canvas/wiredraw.js; Drawflow's own version scans the DOM and reads
  // rectangles per wire, and reads garbage for a culled node); `origUpdate` only serves wires with reroute points
  S.editor.updateConnectionNodes = (id) => { if (S.loading) return; fastUpdate(origUpdate, id); paintWires(id); };   // loading: wires are drawn at their first view
  // L3: the dragged wire starts with its source node's kind colour (not the red / green port pastille), and a
  // freshly linked wire is painted at once (Drawflow does not redraw a node's wires when a link is created).
  S.editor.on('connectionStart', (c) => { const m = model(c.output_id); S.dragSrcKind = m ? m.kind : null; paintDragWire(); });
  const origDragUpdate = S.editor.updateConnection.bind(S.editor);
  S.editor.updateConnection = (x, y) => { origDragUpdate(x, y); paintDragWire(x, y); };
  S.editor.on('connectionCreated', (c) => { S.dragSrcKind = null; requestAnimationFrame(() => paintWires('node-' + c.output_id)); });
  S.editor.on('connectionCancel', () => { S.dragSrcKind = null; });
  // Lot L4: Drawflow ends a node drag / pan / wire drag on a `mouseup` of its CONTAINER only. Released over a side
  // panel (palette, inspector), the drag never ended: the node stayed glued to the pointer when it came back, and
  // after an undo rebuild the stale `ele_selected` threw TypeErrors on every move. Finish it from window, only when
  // the release happened outside the canvas (inside, Drawflow's own handler already ran and cleared the flags).
  const finishOutside = (e) => {
    if (!(S.editor.drag || S.editor.drag_point || S.editor.connection || S.editor.editor_selected)) return;
    if (S.editor.container.contains(e.target)) return;
    S.editor.dragEnd(e);
  };
  window.addEventListener('mouseup', finishOutside);
  window.addEventListener('touchend', finishOutside);
  installRetHover();
  S.editor.on('zoom', zoomVars); S.editor.on('translate', (p) => { scheduleMinimap(); applyCull(false, p); });   // S3: Drawflow passes the NEW translation (canvas_x / y are stored after the event)
  setGeoListener(scheduleMinimap);    // S2: a node size change seen by the geometry observer redraws the minimap
  setRetVisible(retVisible());
  // Vars L2: no returning wires any more (no hubs); the toggle stays wired only if a page still has the button
  if ($('#btnRet')) $('#btnRet').onclick = () => setRetVisible(!document.body.classList.contains('ret-visible'));
  $('#btnVars').onclick = () => activateTab('vars');
  installButtonGuards();
  installTriggerDropGuard();
  installSafeNav();      // L8: registered before the keydown below so its capture handlers run first

  // Keys typed in inspector fields must never reach Drawflow (its Delete handler would remove the selected node).
  window.addEventListener('keydown', (e) => {
    if (S.ctx) {
      if (e.target.classList && e.target.classList.contains('csearch')) return;   // the menu's search box handles its own keys
      if (ctxKey(e)) return;
    }
    if (e.target.classList && e.target.classList.contains('finput')) return;   // inline group rename handles its own Enter/Escape
    // L10 hierarchy: its filter field, its inline rename and its rows handle their keys here (never reaching Drawflow)
    if (e.target.id === 'treeFilter') { treeFilterKey(e); e.stopPropagation(); return; }
    if (e.target.classList && e.target.classList.contains('hrename')) {
      if (e.key === 'Enter' || e.key === 'Escape') { e.preventDefault(); if (e.target._fin) e.target._fin(e.key === 'Enter'); }
      e.stopPropagation(); return;
    }
    if (e.target.classList && e.target.classList.contains('hrow') && treeKey(e)) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) { e.stopPropagation(); return; }
    if (S.selFrame && e.key === 'Delete') { e.preventDefault(); e.stopPropagation(); deleteFrame(S.selFrame); return; }
    if (S.selNote && e.key === 'Delete') { e.preventDefault(); e.stopPropagation(); deleteNote(S.selNote); return; }
    if (e.key.toLowerCase() === 'g' && !e.ctrlKey && !e.metaKey && !e.altKey && $('#modal').hidden) { e.preventDefault(); addFrame(); return; }
    if (e.key.toLowerCase() === 'n' && !e.ctrlKey && !e.metaKey && !e.altKey && $('#modal').hidden) { e.preventDefault(); addNote(); return; }
    // L10: Ctrl+C / Ctrl+X / Ctrl+V act on the whole selection (node, hierarchy chain, group, post-it); Suppr on a chain
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'c' && hasSelection()) { e.preventDefault(); copySelection(); return; }
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'x' && hasSelection()) { e.preventDefault(); cutSelection(); return; }
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'v' && S.clipboard) { e.preventDefault(); pasteFragment(S.clipboard); return; }
    if (S.selChain && S.selDf == null && e.key === 'Delete') { e.preventDefault(); e.stopPropagation(); deleteSelection(); return; }
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); }
    else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) { e.preventDefault(); redo(); }
  }, true);

  const dfEl = $('#drawflow');
  // Frame and note drags are tracked on the document so they survive the pointer leaving the title bar.
  document.addEventListener('mousemove', moveFrameDrag); document.addEventListener('mouseup', endFrameDrag);
  document.addEventListener('touchmove', moveFrameDrag, { passive: false }); document.addEventListener('touchend', endFrameDrag);
  // notes: ONE pointer pair (captured pointer, see startNoteDrag)
  document.addEventListener('pointermove', moveNoteDrag, { passive: false });
  document.addEventListener('pointerup', endNoteDrag); document.addEventListener('pointercancel', endNoteDrag);
  // minimap drag (L8): captured pointer, so moves / release outside the minimap still arrive here
  document.addEventListener('pointermove', miniMove, { passive: false });
  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach((t) => document.addEventListener(t, miniUp, true));
  // A press on the bare canvas or on a node unselects the frame / note (their own presses stop before here).
  dfEl.addEventListener('mousedown', (e) => { if (!e.target.closest('.drawflow-node')) { unselectFrame(); unselectNote(); if (clearChainSel()) renderInspector(); } });
  dfEl.addEventListener('dragover', (e) => e.preventDefault());
  dfEl.addEventListener('drop', (e) => {
    e.preventDefault();
    if (editBlocked()) return;                 // lock / hand tool: drops refused (L10: no palette; an external drop of the same payload)
    try { const d = JSON.parse(e.dataTransfer.getData('text/plain')); addAt(d.kind, d.preset, canvasPoint(e.clientX, e.clientY)); } catch (err) { /* foreign drop */ }
  });

  installTree();             // L10: left column = hierarchy (filter, rows, drag and drop)
  $('#btnGroup').onclick = () => addFrame();
  $('#btnNote').onclick = () => addNote();
  $('#btnUndo').onclick = undo; $('#btnRedo').onclick = redo; $('#btnFit').onclick = fit;
  $('#btnValidate').onclick = () => track('Vérification du graphe', async () => { await freshCheck(); validate(true); },
    { delay: AUTO_DELAY_MS, covers: true }).catch(() => {});   // L22: fresh dry run first; a failure is already red + toasted
  $('#btnSave').onclick = save;
  $('#btnMsgs').onclick = () => { $('#msgs').hidden = !$('#msgs').hidden; };
  $('#btnDiag').onclick = () => diagCycle();
  $('#btnExport').onclick = toggleExport;     // L14: options popover, then startExport()
  installTips();
  $('#btnLeft').onclick = () => document.body.classList.toggle('hide-left');
  $('#btnRight').onclick = () => document.body.classList.toggle('hide-right');
  document.querySelectorAll('#tabs button').forEach((b) => { b.onclick = () => activateTab(b.dataset.tab); });
  document.addEventListener('click', () => document.querySelectorAll('.ddl').forEach((l) => { l.hidden = true; }));
  $('#btnYaml').onclick = async () => {
    const r = await api('/api/graph');
    if (!r.ok) { toast('Lecture impossible.', 'err'); return; }
    const src = r.json.source ? 'Source : ' + r.json.source + '\n\n' : '';
    modal('Graphe actif (YAML, lecture seule)', h('pre', {}, src + toYaml(r.json)), [{ label: 'Fermer' }]);
  };
  // Same-tab switch to the robot dashboard; unsaved edits are protected by the beforeunload handler below.
  $('#btnDash').onclick = () => { location.href = '/dash'; };
  $('#btnReset').onclick = () => modal('Revenir au graphe par défaut ?',
    h('p', {}, 'Le graphe actuel est sauvegardé, puis remplacé par celui livré avec le robot. Vos positions de nœuds sont effacées.'
      + (isDirty() ? ' Les modifications non enregistrées de cette page (nœuds, groupes, post-it) seront perdues.' : '')),
    [{ label: 'Annuler' }, { label: 'Revenir au graphe par défaut', cls: 'danger', fn: async () => {
      const r = await postJson('/api/graph/reset', {});
      toast(r.ok ? r.json.message : 'Échec (' + r.status + ')', r.ok ? 'ok' : 'err');
      if (r.ok) await loadAll();
    } }]);
  $('#modal').addEventListener('click', (e) => { if (e.target.id === 'modal') $('#modal').hidden = true; });
  if (innerWidth <= 900) { document.body.classList.add('hide-left'); document.body.classList.add('hide-right'); }

  task.set(0.6);
  const vis = await loadAll();
  if (!vis) task.fail();                       // loadAll already toasted why
  else task.set(0.95);
  loadJournal();
  connectWs();
  setInterval(paintHeart, 500);
  setInterval(pollLive, 500);
  // L23: any unsaved edit (nodes, groups, post-its, hierarchy; typing not yet committed included) asks before leaving
  window.addEventListener('beforeunload', (e) => { if (isDirty()) { e.preventDefault(); e.returnValue = ''; } });
  runDebug();
}
