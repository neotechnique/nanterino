"""Dialogue state graph: YAML loader + validator + dispatch engine (logging: robotlog via nanterino.log).

Purpose
    The robot's conversation logic (which event moves which state to which state, what is said,
    which silence delays apply) lives in a French, human-editable file (`graph.yaml`) instead of
    Python. This module turns that file into a frozen `Graph` and runs it with `GraphEngine`.
    No LLM is involved in decisions: dispatch is a plain deterministic table lookup (zero latency).

Boundary
    - graph.py knows NOTHING about audio, threads or the Brain: it only calls the registries it is
      given (`actions`: name -> fn(kw, **args), `guards`: name -> fn(kw) -> bool) and
      `brain._go(state, reason)`, `brain.state / since / last_speech`. brain.py implements them.
    - The vocabulary is CLOSED and declared here (EVENTS, ACTION_SPECS, GUARDS). A name the file
      uses that is not declared is a load error with a clear message, never a runtime surprise.
      Adding an action / condition (guard) / trigger (event) = drop one module into nanterino/nodes/actions/,
      conditions/ or triggers/ (lots M1, M2: metadata + run() / test() / match() in that file; see nanterino/nodes).

File format (see nanterino/graph.yaml, the commented default)
    states.<name>: description, on_enter [actions], transitions [..]
    global: transitions valid from any state; searched BEFORE the current state's transitions
    transition: on <event> | after <cfg key or seconds> + since <state|last_speech>,
                when <guard(s); `{not: guard}` negates one>, only_in/not_in <states>, do [actions], to <state>,
                reason <text | $source>, then [actions after the move], description
    intents.<name>: words | words_from <cfg key> | regex, only_in, description; first match in file
                order wins; no match = event `intent.question`
    Gotcha: PyYAML reads the bare words on/off/yes/no as booleans; the loader below only keeps
    true/false as booleans so `- on: stop` and `on: off` mean what they say.

Wave 2 (2026-10-31)
    - Every registry entry has an `icon` (Tabler name) next to its French label; `vocabulary()` returns them
      and `all_icons()` lists the set the editor must vendor.
    - A transition may carry `enabled: false`: validated, kept in the file, ignored by dispatch()/tick().
    - New actions say_text / set_expression / wait / gaze, new events personnes_multiples / ouverture /
      fermeture / inactivite_longue / say_done, new guard dans_les_horaires (see brain.py for the capabilities).
    - `wait` is the only non-blocking action: GraphEngine._exec hands the rest of the chain to
      `brain.defer(delay, fn)`; every fired chain is reported to `brain.note_fire` (journal, simulator).

Variables (lot L1, 2026-10-31)
    - `variables: {names: {...}, lists: {...}}` declares typed user variables (bool, number, string, choice, duration)
      and lists (string/number/bool items, or bound read-only to a config key `from:` / an intent's words `intent:`).
      SYSTEM_VARS (etat, tours, max_tours, reparations, max_reparations) are read-only views of the brain's state.
    - New actions set_var / add_var / toggle_var / list_add / list_remove / list_clear / say_random, guards with
      arguments (var_compare, var_true, list_contains, list_empty: `when: [{var_compare: {...}}]`), and the event
      `var_changed` (`on: var_changed` + `var:` + optional `value:`). The brain owns the values (`Brain.vars`); this
      module only validates names and types. A system variable is never written and `etat` is never compared or
      watched in YAML (placement under a state, only_in/not_in and on_enter already say it).

Node menu themes + argument help (lot L5, 2026-11-01)
    - Every event / action / guard has exactly one `theme` (EVENT_THEME / ACTION_THEME / GUARD_THEME, checked at import);
      THEME_DOC is the ordered theme table (French label, icon, help) and THEME_SLOTS gives the theme of the entries the
      editor builds from data (intents, the delay trigger, the per-state entries). vocabulary() returns `theme` on each
      entry, `themes` and `theme_slots`; each argument gets a `help` text (ARG_KIND_HELP) for the inspector tooltips.

Variables v2 (lot L11, 2026-11-01)
    - New name types integer / percent / datetime / timer / expression / gaze / phrase / media / intent_ref / list_ref /
      state_ref / color / vector2 / vector3; number and integer take optional `min` / `max` / `step` (set_var / add_var
      clamp at run time via `fit_value`; a literal outside the bounds is a non-blocking diagnostic `out_of_bounds`).
    - Lists hold every type but timer (and choice); `kind: dict` = key -> value pairs (dict_set / dict_remove / say_dict,
      guards dict_has / dict_value_compare); `mode: plain | shuffle | history` + `max` (oldest item dropped first);
      remember_utterance pushes the visitor's last sentence.
    - Names and lists take `scope: global | conversation` (conversation = reset by clear_conversation) and, for global
      ones, `persist: true` (brain.py + var_store.py keep them in state/vars.json).
    - Time: actions set_now / timer_start / timer_reset, guards elapsed_since / time_between / weekday_in / date_compare,
      event `timer_reached` (`var:` timer + `value:` seconds, once per timer start, same anti-loop as var_changed).
      Every time reading goes through the brain's injectable clocks (`now` monotonic, `wall` epoch): the simulator and
      the tests drive them, nothing here reads the real time.
    - More read-only system variables: heure, jour, derniere_phrase, visage_vu, volume, expression, regard,
      nb_visiteurs_jour. vocabulary() describes each type (`control`, `options`, `ops`, `choices` ...) for the editor.

Invariants
    - dispatch() (GC2-like branches, 2026-10-31): every applicable transition (event match + only_in/not_in + all
      guards, judged against the state at event arrival; global ones first, then the current state's, file order)
      that has NO `to` runs its actions; then the FIRST applicable one with a `to` runs (do -> move -> then). A
      second applicable moving transition is a conflict: ignored, logged once, journaled with `conflict: true`.
      Transitions of one editor trigger share a `fan:` id; their common leading actions run once per event.
      The packaged graph therefore makes its "otherwise" transitions explicit with `{not: guard}`.
    - tick(): same rule for the `after:` transitions of the CURRENT state only (driven by the heartbeat); a
      non-moving `after:` chain fires once per time base instead of on every heartbeat.
    - An invalid override file never stops the robot: `load_active` logs the error (errors.log) and
      falls back to the default graph shipped with the code.

Node modules (lot M1, 2026-11-01)
    - Actions live in nanterino/nodes/actions/<id>.py (one class each: label, help, icon, theme, args, run()).
      ACTION_DOC / ACTION_SPECS / ACTION_ICON / ACTION_THEME are views of nanterino.nodes.ACTIONS (palette order =
      the modules' `order`); /api/graph/vocab is byte-identical to the former tables (tests/golden/vocab-*.json).
      ARG_KINDS lists the argument kinds a module may use; check_family() refuses an unknown theme or kind at import.
    - Lot M2: guards live in nanterino/nodes/conditions/<id>.py (test()), events in nanterino/nodes/triggers/<id>.py.
      GUARD_DOC / GUARD_ARGS / GUARD_SPECS / GUARD_AS_VARS / GUARD_ICON / GUARD_THEME and EVENT_DOC / EVENTS /
      INTERNAL_EVENTS / WATCH_EVENTS / EVENT_ICON / EVENT_THEME are views of CONDITIONS / TRIGGERS. The
      var_changed / timer_reached modules own their `var:` / `value:` check (parser), match (engine), subscription
      (Graph.watched_vars / timer_watches) and inspector schema (vocabulary). Data-derived palette entries
      (intents, `after:`, per-state entries) stay generated here from the graph (nanterino/nodes/__init__.py).
    - Lot M3: variable types live in nanterino/vartypes/<id>.py, list kinds in nanterino/listkinds/<id>.py, list modes
      in nanterino/listmodes/<id>.py (one class each). VAR_TYPES / LIST_TYPES / TYPE_CONTROL / TYPE_DEFAULT /
      NUMERIC_TYPES ... / LIST_KINDS / LIST_MODES are views of those registries; type_ok, coerce_value, compatible,
      fit_value, graph_choices, persisted_ok and the parser's type checks call the type modules; a list declaration's
      kind-specific body is parsed by its kind module. The vocabulary stays byte-identical (tests/golden).
    - Lot M4: value sources (nanterino/properties/get/<id>.py) and write targets (properties/set/<id>.py). The fields
      of PROPERTY_FIELD kinds accept `{get: <source>, ...}` besides a constant (and `$x` / `$utterance` where they
      always did): _Parser.var_args validates them through properties.check_field (typing end to end, bounded nesting)
      and stores the compiled form; Brain._resolve evaluates them. The vocabulary gains additive keys only
      (`properties`, per-argument `props`): tests/golden/vocab-*.pre-m4.json = the new golden minus those keys.

How to test
    python -m tests.test_brain_graph      (parity traces + invalid-graph / watchdog / heartbeat tests)
    python -m tests.test_nodes_registry   (node discovery, drop-a-file, broken module, vocab golden)
    python -m tests.test_vartypes_registry   (variable types / list kinds / list modes: discovery, contract, persistence)
    python -m tests.test_properties      (value sources / write targets: typing, run time, shorthands, round trips)
"""
import datetime
import os
import re
import sys
import types
from dataclasses import dataclass

import yaml

from .log import log
from . import nodes as _nodes
from . import listkinds as _listkinds, listmodes as _listmodes, vartypes as _vartypes
from . import properties as _props
from .body import motion as _motion   # lot B1: gesture / pose library (pure: no graph / brain import)

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graph.yaml")

# ---------------------------------------------------------------- closed vocabulary
# Events a transition may react to (`on:`). `utterance` and `tick` are engine-internal: an utterance
# is classified into an `intent.*` event, a tick drives `after:` delays.
#
# SINGLE SOURCE of the vocabulary: the node modules of nanterino/nodes/ (lots M1, M2) carry the French label +
# help + icon + theme shown by the visual editor (`vocabulary()` -> GET /api/graph/vocab). The tables below are
# VIEWS of the registries, in palette order (the modules' `order`), so a name cannot exist for the validator
# without being documented for the editor.
# Events (lot M2): nanterino/nodes/triggers/<id>.py. EVENT_DOC: name -> (label, help, internal flag).
_TRIGGER_NODES = _nodes.TRIGGERS
EVENT_DOC = {n.id: (n.label, n.help, n.internal) for n in _TRIGGER_NODES.values()}
EVENTS = frozenset(EVENT_DOC)
INTERNAL_EVENTS = frozenset(k for k, v in EVENT_DOC.items() if v[2])

# Actions (lot M1, 2026-11-01): one module per action under nanterino/nodes/actions/, discovered by
# nanterino.nodes (closed: that package only). The tables below are VIEWS of that registry, in palette order;
# there is no second list of actions here. ACTION_DOC: name -> (label, help, {argument name: Arg(kind, label)}).
# kinds: cfgkey (a config key), event, delay (seconds or cfg key) ... (ARG_KINDS lists them all).
_ACTION_NODES = _nodes.ACTIONS
ACTION_DOC = {n.id: (n.label, n.help, dict(n.args)) for n in _ACTION_NODES.values()}
EXPRESSIONS = {"content": "Content", "surpris": "Surpris", "reflechit": "Réfléchit", "triste": "Triste", "neutre": "Neutre"}
GAZE_MODES = {"suivre": "Suivre le visiteur", "devant": "Regarder devant", "errer": "Errer"}
TEXT_MAX = 300      # say_text.text length limit (it is synthesised once at graph load)
SECONDS_MAX = 3600  # set_expression.seconds upper bound
ACTION_SPECS = {n: {a: kd[0] for a, kd in spec[2].items()} for n, spec in ACTION_DOC.items()}

# Guards (lot M2): nanterino/nodes/conditions/<id>.py. GUARD_DOC: name -> (label, help); GUARD_ARGS: the guards
# with arguments (same kinds as ACTION_DOC; `anyvar` = any variable, system ones included, `op` = OPS).
_CONDITION_NODES = _nodes.CONDITIONS
GUARD_DOC = {n.id: (n.label, n.help) for n in _CONDITION_NODES.values()}
GUARDS = frozenset(GUARD_DOC)
GUARD_ARGS = {n.id: dict(n.args) for n in _CONDITION_NODES.values() if n.args}
GUARD_SPECS = {g: {a: kd[0] for a, kd in GUARD_ARGS.get(g, {}).items()} for g in GUARD_DOC}
# Display of the counter guards as variable comparisons (the compiled guard does not change: parity).
GUARD_AS_VARS = {n.id: n.as_vars for n in _CONDITION_NODES.values() if n.as_vars}
OPS = {"=": "égal à", "!=": "différent de", "<": "inférieur à", "<=": "inférieur ou égal à", ">": "supérieur à",
       ">=": "supérieur ou égal à"}
ORDER_OPS = frozenset({"<", "<=", ">", ">="})   # allowed on ORDERED_TYPES only (numbers, durations, dates)

# ---------------------------------------------------------------- variables (lot L1; lot M3: type modules)
# SINGLE SOURCE: one module per type in nanterino/vartypes/ (label, control, default, flags, validation ...). The
# tables below are VIEWS of that registry, in its order (the modules' `order`): the editor's menus and the error
# messages list the types in this order.
VARTYPES = _vartypes.VARTYPES
VAR_TYPES = {k: t.label for k, t in VARTYPES.items()}
# List item types: the types with item_ok (every name type but timer and choice), in LIST_TYPES order.
LIST_TYPES = {t.id: t.item_label or t.label for t in _vartypes.item_types(VARTYPES)}


def _flagged(flag: str) -> frozenset:
    return frozenset(k for k, t in VARTYPES.items() if getattr(t, flag))


NUMERIC_TYPES = _flagged("numeric")    # timer reads as elapsed seconds
ORDERED_TYPES = _flagged("ordered")    # types the <, <=, >, >= operators accept (numbers, durations, dates)
TEXT_TYPES = _flagged("text")          # interchangeable texts ($utterance fits them)
TEXTLIKE_TYPES = _flagged("textlike")  # may feed a string / phrase value
BOUNDED_TYPES = _flagged("bounded")    # take min / max / step
REF_TYPES = _flagged("ref")
NULLABLE_TYPES = _flagged("nullable")  # `value: null` = empty / not started
# Editor control per type (inspector + variable manager) and the initial value a new variable gets.
TYPE_CONTROL = {k: t.control for k, t in VARTYPES.items()}
TYPE_DEFAULT = {k: t.default for k, t in VARTYPES.items()}
WEEKDAYS = {"lun": "Lundi", "mar": "Mardi", "mer": "Mercredi", "jeu": "Jeudi", "ven": "Vendredi", "sam": "Samedi", "dim": "Dimanche"}
SCOPES = {"global": ("Globale", "Garde sa valeur jusqu'au rechargement du graphe (ou plus longtemps si elle est persistante)."),
          "conversation": ("Conversation", "Revient à sa valeur initiale à chaque « Oublier la conversation », donc à chaque nouveau visiteur.")}
# Lot M3: list kinds (nanterino/listkinds/) and list modes (nanterino/listmodes/), one module each; views.
LIST_KINDS = {k: (m.label, m.help) for k, m in _listkinds.LISTKINDS.items()}
LIST_MODES = {k: (m.label, m.help) for k, m in _listmodes.LISTMODES.items()}
KEY_MAX = 60   # dictionary key length
MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "media")   # repo media/
MEDIA_EXTS = (".wav", ".mp3", ".ogg", ".flac", ".json")
MEDIA_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")   # a bare file name of media/, no folder
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?$")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
# Variable argument kinds: (writable, allowed variable types or None = all). System variables are never writable.
VAR_KIND_TYPES = {
    "var": (True, frozenset(VAR_TYPES) - {"timer"}), "numvar": (True, NUMERIC_TYPES - {"timer"}),
    "boolvar": (True, frozenset({"bool"})), "datetimevar": (True, frozenset({"datetime"})), "timervar": (True, frozenset({"timer"})),
    "anyvar": (False, None), "anyboolvar": (False, frozenset({"bool"})), "textvar": (False, TEXT_TYPES),
    "timeref": (False, frozenset({"datetime", "timer"})), "datevar_any": (False, frozenset({"datetime"})),
}
# List argument kinds: (writable, allowed item types or None = all, list kind).
LIST_KIND_RULES = {
    "wlist": (True, None, "list"), "rlist": (False, frozenset({"string", "phrase"}), "list"), "rlist_any": (False, None, "list"),
    "wtextlist": (True, frozenset({"string", "phrase"}), "list"),
    "wdict": (True, None, "dict"), "rdict": (False, None, "dict"), "rtextdict": (False, frozenset({"string", "phrase"}), "dict"),
}
# Lot L27 `empty_list` diagnostic: actions that say an item of their `list` argument, and actions that add items to it
# (wlist actions that only clear / sort / shuffle / remove never fill an empty list). A new filler action goes here.
EMPTY_LIST_READERS = frozenset({"say_random", "say_list_item"})
LIST_FILLERS = frozenset({"list_add", "remember_utterance"})
# Every argument kind a node module may declare (checked by nanterino.nodes.check_family below): the kinds the
# _Parser checks and vocabulary() renders. An unknown kind would silently render as a delay: refused at import.
ARG_KINDS = frozenset(VAR_KIND_TYPES) | frozenset(LIST_KIND_RULES) | frozenset({
    "cfgkey", "event", "delay", "text", "expression", "seconds", "gazemode", "value", "listvalue", "op", "number",
    "dictkey", "seconds0", "hhmm", "weekdays", "optext", "onoff", "loglevel", "media",
    "gesture", "pose", "bodygroup", "arm"})
# Lot B1 (2026-11-04) Mouvement enumerations: {kind: {value: French label}}. gesture / pose come from the library
# nanterino/body/gestures.yaml (read at import), bodygroup / arm from nanterino/body/motion.py. Parser: calls()
# (actions) and guard_enums (conditions) refuse any other value; vocabulary(): an `enum` argument (no editor code).
MOTION_ENUMS = {"gesture": {k: g["label"] for k, g in _motion.LIB["gestures"].items()},
                "pose": {k: p["label"] for k, p in _motion.LIB["poses"].items()},
                "bodygroup": dict(_motion.GROUP_LABELS), "arm": dict(_motion.ARM_LABELS)}
# Lot N1 (2026-11-02) enumerated kinds: on/off switches (set_mute / set_deaf), journal levels (log_note,
# notify_dashboard, journal_entry) and a playable media file (play_media: a .wav of media/).
ONOFF = {"on": "Activé", "off": "Désactivé"}
LOG_LEVELS = {"info": "Information", "warning": "Avertissement", "error": "Erreur"}
PLAYABLE_EXTS = (".wav",)
# Lot M4 (properties): the argument kinds whose field accepts a value source `{get: ...}`, with the field type the
# source must fit ("of" = the type of the variable / list / dictionary the call names; else a variable type id). The
# names-of-things kinds (variables, lists, events, enumerations ...) stay plain references. `text` (say_text) is not
# here on purpose: its phrase is synthesised once at graph load. Trigger arguments (var_changed / timer_reached) are
# filters, not values: their modules keep their own check.
PROPERTY_FIELD = {"value": "of", "listvalue": "of", "dictkey": "string", "number": "number", "seconds0": "number",
                  "optext": "string"}
# Kinds that always accepted `$x` / `$utterance`: there {get: variable / utterance} compiles to that same shorthand.
SHORTHAND_KINDS = frozenset({"value", "listvalue", "dictkey"})
# Kinds whose node code reads the argument without Brain._resolve: brain._build_engine evaluates their sources first.
PRE_RESOLVE_KINDS = frozenset(PROPERTY_FIELD) - SHORTHAND_KINDS
# Events whose transitions carry `var:` / `value:` (lot M2: the triggers that declare args; a tuple, in order).
WATCH_EVENTS = tuple(n.id for n in _TRIGGER_NODES.values() if n.args)
# Lot N1: the argument names each of them declares (journal_entry filters on `value:` only, no `var:`).
EVENT_ARGS = {n.id: tuple(n.args) for n in _TRIGGER_NODES.values() if n.args}
# Read-only views of the brain's own state: (type, label, help). `etat` gets the state names as choices, `jour` the
# WEEKDAYS ids. Lot L11 adds the clock / face / audio views after the five counters (their order is part of the API).
SYSTEM_VARS = {
    "etat": ("choice", "État", "L'état courant du robot (changer d'état : action « Changer une variable » sur etat)."),
    "tours": ("number", "Tours de parole", "Échanges de la conversation en cours."),
    "max_tours": ("number", "Tours maximum", "Nombre maximal d'échanges d'une conversation (garde-fou)."),
    "reparations": ("number", "Demandes de répétition", "« Pardon ? » de suite."),
    "max_reparations": ("number", "Répétitions maximum", "« Pardon ? » permis de suite."),
    "heure": ("datetime", "Maintenant", "Date et heure actuelles (horloge du robot)."),
    "jour": ("choice", "Jour", "Jour de la semaine : lun, mar, mer, jeu, ven, sam, dim."),
    "derniere_phrase": ("phrase", "Dernière phrase", "La dernière phrase entendue du visiteur."),
    "visage_vu": ("bool", "Visage vu", "Vrai quand la caméra voit au moins un visage."),
    "volume": ("percent", "Volume", "Volume du haut-parleur, de 0 à 100."),
    "expression": ("expression", "Expression", "Expression affichée par le visage (neutre hors action « Changer l'expression »)."),
    "regard": ("gaze", "Regard", "Mode de regard du visage (action « Régler le regard »)."),
    "nb_visiteurs_jour": ("integer", "Visiteurs du jour", "Conversations commencées aujourd'hui (sorties de la veille) ; gardé au redémarrage, remis à zéro à minuit."),
}
VOLATILE_SYSTEM_VARS = frozenset({"heure", "jour"})   # follow the wall clock: left out of simulator traces without start_time
VAR_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
CHOICE_MAX, LIST_MAX = 40, 200   # choices per choice variable, items per list
def coerce_value(vtype: str, v):
    """Editor text -> typed literal ('3' -> 3 for number/duration, 'true'/'false' -> bool); anything else unchanged.

    The visual editor's inputs may send numbers and booleans as text; the YAML validator is strict, so the
    compiler (graph_visual.from_visual) converts with this helper using the variable's declared type."""
    if not isinstance(v, str) or v.startswith("$"):
        return v
    t = VARTYPES.get(vtype)
    return t.coerce(v) if t is not None else v   # lot M3: the type module's coerce()


_VAR_KEYS = {"type", "value", "choices", "description", "min", "max", "step", "scope", "persist"}
_LIST_KEYS = {"type", "items", "from", "intent", "description", "kind", "mode", "max", "scope", "persist"}


def parse_iso(v):
    """datetime of a local ISO text (YYYY-MM-DDTHH:MM[:SS], a space instead of T allowed), else None."""
    if not isinstance(v, str) or not _ISO.match(v):
        return None
    try:
        return datetime.datetime.fromisoformat(v.replace(" ", "T"))
    except ValueError:
        return None


def type_ok(vtype: str, v, choices=()) -> bool:
    """Is `v` a valid literal of `vtype`? `choices` = allowed values of a choice / *_ref type (refs also accept None).
    Lot M3: the type module's validate(); an unknown type accepts nothing."""
    t = VARTYPES.get(vtype)
    return t.validate(v, choices) if t is not None else False


def compatible(src: str, dst: str) -> bool:
    """May a `$<variable>` of type `src` feed a value of type `dst`?"""
    if src == dst:
        return True
    if src in NUMERIC_TYPES and dst in NUMERIC_TYPES - {"timer"}:
        return True
    if src in TEXT_TYPES and dst in TEXT_TYPES:
        return True
    return dst in ("string", "phrase") and src in TEXTLIKE_TYPES


def fit_value(var, v):
    """Run-time value written to `var` by set_var / add_var: integers rounded, percent kept in 0..100, `min` / `max`
    clamped. Non-numbers are returned unchanged (the validator already checked the literals). Lot M3: the type
    module's clamp() (fit() = integer rounding / percent range, then the variable's bounds)."""
    return VARTYPES[var.type].clamp(v, var.vmin, var.vmax)


def graph_choices(graph, vtype: str, choices=()) -> tuple:
    """Allowed values of a choice / reference type in `graph` (intents incl. the implicit `question`, lists, states).
    Lot M3: the type module's choices(ctx)."""
    t = VARTYPES.get(vtype)
    if t is None or not t.ref:
        return tuple(choices)
    names = _vartypes.Names(tuple(i.name for i in graph.intents) + ("question",), tuple(graph.lists), tuple(graph.states))
    return t.choices(names, choices)


def persisted_ok(graph, vtype: str, v, choices=()) -> bool:
    """A value read back from state/vars.json still fits the declared type (a timer stores its start epoch).
    Lot M3: the type module's stored_ok()."""
    t = VARTYPES.get(vtype)
    return t is not None and t.stored_ok(v, graph_choices(graph, vtype, choices))


def media_files(cfg: dict | None = None) -> list:
    """Sorted file names of media/ the `media` type offers (cfg `media_dir` overrides the folder; missing = [])."""
    d = (cfg or {}).get("media_dir") or MEDIA_DIR
    try:
        names = os.listdir(d)
    except OSError:
        return []
    return sorted(n for n in names if n.lower().endswith(MEDIA_EXTS) and MEDIA_NAME.match(n) and os.path.isfile(os.path.join(d, n)))

# Config keys usable as `after:` / `schedule.delay` (seconds); the current value is read from cfg.
DELAY_DOC = {
    "silence_relance_s": "Silence avant relance",
    "silence_cloture_s": "Silence avant de conclure",
    "cloture_to_veille_s": "Pause avant le retour en veille",
}
SINCE_DOC = {"state": "depuis l'entrée dans l'état", "last_speech": "depuis la dernière parole"}
SINCE = tuple(SINCE_DOC)
REQUIRED_STATES = ("veille", "eteint")
# Label + help of the states the default graph ships (other states fall back to their description).
STATE_DOC = {
    "veille": "Veille", "accueil": "Accueil", "ecoute": "Écoute", "reponse": "Réponse",
    "relance": "Relance", "cloture": "Clôture", "eteint": "Éteint",
}
PHRASE_KEYS = ("greeting", "relance", "goodbye", "repair_text")  # config keys offered for speak_phrase.text

# ---------------------------------------------------------------- icons (Tabler Icons names, MIT)
# One icon per registry entry, returned by vocabulary() as `icon`; the editor vendors exactly the set
# `all_icons()` returns (Notes/graph-visual-format.md lists it). A module-level check below refuses a
# registry entry without an icon, so the vocabulary and its icons cannot drift apart.
KIND_DOC = {  # editor node kinds
    "start": ("Départ", "flag"), "trigger": ("Déclencheur", "bolt"), "condition": ("Condition", "git-branch"),
    "action": ("Action", "player-play"), "goto": ("Aller à un état", "arrow-right"), "end": ("Fin de chaîne", "square"),
}
# (input count, output ports, legacy) per kind: a trigger has NO input (lot L1); goto is import-only (legacy).
KIND_PORTS = {"start": (0, ("out",), False), "trigger": (0, ("out",), False), "condition": (1, ("true", "false"), False),
              "action": (1, ("out",), False), "goto": (1, (), True), "end": (1, (), False)}
# Icon of each event / guard: declared by its module (nanterino/nodes/triggers|conditions/<id>.py `icon`), lot M2.
EVENT_ICON = {n.id: n.icon for n in _TRIGGER_NODES.values()}
# Icon of each action: declared by its module (nanterino/nodes/actions/<id>.py `icon`), lot M1.
ACTION_ICON = {n.id: n.icon for n in _ACTION_NODES.values()}
GUARD_ICON = {n.id: n.icon for n in _CONDITION_NODES.values()}
STATE_ICON = {"veille": "moon", "accueil": "hand-move", "ecoute": "ear", "reponse": "message", "relance": "refresh",
              "cloture": "door-exit", "eteint": "power"}
INTENT_ICON = {"appel": "bell", "au_revoir": "hand-move", "chanson": "music", "question": "question-mark"}
DELAY_ICON, SINCE_ICON = "clock", {"state": "clock", "last_speech": "microphone"}
DEFAULT_STATE_ICON, DEFAULT_INTENT_ICON = "circle-dot", "message"
assert set(EVENT_ICON) == set(EVENT_DOC) and set(ACTION_ICON) == set(ACTION_DOC) and set(GUARD_ICON) == set(GUARD_DOC), \
    "every event / action / guard needs exactly one icon"

# ---------------------------------------------------------------- themes (lot L5, node menu)
# The editor's node menu is Category (Déclencheurs / Actions / Conditions = node kinds) > Theme > item. Themes are
# SHARED by the three categories (a theme "Micro & écoute" holds triggers, actions and conditions). Each registry
# entry has exactly one theme (checked below); the editor shows a theme in a category only when it has items there and
# never decides a theme itself. Theme order = dict order. value = (French label, Tabler icon, help).
THEME_DOC = {
    "conversation": ("Conversation", "message", "Le déroulé d'un échange : accueil, réponse, tours de parole, demandes de répétition."),
    "parole": ("Parole & voix", "volume", "Ce que le robot dit, et quand il a fini de parler."),
    "micro": ("Micro & écoute", "microphone", "Le micro, l'écoute du visiteur et les interruptions."),
    "vision": ("Visage & vision", "scan-eye", "La caméra (visages vus) et le visage affiché à l'écran (expression, regard)."),
    "intentions": ("Intentions", "bell", "Ce que le visiteur veut dire, reconnu dans sa phrase (panneau Intentions)."),
    "variables": ("Variables", "text-caption", "Les variables du graphe (panneau Variables)."),
    "listes": ("Listes", "square", "Les listes du graphe (panneau Variables, onglet Listes)."),
    "etat": ("État", "arrow-right", "L'état du robot (variable système etat) : y entrer, le tester, le changer."),
    "temps": ("Temps & délais", "clock", "Délais, attentes, horaires d'ouverture et inactivité."),
    "systeme": ("Tableau de bord & système", "power", "Les boutons du tableau de bord et les commandes tapées."),
    "evenements": ("Événements", "bolt", "Événements programmés ou envoyés par le graphe lui-même."),
    # lot B1 (2026-11-04): last, so the order of the older themes (and the goldens) does not move
    "mouvement": ("Mouvement", "hand-move", "Le corps du robot : regarder, gestes, poses, bras, déplacements de la base, "
                  "arrêts (simulé tant que les moteurs ne sont pas branchés)."),
}
# A node module with an unknown theme / argument kind stops the start here (NodeRegistryError naming the file),
# before the generic theme asserts below.
_nodes.check_family(_ACTION_NODES, "actions", THEME_DOC, ARG_KINDS)
_nodes.check_family(_CONDITION_NODES, "conditions", THEME_DOC, ARG_KINDS)
_nodes.check_family(_TRIGGER_NODES, "triggers", THEME_DOC, ARG_KINDS)
_vartypes.check_registry(VARTYPES)   # lot M3: every type default is a valid value (RegistryError naming the file)
# Theme of each event / guard: declared by its module (`theme` attribute, never the folder), lot M2.
EVENT_THEME = {n.id: n.theme for n in _TRIGGER_NODES.values()}
# Theme of each action: declared by its module (nanterino/nodes/actions/<id>.py `theme`), lot M1.
ACTION_THEME = {n.id: n.theme for n in _ACTION_NODES.values()}
GUARD_THEME = {n.id: n.theme for n in _CONDITION_NODES.values()}
# Theme of the entries the editor builds from DATA (not from a registry): one trigger per intent, the delay trigger,
# one "etat becomes X" trigger / "etat = X" condition / "Changer d'état → X" action per state.
THEME_SLOTS = {"intent": "intentions", "after": "temps", "state_enter": "etat", "state_test": "etat", "state_move": "etat"}
assert set(EVENT_THEME) == set(EVENT_DOC) and set(ACTION_THEME) == set(ACTION_DOC) and set(GUARD_THEME) == set(GUARD_DOC), \
    "every event / action / guard needs exactly one theme"
assert set(EVENT_THEME.values()) | set(ACTION_THEME.values()) | set(GUARD_THEME.values()) | set(THEME_SLOTS.values()) <= set(THEME_DOC), \
    "a theme used by an entry is missing from THEME_DOC"

# Help text of an argument, by argument kind (inspector tooltips); a kind without an entry gets no help.
ARG_KIND_HELP = {
    "cfgkey": "Une phrase de la configuration du robot : accueil, relance, au revoir ou demande de répétition.",
    "event": "Événement envoyé au graphe : il lance les déclencheurs « Un événement arrive » qui l'attendent.",
    "delay": "Un nombre de secondes, ou le nom d'une clé de réglage (sa valeur actuelle est utilisée).",
    "text": "Phrase libre ; sa voix est calculée une fois, au chargement du graphe.",
    "expression": "Expression du visage affichée à l'écran.",
    "seconds": "Durée en secondes (un nombre).",
    "gazemode": "Où regarde le visage affiché.",
    "var": "Variable modifiée (à créer dans le panneau Variables) ; « etat » change l'état du robot.",
    "numvar": "Variable de type nombre ou durée qui sera modifiée.",
    "boolvar": "Variable vrai/faux qui sera inversée.",
    "anyvar": "Variable lue ; les variables système (etat, tours…) sont permises.",
    "anyboolvar": "Variable vrai/faux lue ; les variables système sont permises.",
    "wlist": "Liste modifiée ; une liste liée à la configuration ou à une intention est en lecture seule.",
    "rlist": "Liste de textes dans laquelle une phrase est tirée au hasard.",
    "rlist_any": "Liste lue (tous types).",
    "value": "Valeur du même type que la variable ou la liste choisie juste au-dessus.",
    "listvalue": "Élément cherché ; « $utterance » = la phrase que le visiteur vient de dire.",
    "op": "Comparaison : = et ≠ pour tous les types ; <, ≤, >, ≥ seulement pour les nombres et les durées.",
    "number": "Un nombre (négatif pour retirer).",
    "datetimevar": "Variable de type date et heure.",
    "timervar": "Variable de type chrono.",
    "textvar": "Variable texte ou phrase dont le contenu est dit (les variables système permises).",
    "timeref": "Variable date et heure, ou chrono : le temps écoulé depuis la date ou depuis le départ du chrono.",
    "datevar_any": "Variable date et heure lue ; « heure » (maintenant) est permise.",
    "wtextlist": "Liste de textes modifiable.",
    "wdict": "Dictionnaire modifiable (panneau Variables, onglet Listes, sorte « dictionnaire »).",
    "rdict": "Dictionnaire lu (tous types de valeurs).",
    "rtextdict": "Dictionnaire dont les valeurs sont des textes à dire.",
    "dictkey": "Clé du dictionnaire ; « $utterance » = une clé contenue dans la phrase du visiteur, « $variable » = la valeur d'une variable texte.",
    "seconds0": "Nombre de secondes (0 ou plus).",
    "hhmm": "Heure au format hh:mm (00:00 à 23:59).",
    "weekdays": "Un ou plusieurs jours de la semaine.",
    "optext": "Texte dit quand la clé est absente ; vide = rien n'est dit.",
    "onoff": "Activé ou désactivé.",
    "loglevel": "Niveau du message : information, avertissement ou erreur.",
    "media": "Fichier son (.wav) du dossier media/ du robot.",
    # lot B1 (Mouvement)
    "gesture": "Geste de la bibliothèque nanterino/body/gestures.yaml.",
    "pose": "Pose de la bibliothèque nanterino/body/gestures.yaml.",
    "bodygroup": "Partie du corps : tout le corps, la tête, un bras ou la base.",
    "arm": "Bras droit, bras gauche ou les deux.",
}


def state_icon(name: str) -> str:
    return STATE_ICON.get(name, DEFAULT_STATE_ICON)


def all_icons() -> list:
    """Sorted union of every icon the vocabulary can return (what the editor must vendor)."""
    used = {i for _l, i in KIND_DOC.values()}
    for d in (EVENT_ICON, ACTION_ICON, GUARD_ICON, STATE_ICON, INTENT_ICON, SINCE_ICON):
        used |= set(d.values())
    used |= {ic for _l, ic, _h in THEME_DOC.values()}
    return sorted(used | {DELAY_ICON, DEFAULT_STATE_ICON, DEFAULT_INTENT_ICON})


_props.check_registry(_props.GETS, _props.SETS, all_icons(), VAR_TYPES)   # lot M4: vendored icons, known output types

_TOP_KEYS = {"version", "description", "states", "global", "intents", "variables"}
_STATE_KEYS = {"description", "on_enter", "transitions"}
_TR_KEYS = {"on", "after", "since", "when", "only_in", "not_in", "do", "to", "reason", "then", "description", "enabled", "fan",
            "var", "value"}
_INTENT_KEYS = {"description", "words", "words_from", "regex", "only_in", "icon"}
_INTENT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class GraphError(ValueError):
    """The graph file is unreadable or invalid; the message lists every problem found.

    `items` keeps the problems as (where, message) pairs so the visual compiler can map them back
    to editor nodes.
    """

    def __init__(self, message, items=()):
        super().__init__(message)
        self.items = tuple(items)


# ---------------------------------------------------------------- frozen model
@dataclass(frozen=True)
class Call:
    name: str
    args: types.MappingProxyType

    def label(self) -> str:
        return self.name if not self.args else "%s(%s)" % (self.name, ", ".join("%s=%s" % kv for kv in self.args.items()))


@dataclass(frozen=True)
class Cond:
    """One guard of a `when:` list; `negate` comes from the `{not: guard}` form."""
    name: str
    negate: bool = False
    args: types.MappingProxyType = types.MappingProxyType({})   # guards with arguments (var_compare ...)

    def label(self) -> str:
        core = self.name if not self.args else "%s(%s)" % (self.name, ", ".join("%s=%s" % kv for kv in self.args.items()))
        return ("not " if self.negate else "") + core


class _NoValue:
    """Sentinel: a `var_changed` transition without `value:` reacts to any change."""

    def __repr__(self):
        return "NOVALUE"


NOVALUE = _NoValue()


@dataclass(frozen=True)
class Variable:
    name: str
    type: str
    value: object
    choices: tuple = ()
    description: str = ""
    vmin: object = None          # lot L11: optional bounds of number / integer (YAML `min` / `max` / `step`)
    vmax: object = None
    step: object = None
    scope: str = "global"        # "conversation": reset by clear_conversation
    persist: bool = False        # global only: kept in state/vars.json (brain.py + var_store.py)


@dataclass(frozen=True)
class VarList:
    name: str
    type: str
    items: object                 # tuple (kind list) or read-only mapping key -> value (kind dict)
    description: str = ""
    source: tuple | None = None   # ("cfg", key) | ("intent", name): bound, read-only; None = user list (writable)
    kind: str = "list"            # lot L11: "list" | "dict"
    mode: str = "plain"           # "plain" | "shuffle" (say_random bag) | "history" (last `maxlen` items)
    maxlen: int | None = None     # YAML `max`: an addition beyond it drops the oldest item
    scope: str = "global"
    persist: bool = False


@dataclass(frozen=True)
class Transition:
    on: str | None
    after: object          # None, a number, or a cfg key
    since: str | None
    when: tuple
    only_in: tuple | None
    not_in: tuple | None
    do: tuple
    to: str | None
    reason: str | None
    then: tuple
    description: str
    enabled: bool = True   # False = kept in the file / editor but ignored by the engine
    fan: str | None = None  # branches of ONE editor trigger share a fan id: shared leading actions run once
    var: str | None = None  # `on: var_changed` only: the watched variable
    value: object = NOVALUE  # `on: var_changed` only: the value that must be reached (NOVALUE = any change)


@dataclass(frozen=True)
class State:
    name: str
    description: str
    on_enter: tuple
    transitions: tuple


@dataclass(frozen=True)
class Intent:
    name: str
    description: str
    words: tuple
    words_from: str | None
    regex: object          # compiled pattern or None
    regex_src: str | None
    only_in: tuple | None
    icon: str | None = None


@dataclass(frozen=True)
class Graph:
    states: types.MappingProxyType
    globals: tuple
    intents: tuple
    source: str
    warnings: tuple = ()
    variables: types.MappingProxyType = types.MappingProxyType({})   # name -> Variable (user variables)
    lists: types.MappingProxyType = types.MappingProxyType({})       # name -> VarList
    diagnostics: tuple = ()   # lot L11: non-blocking (where, message, kind) remarks, e.g. kind "out_of_bounds"

    def timer_watches(self) -> tuple:
        """(timer variable, seconds) pairs some enabled `timer_reached` transition waits for (polled by the heartbeat).
        Owned by nanterino/nodes/triggers/timer_reached.py (subscribe)."""
        return _TRIGGER_NODES["timer_reached"].subscribe(self)

    def watched_vars(self) -> frozenset:
        """Variables some enabled `var_changed` transition listens to (the brain posts only those changes).
        Owned by nanterino/nodes/triggers/var_changed.py (subscribe)."""
        return _TRIGGER_NODES["var_changed"].subscribe(self)

    def variables_raw(self) -> dict:
        """The `variables:` block as plain data (to_dict, vocabulary)."""
        names = {}
        for v in self.variables.values():
            d = {"type": v.type, "value": v.value}
            if v.choices:
                d["choices"] = list(v.choices)
            for k, attr, dflt in (("min", "vmin", None), ("max", "vmax", None), ("step", "step", None),
                                  ("scope", "scope", "global"), ("persist", "persist", False)):   # lot L11, only when set
                if getattr(v, attr) != dflt:
                    d[k] = getattr(v, attr)
            if v.description:
                d["description"] = v.description
            names[v.name] = d
        lists = {}
        for li in self.lists.values():
            d = {"type": li.type}
            if li.kind != "list":
                d["kind"] = li.kind
            if li.source:
                d["from" if li.source[0] == "cfg" else "intent"] = li.source[1]
            else:
                d["items"] = dict(li.items) if li.kind == "dict" else list(li.items)
            for k, attr, dflt in (("mode", "mode", "plain"), ("max", "maxlen", None), ("scope", "scope", "global"),
                                  ("persist", "persist", False)):
                if getattr(li, attr) != dflt:
                    d[k] = getattr(li, attr)
            if li.description:
                d["description"] = li.description
            lists[li.name] = d
        return {"names": names, "lists": lists}

    def to_dict(self) -> dict:
        """JSON-friendly view for GET /api/graph (future visual editor)."""
        def tr(t):
            d = {"description": t.description}
            if not t.enabled:
                d["enabled"] = False
            for k in ("on", "after", "since", "to", "reason", "fan", "var"):
                if getattr(t, k) is not None:
                    d[k] = getattr(t, k)
            if t.value is not NOVALUE:
                d["value"] = t.value
            for k in ("when", "only_in", "not_in"):
                if getattr(t, k):
                    d[k] = [c.label() if k == "when" else c for c in getattr(t, k)]
            for k in ("do", "then"):
                if getattr(t, k):
                    d[k] = [c.label() for c in getattr(t, k)]
            return d
        return {
            "source": self.source, "warnings": list(self.warnings),
            "states": {n: {"description": s.description, "on_enter": [c.label() for c in s.on_enter],
                           "transitions": [tr(t) for t in s.transitions]} for n, s in self.states.items()},
            "global": [tr(t) for t in self.globals],
            "intents": {i.name: {"description": i.description, "only_in": list(i.only_in or ()),
                                 **({"words": list(i.words)} if i.words else {}),
                                 **({"words_from": i.words_from} if i.words_from else {}),
                                 **({"regex": i.regex_src} if i.regex_src else {}),
                                 **({"icon": i.icon} if i.icon else {})} for i in self.intents},
            **({"variables": self.variables_raw()} if (self.variables or self.lists) else {}),
        }


# ---------------------------------------------------------------- loader
class _Loader(yaml.SafeLoader):
    """SafeLoader where only true/false are booleans (on/off/yes/no stay plain strings)."""


_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:bool"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()}
_Loader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
                              list("tTfF"))


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class _Parser:
    """Collects ALL problems instead of stopping at the first one, so a file is fixed in one pass."""

    def __init__(self, data, cfg, source):
        self.data, self.cfg, self.source = data, cfg, source
        self.errors, self.warnings, self.items = [], [], []
        self.vars, self.lists, self.state_names = {}, {}, []   # filled by build() before any transition is read
        self.intent_names, self.list_names = [], []           # lot L11: choices of intent_ref / list_ref values
        self.diagnostics = []                                 # lot L11: (where, message, kind), non-blocking
        self.list_reads, self.list_fills = [], set()          # lot L27: (where, call, list) of say_random / say_list_item; written lists

    def diag(self, where, msg, kind):
        """A non-blocking remark: kept in Graph.warnings and in Graph.diagnostics (editor badge, /api/graph/check)."""
        self.warnings.append("%s: %s" % (where, msg))
        self.diagnostics.append((where, msg, kind))

    def err(self, where, msg):
        self.errors.append("%s: %s" % (where, msg))
        self.items.append((where, msg))

    def need_desc(self, where, d):
        if not (isinstance(d.get("description"), str) and d["description"].strip()):
            self.warnings.append("%s: no French `description`" % where)
        return str(d.get("description") or "").strip()

    def as_list(self, where, v):
        if v is None:
            return []
        if isinstance(v, (str, dict)):
            return [v]
        if isinstance(v, list):
            return v
        self.err(where, "expected a name or a list, got %r" % (v,))
        return []

    def calls(self, where, v, allow_post=True):
        out = []
        for i, item in enumerate(self.as_list(where, v)):
            if isinstance(item, str):
                name, args = item, {}
            elif isinstance(item, dict) and len(item) == 1:
                name, args = next(iter(item.items()))
                if args is None:
                    args = {}
            else:
                self.err(where, "action #%d must be a name or {name: {args}}" % i); continue
            spec = ACTION_SPECS.get(name)
            if spec is None:
                self.err(where, "unknown action %r (allowed: %s)" % (name, ", ".join(sorted(ACTION_SPECS)))); continue
            if not isinstance(args, dict):
                self.err(where, "arguments of %s must be a mapping" % name); continue
            if set(args) != set(spec):
                self.err(where, "action %s takes %s, got %s" % (name, sorted(spec) or "no argument", sorted(args))); continue
            args = dict(args, **self.var_args(where, name, spec, args))   # lot M4: compiled value sources
            for k, kind in spec.items():
                val = args[k]
                if kind == "cfgkey" and val not in self.cfg:
                    self.err(where, "%s.%s: %r is not a config key" % (name, k, val))
                elif kind == "event" and (val not in EVENTS or val in ("tick",) + WATCH_EVENTS):
                    self.err(where, "%s.%s: unknown event %r" % (name, k, val))
                elif kind == "delay" and not (_num(val) or (isinstance(val, str) and _num(self.cfg.get(val)))):
                    self.err(where, "%s.%s: %r is neither a number nor a numeric config key" % (name, k, val))
                elif kind == "text" and not (isinstance(val, str) and val.strip() and len(val) <= TEXT_MAX):
                    self.err(where, "%s.%s: expected a non-empty text of at most %d characters" % (name, k, TEXT_MAX))
                elif kind == "expression" and val not in EXPRESSIONS:
                    self.err(where, "%s.%s: unknown expression %r (allowed: %s)" % (name, k, val, ", ".join(EXPRESSIONS)))
                elif kind == "gazemode" and val not in GAZE_MODES:
                    self.err(where, "%s.%s: unknown gaze mode %r (allowed: %s)" % (name, k, val, ", ".join(GAZE_MODES)))
                elif kind == "seconds" and not (_num(val) and 0 < val <= SECONDS_MAX):
                    self.err(where, "%s.%s: expected a number of seconds in (0, %d]" % (name, k, SECONDS_MAX))
                elif kind in MOTION_ENUMS and val not in MOTION_ENUMS[kind]:   # lot B1
                    self.err(where, "%s.%s: unknown %s %r (allowed: %s)" % (name, k, kind, val, ", ".join(MOTION_ENUMS[kind])))
            if name in EMPTY_LIST_READERS and isinstance(args.get("list"), str):
                self.list_reads.append((where, name, args["list"]))
            if name in LIST_FILLERS and isinstance(args.get("list"), str):   # an action that adds items to its list
                self.list_fills.add(args["list"])
            out.append(Call(name, types.MappingProxyType(dict(args))))
        return tuple(out)

    def empty_list_diagnostics(self):
        """Lot L27: warning `empty_list` for a say_random / say_list_item whose list is empty in the `variables` block
        and filled by no action: it never says anything (its completion event still fires, ok=False)."""
        for where, call, name in self.list_reads:
            li = self.lists.get(name)
            if li is None or li.source is not None or li.kind != "list" or li.items or name in self.list_fills:
                continue
            self.diag(where, "%s.list: list %r is empty and no action fills it (nothing is said, the end event "
                             "still fires)" % (call, name), "empty_list")

    # -- variables (lot L1)
    def var_info(self, name):
        """(type, choices) of a user or system variable, or None."""
        if name in self.vars:
            v = self.vars[name]
            return v.type, v.choices
        if name in SYSTEM_VARS:
            return SYSTEM_VARS[name][0], (tuple(self.state_names) if name == "etat" else tuple(WEEKDAYS) if name == "jour" else ())
        return None

    def type_choices(self, vtype, choices=()):
        """Allowed values of a choice / reference type while parsing (the Graph does not exist yet): the type
        module's choices(ctx), the parser itself exposing intent_names / list_names / state_names (lot M3)."""
        t = VARTYPES.get(vtype)
        return t.choices(self, choices) if t is not None else tuple(choices)

    def check_value(self, where, what, vtype, choices, val, utterance=False):
        """Validate a literal (or a `$<var>` reference) against a variable / list item type."""
        if isinstance(val, str) and val.startswith("$"):
            ref = val[1:]
            if ref == "utterance":   # the visitor's last sentence (list_contains: an item contained in it)
                if vtype not in TEXT_TYPES:
                    self.err(where, "%s: $utterance is a text, %s expected" % (what, vtype))
                return
            info = self.var_info(ref)
            if info is None:
                self.err(where, "%s: unknown variable %r" % (what, ref))
            elif not compatible(info[0], vtype):
                self.err(where, "%s: variable %r is %s, expected %s" % (what, ref, info[0], vtype))
            return
        if not type_ok(vtype, val, self.type_choices(vtype, choices)):
            self.err(where, "%s: %r is not a valid %s value%s" % (
                what, val, vtype, " (choices: %s)" % ", ".join(map(str, choices)) if vtype == "choice" else ""))

    def var_args(self, where, name, spec, args):
        """Check the variable-related arguments of an action / guard call (kinds of ACTION_DOC / GUARD_ARGS).

        Returns {argument: compiled value} for the arguments given as a value source (lot M4); the caller stores
        those instead of the raw mapping (a shorthand source compiles to its `$x` / `$utterance` / literal form, which
        then goes through the pre-M4 checks below, messages included)."""
        target = None                                   # (type, choices) the `value` argument must match
        # lot N1: a guard whose `op` compares a count (list_count_compare: no value argument) orders any list
        count_op = "count" in spec and not any(kd in ("value", "listvalue") for kd in spec.values())
        target_var = None                               # lot L11: user Variable behind `target` (bounds diagnostic)
        fixed = {}
        for k, kind in spec.items():
            val = args.get(k)
            what = "%s.%s" % (name, k)
            if kind in PROPERTY_FIELD and _props.is_property(val):
                field = target if PROPERTY_FIELD[kind] == "of" else (PROPERTY_FIELD[kind], ())
                if field is None:
                    continue   # the variable / list argument was refused: already reported
                val = _props.check_field(self, where, what, field[0], field[1], val, shorthand=kind in SHORTHAND_KINDS)
                if val is _props.INVALID:
                    continue
                fixed[k] = val
                if _props.is_property(val):
                    continue   # fully checked by the source (typing included)
            if kind in VAR_KIND_TYPES:
                writable, allowed = VAR_KIND_TYPES[kind]
                info = self.var_info(val) if isinstance(val, str) else None
                if info is None:
                    self.err(where, "%s: unknown variable %r" % (what, val)); continue
                if writable and val in SYSTEM_VARS:
                    self.err(where, "%s: %r is a read-only system variable%s" % (
                        what, val, " (change the state with `to:`)" if val == "etat" else "")); continue
                if kind == "anyvar" and val == "etat":
                    self.err(where, "%s: compare the state with only_in / not_in or by placing the transition under the state" % what); continue
                if kind == "numvar" and info[0] not in allowed:
                    self.err(where, "%s: %r is not a number or duration variable" % (what, val)); continue
                if kind in ("boolvar", "anyboolvar") and info[0] != "bool":
                    self.err(where, "%s: %r is not a true/false variable" % (what, val)); continue
                if kind == "var" and info[0] == "timer":
                    self.err(where, "%s: %r is a timer: use timer_start / timer_reset" % (what, val)); continue
                if allowed is not None and info[0] not in allowed:
                    self.err(where, "%s: %r is a %s variable, expected %s" % (what, val, info[0], " / ".join(sorted(allowed)))); continue
                target, target_var = info, self.vars.get(val)
                if kind == "timeref":
                    target = ("number", ())     # elapsed_since compares seconds
            elif kind in LIST_KIND_RULES:
                writable, allowed, lkind = LIST_KIND_RULES[kind]
                li = self.lists.get(val) if isinstance(val, str) else None
                if li is None:
                    self.err(where, "%s: unknown %s %r" % (what, "dictionary" if lkind == "dict" else "list", val)); continue
                if li.kind != lkind:
                    self.err(where, "%s: %r is %s" % (what, val, "a list, not a dictionary" if lkind == "dict"
                                                      else "a dictionary (use the dictionary actions / conditions)")); continue
                if writable and li.source:
                    self.err(where, "%s: list %r is bound to %s %r (read-only)" % (
                        what, val, "config key" if li.source[0] == "cfg" else "intent", li.source[1])); continue
                if allowed is not None and li.type not in allowed:
                    self.err(where, "%s: %s %r does not hold texts" % (what, "dictionary" if lkind == "dict" else "list", val)); continue
                target, target_var = (li.type, ()), None
            elif kind == "op":
                if val not in OPS:
                    self.err(where, "%s: unknown operator %r (allowed: %s)" % (what, val, " ".join(OPS)))
                elif val in ORDER_OPS and target and target[0] not in ORDERED_TYPES and not count_op:
                    self.err(where, "%s: %r only compares numbers, durations or dates" % (what, val))
            elif kind == "number":
                if not _num(val):
                    self.err(where, "%s: expected a number" % what)
            elif kind == "seconds0":
                if not (_num(val) and 0 <= val <= 10 ** 7):
                    self.err(where, "%s: expected a number of seconds >= 0" % what)
            elif kind == "hhmm":
                if not (isinstance(val, str) and _HHMM.match(val)):
                    self.err(where, "%s: expected a time hh:mm (00:00 to 23:59), got %r" % (what, val))
            elif kind == "weekdays":
                if not (isinstance(val, list) and val and all(isinstance(d, str) and d in WEEKDAYS for d in val)
                        and len(set(val)) == len(val)):
                    self.err(where, "%s: expected distinct days among %s" % (what, ", ".join(WEEKDAYS)))
            elif kind == "onoff":
                if val not in ONOFF:
                    self.err(where, "%s: expected on or off, got %r" % (what, val))
            elif kind == "loglevel":
                if val not in LOG_LEVELS:
                    self.err(where, "%s: unknown level %r (allowed: %s)" % (what, val, ", ".join(LOG_LEVELS)))
            elif kind == "media":
                if not (isinstance(val, str) and MEDIA_NAME.match(val) and val.lower().endswith(PLAYABLE_EXTS)):
                    self.err(where, "%s: expected a .wav file name of media/, got %r" % (what, val))
            elif kind == "optext":
                if not (isinstance(val, str) and len(val) <= TEXT_MAX):
                    self.err(where, "%s: expected a text of at most %d characters (may be empty)" % (what, TEXT_MAX))
            elif kind == "dictkey":
                if isinstance(val, str) and val.startswith("$") and val != "$utterance":
                    info = self.var_info(val[1:])
                    if info is None:
                        self.err(where, "%s: unknown variable %r" % (what, val[1:]))
                    elif not compatible(info[0], "string"):
                        self.err(where, "%s: variable %r is %s, a text is expected as key" % (what, val[1:], info[0]))
                elif not (isinstance(val, str) and val.strip() and len(val) <= KEY_MAX):
                    self.err(where, "%s: expected a key text of 1..%d characters (or $utterance / $variable)" % (what, KEY_MAX))
            elif kind in ("value", "listvalue"):
                if target is not None:
                    n_err = len(self.errors)
                    self.check_value(where, what, target[0], target[1], val, utterance=kind == "listvalue")
                    tv = target_var
                    if (len(self.errors) == n_err and tv is not None and _num(val)
                            and ((tv.vmin is not None and val < tv.vmin) or (tv.vmax is not None and val > tv.vmax))):
                        self.diag(where, "%s: %r is outside [%s, %s] of variable %r (clamped at run time)" % (
                            what, val, "-inf" if tv.vmin is None else tv.vmin, "+inf" if tv.vmax is None else tv.vmax, tv.name),
                            "out_of_bounds")
        return fixed

    def guard_enums(self, where, name, spec, args):
        """Lot N2: the enumerated kinds a CONDITION may take (expression_is, gaze_is, scheduled_pending, event_recent; lot N3:
        the media file of media_is).

        Actions check the same kinds in calls() (same rules, same messages); var_args does not, so an action is never
        reported twice."""
        for k, kind in spec.items():
            val, what = args.get(k), "%s.%s" % (name, k)
            if kind == "expression" and val not in EXPRESSIONS:
                self.err(where, "%s: unknown expression %r (allowed: %s)" % (what, val, ", ".join(EXPRESSIONS)))
            elif kind == "gazemode" and val not in GAZE_MODES:
                self.err(where, "%s: unknown gaze mode %r (allowed: %s)" % (what, val, ", ".join(GAZE_MODES)))
            elif kind == "event" and (val not in EVENTS or val in ("tick",) + WATCH_EVENTS):
                self.err(where, "%s: unknown event %r" % (what, val))
            elif kind == "media" and not (isinstance(val, str) and MEDIA_NAME.match(val) and val.lower().endswith(PLAYABLE_EXTS)):
                # lot N3 (media_is): the same rule and message as the play_media action
                self.err(where, "%s: expected a .wav file name of media/, got %r" % (what, val))
            elif kind in MOTION_ENUMS and val not in MOTION_ENUMS[kind]:
                # lot B1 (at_pose, is_moving, joint_at_limit): the same rule and message as the Mouvement actions
                self.err(where, "%s: unknown %s %r (allowed: %s)" % (what, kind, val, ", ".join(MOTION_ENUMS[kind])))

    def variables(self, d, intent_names):
        """Parse the `variables:` block into self.vars / self.lists."""
        if d is None:
            return
        if not isinstance(d, dict) or set(d) - {"names", "lists"}:
            self.err("variables", "must be a mapping with `names:` and/or `lists:`"); return
        names, lists = d.get("names") or {}, d.get("lists") or {}
        if not isinstance(names, dict) or not isinstance(lists, dict):
            self.err("variables", "`names:` and `lists:` must be mappings"); return
        self.list_names = [n for n in lists if isinstance(n, str)]   # list_ref values may name a list declared below
        for n, spec in names.items():
            w = "variable %s" % n
            if not (isinstance(n, str) and VAR_NAME.match(n)) or n in SYSTEM_VARS:
                self.err(w, "name must match [a-z][a-z0-9_]{0,31} and not be a system variable (%s)" % ", ".join(SYSTEM_VARS)); continue
            if not isinstance(spec, dict):
                self.err(w, "must be a mapping {type, value}"); continue
            for k in set(spec) - _VAR_KEYS:
                self.err(w, "unknown key %r" % k)
            vt = spec.get("type")
            if vt not in VAR_TYPES:
                self.err(w, "type must be one of %s" % ", ".join(VAR_TYPES)); continue
            choices = VARTYPES[vt].parse_choices(self, w, spec)   # lot M3: () / declared choices / None = error
            if choices is None:
                continue
            if "value" not in spec:
                self.err(w, "`value:` (initial value) is required"); continue
            n_err = len(self.errors)
            if isinstance(spec["value"], str) and spec["value"].startswith("$"):
                self.err(w, "the initial value cannot be a reference"); continue
            self.check_value(w, "value", vt, choices, spec["value"])
            vmin, vmax, step = self.bounds(w, vt, spec)
            scope, persist = self.scope_persist(w, spec)
            val = spec["value"]
            if len(self.errors) == n_err and _num(val) and ((vmin is not None and val < vmin) or (vmax is not None and val > vmax)):
                self.err(w, "initial value %r is outside [%s, %s]" % (val, vmin, vmax))
            if len(self.errors) == n_err:
                self.vars[n] = Variable(n, vt, val, choices, str(spec.get("description") or "").strip(), vmin, vmax, step, scope, persist)
        for n, spec in lists.items():
            w = "list %s" % n
            if not (isinstance(n, str) and VAR_NAME.match(n)) or n in SYSTEM_VARS or n in self.vars:
                self.err(w, "name must match [a-z][a-z0-9_]{0,31} and differ from every variable"); continue
            if not isinstance(spec, dict):
                self.err(w, "must be a mapping {type, items}"); continue
            for k in set(spec) - _LIST_KEYS:
                self.err(w, "unknown key %r" % k)
            lkind = spec.get("kind", "list")
            if lkind not in LIST_KINDS:
                self.err(w, "kind must be one of %s" % ", ".join(LIST_KINDS)); continue
            lt = spec.get("type", "string")
            if lt not in LIST_TYPES:
                self.err(w, "type must be one of %s" % ", ".join(LIST_TYPES)); continue
            if sum(k in spec for k in ("items", "from", "intent")) != 1:
                self.err(w, "exactly one of items / from (config key) / intent is required"); continue
            mode, maxlen = spec.get("mode", "plain"), spec.get("max")
            if mode not in LIST_MODES:
                self.err(w, "mode must be one of %s" % ", ".join(LIST_MODES)); continue
            if maxlen is not None and not (isinstance(maxlen, int) and not isinstance(maxlen, bool) and 1 <= maxlen <= LIST_MAX):
                self.err(w, "`max:` must be an integer in 1..%d" % LIST_MAX); continue
            if _listmodes.LISTMODES[mode].needs_max and maxlen is None:
                self.err(w, "mode %s needs `max:` (how many items are kept)" % mode); continue
            n_err = len(self.errors)
            scope, persist = self.scope_persist(w, spec)
            if len(self.errors) > n_err:
                continue
            desc = str(spec.get("description") or "").strip()
            # lot M3: the kind module parses the rest (dict: key -> value pairs; list: items / from / intent)
            vl = _listkinds.LISTKINDS[lkind].parse(self, w, n, spec, lt, mode, maxlen, scope, persist, desc, intent_names)
            if vl is not None:
                self.lists[n] = vl

    def bounds(self, w, vt, spec):
        """`min` / `max` / `step` of a number / integer variable (lot L11); errors are collected, values returned."""
        vmin, vmax, step = spec.get("min"), spec.get("max"), spec.get("step")
        if vmin is None and vmax is None and step is None:
            return None, None, None
        if vt not in BOUNDED_TYPES:
            self.err(w, "`min` / `max` / `step` only go with types %s" % ", ".join(sorted(BOUNDED_TYPES)))
            return None, None, None
        for k, x in (("min", vmin), ("max", vmax)):
            if x is not None and not (_num(x) and (not VARTYPES[vt].integral or isinstance(x, int))):
                self.err(w, "`%s:` must be %s" % (k, "an integer" if VARTYPES[vt].integral else "a number"))
        if step is not None and not (_num(step) and step > 0):
            self.err(w, "`step:` must be a number > 0")
        if _num(vmin) and _num(vmax) and vmin > vmax:
            self.err(w, "`min:` is greater than `max:`")
        return vmin, vmax, step

    def scope_persist(self, w, spec):
        """`scope` (global | conversation) and `persist` (global only) of a variable or list (lot L11)."""
        scope, persist = spec.get("scope", "global"), spec.get("persist", False)
        if scope not in SCOPES:
            self.err(w, "`scope:` must be one of %s" % ", ".join(SCOPES)); scope = "global"
        if not isinstance(persist, bool):
            self.err(w, "`persist:` must be true or false"); persist = False
        if persist and scope != "global":
            self.err(w, "`persist: true` needs `scope: global` (a conversation variable is reset for every visitor)")
        return scope, persist

    def transition(self, where, t, state_names, intent_events, is_global):
        if not isinstance(t, dict):
            self.err(where, "a transition must be a mapping"); return None
        for k in set(t) - _TR_KEYS:
            self.err(where, "unknown key %r (allowed: %s)" % (k, ", ".join(sorted(_TR_KEYS))))
        on, after, since = t.get("on"), t.get("after"), t.get("since")
        if (on is None) == (after is None):
            self.err(where, "exactly one of `on:` (event) or `after:` (delay) is required")
        if on is not None and (on not in EVENTS - INTERNAL_EVENTS and on not in intent_events):
            self.err(where, "unknown event %r (allowed: %s, intent.*)" % (
                on, ", ".join(sorted(EVENTS - INTERNAL_EVENTS))))
        if after is not None:
            if is_global:
                self.err(where, "`after:` is not allowed in global transitions")
            if not (_num(after) or (isinstance(after, str) and _num(self.cfg.get(after)))):
                self.err(where, "`after: %r` is neither a number nor a numeric config key" % (after,))
            since = since or "state"
            if since not in SINCE:
                self.err(where, "`since` must be one of %s" % (SINCE,))
        elif since is not None:
            self.err(where, "`since:` only goes with `after:`")
        var, value = t.get("var"), t.get("value", NOVALUE)
        if on in WATCH_EVENTS:   # lot M2: the trigger module checks its own `var:` / `value:`
            _TRIGGER_NODES[on].check(self, where, var, value)
        elif var is not None or value is not NOVALUE:
            self.err(where, "`var:` / `value:` only go with `on: var_changed` / `on: timer_reached`")
        when = []
        for g in self.as_list(where, t.get("when")):
            neg = False
            if isinstance(g, dict) and set(g) == {"not"}:  # negated guard: `when: [{not: guard}]` / {not: {g: args}}
                g, neg = g["not"], True
            args = {}
            if isinstance(g, dict):          # guard with arguments: {var_compare: {name, op, value}}
                if len(g) != 1:
                    self.err(where, "a guard mapping must be {not: guard} or {guard: {args}}, got %r" % (g,)); continue
                g, args = next(iter(g.items()))
                if not isinstance(args, dict):
                    self.err(where, "arguments of guard %s must be a mapping" % (g,)); continue
            if not isinstance(g, str) or g not in GUARDS:
                self.err(where, "unknown guard %r (allowed: %s)" % (g, ", ".join(sorted(GUARDS)))); continue
            spec = GUARD_SPECS[g]
            if set(args) != set(spec):
                self.err(where, "guard %s takes %s, got %s" % (g, sorted(spec) or "no argument", sorted(args))); continue
            n_err = len(self.errors)
            args = dict(args, **self.var_args(where, g, spec, args))   # lot M4: compiled value sources
            self.guard_enums(where, g, spec, args)                     # lot N2: expression / gazemode / event
            if len(self.errors) == n_err:
                when.append(Cond(g, neg, types.MappingProxyType(dict(args))))
        when = tuple(when)
        lists = {}
        for k in ("only_in", "not_in"):
            v = t.get(k)
            lists[k] = tuple(self.as_list(where, v)) if v is not None else None
            for s in lists[k] or ():
                if s not in state_names:
                    self.err(where, "%s: unknown state %r" % (k, s))
        to = t.get("to")
        if to is not None and to not in state_names:
            self.err(where, "`to:` unknown state %r (states: %s)" % (to, ", ".join(sorted(state_names))))
        reason = t.get("reason")
        if reason is not None and not isinstance(reason, str):
            self.err(where, "`reason:` must be text")
        desc = self.need_desc(where, t)
        enabled = t.get("enabled", True)
        if not isinstance(enabled, bool):
            self.err(where, "`enabled:` must be true or false")
            enabled = True
        fan = t.get("fan")
        if fan is not None and not (isinstance(fan, str) and fan.strip()):
            self.err(where, "`fan:` must be a non-empty text (written by the visual editor)")
            fan = None
        return Transition(on, after, since, when, lists["only_in"], lists["not_in"],
                          self.calls(where + " do", t.get("do")), to, reason,
                          self.calls(where + " then", t.get("then")), desc, enabled, fan,
                          var if on in WATCH_EVENTS else None, value if on in WATCH_EVENTS else NOVALUE)

    def build(self) -> Graph:
        d = self.data
        if not isinstance(d, dict):
            raise GraphError("%s: the file must contain a mapping (states:, global:, intents:)" % self.source)
        for k in set(d) - _TOP_KEYS:
            self.err("top level", "unknown key %r" % k)
        states_raw = d.get("states")
        if not isinstance(states_raw, dict) or not states_raw:
            raise GraphError("%s: `states:` is missing or empty" % self.source)
        names = set(states_raw)
        for s in REQUIRED_STATES:
            if s not in names:
                self.err("states", "required state %r is missing" % s)
        # intents first: their names define the legal `intent.*` events
        intents, ints_raw = [], d.get("intents") or {}
        if not isinstance(ints_raw, dict):
            self.err("intents", "must be a mapping"); ints_raw = {}
        for n, spec in ints_raw.items():
            w = "intent %s" % n
            if n == "question":
                self.err(w, "`question` is the implicit fallback intent, do not declare it"); continue
            if not (isinstance(n, str) and _INTENT_NAME.match(n)):
                self.err(w, "name must match [a-z][a-z0-9_]{0,31} (it becomes the event intent.<name>)"); continue
            if not isinstance(spec, dict):
                self.err(w, "must be a mapping"); continue
            for k in set(spec) - _INTENT_KEYS:
                self.err(w, "unknown key %r" % k)
            if sum(k in spec for k in ("words", "words_from", "regex")) != 1:
                self.err(w, "exactly one of words / words_from / regex is required")
            words = tuple(str(x).lower() for x in self.as_list(w, spec.get("words")) if str(x).strip())
            if "words" in spec and not words:
                self.err(w, "`words` needs at least one non-empty word")
            wf = spec.get("words_from")
            if wf is not None and not isinstance(self.cfg.get(wf), (list, tuple)):
                self.err(w, "words_from: %r is not a config key holding a list" % (wf,))
            rx = None
            if "regex" in spec:
                try:
                    rx = re.compile(spec["regex"])
                except (re.error, TypeError) as e:
                    self.err(w, "bad regex: %s" % e)
            oi = tuple(self.as_list(w, spec.get("only_in"))) if spec.get("only_in") is not None else None
            for s in oi or ():
                if s not in names:
                    self.err(w, "only_in: unknown state %r" % s)
            icon = spec.get("icon")
            if icon is not None and not (isinstance(icon, str) and re.fullmatch(r"[a-z0-9-]{1,40}", icon)):
                self.err(w, "icon must be a Tabler icon name (lowercase letters, digits, dashes)"); icon = None
            intents.append(Intent(n, self.need_desc(w, spec), words, wf, rx, spec.get("regex") if rx else None, oi, icon))
        intent_events = {"intent." + i.name for i in intents} | {"intent.question"}
        # variables next: lists may mirror an intent's words; transitions below reference both
        self.state_names = list(states_raw)
        self.intent_names = [i.name for i in intents] + ["question"]
        self.variables(d.get("variables"), {i.name: (list(i.words) or list(self.cfg.get(i.words_from) or []))
                                            for i in intents if i.words or i.words_from})
        states = {}
        for n, spec in states_raw.items():
            w = "state %s" % n
            if not isinstance(spec, dict):
                self.err(w, "must be a mapping"); continue
            for k in set(spec) - _STATE_KEYS:
                self.err(w, "unknown key %r" % k)
            trs = []
            for i, t in enumerate(spec.get("transitions") or []):
                tr = self.transition("%s transition #%d" % (w, i + 1), t, names, intent_events, False)
                if tr:
                    trs.append(tr)
            states[n] = State(n, self.need_desc(w, spec), self.calls(w + " on_enter", spec.get("on_enter")), tuple(trs))
        globs = []
        for i, t in enumerate(d.get("global") or []):
            tr = self.transition("global transition #%d" % (i + 1), t, names, intent_events, True)
            if tr:
                globs.append(tr)
        self.empty_list_diagnostics()
        if self.errors:
            raise GraphError("%s: %d problem(s):\n  - %s" % (self.source, len(self.errors), "\n  - ".join(self.errors)),
                             self.items)
        return Graph(types.MappingProxyType(states), tuple(globs), tuple(intents), self.source, tuple(self.warnings),
                     types.MappingProxyType(dict(self.vars)), types.MappingProxyType(dict(self.lists)), tuple(self.diagnostics))


def parse_graph(data, cfg: dict, source: str = "<memory>") -> Graph:
    return _Parser(data, cfg, source).build()


def load_graph(path: str, cfg: dict) -> Graph:
    """Read + validate one YAML file; raises GraphError with every problem listed."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.load(f, Loader=_Loader)
    except (OSError, yaml.YAMLError) as e:
        raise GraphError("%s: cannot read/parse: %s" % (path, e)) from e
    return parse_graph(data, cfg, path)


def load_active(cfg: dict) -> tuple[Graph, str | None]:
    """The graph the robot runs: override file if valid, else the packaged default.

    Returns (graph, error_message_or_None). A broken override is reported through log.error (so it
    lands in errors.log) and the robot still starts on the default graph.
    """
    override = cfg.get("graph_file")
    if override and os.path.exists(override):
        try:
            g = load_graph(override, cfg)
            for w in g.warnings:
                log.warning("graph %s", w)
            return g, None
        except GraphError as e:
            log.error("graph override invalid, using default graph: %s", e)
            return load_graph(DEFAULT_PATH, cfg), str(e)
    return load_graph(DEFAULT_PATH, cfg), None


def vocabulary(cfg: dict, graph: "Graph | None" = None) -> dict:
    """Palette for the visual editor (GET /api/graph/vocab), derived from the registries above.

    `graph` (the active one) supplies the states and intents, which are data, not code; delay values
    are read from `cfg` so the editor shows the current seconds.
    """
    ev = [{"id": k, "label": v[0], "help": v[1], "icon": EVENT_ICON[k], "theme": EVENT_THEME[k]}
          for k, v in EVENT_DOC.items() if not v[2]]
    ev_ids = [e["id"] for e in ev if e["id"] not in WATCH_EVENTS]   # they need arguments: never emitted by name
    _self_mod = sys.modules[__name__]
    for e in ev:
        ea = _TRIGGER_NODES[e["id"]].editor_args(_self_mod)   # lot M2: var_changed / timer_reached own their schema
        if ea is not None:
            e["args"] = ea

    def var_arg(a, kind, alabel):
        """Argument schema of the variable kinds (lot L1); None for the older kinds."""
        if kind in VAR_KIND_TYPES:
            writable, allowed = VAR_KIND_TYPES[kind]
            return {"name": a, "type": "var", "var_types": [t for t in VAR_TYPES if allowed is None or t in allowed],
                    "writable": writable, "label": alabel}
        if kind in LIST_KIND_RULES:
            writable, allowed, lkind = LIST_KIND_RULES[kind]
            return {"name": a, "type": "list", "list_types": [t for t in LIST_TYPES if allowed is None or t in allowed],
                    "list_kinds": [lkind], "writable": writable, "label": alabel}
        if kind == "dictkey":
            return {"name": a, "type": "text", "max_len": KEY_MAX, "utterance": True, "vars": True, "label": alabel}
        if kind == "seconds0":
            return {"name": a, "type": "number", "options": [], "min": 0, "label": alabel}
        if kind == "hhmm":
            return {"name": a, "type": "time", "label": alabel}
        if kind == "weekdays":
            return {"name": a, "type": "multi", "options": list(WEEKDAYS), "labels": dict(WEEKDAYS), "label": alabel}
        if kind == "optext":
            return {"name": a, "type": "text", "max_len": TEXT_MAX, "optional": True, "label": alabel}
        if kind in ("value", "listvalue"):
            d = {"name": a, "type": "value", "of": next(k for k in ("name", "list", "dict") if k in spec), "label": alabel}
            if kind == "listvalue":
                d["utterance"] = True    # "$utterance" offered
            return d
        if kind == "op":
            return {"name": a, "type": "enum", "options": list(OPS), "labels": dict(OPS), "label": alabel}
        if kind == "number":
            return {"name": a, "type": "number", "options": [], "label": alabel}
        if kind == "onoff":     # lot N1
            return {"name": a, "type": "enum", "options": list(ONOFF), "labels": dict(ONOFF), "label": alabel}
        if kind == "loglevel":
            return {"name": a, "type": "enum", "options": list(LOG_LEVELS), "labels": dict(LOG_LEVELS), "label": alabel}
        if kind == "media":
            return {"name": a, "type": "enum", "options": [m for m in media_files(cfg) if m.lower().endswith(PLAYABLE_EXTS)],
                    "label": alabel}
        # Lot N2: the enumerated kinds conditions now take too (expression_is, gaze_is, scheduled_pending, event_recent);
        # the dicts are exactly the ones the action loop below always built for them (the goldens stay additive).
        if kind == "expression":
            return {"name": a, "type": "enum", "options": list(EXPRESSIONS), "labels": dict(EXPRESSIONS), "label": alabel}
        if kind == "gazemode":
            return {"name": a, "type": "enum", "options": list(GAZE_MODES), "labels": dict(GAZE_MODES), "label": alabel}
        if kind == "event":
            return {"name": a, "type": "enum", "options": ev_ids, "label": alabel}
        if kind in MOTION_ENUMS:   # lot B1: gesture / pose (library), bodygroup, arm
            return {"name": a, "type": "enum", "options": list(MOTION_ENUMS[kind]), "labels": dict(MOTION_ENUMS[kind]),
                    "label": alabel}
        return None

    actions = []
    for name, (label, hlp, spec) in ACTION_DOC.items():
        args = []
        for a, (kind, alabel) in spec.items():
            va = var_arg(a, kind, alabel)
            if va is not None:
                args.append(va)
            elif kind == "cfgkey":
                args.append({"name": a, "type": "enum", "options": list(PHRASE_KEYS), "label": alabel})
            elif kind == "text":   # (event / expression / gazemode: var_arg above, lot N2)
                args.append({"name": a, "type": "text", "max_len": TEXT_MAX, "label": alabel})
            elif kind == "seconds":  # plain number of seconds, no config key
                args.append({"name": a, "type": "number", "options": [], "label": alabel})
            else:  # delay: a number of seconds, or one of the `options` config keys
                args.append({"name": a, "type": "number", "options": list(DELAY_DOC), "label": alabel})
        for d, (_a, (kind, _l)) in zip(args, spec.items()):
            d["help"] = ARG_KIND_HELP.get(kind, "")
            if kind in PROPERTY_FIELD:   # lot M4 (additive key): the field accepts a value source of this type
                d["props"] = PROPERTY_FIELD[kind]
        actions.append({"id": name, "label": label, "help": hlp, "icon": ACTION_ICON[name], "theme": ACTION_THEME[name], "args": args})
    guards = []
    for k, v in GUARD_DOC.items():
        spec = GUARD_ARGS.get(k, {})
        g = {"id": k, "label": v[0], "help": v[1], "icon": GUARD_ICON[k], "theme": GUARD_THEME[k],
             "args": [dict(var_arg(a, kind, alabel), help=ARG_KIND_HELP.get(kind, ""),
                           **({"props": PROPERTY_FIELD[kind]} if kind in PROPERTY_FIELD else {}))   # lot M4 (additive)
                      for a, (kind, alabel) in spec.items()]}
        if k in GUARD_AS_VARS:
            g["as_vars"] = GUARD_AS_VARS[k]
        guards.append(g)
    delays = [{"key": k, "value": cfg.get(k), "label": v, "icon": DELAY_ICON} for k, v in DELAY_DOC.items()]
    since = [{"id": k, "label": v, "icon": SINCE_ICON[k]} for k, v in SINCE_DOC.items()]
    kinds = [{"id": k, "label": lab, "icon": ic, "inputs": KIND_PORTS[k][0], "outputs": list(KIND_PORTS[k][1]),
              "legacy": KIND_PORTS[k][2]} for k, (lab, ic) in KIND_DOC.items()]
    states, intents = [], [{"id": "question", "label": "Une question (aucun autre motif reconnu)",
                            "event": "intent.question", "icon": INTENT_ICON["question"], "fixed": True,
                            "description": "Aucun autre motif reconnu.", "only_in": []}]
    if graph is not None:
        states = [{"id": n, "label": STATE_DOC.get(n, n.capitalize()), "description": s.description,
                   "icon": state_icon(n)} for n, s in graph.states.items()]
        intents = [_intent_entry(i) for i in graph.intents] + intents
    return {"events": ev, "actions": actions, "guards": guards, "delays": delays, "since": since,
            "states": states, "intents": intents, "kinds": kinds,
            "var_types": [_type_entry(k, graph, cfg) for k in VAR_TYPES],
            "list_types": [{"id": k, "label": v, "control": TYPE_CONTROL[k]} for k, v in LIST_TYPES.items()],
            "ops": [{"id": k, "label": v} for k, v in OPS.items()],
            # lot L11: operator set per type, scopes, list kinds / modes, weekdays, media files
            "op_sets": {k: t.ops() for k, t in VARTYPES.items()},
            "scopes": [{"id": k, "label": lab, "help": hlp} for k, (lab, hlp) in SCOPES.items()],
            "list_kinds": [{"id": k, "label": lab, "help": hlp} for k, (lab, hlp) in LIST_KINDS.items()],
            "list_modes": [{"id": k, "label": lab, "help": hlp} for k, (lab, hlp) in LIST_MODES.items()],
            "weekdays": [{"id": k, "label": v} for k, v in WEEKDAYS.items()],
            "media": media_files(cfg),
            "themes": [{"id": k, "label": lab, "icon": ic, "help": hlp, "order": i}
                       for i, (k, (lab, ic, hlp)) in enumerate(THEME_DOC.items())],
            "theme_slots": dict(THEME_SLOTS),
            "variables": variable_entries(graph, cfg),
            # lot M4 (additive key, last): value sources + write targets for the editor's source picker (lot M5)
            "properties": _props.vocabulary(_self_mod, cfg),
            # lot M5 (additive key, last): which value types may feed which field type (compatible(src, dst)), so the
            # editor's source picker never re-implements the typing rules: {src type: [field types it may feed]}
            "type_compat": {s: [d for d in VAR_TYPES if compatible(s, d)] for s in VAR_TYPES}}


def _type_entry(k: str, graph: "Graph | None", cfg: dict) -> dict:
    """Editor description of one variable type (lot L11): control, options, operators, list use, choices.
    Lot M3: built by the type module (VarType.entry)."""
    return VARTYPES[k].entry(graph, cfg)


def variable_entries(graph: "Graph | None", cfg: dict) -> dict:
    """Variable manager rows: system variables first (read-only), then the graph's own names and lists.

    Lot L11: user rows carry `scope` / `persist` (+ `min` / `max` / `step` when set), list rows `kind` / `mode` / `max`;
    a dictionary's `items` is a {key: value} object."""
    names = [{"id": n, "type": t, "label": lab, "description": hlp, "system": True, "readonly": True,
              **({"choices": list(graph.states) if graph is not None else []} if n == "etat" else {}),
              **({"choices": list(WEEKDAYS)} if n == "jour" else {})}
             for n, (t, lab, hlp) in SYSTEM_VARS.items()]
    lists = []
    if graph is not None:
        for v in graph.variables.values():
            d = {"id": v.name, "type": v.type, "value": v.value, "description": v.description, "system": False, "readonly": False,
                 "scope": v.scope, "persist": v.persist}
            if v.choices:
                d["choices"] = list(v.choices)
            for k, attr in (("min", "vmin"), ("max", "vmax"), ("step", "step")):
                if getattr(v, attr) is not None:
                    d[k] = getattr(v, attr)
            names.append(d)
        for li in graph.lists.values():
            items = _listkinds.LISTKINDS[li.kind].editor_items(li, cfg)   # lot M3: the kind module
            d = {"id": li.name, "type": li.type, "items": items, "description": li.description, "readonly": bool(li.source),
                 "kind": li.kind, "mode": li.mode, "max": li.maxlen, "scope": li.scope, "persist": li.persist}
            if li.source:
                d["source"] = {li.source[0]: li.source[1]}
            lists.append(d)
    return {"names": names, "lists": lists}


def say_texts(graph: "Graph") -> list:
    """Distinct `say_text` phrases of a graph, in file order (the brain pre-synthesises them at load)."""
    calls = [c for s in graph.states.values() for c in s.on_enter]
    for t in list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]:
        calls += list(t.do) + list(t.then)
    texts = []

    def lit(v):   # a literal phrase (not a `$reference`)
        return isinstance(v, str) and v.strip() and not v.startswith("$")
    for c in calls:
        if c.name == "say_text":
            texts.append(c.args["text"])
        elif c.name == "say_random" and c.args["list"] in graph.lists:   # every phrase of the list, cached like say_text
            texts += [x for x in graph.lists[c.args["list"]].items if isinstance(x, str) and x.strip()]
        elif c.name == "say_dict" and c.args["dict"] in graph.lists:     # lot L11: every value + the fallback
            texts += [x for x in graph.lists[c.args["dict"]].items.values() if lit(x)]
            if lit(c.args["fallback"]):
                texts.append(c.args["fallback"])
        elif c.name == "set_var" and c.args["name"] in graph.variables and graph.variables[c.args["name"]].type == "phrase" \
                and lit(c.args["value"]):
            texts.append(c.args["value"])
        elif c.name == "dict_set" and c.args["dict"] in graph.lists and graph.lists[c.args["dict"]].type == "phrase" \
                and lit(c.args["value"]):
            texts.append(c.args["value"])
    # lot L11: a phrase variable is spoken text, its initial value is synthesised like say_text
    texts += [v.value for v in graph.variables.values() if v.type == "phrase" and lit(v.value)]
    return list(dict.fromkeys(texts))


def _intent_entry(i: "Intent") -> dict:
    d = {"id": i.name, "label": i.description or i.name, "event": "intent." + i.name,
         "icon": i.icon or INTENT_ICON.get(i.name, DEFAULT_INTENT_ICON), "description": i.description,
         "only_in": list(i.only_in or ())}
    if i.words:
        d["words"] = list(i.words)
    if i.regex_src:
        d["regex"] = i.regex_src
    if i.words_from:
        d["words_from"], d["shared"] = i.words_from, True   # list lives in config.json: shared with the config
    return d


# ---------------------------------------------------------------- engine
class GraphEngine:
    """Runs a Graph against a Brain-like object. All methods are called from the brain loop thread."""

    def __init__(self, graph: Graph, brain, actions: dict, guards: dict, cfg: dict):
        missing = (set(ACTION_SPECS) - set(actions)) | (GUARDS - set(guards))
        if missing:
            raise RuntimeError("graph vocabulary not implemented by the brain: %s" % sorted(missing))
        self.graph, self.brain, self.actions, self.guards, self.cfg = graph, brain, actions, guards, cfg
        # Structural chain key of every transition (same keys as graph.layout.json / the visual editor):
        # `<state>/t<n>` for the n-th transition of a state, `global/t<n>`. Looked up by identity.
        self._keys = {}
        self._conflicts = set()      # (loser chain key, winner chain key) already logged
        self._after_once = set()     # (id(non-moving `after` chain), time base) already fired
        for sname, st in graph.states.items():
            for i, tr in enumerate(st.transitions):
                self._keys[id(tr)] = "%s/t%d" % (sname, i)
        for i, tr in enumerate(graph.globals):
            self._keys[id(tr)] = "global/t%d" % i

    # -- helpers
    def _run(self, calls, kw):
        self._exec([("call", c) for c in calls], kw)

    def _exec(self, steps, kw):
        """Run ("call", Call) / ("move", (transition, journal entry)) steps in order.

        `wait` is the one non-blocking action: it hands the REST of the steps to the brain, which resumes
        them from the heartbeat once the delay elapsed (other events keep flowing meanwhile).
        """
        for n, (kind, item) in enumerate(steps):
            if kind == "move":
                self._move(*item, kw)
            elif item.name == "wait":
                rest = steps[n + 1:]
                self.brain.defer(self._delay(item.args["seconds"]), lambda rest=rest: self._exec(rest, kw))
                return
            else:
                self.actions[item.name](kw, **item.args)

    def _move(self, tr, entry, kw):
        if not tr.to:
            return
        reason = tr.reason or tr.on or "after"
        if reason == "$source":
            reason = kw.get("source", "ui")
        self.brain._go(tr.to, reason)  # looked up on the instance each time (tests wrap it)
        if entry is not None:
            entry.update(to=self.brain.state, moved=True, reason=reason)

    def _applies(self, tr: Transition, state: str, kw: dict) -> bool:
        if tr.only_in is not None and state not in tr.only_in:
            return False
        if tr.not_in is not None and state in tr.not_in:
            return False
        return all(bool(self.guards[g.name](kw, **g.args)) != g.negate for g in tr.when)

    def _var_match(self, tr: Transition, kw: dict) -> bool:
        """`var_changed` / `timer_reached` transitions only react to their variable (and value / seconds): the
        trigger module's match() decides (lot M2). `var:` -> name, `value:` -> value; a missing value is left out
        (the module's default ANY)."""
        if tr.on not in WATCH_EVENTS:
            return True
        args = {"name": tr.var} if "name" in _TRIGGER_NODES[tr.on].args else {}
        if tr.value is not NOVALUE:
            args["value"] = tr.value
        return bool(_TRIGGER_NODES[tr.on].match(_nodes.NodeContext(self.brain, kw, self.cfg, self.graph), tr.on, **args))

    def _fire(self, tr: Transition, kw: dict, event: str | None, done: dict | None = None):
        """Run one chain: its `do` actions, the move, its `then` actions.

        `done` (fan id -> list of already executed tagged call sequences) lets branches of ONE editor trigger
        share their leading actions: a call the same fan already executed as a common prefix is skipped, so
        a node shared by two outgoing paths acts once per event, not once per path.
        """
        note = getattr(self.brain, "note_fire", None)   # live journal (Brain); absent on bare test doubles
        entry = note(self._keys.get(id(tr)), tr, event) if note else None
        tagged = [("do", c) for c in tr.do] + [("then", c) for c in tr.then]
        skip = 0
        if done is not None and tr.fan:
            for prev in done.get(tr.fan, ()):
                k = 0
                while k < min(len(prev), len(tagged)) and prev[k] == tagged[k]:
                    k += 1
                skip = max(skip, k)
            done.setdefault(tr.fan, []).append(tuple(tagged))
        do = [c for i, c in enumerate(tr.do) if i >= skip]
        then = [c for i, c in enumerate(tr.then) if len(tr.do) + i >= skip]
        self._exec([("call", c) for c in do] + [("move", (tr, entry))] + [("call", c) for c in then], kw)

    def _conflict(self, tr: Transition, winner: Transition, kw: dict, event: str | None):
        """A second matching chain that changes state: ignored, journaled (`conflict: true`) and logged once."""
        key = (self._keys.get(id(tr)), self._keys.get(id(winner)))
        if key not in self._conflicts:
            self._conflicts.add(key)
            log.warning("graph conflict: %s ignored for event %r, %s already changes the state", key[0], event, key[1])
        note = getattr(self.brain, "note_fire", None)
        if note:
            entry = note(key[0], tr, event)
            entry.update(conflict=True, actions=[], moved=False, winner=key[1])

    def _run_matches(self, cands: list, kw: dict, event: str | None, state: str) -> bool:
        """Run every matching chain that stays in the state, then the FIRST one that changes it.

        All candidates were matched against the state at event arrival. Non-moving chains (no `to`: actions only
        or End) run first in evaluation order (global transitions, then the state's, file order); then the single
        moving chain (do -> go -> then); further moving chains are conflicts and ignored.
        """
        done: dict = {}
        movers = [t for t in cands if t.to]
        for tr in cands:
            if not tr.to:
                self._fire(tr, kw, event, done)
        if movers:
            if self.brain.state != state:
                log.warning("graph: %s skipped, a side chain already moved %s -> %s", self._keys.get(id(movers[0])), state, self.brain.state)
            else:
                self._fire(movers[0], kw, event, done)
            for extra in movers[1:]:
                self._conflict(extra, movers[0], kw, event)
        return bool(cands)

    # -- public API
    def enter(self, state: str):
        """Run the `on_enter` actions of `state` (called by Brain._go and at boot)."""
        self._run(self.graph.states[state].on_enter, {})

    def classify(self, text: str, state: str) -> str:
        """Intent event for a transcript, first match in file order, else `intent.question`."""
        low = text.lower()
        for it in self.graph.intents:
            if it.only_in is not None and state not in it.only_in:
                continue
            if it.words and any(w in low for w in it.words):
                return "intent." + it.name
            if it.words_from and any(w in low for w in self.cfg[it.words_from]):
                return "intent." + it.name
            if it.regex is not None and it.regex.search(low):
                return "intent." + it.name
        return "intent.question"

    def dispatch(self, event: str, kw: dict) -> bool:
        """Fire the first applicable transition for `event`; False when nothing reacted."""
        state = self.brain.state
        if event == "utterance":
            event = self.classify(kw.get("text", ""), state)
        cands = [tr for tr in self.graph.globals + self.graph.states[state].transitions
                 if tr.enabled and tr.on == event and self._var_match(tr, kw) and self._applies(tr, state, kw)]
        return self._run_matches(cands, kw, event, state) if cands else False

    def _delay(self, after) -> float:
        return float(after if _num(after) else self.cfg[after])

    def tick(self, now: float) -> bool:
        """Heartbeat step: fire every elapsed `after:` chain of the current state that stays in it (once each
        per time base, otherwise a 10 Hz heartbeat would repeat it), then the first elapsed one that moves."""
        state = self.brain.state
        cands = []
        for tr in self.graph.states[state].transitions:
            if tr.after is None or not tr.enabled or not self._applies(tr, state, {}):
                continue
            base = self.brain.last_speech if tr.since == "last_speech" else self.brain.since
            if now - base > self._delay(tr.after):  # strict, like the old hard-coded timers
                if not tr.to:
                    if (id(tr), base) in self._after_once:
                        continue
                    if len(self._after_once) > 256:
                        self._after_once.clear()
                    self._after_once.add((id(tr), base))
                cands.append(tr)
        return self._run_matches(cands, {}, "after", state) if cands else False
