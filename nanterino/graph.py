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
                when <guard(s)>, only_in/not_in <states>, do [actions], to <state>,
                reason <text | $source>, then [actions after the move], description
    intents.<name>: words | words_from <cfg key> | regex, only_in, description; first match in file
                order wins; no match = event `intent.question`
    Gotcha: PyYAML reads the bare words on/off/yes/no as booleans; the loader below only keeps
    true/false as booleans so `- on: stop` and `on: off` mean what they say.

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
EVENTS = frozenset({
    "stop", "off", "on", "start", "visage", "visage_perdu", "greeting_done", "relance_done",
    "goodbye_done", "cloture_done", "answer_done", "hush", "barge_in", "sing", "not_understood",
    "ask", "utterance", "tick"})
INTERNAL_EVENTS = frozenset({"utterance", "tick"})

# Action name -> {argument name: kind}. kinds: cfgkey (a config key), event, delay (seconds or cfg key).
ACTION_SPECS = {
    "cancel_all": {}, "mic_on": {}, "mic_off": {}, "mic_off_no_barge_in": {},
    "clear_conversation": {}, "clear_history": {}, "reset_repairs": {}, "reset_silence": {},
    "subtitle_listening": {}, "count_turn": {}, "count_repair": {}, "set_relance_text": {},
    "speak_relance": {}, "start_answer": {}, "start_sing": {}, "as_utterance": {},
    "speak_phrase": {"text": "cfgkey", "done": "event"},
    "schedule": {"event": "event", "delay": "delay"},
    "emit": {"event": "event"},
}
GUARDS = frozenset({"auto_greet_on_face", "barge_in", "not_busy", "mic_active", "not_speaking",
                    "repairs_left", "turns_left"})
SINCE = ("state", "last_speech")
REQUIRED_STATES = ("veille", "eteint")

_TOP_KEYS = {"version", "description", "states", "global", "intents"}
_STATE_KEYS = {"description", "on_enter", "transitions"}
_TR_KEYS = {"on", "after", "since", "when", "only_in", "not_in", "do", "to", "reason", "then", "description"}
_INTENT_KEYS = {"description", "words", "words_from", "regex", "only_in"}


class GraphError(ValueError):
    """The graph file is unreadable or invalid; the message lists every problem found."""


# ---------------------------------------------------------------- frozen model
@dataclass(frozen=True)
class Call:
    name: str
    args: types.MappingProxyType

    def label(self) -> str:
        return self.name if not self.args else "%s(%s)" % (self.name, ", ".join("%s=%s" % kv for kv in self.args.items()))


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
            for k in ("on", "after", "since", "to", "reason"):
                if getattr(t, k) is not None:
                    d[k] = getattr(t, k)
            for k in ("when", "only_in", "not_in"):
                if getattr(t, k):
                    d[k] = list(getattr(t, k))
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
                                 **({"regex": i.regex_src} if i.regex_src else {})} for i in self.intents},
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
        self.errors, self.warnings = [], []

    def err(self, where, msg):
        self.errors.append("%s: %s" % (where, msg))

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
        when = tuple(self.as_list(where, t.get("when")))
        for g in when:
            if g not in GUARDS:
                self.err(where, "unknown guard %r (allowed: %s)" % (g, ", ".join(sorted(GUARDS))))
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
        return Transition(on, after, since, when, lists["only_in"], lists["not_in"],
                          self.calls(where + " do", t.get("do")), to, reason,
                          self.calls(where + " then", t.get("then")), desc)

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
            if not isinstance(spec, dict):
                self.err(w, "must be a mapping"); continue
            for k in set(spec) - _INTENT_KEYS:
                self.err(w, "unknown key %r" % k)
            if sum(k in spec for k in ("words", "words_from", "regex")) != 1:
                self.err(w, "exactly one of words / words_from / regex is required")
            words = tuple(str(x).lower() for x in self.as_list(w, spec.get("words")))
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
            intents.append(Intent(n, self.need_desc(w, spec), words, wf, rx, spec.get("regex") if rx else None, oi))
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
            raise GraphError("%s: %d problem(s):\n  - %s" % (self.source, len(self.errors), "\n  - ".join(self.errors)))
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


# ---------------------------------------------------------------- engine
class GraphEngine:
    """Runs a Graph against a Brain-like object. All methods are called from the brain loop thread."""

    def __init__(self, graph: Graph, brain, actions: dict, guards: dict, cfg: dict):
        missing = (set(ACTION_SPECS) - set(actions)) | (GUARDS - set(guards))
        if missing:
            raise RuntimeError("graph vocabulary not implemented by the brain: %s" % sorted(missing))
        self.graph, self.brain, self.actions, self.guards, self.cfg = graph, brain, actions, guards, cfg

    # -- helpers
    def _run(self, calls, kw):
        for c in calls:
            self.actions[c.name](kw, **c.args)

    def _applies(self, tr: Transition, state: str, kw: dict) -> bool:
        if tr.only_in is not None and state not in tr.only_in:
            return False
        if tr.not_in is not None and state in tr.not_in:
            return False
        return all(self.guards[g](kw) for g in tr.when)

    def _fire(self, tr: Transition, kw: dict):
        self._run(tr.do, kw)
        if tr.to:
            reason = tr.reason or tr.on or "after"
            if reason == "$source":
                reason = kw.get("source", "ui")
            self.brain._go(tr.to, reason)  # looked up on the instance each time (tests wrap it)
        self._run(tr.then, kw)

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
            if tr.on == event and self._applies(tr, state, kw):
                self._fire(tr, kw)
                return True
        return False

    def _delay(self, after) -> float:
        return float(after if _num(after) else self.cfg[after])

    def tick(self, now: float) -> bool:
        """Heartbeat step: fire the first elapsed `after:` transition of the current state."""
        state = self.brain.state
        for tr in self.graph.states[state].transitions:
            if tr.after is None or not self._applies(tr, state, {}):
                continue
            base = self.brain.last_speech if tr.since == "last_speech" else self.brain.since
            if now - base > self._delay(tr.after):  # strict, like the old hard-coded timers
                self._fire(tr, {})
                return True
        return False
