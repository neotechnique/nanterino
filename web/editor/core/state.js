/**
 * Editor core: constants, vocabulary accessors and the shared mutable state S.
 *
 * Purpose :  node kinds (KINDS, CATS, KIND_TIP, PORT_TIP), vocabulary lookups (evs, stateLabel / stateIcon / stateColor),
 *            and S: every reassignable editor state (V vocabulary, meta, the Drawflow editor, selection, history,
 *            diagnostics, panels) in one object.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  nothing (leaf module)
 * Invariant: modules reassign state only through S.<name> (ES imports are read-only); initial values are those of the
 *            former single file.
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
export const KINDS = {
  // Legacy Start (lot L4: the server no longer produces it, rebuild() drops one found in an old document, the palette
  // and the context menu never offer it). Kept only so code paths that still name the kind stay harmless.
  start:     { label: 'Début',            cls: 'start',     ins: 0, outs: 1, color: 'var(--start)',   icon: 'flag' },
  // Vars L2: a trigger starts a chain, it has NO input port (contract: inputs = 0; the server refuses any wire into it).
  trigger:   { label: 'Déclencheur',      cls: 'trigger',   ins: 0, outs: 1, color: 'var(--trigger)', icon: 'bolt' },
  condition: { label: 'Condition',        cls: 'condition', ins: 1, outs: 2, color: 'var(--cond)',    icon: 'git-branch' },
  action:    { label: 'Action',           cls: 'action',    ins: 1, outs: 1, color: 'var(--action)',  icon: 'player-play' },
  // Legacy terminal (only drawn when a document still carries one; the palette never offers it).
  goto:      { label: "Aller à l'état",   cls: 'goto',      ins: 1, outs: 0, color: 'var(--goto)',    icon: 'arrow-right' },
  end:       { label: 'Fin',              cls: 'end',       ins: 1, outs: 0, color: 'var(--end)',     icon: 'square' },
  // Legacy L6 hub (import tolerance only: the server never produces it now). Drawn as an inert card, no ports.
  state:     { label: 'État (ancien)',    cls: 'state',     ins: 0, outs: 0, color: 'var(--state)',   icon: 'circle-dot' },
};
const NOT_IN_PALETTE = new Set(['start', 'goto', 'state']);
// Lot L5 tooltips: what a node kind does (node header) and what each port means.
export const KIND_TIP = {
  trigger: 'Déclencheur : démarre une chaîne quand son événement arrive (ou après son délai). Il n’a pas d’entrée.',
  condition: 'Condition : teste une garde ou une variable. Sortie Vrai : la chaîne continue ; sortie Faux : la branche suivante démarre.',
  action: 'Action : ce que fait le robot. Les actions d’une chaîne s’exécutent dans l’ordre des fils.',
  end: 'Fin : termine la chaîne sans changer d’état.',
  goto: 'Ancien nœud « Aller à » : utilisez l’action « Changer d’état ».', state: 'Ancien nœud État : il n’est plus utilisé.', start: '',
};
export const PORT_TIP = {
  in: 'Entrée : reçoit la suite d’un déclencheur, d’une condition ou d’une action.',
  trigger: 'Sortie : la chaîne démarre ici quand le déclencheur se produit.',
  true: 'Vrai : suite exécutée quand la condition est vraie.',
  false: 'Faux : suite exécutée quand la condition est fausse (la branche suivante).',
  action: 'Sortie : nœud suivant, exécuté après cette action.',
};
// Node menu categories (lot L5) = the three insertable node kinds; their themes come from the vocabulary.
export const CATS = [
  { id: 'trigger', label: 'Déclencheurs', icon: 'bolt', tip: 'Ce qui démarre une chaîne : un événement, une intention, un délai, une entrée dans un état.' },
  { id: 'action', label: 'Actions', icon: 'player-play', tip: 'Ce que fait le robot, dans l’ordre de la chaîne.' },
  { id: 'condition', label: 'Conditions', icon: 'git-branch', tip: 'Ce qui est testé : la suite Vrai ou Faux en dépend.' },
];
export const NODE_KINDS = ['trigger', 'condition', 'action', 'end'];   // kinds the canvas menu inserts (L4: no Start; L10: Fin = Actions › État)
// Post-it palette (pastel), first = default.
export const NOTE_COLORS = [['Jaune', '#fff59d'], ['Rose', '#f8bbd0'], ['Vert', '#c8e6c9'], ['Bleu', '#bbdefb'], ['Orange', '#ffe0b2'], ['Violet', '#e1bee7']];
// Link rules (mirror of graph_visual.from_visual; the server stays the judge): Start is display only (no link),
// NOTHING enters a trigger (it starts a chain), everything else may feed any node that has an input.
export const NO_TRIGGER_INPUT = "Un déclencheur n'a pas d'entrée : il démarre une chaîne. Reliez sa sortie à une condition ou à une action.";
export function linkProblem(from, to) {
  const a = from.kind, b = to.kind;
  if (b === 'start') return 'Le nœud Début ne reçoit aucun lien.';
  if (b === 'trigger') return NO_TRIGGER_INPUT;
  if (a === 'start') return "Le nœud Début ne se relie à rien : l'état de départ est fixé par le robot.";
  if (a === 'state' || b === 'state') return "Les anciens nœuds État ne se relient plus : utilisez « Changer d'état » (action) et la condition « etat = … ».";
  return null;
}

// ---------- state ----------
// shared state: S.V (core/state.js)
// shared state: S.meta (core/state.js)   // top-level doc fields other than nodes/links
// shared state: S.editor (core/state.js)
export const nidToDf = new Map();       // our node id -> Drawflow id
// shared state: S.loading (core/state.js)
// shared state: S.selDf (core/state.js)
// shared state: S.hist, S.histIdx, S.savedSnap (core/state.js)
// shared state: S.serverErrors (core/state.js)           // [{node,message,intent?}] from the last POST
// shared state: S.simErrors (core/state.js)              // same shape, from the last POST /api/graph/simulate (400)
// shared state: S.intentErrs (core/state.js)             // intent name -> server message
// shared state: S.simState (core/state.js)             // state the simulator ended in (band highlight)
export const freshIds = new Set();      // ids of nodes dropped from the palette and not yet validated / saved
// shared state: S.issues (core/state.js)          // nid -> [{level,message}] (client analysis + server errors)
// Branch analysis from POST /api/graph/check: warnings (several branches of a trigger that change the state)
// and, per trigger with several outgoing branches, the engine's execution order (rank).
// shared state: S.fanInfo (core/state.js)
// shared state: S.checkTimer, S.lastCheckKey (core/state.js)
// shared state: S.checkErrors (core/state.js)            // lot L5: errors of the last POST /api/graph/check (dry run while editing), same shape
// shared state: S.globalIssues (core/state.js)           // issues without a node
// shared state: S.liveState (core/state.js)
// shared state: S.lastWs, S.lastAge (core/state.js)
// shared state: S.idCounter (core/state.js)
// shared state: S.addJitter (core/state.js)
// Extra data of the hop into a state node: key "from|port|to" -> {reason?, description?} (the transition's journal
// reason, and its description when no node of the chain can carry it). Rebuilt from doc.links, written back by serialize().
// shared state: S.linkMeta (core/state.js)
// shared state: S.selConn (core/state.js)              // {out, in, cls} (Drawflow ids) of the selected wire, else null
export const linkKey = (f, p, t) => f + '|' + p + '|' + t;

export const byId = (list, id) => (list || []).find((x) => x.id === id);
// Triggerable events = vocabulary events + one `intent.<id>` event per recognised intent.
// Intents of the document being edited (meta.intents) count too: a new intent is usable as a trigger at once.
export const INTENT_NAME = /^[a-z][a-z0-9_]{0,31}$/;
export const evs = () => {
  const out = S.V.events.slice(), seen = new Set();
  S.V.intents.forEach((i) => { seen.add(i.id); out.push({ id: i.event || 'intent.' + i.id, label: 'Intention « ' + i.id + ' »', help: i.label, icon: i.icon || 'message' }); });
  Object.keys(S.meta.intents || {}).forEach((n) => { if (!seen.has(n) && n !== 'question') out.push({ id: 'intent.' + n, label: 'Intention « ' + n + ' »', help: (S.meta.intents[n] || {}).description || '', icon: (S.meta.intents[n] || {}).icon || 'message' }); });
  return out;
};
export const stateLabel = (id) => { const s = byId(S.V.states, id); return s ? s.label : id; };
export const stateIcon = (id) => {
  const d = (S.meta.states || []).find((x) => x.id === id), s = byId(S.V.states, id);
  return (d && d.icon) || (s && s.icon) || 'circle-dot';
};
// Header icon of a node: the vocabulary entry it uses, else its kind icon.
export function iconOf(m) {
  const p = m.params || {}, k = KINDS[m.kind];
  if (m.kind === 'trigger') {
    if (p.type === 'event' && p.event === 'var_changed' && p.name === 'etat' && p.value) return stateIcon(p.value);
    if (p.type === 'event') { const e = byId(evs(), p.event); return (e && e.icon) || k.icon; }
    if (p.type === 'after') { const s = byId(S.V.since, p.since || 'state'); return (s && s.icon) || 'clock'; }
    if (p.type === 'enter') return stateIcon(p.state);
  }
  if (m.kind === 'condition' && p.type === 'guard') { const g = byId(S.V.guards, p.guard); return (g && g.icon) || k.icon; }
  if (m.kind === 'action') { const a = byId(S.V.actions, p.action); return (a && a.icon) || k.icon; }
  return k.icon;
}
export const stateColor = (id) => {
  if (id === 'global') return '#8a6d1d';
  const s = (S.meta.states || []).find((x) => x.id === id);
  return s && s.color ? s.color : '#566';
};

// ---------- shared mutable state (lot M6) ----------
// Every top-level `let` of the former single-file editor lives here so that any module can reassign it
// (ES module imports are read-only bindings). Grouped by the module that owns it; initial values unchanged.
export const S = {
  // tooltips/tooltips.js
  tipEl: null,
  tipTimer: 0,
  tipFor: null,
  tipTouch: 0,
  tipOpenAt: null,
  // core/state.js
  V: { events: [], actions: [], guards: [], delays: [], since: [], states: [], intents: [], kinds: [] },
  meta: { version: 1, states: [], intents: {}, order: [] },   // top-level doc fields other than nodes/links
  editor: null,
  loading: false,
  selDf: null,
  hist: [],
  histIdx: -1,
  savedSnap: '',
  serverErrors: [],   // [{node,message,intent?}] from the last POST
  simErrors: [],   // same shape, from the last POST /api/graph/simulate (400)
  intentErrs: {},   // intent name -> server message
  simState: null,   // state the simulator ended in (band highlight)
  issues: new Map(),   // nid -> [{level,message}] (client analysis + server errors)
  fanInfo: { warnings: [], fans: {} },
  checkTimer: null,
  lastCheckKey: '',
  checkErrors: [],   // lot L5: errors of the last POST /api/graph/check (dry run while editing), same shape
  globalIssues: [],   // issues without a node
  liveState: null,
  lastWs: 0,
  lastAge: null,
  idCounter: 0,
  addJitter: 0,
  linkMeta: new Map(),
  selConn: null,   // {out, in, cls} (Drawflow ids) of the selected wire, else null
  // core/history.js
  commitTimer: null,
  // core/chains.js
  liveChains: { keys: new Map(), byTrigger: new Map() },   // chains of the document the robot runs (last loaded / saved)
  // diagnostics/check.js
  checkInflight: null,
  checkOkKey: '',
  diagIdx: -1,
  // canvas/wires.js
  gradSeq: 0,
  dragSrcKind: null,
  badgesEl: null,
  badgeRaf: 0,
  retHover: null,
  // minimap/overview.js
  jumpEl: null,
  miniEl: null,
  miniRaf: 0,
  // minimap/minimap.js
  miniDrag: null,
  // frames/groups.js
  selFrame: null,
  framesEl: null,
  frameDrag: null,
  // frames/nesting.js
  dropEl: null,   // frame element outlined as the drop target of the current drag
  dropCls: '',   // frame element outlined as the drop target of the current drag
  // frames/notes.js
  selNote: null,
  notesEl: null,
  noteDrag: null,
  // canvas/navigation.js
  navLocked: false,
  navHand: false,
  navSpace: false,
  navPan: null,
  helpEl: null,
  // menu/context-menu.js
  ctx: null,
  // clipboard/clipboard.js
  clipboard: null,
  selChain: null,   // {tid, ids}: trigger id (null for a multi-node paste) + node ids, trigger first
  // hierarchy/tree.js
  treeFold: null,
  treeTimer: 0,
  treeDrag: null,
  treeRename: false,
  treeJustDragged: false,
  treeOwner: new Map(),   // last build: node id -> its row key ; row key -> parent row key
  treeUp: new Map(),   // last build: node id -> its row key ; row key -> parent row key
  // panels/live.js
  wsFails: 0,
  wsOpened: false,
  curTab: 'node',
  // panels/history-panels.js
  journal: [],
  liveSeen: false,
  seenT: 0,
  // canvas/trigger-guard.js
  noInputRefusals: 0,   // test hook: wires refused because they ended on a trigger
  // export/export.js
  exportPop: null,
  exportRun: null,
  exportInfo: null,
};
