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
      Adding a capability = add the name here AND implement it in brain.py.

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

Invariants
    - dispatch(): global transitions first, then the current state's, first applicable one wins
      (event match + only_in/not_in + all guards); its `do` actions run, then the move, then `then`.
    - tick(): evaluates `after:` transitions of the CURRENT state only (driven by the heartbeat).
    - An invalid override file never stops the robot: `load_active` logs the error (errors.log) and
      falls back to the default graph shipped with the code.

How to test
    python -m tests.test_brain_graph      (parity traces + invalid-graph / watchdog / heartbeat tests)
"""
import os
import re
import types
from dataclasses import dataclass

import yaml

from .log import log

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graph.yaml")

# ---------------------------------------------------------------- closed vocabulary
# Events a transition may react to (`on:`). `utterance` and `tick` are engine-internal: an utterance
# is classified into an `intent.*` event, a tick drives `after:` delays.
#
# SINGLE SOURCE of the vocabulary: each registry below carries the French label + help shown by the
# visual editor (`vocabulary()` -> GET /api/graph/vocab). EVENTS / ACTION_SPECS / GUARDS are derived
# from them, so a name cannot exist for the validator without being documented for the editor.
# value = (label, help); events add an `internal` flag.
EVENT_DOC = {
    "stop": ("Bouton Stop", "Le bouton Stop du tableau de bord est pressé : se taire et revenir en veille.", False),
    "off": ("Bouton Éteindre", "Le bouton Éteindre est pressé : le robot s'éteint (micro coupé).", False),
    "on": ("Bouton Allumer", "Le bouton Allumer est pressé : le robot sort de l'état éteint.", False),
    "start": ("Bouton Démarrer", "Le bouton Démarrer du tableau de bord, ou un appui sur le visage de l'écran.", False),
    "visage": ("Un visage apparaît", "La caméra voit un visage alors qu'il n'y en avait plus.", False),
    "visage_perdu": ("Le visage disparaît", "Plus aucun visage vu depuis lost_face_s (10 s). Le graphe par défaut n'en a qu'un exemple désactivé.", False),
    "greeting_done": ("Salutation terminée", "Le robot a fini de dire la phrase d'accueil.", False),
    "relance_done": ("Relance terminée", "Le robot a fini de dire la phrase de relance (ou de demande de répétition).", False),
    "goodbye_done": ("Au revoir terminé", "Le robot a fini de dire au revoir.", False),
    "cloture_done": ("Pause de clôture terminée", "Le délai programmé après l'au revoir est écoulé (action « Programmer un événement »).", False),
    "answer_done": ("Réponse terminée", "Le robot a fini de répondre (ou de chanter).", False),
    "hush": ("« Tais-toi »", "Le visiteur ou le bouton demande au robot de se taire.", False),
    "barge_in": ("Le visiteur coupe la parole", "Le visiteur parle pendant que le robot répond (interruption activée dans la configuration).", False),
    "sing": ("Demande de chanson", "Le bouton Chanson ou le visiteur demande à Nanterino de chanter.", False),
    "not_understood": ("Parole non comprise", "Du bruit ou une parole inexploitable a été entendu.", False),
    "ask": ("Question tapée", "Une question est tapée sur le tableau de bord (test sans micro).", False),
    "personnes_multiples": ("Plusieurs personnes", "Au moins 2 visages restent visibles pendant 1 s (posté une fois, ré-armé quand il y en a moins de 2).", False),
    "ouverture": ("Ouverture", "L'heure d'ouverture de la configuration `opening_hours` vient de passer (jamais si les horaires sont vides).", False),
    "fermeture": ("Fermeture", "L'heure de fermeture de la configuration `opening_hours` vient de passer (jamais si les horaires sont vides).", False),
    "inactivite_longue": ("Longue inactivité", "Aucun visage ni parole depuis idle_long_s (300 s) ; posté une seule fois jusqu'à la prochaine activité.", False),
    "say_done": ("Phrase libre terminée", "Le robot a fini de dire la phrase de l'action « Dire un texte ».", False),
    "utterance": ("Phrase du visiteur", "Interne : une phrase transcrite, classée en événement intent.*.", True),
    "tick": ("Battement de coeur", "Interne : le battement de coeur (10 Hz) qui fait avancer les délais.", True),
}
EVENTS = frozenset(EVENT_DOC)
INTERNAL_EVENTS = frozenset(k for k, v in EVENT_DOC.items() if v[2])

# Action name -> (label, help, {argument name: (kind, label)}).
# kinds: cfgkey (a config key), event, delay (seconds or cfg key).
ACTION_DOC = {
    "cancel_all": ("Se taire", "Coupe immédiatement le son et annule toute réponse en cours.", {}),
    "mic_on": ("Ouvrir le micro", "Le robot se remet à écouter (sauf mode sourd).", {}),
    "mic_off": ("Couper le micro", "Le robot n'écoute plus.", {}),
    "mic_off_no_barge_in": ("Couper le micro (sauf interruption)", "Coupe le micro, sauf si l'interruption est activée dans la configuration.", {}),
    "clear_conversation": ("Oublier la conversation", "Efface l'historique, le compteur de tours et le sous-titre.", {}),
    "clear_history": ("Effacer l'historique", "Efface seulement l'historique des échanges.", {}),
    "reset_repairs": ("Remettre à zéro les demandes de répétition", "Le compteur de « pardon ? » repart de zéro.", {}),
    "reset_silence": ("Redémarrer le chrono de silence", "La dernière parole est considérée comme étant maintenant.", {}),
    "subtitle_listening": ("Afficher « Je vous écoute »", "Met le sous-titre de l'écran sur « Je vous écoute ».", {}),
    "count_turn": ("Compter un tour de parole", "Ajoute un échange au compteur de la conversation.", {}),
    "count_repair": ("Compter une demande de répétition", "Ajoute un « pardon ? » au compteur.", {}),
    "set_relance_text": ("Préparer la phrase « répétez »", "La prochaine relance dira la phrase de demande de répétition.", {}),
    "speak_relance": ("Dire la relance", "Dit la phrase de relance (ou de répétition si elle est préparée), puis relance_done.", {}),
    "start_answer": ("Répondre à la question", "Lance la recherche et la réponse à la phrase du visiteur.", {}),
    "start_sing": ("Chanter", "Lance la chanson de Nanterino.", {}),
    "as_utterance": ("Traiter la question tapée", "Traite le texte tapé comme s'il avait été dit.", {}),
    "speak_phrase": ("Dire une phrase fixe", "Dit une phrase de la configuration, puis déclenche l'événement indiqué.",
                     {"text": ("cfgkey", "Phrase à dire"), "done": ("event", "Événement à la fin")}),
    "schedule": ("Programmer un événement", "Déclenche un événement après un délai (annulé si le robot est arrêté entre-temps).",
                 {"event": ("event", "Événement à déclencher"), "delay": ("delay", "Délai (secondes ou clé de configuration)")}),
    "emit": ("Déclencher un événement", "Envoie tout de suite un événement au graphe.", {"event": ("event", "Événement à déclencher")}),
    "say_text": ("Dire un texte", "Dit une phrase libre (voix calculée à l'avance au chargement du graphe ; muet = reste muet), puis déclenche say_done.",
                 {"text": ("text", "Phrase à dire")}),
    "set_expression": ("Changer l'expression du visage", "Affiche une expression (content, surpris, réfléchit, triste, neutre) pendant un nombre de secondes, puis revient à l'expression de l'état.",
                       {"name": ("expression", "Expression"), "seconds": ("seconds", "Durée (secondes)")}),
    "wait": ("Attendre", "Pause sans bloquer le robot : la suite de la chaîne reprend après le délai, les autres événements continuent d'être traités.",
             {"seconds": ("delay", "Durée (secondes ou clé de configuration)")}),
    "gaze": ("Régler le regard", "Le regard du visage suit le visiteur, regarde devant lui, ou erre ; reste jusqu'au prochain réglage (retour à « suivre » en veille).",
             {"mode": ("gazemode", "Regard")}),
}
EXPRESSIONS = {"content": "Content", "surpris": "Surpris", "reflechit": "Réfléchit", "triste": "Triste", "neutre": "Neutre"}
GAZE_MODES = {"suivre": "Suivre le visiteur", "devant": "Regarder devant", "errer": "Errer"}
TEXT_MAX = 300      # say_text.text length limit (it is synthesised once at graph load)
SECONDS_MAX = 3600  # set_expression.seconds upper bound
ACTION_SPECS = {n: {a: kd[0] for a, kd in spec[2].items()} for n, spec in ACTION_DOC.items()}

GUARD_DOC = {
    "auto_greet_on_face": ("L'accueil automatique est activé", "Réglage « accueil automatique » de la configuration."),
    "barge_in": ("L'interruption est activée", "Réglage « barge_in » : le visiteur peut couper la parole du robot."),
    "not_busy": ("Aucune transcription en cours", "Le robot n'est pas en train de transcrire une phrase."),
    "mic_active": ("Le micro est ouvert", "Le micro écoute en ce moment."),
    "not_speaking": ("Le robot ne parle pas", "Aucun son n'est en cours de lecture."),
    "repairs_left": ("Il reste des demandes de répétition", "Le robot a demandé de répéter moins de 2 fois de suite."),
    "turns_left": ("Il reste des tours de parole", "La conversation n'a pas atteint le nombre maximal d'échanges."),
    "dans_les_horaires": ("Dans les horaires d'ouverture", "Les horaires `opening_hours` de la configuration sont en cours (toujours vrai s'ils sont vides)."),
}
GUARDS = frozenset(GUARD_DOC)

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
EVENT_ICON = {
    "stop": "hand-stop", "off": "power", "on": "power", "start": "player-play", "visage": "scan-eye",
    "visage_perdu": "user-off", "greeting_done": "hand-move", "relance_done": "refresh", "goodbye_done": "door-exit",
    "cloture_done": "clock", "answer_done": "message", "hush": "volume-off", "barge_in": "microphone",
    "sing": "music", "not_understood": "question-mark", "ask": "keyboard", "utterance": "microphone", "tick": "clock",
    "personnes_multiples": "users", "ouverture": "lock-open", "fermeture": "lock", "inactivite_longue": "hourglass",
    "say_done": "text-caption",
}
ACTION_ICON = {
    "cancel_all": "x", "mic_on": "microphone", "mic_off": "microphone-off", "mic_off_no_barge_in": "microphone-off",
    "clear_conversation": "eraser", "clear_history": "eraser", "reset_repairs": "refresh", "reset_silence": "clock",
    "subtitle_listening": "ear", "count_turn": "plus", "count_repair": "plus", "set_relance_text": "message",
    "speak_relance": "volume", "start_answer": "message", "start_sing": "music", "as_utterance": "keyboard",
    "speak_phrase": "volume", "schedule": "clock", "emit": "bolt", "say_text": "text-caption",
    "set_expression": "mood-smile", "wait": "hourglass", "gaze": "eye",
}
GUARD_ICON = {
    "auto_greet_on_face": "scan-eye", "barge_in": "hand-stop", "not_busy": "circle-dot", "mic_active": "microphone",
    "not_speaking": "volume-off", "repairs_left": "refresh", "turns_left": "message", "dans_les_horaires": "calendar-time",
}
STATE_ICON = {"veille": "moon", "accueil": "hand-move", "ecoute": "ear", "reponse": "message", "relance": "refresh",
              "cloture": "door-exit", "eteint": "power"}
INTENT_ICON = {"appel": "bell", "au_revoir": "hand-move", "chanson": "music", "question": "question-mark"}
DELAY_ICON, SINCE_ICON = "clock", {"state": "clock", "last_speech": "microphone"}
DEFAULT_STATE_ICON, DEFAULT_INTENT_ICON = "circle-dot", "message"
assert set(EVENT_ICON) == set(EVENT_DOC) and set(ACTION_ICON) == set(ACTION_DOC) and set(GUARD_ICON) == set(GUARD_DOC), \
    "every event / action / guard needs exactly one icon"


def state_icon(name: str) -> str:
    return STATE_ICON.get(name, DEFAULT_STATE_ICON)


def all_icons() -> list:
    """Sorted union of every icon the vocabulary can return (what the editor must vendor)."""
    used = {i for _l, i in KIND_DOC.values()}
    for d in (EVENT_ICON, ACTION_ICON, GUARD_ICON, STATE_ICON, INTENT_ICON, SINCE_ICON):
        used |= set(d.values())
    return sorted(used | {DELAY_ICON, DEFAULT_STATE_ICON, DEFAULT_INTENT_ICON})

_TOP_KEYS = {"version", "description", "states", "global", "intents"}
_STATE_KEYS = {"description", "on_enter", "transitions"}
_TR_KEYS = {"on", "after", "since", "when", "only_in", "not_in", "do", "to", "reason", "then", "description", "enabled"}
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

    def label(self) -> str:
        return ("not " if self.negate else "") + self.name


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

    def to_dict(self) -> dict:
        """JSON-friendly view for GET /api/graph (future visual editor)."""
        def tr(t):
            d = {"description": t.description}
            if not t.enabled:
                d["enabled"] = False
            for k in ("on", "after", "since", "to", "reason"):
                if getattr(t, k) is not None:
                    d[k] = getattr(t, k)
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
            for k, kind in spec.items():
                val = args[k]
                if kind == "cfgkey" and val not in self.cfg:
                    self.err(where, "%s.%s: %r is not a config key" % (name, k, val))
                elif kind == "event" and (val not in EVENTS or val == "tick"):
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
            out.append(Call(name, types.MappingProxyType(dict(args))))
        return tuple(out)

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
        when = []
        for g in self.as_list(where, t.get("when")):
            neg = False
            if isinstance(g, dict):  # negated guard: `when: [{not: guard}]`
                if set(g) != {"not"}:
                    self.err(where, "a guard mapping must be {not: guard}, got %r" % (g,)); continue
                g, neg = g["not"], True
            if g not in GUARDS:
                self.err(where, "unknown guard %r (allowed: %s)" % (g, ", ".join(sorted(GUARDS)))); continue
            when.append(Cond(g, neg))
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
        return Transition(on, after, since, when, lists["only_in"], lists["not_in"],
                          self.calls(where + " do", t.get("do")), to, reason,
                          self.calls(where + " then", t.get("then")), desc, enabled)

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
        if self.errors:
            raise GraphError("%s: %d problem(s):\n  - %s" % (self.source, len(self.errors), "\n  - ".join(self.errors)),
                             self.items)
        return Graph(types.MappingProxyType(states), tuple(globs), tuple(intents), self.source, tuple(self.warnings))


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
    ev = [{"id": k, "label": v[0], "help": v[1], "icon": EVENT_ICON[k]} for k, v in EVENT_DOC.items() if not v[2]]
    ev_ids = [e["id"] for e in ev]
    actions = []
    for name, (label, hlp, spec) in ACTION_DOC.items():
        args = []
        for a, (kind, alabel) in spec.items():
            if kind == "cfgkey":
                args.append({"name": a, "type": "enum", "options": list(PHRASE_KEYS), "label": alabel})
            elif kind == "event":
                args.append({"name": a, "type": "enum", "options": ev_ids, "label": alabel})
            elif kind == "text":
                args.append({"name": a, "type": "text", "max_len": TEXT_MAX, "label": alabel})
            elif kind == "expression":
                args.append({"name": a, "type": "enum", "options": list(EXPRESSIONS), "labels": dict(EXPRESSIONS), "label": alabel})
            elif kind == "gazemode":
                args.append({"name": a, "type": "enum", "options": list(GAZE_MODES), "labels": dict(GAZE_MODES), "label": alabel})
            elif kind == "seconds":  # plain number of seconds, no config key
                args.append({"name": a, "type": "number", "options": [], "label": alabel})
            else:  # delay: a number of seconds, or one of the `options` config keys
                args.append({"name": a, "type": "number", "options": list(DELAY_DOC), "label": alabel})
        actions.append({"id": name, "label": label, "help": hlp, "icon": ACTION_ICON[name], "args": args})
    guards = [{"id": k, "label": v[0], "help": v[1], "icon": GUARD_ICON[k]} for k, v in GUARD_DOC.items()]
    delays = [{"key": k, "value": cfg.get(k), "label": v, "icon": DELAY_ICON} for k, v in DELAY_DOC.items()]
    since = [{"id": k, "label": v, "icon": SINCE_ICON[k]} for k, v in SINCE_DOC.items()]
    kinds = [{"id": k, "label": lab, "icon": ic} for k, (lab, ic) in KIND_DOC.items()]
    states, intents = [], [{"id": "question", "label": "Une question (aucun autre motif reconnu)",
                            "event": "intent.question", "icon": INTENT_ICON["question"], "fixed": True,
                            "description": "Aucun autre motif reconnu.", "only_in": []}]
    if graph is not None:
        states = [{"id": n, "label": STATE_DOC.get(n, n.capitalize()), "description": s.description,
                   "icon": state_icon(n)} for n, s in graph.states.items()]
        intents = [_intent_entry(i) for i in graph.intents] + intents
    return {"events": ev, "actions": actions, "guards": guards, "delays": delays, "since": since,
            "states": states, "intents": intents, "kinds": kinds}


def say_texts(graph: "Graph") -> list:
    """Distinct `say_text` phrases of a graph, in file order (the brain pre-synthesises them at load)."""
    calls = [c for s in graph.states.values() for c in s.on_enter]
    for t in list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]:
        calls += list(t.do) + list(t.then)
    return list(dict.fromkeys(c.args["text"] for c in calls if c.name == "say_text"))


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
        return all(bool(self.guards[g.name](kw)) != g.negate for g in tr.when)

    def _fire(self, tr: Transition, kw: dict, event: str | None):
        note = getattr(self.brain, "note_fire", None)   # live journal (Brain); absent on bare test doubles
        entry = note(self._keys.get(id(tr)), tr, event) if note else None
        self._exec([("call", c) for c in tr.do] + [("move", (tr, entry))] + [("call", c) for c in tr.then], kw)

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
        for tr in self.graph.globals + self.graph.states[state].transitions:
            if tr.enabled and tr.on == event and self._applies(tr, state, kw):
                self._fire(tr, kw, event)
                return True
        return False

    def _delay(self, after) -> float:
        return float(after if _num(after) else self.cfg[after])

    def tick(self, now: float) -> bool:
        """Heartbeat step: fire the first elapsed `after:` transition of the current state."""
        state = self.brain.state
        for tr in self.graph.states[state].transitions:
            if tr.after is None or not tr.enabled or not self._applies(tr, state, {}):
                continue
            base = self.brain.last_speech if tr.since == "last_speech" else self.brain.since
            if now - base > self._delay(tr.after):  # strict, like the old hard-coded timers
                self._fire(tr, {}, "after")
                return True
        return False
