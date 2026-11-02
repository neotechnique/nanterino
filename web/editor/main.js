/**
 * Nanterino visual graph editor (Game Creator 2 style node editor).
 *
 * Purpose : draw / edit the robot dialogue graph as nodes (Trigger, Condition, Action, End; legacy Goto / State) and
 *           round-trip it through the node-document contract (Notes/graph-visual-format.md).
 * Boundary: talks only to GET /api/graph/visual, /api/graph/vocab, /api/graph, /api/graph/versions, /api/graph/vars,
 *           /api/graph/trace, POST /api/graph/visual, /api/graph/simulate, /api/graph/reset,
 *           /api/graph/versions/<id>/restore, /api/graph/check, /api/graph/vars/reset (L12), POST /api/graph/snapshot +
 *           GET /api/graph/snapshot/status + /api/graph/snapshot.png (L14 "Exporter l'image": read-only PNG export), GET /web/vendor/tabler/<name>.svg (icons) and WS /ws (live state,
 *           heartbeat, last_transition). graph.yaml stays the only executed artifact; the server compiles and
 *           validates, this page never decides what is valid on its own (client checks below are structural
 *           hints only). Wave 2 adds: icons (read from the vocabulary, never chosen here), disabled chains,
 *           panels Tester / Versions / Journal, editable intents, forms for say_text / set_expression / wait / gaze.
 *           computeChains() mirrors the server compiler's chain keys (<state>/t<n>, global/t<n>, <state>/enter)
 *           so a simulator or journal entry (which only carries a chain key) can light its nodes.
 *           Groups (cosmetic frames, meta.frames): drawn in #frames, saved only in graph.layout.json by the server;
 *           they never reach graph.yaml.
 *           L6 (2026-10-31): one State node per state (hub; trigger input accepts state links only; no go-to, no auto bands),
 *           gradient wires (paintWires), post-it notes (meta.notes, #notes layer), left-button-only dragging and a right-click
 *           context menu (installButtonGuards / openContextFor), link meta {reason, description} on hops into a state node.
 *           L8: safe navigation (installSafeNav): Space+drag and hand tool (H) pan only, wheel pans / Ctrl+wheel zooms,
 *           persisted read-only lock (L, editBlocked()), canvas view keys, "?" help popover.
 *           Vars L2 (2026-10-31, contract "Variables et triggers sans entrée"): the state is the system variable `etat`;
 *           no State hub / go-to node is drawn any more (a legacy hub only survives as an inert card), a trigger has NO
 *           input port (Drawflow node with 0 inputs + a drop guard that toasts), "etat = X" conditions / set_var(etat)
 *           actions / var_changed(etat) triggers place the chains (computeChains mirrors that), the auto frames
 *           `auto-<state>` are the columns (jump bar, minimap, semantic cards, live / simulated state glow).
 *           Variables panel (tab "vars": Noms / Listes) edits doc.variables; GET /api/graph/vars feeds its live column
 *           (polled <= 1 Hz only while the tab is open). Inspector args of type var / list / value / enum are typed
 *           controls; the Tester shows the simulated variables of each trace entry (changed ones highlighted).
 *           L3 (2026-10-31): if/else pairs arrive as ONE condition using its Faux output (server side); every wire,
 *           including the one being dragged (paintDragWire), is a gradient from the SOURCE node kind colour to the
 *           target kind colour: a Faux wire starts green like its condition, the red pastille is only a port marker.
 *           L4 (2026-11-01): no Start node (palette, Insérer menu and import drop it; a trigger starts its chain); wires
 *           follow dragged nodes again: the gradient <defs> sits after the wire path (Drawflow writes svg.children[0]).
 *           L5 (2026-11-01): node menu = Category (trigger / action / condition) > shared Theme > item, themes read from the
 *           vocabulary (`theme`, `themes`, `theme_slots`; menuItems / menuTree) in the palette tree and the cascading
 *           "Insérer" menus; one tooltip component (data-tip / borrowed title, #tip in <body>, long press / "i" icon on
 *           touch); post-it display modes (note.display 'compact' | absent = full, auto-grow); node diagnostics: badges
 *           from client checks + /api/graph/check errors (`at` = faulty node), toolbar counter #btnDiag cycling them.
 *           L8 (2026-11-01): hover bubble on the whole node (nodeTipOf: kind + vocabulary help, settings, Category › Theme,
 *           problems; never during a drag / wire / pan, swaps at once between a node and its own badge or ports);
 *           minimap press-and-drag navigation (pointer capture, one rAF per frame, wheel = zoom); nested groups: frames
 *           and post-its carry `parent` (frame id), drops re-parent with a drop-target outline, parents grow to fit
 *           and never shrink below their children, deleting a group hands its children to its parent.
 *           L9 (2026-11-01): the drop target is the deepest frame under the POINTER (dropTargetAt), whatever the sizes;
 *           a state column refuses to enter a group (red outline, back in place, toast); the first nesting choice
 *           writes an explicit `parent` (null = top level) on every user frame / post-it so adoptLegacy never reruns.
 *           Default column post-its (note.auto = "state:<group>") come from the server (graph_visual.column_notes).
 *           L10 (2026-11-01): flat right-click menu: Déclencheurs ▸ / Actions ▸ / Conditions ▸ (Category > Theme > item),
 *           Post-it, Groupe de nœuds, Copier la sélection / Couper / Coller; no search field (typing filters, ctxFilter);
 *           no empty blocks; "Fin" and "Changer d'état → X" only under Actions › État; node / group / post-it menus start
 *           with Copier, Couper, Dupliquer, Supprimer (+ Désactiver la chaîne), Ranger dans le groupe ▸. Fragment clipboard
 *           (selection = node | chain picked in the hierarchy | group or column | post-it; internal links, sub-groups and
 *           post-its kept; paste / cut / duplicate = one undo step through one rebuild). The left column is a Unity-style
 *           hierarchy replacing the palette and the COLONNES / GROUPES lists (buildTree / renderTree: columns > nested
 *           groups > chains > post-its, fold state per browser, diagnostics rolled up on folded rows, click = select +
 *           centre, double-click = rename, drag a row onto a column / group row = moveInto with the canvas drop rules,
 *           selection synced both ways). The first right tab is "Inspecteur": node, wire, group, column, post-it or a
 *           whole chain (steps + diagnostics).
 *           L12 (2026-11-01, contract "Variables v2"): every type list comes from the vocabulary (var_types[].control /
 *           options / ops / choices / range / size, list_types, op_sets, scopes, list_kinds, list_modes, weekdays), never
 *           hardcoded here. Variables panel: Portée column + Persistante (globals only), min / max / step, one typed
 *           control per `control` (valueInput), Réinitialiser = POST /api/graph/vars/reset, live values (chrono = elapsed
 *           seconds, refreshed by the 1 Hz poll); Listes: kind list / dict (key -> value sub-table), mode, max, scope,
 *           persist. Inspector: typed `value` (by the chosen variable / list / dict), `time` (hh:mm), `multi` (week days),
 *           `text` keys with $utterance / $variable, `number` with `min`, operators filtered by op_sets, args of any event
 *           (timer_reached). Diagnostics: server `out_of_bounds` warnings on the faulty node, client type mismatch hints,
 *           persisted values refused at load (`store.ignored` of GET /api/graph/vars, fetched once at load and after save)
 *           as global warnings. Tester: simulated variables grouped by scope (Système / Globales / Conversation),
 *           conversation ones marked "remises à zéro à chaque nouvelle conversation".
 *           M5 (2026-11-02, contract "Propriétés"): value source picker. An inspector field whose vocabulary argument
 *           carries `props` gets a ▾ button (« Source de la valeur »): menu grouped Valeur fixe / Variables / Listes /
 *           Robot / Hasard / Temps / Calcul from V.properties.get, only the sources whose `out` fits the field type
 *           (V.type_compat = server graph.compatible; `{"of": arg}` narrows the source's var / list / enum choices);
 *           a source shows as a chip with its own args indented (argFields recursion, ▾ again on `props` args, at most
 *           SRC_MAX_DEPTH = server MAX_DEPTH levels). Written as `{get: <id>, ...}`; `{get: variable, name: x}` /
 *           `{get: utterance}` are stored as "$x" / "$utterance" where `$` was already allowed (never a top-level
 *           number field). Typed literals inside sources (numOrKey): the visual compiler does not coerce them.
 *           Cards / node tooltip say the source in words (srcWords); varUses / renameUses walk sources.
 *           M6 (2026-11-02, plan "modular nodes / variables / properties" section 4): the former single-file
 *           web/editor.js is split into native ES modules under web/editor/ (no build step, no bundler). This file
 *           (main.js) is the entry: it imports the modules, publishes the test hooks (window.__editor, same API as
 *           before) and calls boot(). Reassignable state lives in core/state.js `S` (ES imports are read-only), every
 *           other top-level function / constant is an explicit export of its module. Served by GET /web/editor/<path>
 *           (server.py: lowercase path, .js / .css only, under web/editor/, no-cache like the other editor assets).
 * Module map (web/editor/):
 *   core/util.js                  Editor core: tiny DOM helpers.
 *   tooltips/tooltips.js          Editor tooltips (lot L5): one lightweight component for the whole page.
 *   core/state.js                 Editor core: constants, vocabulary accessors and the shared mutable state S.
 *   variables/model.js            Variables (Vars L2): definitions of the document variables and lists.
 *   inspector/property-picker.js  Inspector: value source picker (lot M5, contract "Propriétés").
 *   core/api.js                   Editor core: network calls and model access over the Drawflow data.
 *   canvas/nodes.js               Canvas: node rendering.
 *   core/serialize.js             Editor core: (de)serialization of the node document.
 *   core/history.js               Editor core: undo / redo history.
 *   core/chains.js                Editor core: chain keys (mirror of graph_visual.compile).
 *   diagnostics/analysis.js       Diagnostics: structural client hints (not the validator).
 *   diagnostics/check.js          Diagnostics: branch order, server dry run and badges.
 *   canvas/view.js                Canvas: view helpers.
 *   canvas/wires.js               Canvas: wires.
 *   minimap/overview.js           Overview (L7): zoom-scaled frame titles, semantic zoom, jump bar.
 *   minimap/minimap.js            Minimap navigation (lot L8).
 *   frames/groups.js              Frames: groups (cosmetic frames, "Groupe").
 *   frames/nesting.js             Frames: nested groups (lot L8 / L9), frame drawing and editing.
 *   frames/notes.js               Frames: post-it notes.
 *   canvas/navigation.js          Canvas: mouse button guards and safe navigation (L8).
 *   menu/context-menu.js          Menus: the right-click context menu (L10 flat menu).
 *   clipboard/clipboard.js        Selection and fragment clipboard (lot L10).
 *   menu/node-menu.js             Menus: adding nodes and the node menu tree (lot L5).
 *   hierarchy/tree.js             Hierarchy (lot L10): Unity-style tree of the left column.
 *   inspector/fields.js           Inspector: basic form controls and the wire inspector.
 *   inspector/arg-fields.js       Inspector: typed argument controls (Vars L2, L12, M5).
 *   inspector/inspector.js        Inspector: the right-hand Inspecteur tab.
 *   panels/intents.js             Panels: intents (editable words, regex, only_in, description, new intents).
 *   variables/panel.js            Variables panel (Vars L2): state, renames, live values.
 *   variables/values.js           Variables panel: typed value controls.
 *   variables/tables.js           Variables panel: Noms / Listes tables.
 *   core/ui.js                    Editor core: toast, modal and YAML preview.
 *   core/actions.js               Editor core: toolbar actions.
 *   panels/live.js                Panels: live view and right-hand tabs.
 *   tester/tester.js              Tester (POST /api/graph/simulate on the current, possibly unsaved, document).
 *   panels/history-panels.js      Panels: Versions and Journal.
 *   canvas/trigger-guard.js       Canvas: no wire into a trigger (Vars L2).
 *   core/boot.js                  Editor core: boot.
 *   export/export.js              Export (lot L14): "Exporter l'image".
 *   core/debug.js                 Editor core: debug scenarios (#debug=...).
 *   core/progress.js              Editor core: the one non-blocking progress bar + chip (lot L22).
 *   main.js                       entry: imports, window.__editor test hooks, boot().
 * Invariants:
 *   - The Drawflow canvas is the working copy; every node keeps its full server model in node.data.model
 *     (unknown params such as `group` or `global: true` and unknown node fields survive a round trip).
 *   - serialize() is the single exit point of the document (used by save, undo history and dirty check).
 *   - Node ids are our own `n<k>` ids (Drawflow's numeric ids are never sent).
 *   - NEVER touches /api/control (it rewrites config.json).
 * Test    : open /editor (loads web/editor/main.js); add `#debug=roundtrip` to run the in-page round-trip check (result in the overlay),
 *           `#debug=select` / `#debug=error` for the screenshot scenarios. Library: Drawflow 0.0.60 (MIT, vendored).
 */
import { $, clone, dbg, errLog } from './core/util.js';
import { hideTip } from './tooltips/tooltips.js';
import { S, KINDS, nidToDf } from './core/state.js';
import { listDefs, varDefs } from './variables/model.js';
import { varUses } from './inspector/property-picker.js';
import { api, dfData, dfNode, model } from './core/api.js';
import { nodeEl, nodePath, nodeTipOf, refreshNode } from './canvas/nodes.js';
import { rebuild, serialize } from './core/serialize.js';
import { commitSoon, isDirty, redo, undo } from './core/history.js';
import { computeChains } from './core/chains.js';
import { analyze } from './diagnostics/analysis.js';
import { diagCycle, diagNodes, freshCheck, runCheck } from './diagnostics/check.js';
import { paintWires } from './canvas/wires.js';
import { clearJumpbar } from './minimap/overview.js';
import { frameById, frames } from './frames/groups.js';
import {
  addFrame, adoptLegacy, deleteFrame, descendantFrames, drawFrames, editFrame, editFrameTitle, fit, focusBand,
  focusFrame, focusNode, focusRect, selectFrame, setView
} from './frames/nesting.js';
import { addNote, deleteNote, editNote, notes, selectNote, setNoteDisplay } from './frames/notes.js';
import { setHand, setLock, toggleHelp } from './canvas/navigation.js';
import { closeCtx } from './menu/context-menu.js';
import {
  copyNode, copySelection, cutSelection, duplicateSelection, hasSelection, linkNodes, openContextFor,
  pasteFragment, pasteNode
} from './clipboard/clipboard.js';
import { addAt, menuItems, menuTree } from './menu/node-menu.js';
import { buildTree, moveInto, renderTree, selectChain, treeChains, treeFolded } from './hierarchy/tree.js';
import { renderInspector } from './inspector/inspector.js';
import { intentCard, renderIntents } from './panels/intents.js';
import { refreshVarStore, varsUi } from './variables/panel.js';
import { resetVar } from './variables/values.js';
import { renderVars } from './variables/tables.js';
import { toast } from './core/ui.js';
import { loadAll, postDoc, save, validate } from './core/actions.js';
import { activateTab } from './panels/live.js';
import { addStep, selectTrace, sim, simRun } from './tester/tester.js';
import { loadJournal, loadVersions } from './panels/history-panels.js';
import { boot } from './core/boot.js';
import { exportOpts, startExport, toggleExport } from './export/export.js';
import { progressInfo, startTask } from './core/progress.js';

// ---------- test hooks (used by the verification scenarios; harmless in normal use) ----------
window.__editor = { serialize, postDoc, loadAll, errors: errLog, nodeCount: () => Object.keys(dfData()).length,
  activateTab, sim, addStep, simRun, computeChains, liveChains: () => S.liveChains, focusBand, focusNode, fit, intentCard, renderIntents,
  panDf: (dfid) => { const d = dfNode(dfid), st = $('#drawflow'), z = 0.9; setView(z, st.clientWidth / 2 - (d.pos_x + 400) * z, st.clientHeight / 2 - (d.pos_y + 40) * z); },
  frames, addFrame, selectFrame, focusFrame, editFrame, deleteFrame, editFrameTitle, selFrame: () => S.selFrame,
  dfMap: () => Object.fromEntries(nidToDf), fanInfo: () => S.fanInfo,   // test hooks (headless checks)
  notes, addNote, selectNote, deleteNote, editNote, selNote: () => S.selNote, paintWires, openContextFor, closeCtx, addAt, linkNodes, copyNode, pasteNode,
  linkMeta: () => Object.fromEntries(S.linkMeta), clipboard: () => S.clipboard, ctxOpen: () => !!S.ctx,
  meta: () => S.meta, journal: () => S.journal, renderVars, varsUi, varDefs, listDefs, varUses,
  analyze, globalIssues: () => S.globalIssues, refreshVarStore, resetVar,      // L12 test hooks
  progress: progressInfo, startTask, api,     // L22 test hooks: progress bar state, a task, the fetch wrapper
  toggleExport, startExport, exportInfo: () => S.exportInfo, exportOpts: () => ({ ...exportOpts }), exportBusy: () => !!S.exportRun,   // L14
  noInputRefusals: () => S.noInputRefusals, kinds: () => KINDS, loadJournal, loadVersions, selectTrace, toast,
  nav: () => ({ locked: S.navLocked, hand: S.navHand, space: S.navSpace, zoom: S.editor.zoom, x: S.editor.canvas_x, y: S.editor.canvas_y }),
  setHand, setLock, toggleHelp, save,
  menuTree, menuItems, issues: () => Object.fromEntries(S.issues), diagNodes, diagCycle, checkErrors: () => S.checkErrors, runCheck, freshCheck, clearJumpbar, setNoteDisplay, hideTip,
  selDf: () => S.selDf, validate,
  // lot L10 test hooks: selection / clipboard, hierarchy
  copySelection, cutSelection, pasteFragment, duplicateSelection, hasSelection, selChain: () => S.selChain, selectChain,
  buildTree, renderTree, treeChains, moveInto, treeFold: () => [...treeFolded()],
  isDirty, dirtyShown: () => !$('#dirty').hidden,   // L23 test hooks: save rule (post-its, groups, hierarchy)
  // lot L8 test hooks: node bubble text, minimap mapping / viewport, nesting helpers
  nodeTip: (nid) => { const df = nidToDf.get(nid); return df == null ? null : nodeTipOf(nodeEl(df)); },
  nodePath: (nid) => { const df = nidToDf.get(nid); return df == null ? null : nodePath(model(df)); },
  miniMap: () => (S.miniEl ? { map: S.miniEl._map, view: S.miniEl._view, dragging: !!S.miniDrag } : null),
  descendants: (id) => { const f = frameById(id); return f ? descendantFrames(f).map((g) => g.id) : null; },
  focusRect, adoptLegacy: () => { const c = adoptLegacy(); if (c) drawFrames(); return c; }, undo, redo,
  // lot L5 test hook: merge `params` into a node's params (null value = delete the key), then redraw + re-analyse
  patchNode: (nid, params) => {
    const df = nidToDf.get(nid), m = df != null ? model(df) : null; if (!m) return false;
    for (const k in params) { if (params[k] === null) delete m.params[k]; else m.params[k] = clone(params[k]); }
    refreshNode(df); if (String(S.selDf) === String(df)) renderInspector(); analyze(); commitSoon(); return true;   // M5: Drawflow ids are strings or numbers
  },
  rebuild: (d) => rebuild(d, true),
  dfState: () => ({ drag: S.editor.drag, editorSel: S.editor.editor_selected, ele: S.editor.ele_selected ? (S.editor.ele_selected.id || S.editor.ele_selected.className) : null }) };   // L4 test hook: load a (legacy) document without touching the server

boot().catch((e) => { errLog.push(String(e)); dbg('BOOT ' + e + '\n' + (e.stack || '')); toast('Erreur au démarrage : ' + e, 'err'); });
