"""Dialogue orchestrator: the 6-state machine of the cahier des charges §2 + voice pipeline.

logging: robotlog via nanterino.log. Only states, transitions and latencies are logged.
Conversation history lives in RAM and is wiped at every Clôture (no memory between people).

States: veille -> accueil -> ecoute <-> reponse ; ecoute -> relance -> (ecoute | cloture) -> veille,
plus "eteint" (OFF): mic closed, no listening, no speech, until "start"/"on".
Exits from veille: UI "start" (button / face tap), the word "Nanterino" heard while in veille
(STT-based stand-in until the openWakeWord model of step 9), or `visage` events (step 6).

Graph + heartbeat (2026-10-30): the transitions are no longer coded here. They live in
nanterino/graph.yaml (French, editable; override file /opt/robot/nanterino/graph.yaml) and are run by
nanterino.graph.GraphEngine. This module keeps the *capabilities*: the closed registry of actions and
guards (`_build_engine`) and the audio/LLM/TTS threads. A heartbeat thread posts a `tick` at
cfg["heartbeat_hz"] (10 Hz); the single "brain" loop blocks on the event queue and every tick evaluates
the graph's `after:` delays and the scheduled events. A watchdog thread trips when no tick was processed
for cfg["watchdog_s"] seconds (a handler is stuck): it logs to errors.log, cancels speech, queues a
priority `stop` and restarts a dead loop thread.

Wave 2 (2026-10-31): the same class also runs the editor's simulator (nanterino/sim.py) through constructor seams
(`clock`, `wall`, `mic`, `graph`, `threaded=False`, `start_state`; events are drained by `pump()`). It keeps a
journal of the last 50 fired chains (`note_fire`, `trace()`, snapshot `last_transition`), derives sensor events
(`_sensors`: personnes_multiples, inactivite_longue, ouverture/fermeture) and exposes `expression` / `gaze_mode`
in the snapshot for the face UI.

Variables (lot L1, 2026-10-31): the graph's user variables and lists live here (`vars`, `lists`), initialised from the
graph's `variables:` block on every (re)load; the system variables (etat, tours, max_tours, reparations,
max_reparations) are read from the brain's own state (`var_value`). set_var / add_var / toggle_var post
`var_changed` only for variables a transition watches; a `var_changed` caused while handling a `var_changed` is
dropped (MAX_VAR_CASCADE = 1, logged once per variable). `say_random` speaks through `_speak_then` (cached voice,
AudioOut keeps honouring `muted`). Random picks use `self.rng` (the simulator seeds it: deterministic traces).

Variables v2 (lot L11, 2026-11-01): bounded numbers are clamped (graph.fit_value), `scope: conversation` values go back
to their initial value in clear_conversation, `mode: shuffle` lists draw from a bag (`_bag_pick`, lot M3: the list mode
module nanterino/listmodes/shuffle.py), `history` / `max` lists
drop their oldest item, dictionaries live in `lists` as {key: value}. Timers store their start as a WALL epoch (so a
persisted timer keeps running across a restart) and read as elapsed seconds; the heartbeat posts `timer_reached` once
per (timer, seconds, start) with depth = MAX_VAR_CASCADE (same anti-loop as var_changed). Every time reading uses the
injectable `now` / `wall` clocks (simulator and tests are deterministic). Persistence: an optional `var_store`
(nanterino/var_store.py, given by server.py only; tests pass a temp one) receives the `persist: true` values and the
nb_visiteurs_jour counter from the heartbeat (`_persist_tick`, the store limits writes to one per 2 s); values read
back at load are type-checked (`graph.persisted_ok`), a mismatch is ignored with a warning (`var_store_info`).
`reset_var` (POST /api/graph/vars/reset) restores the initial value and forgets the saved one.

Node modules (lot M1, 2026-11-01): the action closures moved to nanterino/nodes/actions/<id>.py (one module per
action: metadata + run(ctx, **args)); _build_engine binds each one to this brain with a NodeContext. Lot M2: the guard closures moved
the same way to nanterino/nodes/conditions/<id>.py (test()); var_changed / timer_reached matching lives in their
trigger modules (nanterino/nodes/triggers/), while posting them (+ the anti-loop depth) stays here. Shared runtime
helpers (list_push, match_key) live in nanterino/nodes/helpers.py.

Cancellation (fix 2026-10-15): every speaking/answering thread carries the generation number it
was started with. stop/off/hush/barge-in bump the generation, so an old thread can never speak
again or post a late "done" event. (The previous set()+clear() of a shared Event was so fast that
running answers missed it and kept talking after "Stop".)
"""
import datetime
import itertools
import random
import re
import numpy as np
import os
import collections
import queue
import threading
import time

from . import graph as graph_mod
from . import nodes
from . import vartypes
from .listkinds import LISTKINDS
from .listmodes import LISTMODES
from .nodes import NodeContext
from .audio import AudioIn, find_device
from . import hours as hours_mod
from .log import log

VEILLE, ACCUEIL, ECOUTE, REPONSE, RELANCE, CLOTURE, ETEINT = (
    "veille", "accueil", "ecoute", "reponse", "relance", "cloture", "eteint")

# Typical Whisper hallucinations on noise/silence (French YouTube-subtitle artefacts).
PHANTOMS = ("sous-titres", "sous titres", "merci d'avoir regardé", "abonnez-vous", "amara.org",
            "merci de votre attention", "♪", "[musique]", "(musique)")
MAX_TURNS = 12  # safety net: a conversation never loops forever
MAX_REPAIRS = 2  # "pardon ?" at most this many times in a row (system variable max_reparations)
MAX_VAR_CASCADE = 1  # var_changed events a var_changed chain may cause (anti-loop)
JOURNAL_MAX = 50       # fired chains kept for /api/graph/trace
MULTI_FACES_S = 1.0    # personnes_multiples: >= 2 faces for this long
SENSOR_PERIOD_S = 1.0  # opening-hours check rate (the other sensor rules run every tick)
SIM_ANSWER_S, SIM_SONG_S = 2.0, 3.0   # virtual durations of a simulated answer / song (simulator only)
SAY_TEXTS_MAX = 40     # free phrases pre-synthesised per graph (memory bound)


# Single words Whisper typically invents on breath/noise; other single words are real answers
# ("Parc ?", "Musée", "Horaires") and are now accepted (2026-10-16, user: interact better).
SINGLE_NOISE = {"merci", "bon", "ah", "oh", "euh", "hum", "hein", "voilà", "bah", "ok"}


def _fresh_items(li):
    """A user list's initial items as a new mutable container (lot M3: the list kind module's fresh())."""
    return LISTKINDS[li.kind].fresh(li.items)


def is_phantom(text: str, keep_words=()) -> bool:
    low = text.lower().strip(" .!?…,")
    if any(p in low for p in PHANTOMS) or not any(c.isalpha() for c in low):
        return True
    words = low.split()
    if len(words) < 2 and low not in keep_words and (len(low) < 3 or low in SINGLE_NOISE):
        return True
    return False


# Last-resort filter: a speaking robot must never claim it cannot hear/speak or is a text AI.
_DENIALS = re.compile(r"(ne (peux|puis) pas (vous |t')?(entendre|écouter|parler|voir)|ne (vous|t') ?entends pas|"
                      r"ia textuelle|modèle de langage|intelligence artificielle textuelle|assistant virtuel textuel)",
                      re.IGNORECASE)


_DEAD_END = re.compile(r"ne (peux|puis) pas (vous |t')?aider", re.IGNORECASE)


def fix_sentence(sentence: str) -> str:
    # LFM3 sometimes adds Markdown bold (**word**): strip it so the subtitles and the voice stay clean.
    sentence = sentence.replace("**", "").replace("__", "")
    if _DENIALS.search(sentence):
        log.info("answer sentence replaced reason=denial")
        return "Oui, je vous entends très bien."
    if _DEAD_END.search(sentence):  # curt refusal ends the exchange: keep the visitor talking instead
        log.info("answer sentence replaced reason=dead_end")
        return "Je n'ai pas encore cette information. Dites-moi ce que vous cherchez exactement, je vais essayer de vous orienter."
    return sentence


NO_SHEET = ("AUCUNE FICHE PERTINENTE : tu ne connais pas la réponse. Ne donne aucun lieu ni chemin ; dis que tu "
            "n'as pas encore cette information et demande ce que le visiteur cherche exactement.")


def build_messages(cfg: dict, sheets: list[dict], history: list[dict], question: str) -> list[dict]:
    """Chat messages for one answer (shared with /opt/robot/scripts/llm-bench.py).

    "sheets_last" layout keeps the system prompt and examples identical between questions, so
    llama-server can reuse that prefix from its cache, and puts the sheets just before the question.
    """
    context = "\n\n---\n\n".join(s["text"] for s in sheets) or NO_SHEET
    # No sheet found: show the model how to say "I do not know" without inventing.
    examples = list(cfg.get("few_shot", [])) + ([] if sheets else list(cfg.get("few_shot_no_sheet", [])))
    if cfg.get("prompt_layout") == "sheets_last":
        return ([{"role": "system", "content": cfg["system_prompt"]}] + examples + history
                + [{"role": "user", "content": f"Fiches :\n{context}\n\nQuestion du visiteur : {question}"}])
    return ([{"role": "system", "content": f"{cfg['system_prompt']}\n\nFiches :\n{context}"}]
            + examples + history + [{"role": "user", "content": question}])


class Brain:
    def __init__(self, cfg, out, stt, llm, tts, corpus, *, clock=None, wall=None, mic=None, graph=None,
                 threaded=True, start_state=None, var_store=None):
        """`clock`/`wall`/`mic`/`graph`/`threaded` exist for the graph simulator (nanterino/sim.py): a manual
        monotonic clock, a simulated wall clock, a fake microphone, an in-memory Graph (no file read) and no
        threads at all (events are processed by `pump()`). The live robot uses none of them.
        `var_store` (lot L11): a nanterino.var_store.VarStore for the `persist: true` variables; None = no persistence
        (simulator, tests unless they pass a temp store). Only server.py gives the live state/vars.json store."""
        self.cfg, self.out, self.stt, self.llm, self.tts, self.corpus = cfg, out, stt, llm, tts, corpus
        self.now = clock or time.monotonic
        self.wall = wall or time.time
        self._threaded, self._fixed_graph, self._start_state = threaded, graph, start_state
        self.state, self.since = VEILLE, self.now()
        self.subtitle, self.last_speech = "", self.now()
        self.history: list[dict] = []
        self.latencies = collections.deque(maxlen=20)  # ms, end of user speech -> first sound
        # PriorityQueue: the watchdog's `stop` (priority -1) must pass ahead of anything queued.
        # The sequence number keeps FIFO order inside one priority and avoids comparing payload dicts.
        self.events: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        self.gen = 0        # bumped on every cancellation; threads compare with their own copy
        self._busy = False  # an utterance is being transcribed
        self.turns = 0      # exchanges in the current conversation (MAX_TURNS guard)
        self.deaf = bool(cfg.get("deaf", False))  # "Sourd": microphone forced off (tests), persisted
        self.repairs = 0           # consecutive "pardon ?" (max 2, then the normal timers act)
        self._relance_text = None  # one-shot text for the next RELANCE (used by the repair)
        self.stt.prompt = cfg.get("stt_prompt", "")
        self.mic = mic or AudioIn(self._on_utterance, self._on_speech_start,
                                  device=find_device(cfg["mic_device"], "input"),
                                  silence_ms=cfg["vad_silence_ms"], max_s=cfg["max_utterance_s"],
                                  source_match=cfg.get("mic_source_match", ""),
                                  early_ms=cfg.get("stt_early_ms", 0), speculate=self.stt.transcribe)
        # Fixed phrases (greeting, relance, goodbye, repair) are synthesized once and replayed:
        # identical samples, no TTS wait before the robot starts talking.
        self._phrases: dict[str, np.ndarray] = {}
        # Heartbeat / watchdog bookkeeping (read by snapshot() from other threads: plain floats/ints only).
        self.hb_hz = max(0.5, float(cfg.get("heartbeat_hz", 10)))
        self.watchdog_s = float(cfg.get("watchdog_s", 5))
        self._closing = threading.Event()
        self._tick_pending = False   # at most one tick in the queue: a stuck loop must not pile them up
        self._last_beat = self.now()
        self._lag_ms, self._hz, self._trips, self._wd_tripped = 0.0, 0.0, 0, False
        self._beats: collections.deque = collections.deque(maxlen=30)
        self._tick_err_at = 0.0
        self._scheduled: list = []   # (due monotonic, event, gen): replaces the old threading.Timer
        self._sched_lock = threading.Lock()
        self.graph_error = None
        self.graph_pending = False   # a saved graph waits for the next idle state (see request_graph_reload)
        # Journal of fired chains (last 50): feeds GET /api/graph/trace, snapshot()["last_transition"] and
        # the simulator. `journal_hook(entry)` lets the simulator observe each new entry.
        self.journal: collections.deque = collections.deque(maxlen=JOURNAL_MAX)
        self.journal_hook = None
        # Face expression / gaze commands of the graph actions set_expression and gaze (read by the UI).
        self._expression = None      # (name, expires monotonic) or None
        self.gaze_mode = "suivre"
        self._deferred: list = []    # (due monotonic, gen, fn): continuations of the `wait` action
        # Sensor-derived events (personnes_multiples, inactivite_longue, ouverture/fermeture), see _sensors().
        self.faces, self._multi_since, self._multi_posted = 0, None, False
        self.last_activity, self._idle_posted = self.now(), False
        self._open_prev, self._open_check = None, 0.0
        # Graph variables (lot L1): user values (reset at every graph load), last heard sentence ($utterance).
        self.vars, self.lists, self._watched = {}, {}, frozenset()
        self.last_text, self._var_depth, self._cascade_logged = "", 0, set()
        # Lot L11: persistence, timers, shuffle bags, visitor counter (nb_visiteurs_jour = exits from veille today).
        self._store, self._persist_seen, self._persist_ignored = var_store, {}, []
        self._timer_watch, self._timer_fired, self._bags = (), set(), {}
        self._visitors = {"date": "", "count": 0}
        self._graph = None
        self.rng = random.Random()
        self.engine = self._build_engine()
        if self._threaded:
            self._start_threads()
        else:
            self._boot()   # simulator: no threads, the caller drives pump() with a manual clock

    # ------------------------------------------------------------------ public API (UI / sensors)
    def post(self, kind: str, **kw):
        self.events.put((0, next(self._seq), kind, kw))

    def post_priority(self, kind: str, **kw):
        """Handled before every queued event (used by the watchdog)."""
        self.events.put((-1, next(self._seq), kind, kw))

    def snapshot(self) -> dict:
        now = self.now()
        expr = self._expression
        return {"state": self.state, "subtitle": self.subtitle, "mic_on": self.mic.active,
                "mic_level": round(self.mic.level, 3), "out_level": round(self.out.level, 3),
                "speaking": self.out.busy, "muted": self.out.muted, "deaf": self.deaf, "latencies_ms": list(self.latencies),
                "state_age_s": round(now - self.since, 1), "turns": self.turns,
                # graph actions set_expression / gaze (the face UI reads them; `gaze` is taken by /api/live)
                "expression": {"name": expr[0], "left_s": round(expr[1] - now, 1)} if expr and expr[1] > now else None,
                "gaze_mode": self.gaze_mode, "last_transition": self.last_transition(),
                "heartbeat": {"hz": round(self._hz, 1), "lag_ms": round(self._lag_ms, 1),
                              "age_ms": int((now - self._last_beat) * 1000), "trips": self._trips}}

    def reload_graph(self) -> tuple[bool, str | None]:
        """Re-read the graph file; only while idle (veille/eteint) so no conversation is cut mid-state.

        Returns (applied, error): error is the validation message when the file was invalid and the
        default graph is running instead.
        """
        if self.state not in (VEILLE, ETEINT):
            return False, "busy"
        self.graph_pending = False
        self.engine = self._build_engine()
        return True, self.graph_error

    def request_graph_reload(self) -> bool:
        """Apply the graph file now when idle; otherwise remember it and apply on the next entry into
        veille/eteint (see `_go`). Returns True when it was applied immediately."""
        ok, _err = self.reload_graph()
        if not ok:
            self.graph_pending = True
            log.info("graph saved while busy: will be applied at the next idle state")
        return ok

    # ------------------------------------------------------------------ journal of fired chains
    def note_fire(self, chain_key, tr, event):
        """Called by the GraphEngine each time a transition fires; returns the (mutable) journal entry.

        The engine fills `to`/`moved`/`reason` when the chain really changes the state (a chain may also only
        run actions, or be paused by `wait`, so the entry is completed later).
        """
        entry = {"t": round(self.wall(), 3), "mono": self.now(), "event": event, "from": self.state,
                 "to": self.state, "moved": False, "reason": tr.reason or tr.on or "after",
                 "chain": chain_key, "actions": [c.label() for c in tr.do + tr.then]}
        self.journal.append(entry)
        if self.journal_hook:
            self.journal_hook(entry)
        return entry

    @staticmethod
    def _public_entry(e: dict, now: float) -> dict:
        d = {k: v for k, v in e.items() if k != "mono"}
        d["age_s"] = round(max(0.0, now - e["mono"]), 1)
        return d

    def last_transition(self):
        try:
            return self._public_entry(self.journal[-1], self.now())
        except IndexError:
            return None

    def trace(self) -> list:
        """The last fired chains, oldest first (GET /api/graph/trace)."""
        now = self.now()
        return [self._public_entry(e, now) for e in list(self.journal)]

    def defer(self, delay_s: float, fn):
        """Run `fn` in the brain loop after `delay_s` (non-blocking `wait`). A stop/off/hush in between bumps
        `gen` and drops it, exactly like scheduled events."""
        with self._sched_lock:
            self._deferred.append((self.now() + delay_s, self.gen, fn))

    # ------------------------------------------------------------------ sensors (vision count, idle, hours)
    def set_faces(self, n: int):
        """Number of faces the camera sees right now (called by the vision thread, or by the simulator)."""
        self.faces = n
        if n > 0:
            self._activity()

    def _activity(self):
        self.last_activity, self._idle_posted = self.now(), False

    def _sensors(self, now: float):
        """Derived events: personnes_multiples (>= 2 faces for 1 s), inactivite_longue (no face and no
        speech for idle_long_s) and ouverture/fermeture (opening_hours). Runs in the brain loop on every tick."""
        if self.faces >= 2:
            if self._multi_since is None:
                self._multi_since = now
            elif not self._multi_posted and now - self._multi_since >= MULTI_FACES_S:
                self._multi_posted = True
                self.post("personnes_multiples")
        else:
            self._multi_since, self._multi_posted = None, False
        idle_s = float(self.cfg.get("idle_long_s", 300))
        if idle_s > 0 and not self._idle_posted and self.faces == 0 and now - self.last_activity >= idle_s:
            self._idle_posted = True
            self.post("inactivite_longue")
        if now - self._open_check >= SENSOR_PERIOD_S:
            self._open_check = now
            table = hours_mod.safe_parse(self.cfg.get("opening_hours"))
            if table is None:
                self._open_prev = None   # empty / invalid hours: always open, no events
            else:
                is_open = hours_mod.is_open(table, self._wall_dt())
                if self._open_prev is not None and is_open != self._open_prev:
                    self.post("ouverture" if is_open else "fermeture")
                self._open_prev = is_open

    def _wall_dt(self) -> "datetime.datetime":
        return datetime.datetime.fromtimestamp(self.wall())

    def pump(self, limit: int = 5000):
        """Process every queued event synchronously (non-threaded simulator only).

        Raises RuntimeError after `limit` events: a graph whose chains keep posting each other's events would
        otherwise loop forever.
        """
        for _ in range(limit):
            try:
                _, _, kind, kw = self.events.get_nowait()
            except queue.Empty:
                return
            self._handle(kind, kw)
        raise RuntimeError("boucle d'événements : plus de %d événements sans fin" % limit)

    def set_deaf(self, deaf: bool):
        self.deaf = deaf
        if deaf:
            self.mic.stop()
        elif self.state in (VEILLE, ECOUTE) or (self.state == RELANCE and not self.out.busy):
            self.mic.start()
        log.info("deaf=%s", deaf)

    def _mic_on(self):
        """Every mic opening goes through here so the deaf mode can never be bypassed."""
        if not self.deaf:
            self.mic.start()

    # ------------------------------------------------------------------ cancellation
    def _cancel_all(self):
        """Silence now and invalidate every running speak/answer thread."""
        self.gen += 1
        self.out.stop()

    def _alive(self, gen: int) -> bool:
        return gen == self.gen

    # ------------------------------------------------------------------ audio callbacks
    def _on_speech_start(self):
        self.last_speech = self.now()
        self._activity()
        if self.state == REPONSE and self.cfg["barge_in"]:
            self.post("barge_in")

    def _on_utterance(self, pcm, t_end, text=None):
        """`text` is the early transcription of exactly `pcm` when AudioIn already made it."""
        if self._busy or self.state == ETEINT:
            return
        self._busy = True
        try:
            if text is None:
                text = self.stt.transcribe(pcm)
        except Exception:
            log.exception("stt failed")
            text = ""
        finally:
            self._busy = False
        self.last_speech = self.now()
        self._activity()
        if not text or is_phantom(text, keep_words=set(self.cfg["refusal_words"]) | {"nanterino", "oui", "non"}):
            log.info("utterance rejected reason=%s words=%d", "phantom" if text else "empty", len(text.split()))  # never the text itself
            # Loud enough to be someone talking, but nothing usable: ask to repeat instead of
            # staying silent (silence felt like "the robot does not understand").
            self.post("not_understood")
            return
        self.post("utterance", text=text, t_end=t_end)

    # ------------------------------------------------------------------ state machine
    def _go(self, state: str, reason: str):
        log.info("%stransition %s -> %s reason=%s", "" if self._threaded else "[sim] ", self.state, state, reason)
        if self.state == VEILLE and state not in (VEILLE, ETEINT):   # a conversation starts: one more visitor today
            self._visitors_today()
            self._visitors["count"] += 1
        self.state, self.since = state, self.now()
        if state in (VEILLE, ETEINT):
            self.gaze_mode = "suivre"   # a `gaze` command lasts for one conversation
        if self.graph_pending and state in (VEILLE, ETEINT):
            # Deferred editor save: swap graphs here, before the new state's on_enter runs. The old engine
            # object that called us may still run its remaining `then` actions; that is harmless.
            self.graph_pending = False
            self.engine = self._build_engine()
            log.info("pending graph applied on entry into %s error=%s", state, bool(self.graph_error))
        self.engine.enter(state)  # the graph's `on_enter` actions

    def _build_engine(self) -> "graph_mod.GraphEngine":
        """Load the active graph (override file or default) and bind it to this brain's capabilities.

        Actions and guards come from the node registry (nanterino.nodes.ACTIONS, lot M1; nanterino.nodes.CONDITIONS,
        lot M2), the same source graph.ACTION_SPECS / GUARDS are derived from. GraphEngine refuses to start if a name
        of graph.ACTION_SPECS / GUARDS is missing.
        """
        cfg = self.cfg
        if self._fixed_graph is not None:   # simulator: the graph is given in memory, nothing is read from disk
            graph, self.graph_error = self._fixed_graph, None
        else:
            graph, self.graph_error = graph_mod.load_active(cfg)

        # ---- variables (lot L1 + L11): values reset from the graph at every load, then the persisted ones read back
        self._graph = graph
        self.vars = {n: v.value for n, v in graph.variables.items()}
        self.lists = {n: _fresh_items(li) for n, li in graph.lists.items() if not li.source}
        self._watched, self._cascade_logged = graph.watched_vars(), set()
        self._timer_watch, self._timer_fired, self._bags = graph.timer_watches(), set(), {}
        self._load_persisted(graph)

        # ---- actions (lot M1, 2026-11-01): one module per action (nanterino/nodes/actions/<id>.py), bound here.
        # The engine calls fn(kw, **args); each call gets a NodeContext with THIS brain and the cfg / graph captured now
        # (as the former closures did), so an old engine finishing its `then` actions after a pending-graph swap still
        # works on the graph it was built from. Brain attributes are looked up at call time (tests wrap methods).
        def bind(node, entry):
            def call(kw, **args):
                return getattr(node, entry)(NodeContext(self, kw, cfg, graph), **args)
            call.__name__ = call.__qualname__ = "%s_%s" % ("action" if entry == "run" else "guard", node.id)
            return call

        actions = {name: bind(node, "run") for name, node in nodes.ACTIONS.items()}
        # ---- guards (lot M2): one module per condition (nanterino/nodes/conditions/<id>.py), bound the same way; the
        # engine calls fn(kw, **args) and applies `{not: ...}`. Wall clock / counters are read through this brain
        # (self.wall / _wall_dt injectable, brain.MAX_TURNS / MAX_REPAIRS looked up at call time by the modules).
        guards = {name: bind(node, "test") for name, node in nodes.CONDITIONS.items()}
        engine = graph_mod.GraphEngine(graph, self, actions, guards, cfg)
        # Pre-synthesise the graph's free phrases (say_text) like the fixed ones, off the loop thread.
        if self._threaded:
            threading.Thread(target=self._cache_phrases, args=(graph,), daemon=True, name="phrase-cache").start()
        else:
            self._cache_phrases(graph)
        return engine

    def _schedule_at(self, due: float, event: str):
        with self._sched_lock:
            self._scheduled.append((due, event, self.gen))

    def _speak_then(self, text: str, done_event: str):
        self.subtitle = text
        gen = self.gen
        if not self._threaded:   # simulator: play on the fake output, then the done event after its duration
            pcm = self._phrases.get(text)
            if pcm is None:
                pcm = self.tts.synth(text)
            self.out.play(pcm, self.tts.rate)
            self._schedule_at(self.now() + 0.15 + float(getattr(self.out, "dur", 1.0)), done_event)
            return

        def run():
            try:
                pcm = self._phrases.get(text)
                if pcm is None:
                    pcm = self.tts.synth(text)
                if self._alive(gen):
                    self.out.play(pcm, self.tts.rate)
                    self._wait_audio(gen)
            except Exception:
                log.exception("speak failed")
            if self._alive(gen):  # a cancelled thread never moves the state machine
                self.post(done_event, gen=gen)
        threading.Thread(target=run, daemon=True).start()

    def _cache_phrases(self, graph=None):
        """Synthesise once: the fixed config phrases and every `say_text` of `graph` (at most SAY_TEXTS_MAX).

        Synthesis is silent (nothing is played), so a muted robot is unaffected; playback at run time goes
        through AudioOut, which keeps honouring `muted`. A text already cached is skipped, so a graph
        reload only pays for new phrases.
        """
        texts = [(key, self.cfg.get(key)) for key in ("greeting", "relance", "goodbye", "repair_text")]
        if graph is not None:
            texts += [("say_text", t) for t in graph_mod.say_texts(graph)[:SAY_TEXTS_MAX]]
        for key, text in texts:
            if text and text not in self._phrases:
                try:
                    self._phrases[text] = self.tts.synth(text)
                except Exception:
                    log.exception("phrase cache failed key=%s", key)
        log.info("phrase cache ready n=%d", len(self._phrases))

    def _wait_audio(self, gen: int):
        time.sleep(0.15)
        while self.out.busy and self._alive(gen):
            time.sleep(0.05)

    # ------------------------------------------------------------------ threads: loop, heartbeat, watchdog
    def _start_threads(self):
        self._hb_thread = threading.Thread(target=self._heartbeat, daemon=True, name="heartbeat")
        self._hb_thread.start()
        self._start_loop(boot=True)
        threading.Thread(target=self._watchdog, daemon=True, name="watchdog").start()

    def _start_loop(self, boot: bool):
        self._loop_thread = threading.Thread(target=self._loop, args=(boot,), daemon=True, name="brain")
        self._loop_thread.start()

    def shutdown(self):
        """Stop the three threads (tests; the service itself never calls it)."""
        self._closing.set()
        self.post_priority("_quit")

    def _boot(self):
        # Power state survives restarts: an "off" robot stays off after a reboot (user request).
        if self._start_state:          # simulator: begin in any state of the graph
            self.state = self._start_state
        elif self.cfg.get("power") == "off":
            self.state = ETEINT
        try:
            self.engine.enter(self.state)
        except Exception:
            log.exception("boot entry failed")

    def _handle(self, kind: str, kw: dict):
        """One queued event (loop thread, or pump() in the simulator)."""
        if kind == "tick":
            self._on_tick(kw)
            return
        if "gen" in kw and kw["gen"] != self.gen:
            return  # late event from a cancelled thread
        if isinstance(kw.get("text"), str):
            self.last_text = kw["text"]     # `$utterance` of the variable conditions / actions
        self._var_depth = kw.get("depth", 0) if kind in graph_mod.WATCH_EVENTS else 0   # anti-loop (L1, L11)
        try:
            self.engine.dispatch(kind, kw)
        finally:
            self._var_depth = 0

    # ------------------------------------------------------------------ graph variables (lot L1)
    def var_value(self, name: str):
        """Current value of a user or system variable (None when unknown)."""
        if name == "etat":
            return self.state
        if name == "tours":
            return self.turns
        if name == "max_tours":
            return MAX_TURNS
        if name == "reparations":
            return self.repairs
        if name == "max_reparations":
            return MAX_REPAIRS
        if name == "heure":            # lot L11 system views
            return self._now_iso()
        if name == "jour":
            return self._weekday()
        if name == "derniere_phrase":
            return self.last_text
        if name == "visage_vu":
            return self.faces > 0
        if name == "volume":
            vol = getattr(self.out, "volume", self.cfg.get("volume", 0.8))
            return int(min(100, max(0, round(float(vol) * 100)))) if isinstance(vol, (int, float)) else 0
        if name == "expression":
            expr = self._expression
            return expr[0] if expr and expr[1] > self.now() else "neutre"
        if name == "regard":
            return self.gaze_mode
        if name == "nb_visiteurs_jour":
            return self._visitors_today()
        if self._var_type(name) == "timer":
            return self._elapsed(name)
        return self.vars.get(name)

    # ------------------------------------------------------------------ variables v2 helpers (lot L11)
    def _var_type(self, name: str):
        if name in graph_mod.SYSTEM_VARS:
            return graph_mod.SYSTEM_VARS[name][0]
        v = self._graph.variables.get(name) if self._graph is not None else None
        return v.type if v is not None else None

    def _now_iso(self) -> str:
        return self._wall_dt().replace(microsecond=0).isoformat()

    def _weekday(self) -> str:
        return list(graph_mod.WEEKDAYS)[self._wall_dt().weekday()]

    def _elapsed(self, name: str):
        """Seconds since a timer's start (None = stopped) or since a datetime variable (None = empty)."""
        if self._var_type(name) == "timer":
            start = self.vars.get(name)
            return round(self.wall() - start, 3) if isinstance(start, (int, float)) and not isinstance(start, bool) else None
        dt = graph_mod.parse_iso(self.var_value(name))
        return (self._wall_dt() - dt).total_seconds() if dt is not None else None

    def _visitors_today(self) -> int:
        today = self._wall_dt().date().isoformat()
        if self._visitors["date"] != today:   # midnight (or first use): a new day starts at 0
            self._visitors = {"date": today, "count": 0}
        return self._visitors["count"]

    @staticmethod
    def _compare(a, op, b, vtype=None) -> bool:
        """var_compare / dict_value_compare / date_compare / elapsed_since: = and != on anything, order on numbers
        (bools excluded) and, for vtype datetime, on parsed ISO dates. Lot M3: the type module's compare()."""
        return vartypes.compare(a, op, b, vtype)

    def _bag_pick(self, name: str, items: list):
        """Shuffle-bag draw (lot M3: nanterino/listmodes/shuffle.py; the bags stay in self._bags)."""
        return LISTMODES["shuffle"].pick(self, name, items)

    def _reset_scope(self, graph, scope: str):
        """Back to the initial values for every variable / user list of `scope` (no var_changed is posted)."""
        for n, v in graph.variables.items():
            if v.scope == scope:
                self.vars[n] = v.value
        for n, li in graph.lists.items():
            if li.scope == scope and not li.source:
                self.lists[n] = _fresh_items(li)
                self._bags.pop(n, None)

    def reset_var(self, name: str) -> bool:
        """Variable manager button: initial value back, saved value forgotten. False for an unknown / read-only name."""
        g = self._graph
        if g is None:
            return False
        if name in g.variables:
            part = "names"
            self.vars[name] = g.variables[name].value
        elif name in g.lists and not g.lists[name].source:
            part = "lists"
            self.lists[name] = _fresh_items(g.lists[name])
            self._bags.pop(name, None)
        else:
            return False
        self._persist_ignored = [x for x in self._persist_ignored if (x["part"], x["name"]) != (part, name)]
        if self._store is not None:
            self._store.drop(part, name)
            self._persist_seen[(part, name)] = self._persist_entry(part, name)   # not written back by the next tick
        log.info("graph variable %s reset to its initial value", name)
        return True

    def _timers_tick(self):
        """Post `timer_reached` once per (timer, seconds, start); a restarted or reset timer re-arms its triggers."""
        if not self._timer_watch:
            return
        wall, live = self.wall(), set()
        for var, secs in self._timer_watch:
            start = self.vars.get(var)
            if not isinstance(start, (int, float)) or isinstance(start, bool):
                continue
            key = (var, secs, start)
            live.add(key)
            if key not in self._timer_fired and wall - start >= secs:
                self._timer_fired.add(key)
                self.post("timer_reached", name=var, value=secs, depth=MAX_VAR_CASCADE)
        self._timer_fired &= live

    # -- persistence (var_store): which values, read back at load, written from the heartbeat
    def _persist_keys(self) -> list:
        g = self._graph
        return ([("names", n) for n, v in g.variables.items() if v.persist]
                + [("lists", n) for n, li in g.lists.items() if li.persist and not li.source])

    def _persist_entry(self, part: str, name: str) -> dict:
        g = self._graph
        if part == "names":   # lot M3: values / items through the type and kind modules (format unchanged)
            v = g.variables[name]
            return {"type": v.type, "value": vartypes.VARTYPES[v.type].serialize(self.vars.get(name))}
        li, items = g.lists[name], self.lists.get(name)
        return {"type": li.type, "kind": li.kind, "items": LISTKINDS[li.kind].serialize(items, vartypes.VARTYPES[li.type])}

    def _ignore_persisted(self, part: str, name: str, entry, why: str):
        log.warning("vars store: saved %s %r ignored (%s); the initial value is used", part[:-1], name, why)
        self._persist_ignored.append({"part": part, "name": name, "reason": why, "stored": entry})

    def _load_persisted(self, graph):
        """Overlay the values saved in the store (if any) on the fresh graph values; type-checked."""
        self._persist_seen, self._persist_ignored = {}, []
        if self._store is None:
            return
        data = self._store.data
        vis = data.get("system", {}).get("nb_visiteurs_jour")
        if isinstance(vis, dict) and isinstance(vis.get("date"), str) and isinstance(vis.get("count"), int):
            self._visitors = {"date": vis["date"], "count": vis["count"]}
        for n, v in graph.variables.items():
            e = data.get("names", {}).get(n) if v.persist else None
            if e is None:
                continue
            if not isinstance(e, dict) or e.get("type") != v.type:
                self._ignore_persisted("names", n, e, "type changed")
            elif not graph_mod.persisted_ok(graph, v.type, e.get("value"), v.choices):
                self._ignore_persisted("names", n, e, "invalid value")
            else:
                self.vars[n] = graph_mod.fit_value(v, vartypes.VARTYPES[v.type].deserialize(e.get("value")))
        for n, li in graph.lists.items():
            e = data.get("lists", {}).get(n) if li.persist and not li.source else None
            if e is None:
                continue
            items = e.get("items") if isinstance(e, dict) else None
            if not isinstance(e, dict) or e.get("type") != li.type or e.get("kind", "list") != li.kind:
                self._ignore_persisted("lists", n, e, "type changed")
                continue
            restored = LISTKINDS[li.kind].restore(graph, li, items)   # lot M3: per-item type check in the kind module
            if restored is None:
                self._ignore_persisted("lists", n, e, "invalid items")
                continue
            self.lists[n] = restored
        for key in self._persist_keys():
            self._persist_seen[key] = self._persist_entry(*key)   # what is in memory now is not a change to write
        self._persist_seen[("system", "nb_visiteurs_jour")] = dict(self._visitors)

    def _persist_tick(self, now: float):
        """Hand changed persisted values to the store (polled from the heartbeat); the store writes <= 1x / 2 s."""
        if self._store is None:
            return
        for key in self._persist_keys():
            e = self._persist_entry(*key)
            if self._persist_seen.get(key) != e:
                self._persist_seen[key] = e
                self._store.put(key[0], key[1], e)
        vis, vkey = dict(self._visitors), ("system", "nb_visiteurs_jour")
        if self._persist_seen.get(vkey) != vis and (vis["count"] > 0 or self._store.has(*vkey)):
            self._persist_seen[vkey] = vis   # a bare date roll at 0 visitors never creates the file
            self._store.put(vkey[0], vkey[1], vis)
        self._store.maybe_flush(now)

    def var_store_info(self) -> dict:
        """Persistence and scope facts for the variable manager (GET /api/graph/vars `store`)."""
        g = self._graph
        st = self._store
        return {"enabled": st is not None, "path": st.path if st is not None else None,
                "persist": {"names": [n for n, v in g.variables.items() if v.persist],
                            "lists": [n for n, li in g.lists.items() if li.persist]},
                "saved": st.saved() if st is not None else {"names": [], "lists": [], "system": []},
                "ignored": [{k: x[k] for k in ("part", "name", "reason")} for x in self._persist_ignored],
                "scopes": {"names": {n: v.scope for n, v in g.variables.items()},
                           "lists": {n: li.scope for n, li in g.lists.items()}}}

    def list_items(self, name: str) -> list:
        li = self._graph.lists.get(name) if self._graph is not None else None
        if li is not None and li.source and li.source[0] == "cfg":
            return list(self.cfg.get(li.source[1]) or [])   # bound to config.json: always the live words
        if name in self.lists:
            return self.lists[name]
        return list(li.items) if li is not None else []

    def var_snapshot(self, volatile: bool = True) -> dict:
        """Live values for GET /api/graph/vars and the simulator (system variables included).

        A timer shows its elapsed seconds (None = stopped), a dictionary a {key: value} object. `volatile=False` leaves
        out the wall-clock views (heure, jour): the simulator does so when no start time makes them deterministic."""
        names = {n: self.var_value(n) for n in graph_mod.SYSTEM_VARS if volatile or n not in graph_mod.VOLATILE_SYSTEM_VARS}
        names.update({n: self.var_value(n) for n in list(self.vars)})
        lists = {}
        for n in self._graph.lists:
            items = self.list_items(n)
            lists[n] = dict(items) if isinstance(items, dict) else list(items)
        return {"names": names, "lists": lists}

    def _resolve(self, value, kw):
        """A literal, `$utterance` (the sentence being handled, else the last one heard) or `$<variable>`."""
        if isinstance(value, str) and value.startswith("$"):
            ref = value[1:]
            if ref == "utterance":
                return kw.get("text") if isinstance(kw.get("text"), str) else self.last_text
            return self.var_value(ref)
        return value

    def _set_var(self, name: str, value):
        old = self.vars.get(name)
        if old == value and type(old) is type(value):
            return
        self.vars[name] = value
        if name not in self._watched:
            return
        if self._var_depth >= MAX_VAR_CASCADE:   # anti-loop: a var_changed chain does not re-trigger var_changed
            if name not in self._cascade_logged:
                self._cascade_logged.add(name)
                log.warning("graph: var_changed %s dropped (cascade limit %d)", name, MAX_VAR_CASCADE)
            return
        self.post("var_changed", name=name, value=value, old=old, depth=self._var_depth + 1)

    def _loop(self, boot: bool = True):
        if boot:
            self._boot()
        while not self._closing.is_set():
            try:
                _, _, kind, kw = self.events.get()  # blocks: the heartbeat wakes it 10x/s
                if kind == "_quit":
                    return
                self._handle(kind, kw)
            except Exception:
                log.exception("event handling failed")

    def _on_tick(self, kw: dict):
        now = self.now()
        # Beat accounting comes first: "a beat was processed" is what the watchdog measures.
        self._tick_pending, self._wd_tripped, self._last_beat = False, False, now
        self._lag_ms = (now - kw["t"]) * 1000.0
        self._beats.append(now)
        if len(self._beats) > 2 and now > self._beats[0]:
            self._hz = (len(self._beats) - 1) / (now - self._beats[0])
        try:
            self._release_scheduled(now)
            self._sensors(now)
            self._timers_tick()        # lot L11: timer_reached
            self._persist_tick(now)    # lot L11: persisted variables -> var_store
            self.engine.tick(now)
        except Exception:
            if now - self._tick_err_at > 5:  # a systematic bug must not flood the log at 10 Hz
                self._tick_err_at = now
                log.exception("tick handling failed")

    def _release_scheduled(self, now: float):
        with self._sched_lock:
            due = [x for x in self._scheduled if x[0] <= now]
            self._scheduled = [x for x in self._scheduled if x[0] > now]
        for _, event, gen in due:
            self.post(event, gen=gen)  # dropped by the loop if a stop/off bumped gen meanwhile
        with self._sched_lock:
            ready = [x for x in self._deferred if x[0] <= now]
            self._deferred = [x for x in self._deferred if x[0] > now]
        for _, gen, fn in ready:   # continuations of `wait`: run here, in the loop thread, like any event
            if gen == self.gen:
                try:
                    fn()
                except Exception:
                    log.exception("deferred chain failed")

    def _heartbeat(self):
        period = 1.0 / self.hb_hz
        nxt = time.monotonic() + period
        while not self._closing.wait(max(0.0, nxt - time.monotonic())):
            now = time.monotonic()
            nxt += period
            if nxt < now:  # we overslept (suspend, heavy load): do not fire a burst to catch up
                nxt = now + period
            if not self._tick_pending:
                self._tick_pending = True
                self.events.put((0, next(self._seq), "tick", {"t": now}))

    def _watchdog(self):
        check = max(0.05, min(1.0, self.watchdog_s / 4))
        while not self._closing.wait(check):
            if not self._hb_thread.is_alive():
                log.error("watchdog: heartbeat thread died, restarting it")
                self._hb_thread = threading.Thread(target=self._heartbeat, daemon=True, name="heartbeat")
                self._hb_thread.start()
            if not self._loop_thread.is_alive():
                log.error("watchdog: brain loop thread died, restarting it")
                self._start_loop(boot=False)
            age = self.now() - self._last_beat
            if age > self.watchdog_s and not self._wd_tripped:
                self._wd_tripped = True  # one trip per stall; cleared by the next processed beat
                self._trips += 1
                log.error("watchdog: no heartbeat processed for %.1fs in state=%s, forcing stop (trip %d)",
                          age, self.state, self._trips)
                self._cancel_all()
                self.post_priority("stop", source="watchdog")

    def _sing(self, gen: int):
        """Play the pre-built song (song/build_song.py) with line-by-line subtitles."""
        import json
        import wave
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "media", "chanson-nanterino.wav")
        try:
            with wave.open(path) as w:
                rate = w.getframerate()
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            lines = json.load(open(path.replace(".wav", ".json"), encoding="utf-8"))["lines"]
        except Exception:
            log.exception("song not available (build it with song/build_song.py)")
            self.subtitle = "Je n'ai pas encore appris ma chanson."
            time.sleep(2)
            if self._alive(gen):
                self.post("answer_done", gen=gen)
            return
        log.info("song start s=%.1f", len(pcm) / rate)
        self.out.play(pcm, rate)
        t0 = time.monotonic() + self.out.preroll_ms / 1000  # first sample after the wake-up pre-roll
        time.sleep(0.15)
        while self.out.busy and self._alive(gen):
            now = time.monotonic() - t0
            current = [l["text"] for l in lines if l["t"] - 0.3 <= now]
            self.subtitle = "🎵 " + current[-1] if current else "🎵"
            time.sleep(0.05)
        if self._alive(gen):  # finished normally (stop/hush bump gen and silence it)
            log.info("song end")
            self.subtitle = ""
            self.post("answer_done", gen=gen)

    def _answer(self, question: str, t_end: float, gen: int):
        cfg = self.cfg
        sheets = self.corpus.search(question, cfg.get("corpus_k", 3), cfg.get("corpus_rel_min", 0.0))
        messages = build_messages(cfg, sheets, self.history[-2 * cfg["history_turns"]:], question)
        log.info("answer start sheets=%d", len(sheets))
        full, spoken, first = [], 0, True
        try:
            for sentence in self.llm.sentences(messages):
                if not self._alive(gen):
                    return  # cancelled: no audio, no history, no event
                sentence = fix_sentence(sentence)
                full.append(sentence)
                self.subtitle = " ".join(full)  # full detail on screen, only N sentences spoken
                if spoken < cfg["spoken_sentences"]:
                    pcm = self.tts.synth(sentence)
                    if not self._alive(gen):
                        return
                    self.out.play(pcm, self.tts.rate)
                    spoken += 1
                    if first:
                        ms = int((time.monotonic() - t_end) * 1000)
                        self.latencies.append(ms)
                        # What the visitor really waits: from the end of their voice (VAD silence
                        # before t_end) to the first audible sample (after the pre-roll, if any).
                        wait = ms + self.cfg["vad_silence_ms"] + (self.out.preroll_ms if self.out.last_play_preroll else 0)
                        log.info("latency_first_sound_ms=%d wait_visitor_ms=%d", ms, wait)
                        first = False
        except Exception:
            log.exception("answer pipeline failed")
            self.subtitle = "Désolé, j'ai eu un problème."
        if not self._alive(gen):
            return
        self.history += [{"role": "user", "content": question}, {"role": "assistant", "content": " ".join(full)}]
        self._wait_audio(gen)
        if self._alive(gen):
            self.post("answer_done", gen=gen)
