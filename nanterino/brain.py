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

Concept triads (lot N1, 2026-11-02): the brain owns the state behind the N1 nodes and POSTS their triggers on the real
code paths: play_media (media_started / media_finished, `_media`), set_volume / set_muted / set_deaf (also called by
server.py's dashboard controls: volume_changed / mute_changed / deaf_changed; `volume_hook` / `flag_hook` let the server
apply a volume through the speaker profile and persist muted / deaf like the buttons), show_text (text_shown /
text_cleared from the heartbeat, `_shown`), list / dictionary changes (list_changed / dict_changed through
`list_touched`), timer_reset (timer_stopped), the robot journal (`journal_notes`: log_note entries + WARNING/ERROR
records of the live robot's log via nanterino/journal.py; journal_entry) and dashboard notifications (notify,
click_notification; notification_clicked). Every state-change trigger goes through `_changed`: same anti-loop as
var_changed (a change made by a chain a change event started posts nothing), watch triggers only for a listened name.

Trigger / condition parity (lot N2, 2026-11-02): every mic opening / closing goes through `mic_set` (mic_opened /
mic_closed on a real change), set_expression / gaze through `set_expression` / `set_gaze` (expression_changed, also when
an expression expires on the heartbeat; gaze_changed, also on the return to « suivre »), start_sing through `start_song`
(song_started / song_finished, `is_singing`), `_go` posts conversation_started / conversation_ended (plain posts: a state
move is never dropped) and times the conversation, `set_faces` posts face_count_changed, `_handle` notes when each event
was last handled (`event_age`, event_recent). The action modules post answer_started, conversation_cleared, turn_counted,
list_item_added / list_item_removed (`list_item_event`).

Per-theme parity (lot N3, 2026-11-02): `_audio_tick` (heartbeat) posts speech_started on the rising edge of out.busy
(any sound) and keeps the robot's last-sound time (robot_quiet_since), loud_noise when the open mic's level crosses
LOUD_LEVEL; `_on_speech_start` posts voice_detected; `_clock_tick` (sensor period) posts hour_changed / day_changed;
`reset_var` / `_reset_scope` post var_reset, `_set_var` var_bound_reached (a variable reaching its min / max),
`_load_persisted` vars_restored; `list_touched` posts list_emptied / dict_emptied / list_filled and `dict_key_events`
dict_key_set / dict_key_removed (watch triggers: listened names only). `last_said` is the robot's last phrase / answer,
`_faces_zero_since` the start of the current face absence, `started_at` the brain's start (uptime).

Body (lot C3, 2026-11-04): `self.body` is the robot body (nanterino/body: joints, calibration, limits, e-stop). server.py
passes the live one (cfg["body_backend"], state/body-calibration.json); any other Brain (simulator, tests) builds an
in-memory simulated body. The heartbeat ticks it AFTER the graph, in its own try block: a body fault never stops the
graph tick, and the body posts no graph event yet (Mouvement nodes = lot B1), so traces are unchanged.

360-degree sound (lot C2, 2026-11-04): `self.sound` is a nanterino/sound SoundTracker (direction(), level(), history()).
server.py replaces it with the live one (cfg["sound_backend"], default mono = the single USB mic: level only, never a
direction; state/sound-calibration.json); any other Brain gets an in-memory tracker on its own mic. `_sound_tick`
(heartbeat, after the body, own try block) polls it and posts `sound_from_direction` (value = sector) only when a
transition listens to it, the robot is not deaf and the direction is confident: once per sound onset or sector change,
at most one per SOUND_EVENT_GAP_S, re-armed after SOUND_REARM_S without a direction (anti-burst). Mono never posts, so
traces are unchanged.

Mouvement (lot B1, 2026-11-04): `self.motion` is a nanterino/body/motion.py MotionRuntime on `self.body`: the Mouvement
nodes call it (look, gestures of nanterino/body/gestures.yaml, poses, arms, base moves by odometry, stops, face
tracking); its Body event hook only posts graph events (motion_done, motion_interrupted, motion_stopped,
motion_refused, motion_clamped, overcurrent_detected, estop_pressed, estop_released, gesture_done, pose_reached,
base_move_done; face_tracking_changed through `_changed`). The heartbeat ticks it right after the body, in its own try
block. Nothing moves in the shipped graph, so nothing is posted and traces are unchanged. server.py sets
`motion.face_source` to the live vision state; elsewhere face tracking is a logged no-op.

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
from . import properties
from .listkinds import LISTKINDS
from .listmodes import LISTMODES
from .nodes import NodeContext
from .audio import AudioIn, find_device
from . import hours as hours_mod
from . import journal as journal_mod
from . import body as body_mod
from .body import motion as motion_mod
from . import sound as sound_mod
from .sound.angles import sector_of
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
# Lot N1: state-change triggers the brain posts through `_changed` (anti-loop depth carried like var_changed).
CHANGE_EVENTS = frozenset({"media_started", "volume_changed", "mute_changed", "deaf_changed", "text_shown",
                           "text_cleared", "list_changed", "dict_changed", "timer_stopped", "journal_entry",
                           # lot N2 (trigger / condition parity with the actions)
                           "mic_opened", "mic_closed", "expression_changed", "gaze_changed", "song_started",
                           "answer_started", "conversation_cleared", "turn_counted", "list_item_added", "list_item_removed",
                           "face_count_changed",
                           # lot N3 (per-theme parity)
                           "speech_started", "voice_detected", "loud_noise", "var_reset", "var_bound_reached",
                           "random_drawn", "list_emptied", "list_filled", "dict_key_set", "dict_key_removed",
                           "dict_emptied", "schedule_cancelled",
                           # lot B1 (Mouvement)
                           "face_tracking_changed"})
JOURNAL_KEEP = 200        # robot journal entries kept for recent_error (wall time, level, source)
JOURNAL_POST_GAP_S = 0.2  # journal_entry from the log tap: at most one per 0.2 s (an error burst is one event)
NOTIFY_MAX = 20           # pending dashboard notifications kept (oldest dropped)
LOUD_LEVEL, LOUD_REARM = 0.6, 0.3   # lot N3 loud_noise: mic level (0..1) that fires it / that re-arms it
SOUND_EVENT_GAP_S, SOUND_REARM_S = 1.0, 0.5   # lot C2 sound_from_direction: min gap between posts / silence re-arm


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
                 threaded=True, start_state=None, var_store=None, body=None, sound=None):
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
        self._visitors_prev = None   # lot G3: {date, count} of the last finished day (log_state daily summary)
        self._graph = None
        self.rng = random.Random()
        # Lot N1: media playback, text shown by show_text, dashboard notifications, robot journal, server hooks.
        self._media = None            # media/ file play_media is playing (None = none)
        self._shown = None            # (text, until monotonic) of the last show_text still on screen
        self.notifications, self._notif_seq, self._notif_lock = [], 0, threading.Lock()
        self.journal_notes = collections.deque(maxlen=JOURNAL_KEEP)   # (wall epoch, level, "graph" | "robot")
        self._journal_post_at = -1e9
        self._watch = {}              # watch trigger id -> what the active graph listens to (subscribe())
        self.volume_hook = None       # server.py: fn(volume 0..1) through the speaker profile; None = out.volume
        self.flag_hook = None         # server.py: fn(key, value) persisting muted / deaf like the dashboard buttons
        # Lot N2: state behind the new triggers / conditions (see the N2 block of methods below).
        self._expr_last = "neutre"    # last expression posted by expression_changed (the `expression` system view)
        self._song_gen = None         # generation of the song being sung (is_singing); None = no song
        self._conv_since = None       # monotonic start of the current conversation (conversation_duration)
        self._event_at = {}           # event id -> monotonic time it was last handled (event_recent)
        # lot N3: robot sound edge + last phrase, loud-noise latch, wall-clock (date, hour), face absence, uptime.
        # Set before _build_engine: _load_persisted may already post vars_restored.
        self._out_busy_prev, self._spoke_at, self.last_said = False, None, ""
        self._loud, self._clock_prev = False, None
        self._faces_zero_since = self.now()
        self.started_at = self.now()
        # lot C3: the robot body (live one from server.py; otherwise in-memory simulated, never persisted)
        self.body = body if body is not None else body_mod.create(cfg)
        self._body_err_at = -1e9
        # lot C2: 360-degree sound (live tracker from server.py; otherwise in memory on this Brain's mic and clock)
        self.sound = sound if sound is not None else sound_mod.create(cfg, mic=self.mic, clock=self.now, wall=self.wall)
        self._sound_err_at, self._snd_seen, self._snd_sector, self._snd_posted_at = -1e9, -1e9, None, -1e9
        self.engine = self._build_engine()
        # lot B1: Mouvement nodes runtime (after the engine: its hook reads self._watch at post time)
        self.motion = motion_mod.MotionRuntime(self)
        self._motion_err_at = -1e9
        if self._threaded:
            journal_mod.attach(self)  # the live robot's WARNING / ERROR log records feed journal_notes
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
        """Number of faces the camera sees right now (called by the vision thread, or by the simulator).
        Lot N2: face_count_changed when the count changed (external: a sensor, depth 1 for the anti-loop)."""
        changed = n != self.faces
        self.faces = n
        if n > 0:
            self._faces_zero_since = None          # lot N3: no_face_since reads 0 while a face is seen
        elif self._faces_zero_since is None:
            self._faces_zero_since = self.now()
        if n > 0:
            self._activity()
        if changed:
            self._changed("face_count_changed", external=True, value=n)

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
            self._clock_tick()   # lot N3: hour_changed / day_changed
            table = hours_mod.safe_parse(self.cfg.get("opening_hours"))
            if table is None:
                self._open_prev = None   # empty / invalid hours: always open, no events
            else:
                is_open = hours_mod.is_open(table, self._wall_dt())
                if self._open_prev is not None and is_open != self._open_prev:
                    self.post("ouverture" if is_open else "fermeture")
                self._open_prev = is_open

    def _clock_tick(self):
        """Lot N3: hour_changed (value = the new hour 0..23) when the wall clock enters another hour, day_changed (value
        = the weekday id) when the date changes; checked every SENSOR_PERIOD_S, never at the first check."""
        dt = self._wall_dt()
        cur = (dt.date(), dt.hour)
        prev, self._clock_prev = self._clock_prev, cur
        if prev is None or prev == cur:
            return
        self.post("hour_changed", value=cur[1])
        if cur[0] != prev[0]:
            self.post("day_changed", value=self._weekday())

    def _audio_tick(self, now: float):
        """Lot N3 (heartbeat): speech_started on the rising edge of out.busy (a phrase, an answer, the song or a media),
        `_spoke_at` = last tick the speaker was busy (robot_quiet_since); loud_noise when the OPEN mic's level reaches
        LOUD_LEVEL, re-armed below LOUD_REARM (a closed / deaf mic reads 0). Sensor-like: external depth for the anti-loop."""
        busy = bool(self.out.busy)
        if busy:
            self._spoke_at = now
            if not self._out_busy_prev:
                self._changed("speech_started", external=True)
        self._out_busy_prev = busy
        level = float(self.mic.level) if self.mic.active else 0.0
        if not self._loud and level >= LOUD_LEVEL:
            self._loud = True
            self._changed("loud_noise", external=True, value=int(round(min(1.0, level) * 100)))
        elif self._loud and level < LOUD_REARM:
            self._loud = False

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

    def set_deaf(self, deaf: bool, external: bool = True, persist: bool = False):
        """Deaf mode (dashboard button, or the set_deaf action with external=False, persist=True); deaf_changed when
        the value changed. `external` (dashboard) counts as a depth-1 change for the anti-loop."""
        changed = bool(deaf) != bool(self.deaf)
        self.deaf = deaf
        if deaf:
            self.mic_set(False, external=external)
        elif self.state in (VEILLE, ECOUTE) or (self.state == RELANCE and not self.out.busy):
            self.mic_set(True, external=external)
        log.info("deaf=%s", deaf)
        if changed:
            if persist and self.flag_hook is not None:
                self.flag_hook("deaf", bool(deaf))
            self._changed("deaf_changed", external=external, value=bool(deaf))

    # ------------------------------------------------------------------ lot N1: controls, media, text, lists, journal
    def _changed(self, event: str, external: bool = False, name=None, **kw) -> bool:
        """Post a state-change trigger (CHANGE_EVENTS). A watch trigger (list_changed, dict_changed, timer_stopped,
        journal_entry) is posted only when an enabled transition listens to `name` (journal_entry: to any level).
        Anti-loop like var_changed: a change made while handling a change event posts nothing (logged once per
        event); an external change (dashboard, log tap) counts as depth 1, so its own chain cannot re-trigger."""
        if event in self._watch:
            sub = self._watch[event]
            if not sub or (name is not None and name not in sub):
                return False
        if name is not None:
            kw["name"] = name
        if external:
            self.post(event, depth=MAX_VAR_CASCADE, **kw)
            return True
        if self._var_depth >= MAX_VAR_CASCADE:
            if event not in self._cascade_logged:
                self._cascade_logged.add(event)
                log.warning("graph: %s dropped (cascade limit %d)", event, MAX_VAR_CASCADE)
            return False
        self.post(event, depth=self._var_depth + 1, **kw)
        return True

    def set_volume(self, volume: float, external: bool = False):
        """Speaker volume 0..1 (dashboard slider via server.py, set_volume action); volume_changed (value = the
        `volume` system variable, 0..100) when the audible value changed."""
        before = self.var_value("volume")
        v = min(1.0, max(0.0, float(volume)))
        if self.volume_hook is not None:
            self.volume_hook(v)       # live robot: stored in the current speaker's profile, applied to AudioOut
        else:
            self.out.volume = v
        after = self.var_value("volume")
        if after != before:
            self._changed("volume_changed", external=external, value=after)

    def set_muted(self, muted: bool, external: bool = False, persist: bool = False):
        """Mute (dashboard button via server.py, set_mute action): AudioOut keeps running but nothing is heard;
        muting silences what is playing. mute_changed when the value changed."""
        muted = bool(muted)
        if bool(self.out.muted) == muted:
            return
        self.out.muted = muted
        if muted:
            self.out.stop()
        log.info("muted=%s", muted)
        if persist and self.flag_hook is not None:
            self.flag_hook("muted", muted)
        self._changed("mute_changed", external=external, value=muted)

    @staticmethod
    def _read_wav(path: str):
        """16-bit PCM wav -> (mono int16 samples, rate); stereo is averaged."""
        import wave
        with wave.open(path) as w:
            if w.getsampwidth() != 2:
                raise ValueError("16-bit PCM expected")
            ch, rate = w.getnchannels(), w.getframerate()
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        if ch > 1:
            pcm = pcm[: len(pcm) // ch * ch].reshape(-1, ch).mean(axis=1).astype(np.int16)
        return pcm, rate

    def play_media(self, name: str):
        """play_media: a .wav of media/ (cfg `media_dir` overrides) through the speech output, so `muted` is honoured.
        media_started when it starts, media_finished when it ends (at once, with ok=False, when the file cannot be
        read); stop / hush / off (generation bump) cancel it without media_finished."""
        path = os.path.join(self.cfg.get("media_dir") or graph_mod.MEDIA_DIR, name)
        try:
            pcm, rate = self._read_wav(path)
        except Exception as e:
            # lot L27: journal entry here (graph_note: the live log tap must not add it twice)
            log.warning("play_media: %s not playable (%s)", name, type(e).__name__, extra={"graph_note": True})
            self.note_journal("warning", "graph")
            self.post("media_finished", gen=self.gen, file=name, ok=False, reason="unreadable")
            return
        gen = self.gen
        self._media_seq = getattr(self, "_media_seq", 0) + 1
        seq = self._media_seq
        self._media = name
        self.out.play(pcm, rate)
        log.info("media start file=%s s=%.1f", name, len(pcm) / max(1, rate))
        self._changed("media_started", file=name)
        if not self._threaded:   # simulator: the fake output's duration, like a spoken phrase
            self._schedule_at(self.now() + 0.15 + float(getattr(self.out, "dur", 1.0)), "media_finished")
            return

        def run():
            self._wait_audio(gen)
            if self._alive(gen) and self._media_seq == seq:   # a newer play_media owns the end event
                self.post("media_finished", gen=gen, file=name, ok=True)
        threading.Thread(target=run, daemon=True, name="media").start()

    def show_text(self, text: str, seconds: float):
        """show_text: the face's subtitle line shows `text` for `seconds` (text_shown now; text_cleared from the
        heartbeat when the time is up or when speech replaced it)."""
        self.subtitle = text
        self._shown = (text, self.now() + float(seconds))
        self._changed("text_shown")

    def text_displayed(self) -> bool:
        sh = self._shown
        return sh is not None and self.subtitle == sh[0] and self.now() < sh[1]

    def _text_tick(self, now: float):
        sh = self._shown
        if sh is None or (self.subtitle == sh[0] and now < sh[1]):
            return
        if self.subtitle == sh[0]:
            self.subtitle = ""
        self._shown = None
        self._changed("text_cleared")

    def list_copy(self, name: str):
        """Copy of a user list / dictionary before a node changes it (compare with list_touched)."""
        v = self.lists.get(name)
        return dict(v) if isinstance(v, dict) else list(v) if v is not None else None

    def list_touched(self, name: str, before) -> bool:
        """After a list / dictionary action: list_changed / dict_changed when the content really changed."""
        after = self.lists.get(name)
        if after == before and type(after) is type(before):
            return False
        if before and not after:   # lot N3: emptied (listened names only, like list_changed)
            self._changed("dict_emptied" if isinstance(after, dict) else "list_emptied", name=name)
        elif isinstance(after, list):
            li = self._graph.lists.get(name) if self._graph is not None else None
            if li is not None and li.maxlen and len(after) >= li.maxlen > len(before or ()):
                self._changed("list_filled", name=name, value=len(after))   # lot N3: reached its `max`
        return self._changed("dict_changed" if isinstance(after, dict) else "list_changed", name=name)

    def dict_key_events(self, name: str, before) -> None:
        """Lot N3, after dict_set / dict_remove: dict_key_set for a key added or whose value changed, dict_key_removed
        for a key that was present and is gone (value = the key); watch triggers, posted only for a listened dict."""
        after = self.lists.get(name)
        if not isinstance(after, dict) or not isinstance(before, dict):
            return
        for k, v in after.items():
            if k not in before or before[k] != v:
                self._changed("dict_key_set", name=name, value=k)
        for k in before:
            if k not in after:
                self._changed("dict_key_removed", name=name, value=k)

    def note_journal(self, level: str, source: str = "graph", external: bool = False):
        """One robot journal entry (log_note, or a WARNING / ERROR record of the live log via nanterino/journal.py:
        external=True, any thread). journal_entry is posted when a transition listens to it; a record logged by a
        chain a change event started (depth >= MAX_VAR_CASCADE, on the loop thread) is kept but posts nothing, and the
        log tap posts at most one event per JOURNAL_POST_GAP_S (an error burst must not flood the loop)."""
        self.journal_notes.append((self.wall(), level, source))
        if not self._watch.get("journal_entry"):
            return
        if external:
            on_loop = not self._threaded or threading.current_thread() is getattr(self, "_loop_thread", None)
            if on_loop and self._var_depth >= MAX_VAR_CASCADE:
                return
            now = self.now()
            if now - self._journal_post_at < JOURNAL_POST_GAP_S:
                return
            self._journal_post_at = now
        self._changed("journal_entry", external=external, value=level, source=source)

    def recent_error(self, seconds: float) -> bool:
        wall = self.wall()
        return any(lv == "error" and wall - t <= seconds for t, lv, _src in list(self.journal_notes))

    def notify(self, text: str, level: str) -> int:
        """notify_dashboard: a pending notification for the dashboard (GET /api/notifications, /api/status)."""
        with self._notif_lock:
            self._notif_seq += 1
            nid = self._notif_seq
            self.notifications.append({"id": nid, "t": round(self.wall(), 3), "text": text, "level": level})
            del self.notifications[:-NOTIFY_MAX]
        log.info("dashboard notification id=%d level=%s", nid, level)
        return nid

    def notifications_view(self) -> list:
        with self._notif_lock:
            return [dict(n) for n in self.notifications]

    def click_notification(self, nid) -> bool:
        """POST /api/notifications/click: the notification leaves the pending list, notification_clicked is posted."""
        with self._notif_lock:
            hit = next((n for n in self.notifications if n["id"] == nid), None)
            if hit is not None:
                self.notifications.remove(hit)
        if hit is None:
            return False
        self.post("notification_clicked", id=hit["id"], level=hit["level"])
        return True

    def _mic_on(self):
        """Every mic opening goes through here so the deaf mode can never be bypassed."""
        self.mic_set(True)

    # ------------------------------------------------------------------ lot N2: producers of the parity triggers
    def mic_set(self, on: bool, external: bool = False):
        """Open / close the microphone (mic_on / mic_off actions, deaf mode, _mic_on): mic_opened / mic_closed when its
        REAL state changed (an already open mic posts nothing). Opening never bypasses the deaf mode."""
        before = bool(self.mic.active)
        if on:
            if self.deaf:
                return
            self.mic.start()
        else:
            self.mic.stop()
        after = bool(self.mic.active)
        if after != before:
            self._changed("mic_opened" if after else "mic_closed", external=external)

    def set_expression(self, name: str, seconds: float):
        """set_expression: the face shows `name` for `seconds`; expression_changed when the visible expression changed
        (and again from the heartbeat when it expires back to « neutre », see _expr_tick)."""
        self._expression = (name, self.now() + float(seconds))
        self._expr_tick()

    def _expr_tick(self):
        cur = self.var_value("expression")
        if cur != self._expr_last:
            self._expr_last = cur
            self._changed("expression_changed", value=cur)

    def set_gaze(self, mode: str):
        """gaze action, and the return to « suivre » on entry into veille / eteint: gaze_changed when it changed."""
        if mode == self.gaze_mode:
            return
        self.gaze_mode = mode
        self._changed("gaze_changed", value=mode)

    def start_song(self):
        """start_sing: song_started now, song_finished (then answer_done, as before) when the song ends; stop / hush /
        off (generation bump) cancel it without song_finished, and is_singing is false from then on."""
        self._song_gen = self.gen
        self._changed("song_started")
        if not self._threaded:   # simulator: the song "lasts" SIM_SONG_S virtual seconds
            self._schedule_at(self.now() + SIM_SONG_S, "song_finished")
            self._schedule_at(self.now() + SIM_SONG_S, "answer_done")
            return
        threading.Thread(target=self._sing, args=(self.gen,), daemon=True).start()

    def is_singing(self) -> bool:
        return self._song_gen is not None and self._song_gen == self.gen

    def list_item_event(self, event: str, name: str, before, value) -> bool:
        """list_add / remember_utterance / list_remove: list_item_added / list_item_removed (watch triggers: posted only
        for a listened list) when the list content really changed."""
        after = self.lists.get(name)
        if after == before and type(after) is type(before):
            return False
        return self._changed(event, name=name, value=value)

    def scheduled_pending(self, event: str) -> bool:
        """A `schedule` of `event` still waits (and will fire: not cancelled by a stop / off since)."""
        with self._sched_lock:
            return any(x[1] == event and x[2] == self.gen for x in self._scheduled)

    def event_age(self, event: str):
        """Seconds since `event` was last handled (posted events and `emit`), None = never since the start."""
        t = self._event_at.get(event)
        return None if t is None else self.now() - t

    def conversation_age(self):
        """Seconds since the current conversation started (exit from veille / eteint), None outside a conversation."""
        return None if self._conv_since is None else self.now() - self._conv_since

    # ------------------------------------------------------------------ cancellation
    def _cancel_all(self):
        """Silence now and invalidate every running speak/answer thread."""
        self.gen += 1
        self._media = None   # lot N1: a cancelled play_media posts no media_finished
        self.out.stop()

    def _alive(self, gen: int) -> bool:
        return gen == self.gen

    # ------------------------------------------------------------------ audio callbacks
    def _on_speech_start(self):
        self._changed("voice_detected", external=True)   # lot N3 (mic thread: external path only posts)
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
        # Lot N2: conversation_started / conversation_ended (plain posts, no anti-loop depth: a state move is never
        # dropped, like `visage`); the start time feeds conversation_duration.
        idle_before, idle_after = self.state in (VEILLE, ETEINT), state in (VEILLE, ETEINT)
        if idle_before and not idle_after:
            self._conv_since = self.now()
            self.post("conversation_started")
        elif not idle_before and idle_after:
            self._conv_since = None
            self.post("conversation_ended")
        self.state, self.since = state, self.now()
        if state in (VEILLE, ETEINT):
            self.set_gaze("suivre")   # a `gaze` command lasts for one conversation (lot N2: gaze_changed)
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
        # lot N1: list_changed / dict_changed / timer_stopped / journal_entry are posted only when listened to
        self._watch = {k: n.subscribe(graph) for k, n in nodes.TRIGGERS.items()
                       if n.args and k not in ("var_changed", "timer_reached")}
        self._load_persisted(graph)

        # ---- actions (lot M1, 2026-11-01): one module per action (nanterino/nodes/actions/<id>.py), bound here.
        # The engine calls fn(kw, **args); each call gets a NodeContext with THIS brain and the cfg / graph captured now
        # (as the former closures did), so an old engine finishing its `then` actions after a pending-graph swap still
        # works on the graph it was built from. Brain attributes are looked up at call time (tests wrap methods).
        # Lot M4: arguments of graph.PRE_RESOLVE_KINDS (numbers, optional texts) are read by the node code without
        # _resolve: a value source given there is evaluated here first. The other property fields go through _resolve.
        pre_kinds = graph_mod.PRE_RESOLVE_KINDS

        def bind(node, entry):
            pre = tuple(a for a, d in node.args.items() if d.kind in pre_kinds)

            def call(kw, **args):
                for a in pre:
                    if properties.is_property(args.get(a)):
                        args[a] = properties.evaluate(self, kw, args[a])
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

    def _schedule_at(self, due: float, event: str, **kw):
        # entries are (due, event, gen) or, with event fields (lot L27: ok / reason), (due, event, gen, kw)
        with self._sched_lock:
            self._scheduled.append((due, event, self.gen, kw) if kw else (due, event, self.gen))

    def complete_silently(self, action: str, done_event: str, reason: str):
        """Lot L27: a speaking action with nothing to say (empty list, missing key, empty variable...) still ends.

        Invariant: every speaking action posts its completion event, so a chain that waits for it (say_done,
        list_item_said, the `done` of speak_phrase) never traps the robot in a state. The event carries ok=False and
        `reason`; it is delayed like a zero-length phrase (0.15 s, the same margin as _wait_audio) so a state that
        re-enters itself on that event cannot spin the loop. One journal warning (log + Brain.journal_notes) lets the
        editor diagnostics see it; graph_note keeps the live log tap from adding it a second time."""
        log.warning("%s: %s, nothing said (%s still posted)", action, reason, done_event, extra={"graph_note": True})
        self.note_journal("warning", "graph")
        self._schedule_at(self.now() + 0.15, done_event, ok=False, reason=reason)

    def _speak_then(self, text: str, done_event: str):
        self.subtitle = text
        self.last_said = text   # lot N3: said_contains
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
        journal_mod.detach(self)
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
        if kind == "media_finished":
            self._media = None   # lot N1: media_playing is false from here on
        elif kind == "song_finished":
            self._song_gen = None   # lot N2: is_singing is false from here on
        self._event_at[kind] = self.now()   # lot N2: event_recent
        if isinstance(kw.get("text"), str):
            self.last_text = kw["text"]     # `$utterance` of the variable conditions / actions
        self._var_depth = kw.get("depth", 0) if kind in graph_mod.WATCH_EVENTS or kind in CHANGE_EVENTS else 0   # anti-loop (L1, L11, N1)
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
            if self._visitors["date"]:        # lot G3: keep the finished day for the midnight summary (log_state)
                self._visitors_prev = dict(self._visitors)
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
                old = self.vars.get(n)
                self.vars[n] = v.value
                if old != v.value:   # lot N3: var_reset (listened variables only)
                    self._changed("var_reset", name=n, value=v.value)
        for n, li in graph.lists.items():
            if li.scope == scope and not li.source:
                self.lists[n] = _fresh_items(li)
                self._bags.pop(n, None)

    def reset_var(self, name: str, external: bool = True) -> bool:
        """Variable manager button: initial value back, saved value forgotten. False for an unknown / read-only name."""
        g = self._graph
        if g is None:
            return False
        old = self.vars.get(name)
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
        if part == "names" and old != self.vars[name]:
            # lot N3: var_reset (dashboard manager = external; the reset_var action passes external=False)
            self._changed("var_reset", external=external, name=name, value=self.vars[name])
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
        restored = 0   # lot N3: vars_restored when at least one saved value was read back
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
                restored += 1
        for n, li in graph.lists.items():
            e = data.get("lists", {}).get(n) if li.persist and not li.source else None
            if e is None:
                continue
            items = e.get("items") if isinstance(e, dict) else None
            if not isinstance(e, dict) or e.get("type") != li.type or e.get("kind", "list") != li.kind:
                self._ignore_persisted("lists", n, e, "type changed")
                continue
            items_back = LISTKINDS[li.kind].restore(graph, li, items)   # lot M3: per-item type check in the kind module
            if items_back is None:
                self._ignore_persisted("lists", n, e, "invalid items")
                continue
            self.lists[n] = items_back
            restored += 1
        for key in self._persist_keys():
            self._persist_seen[key] = self._persist_entry(*key)   # what is in memory now is not a change to write
        self._persist_seen[("system", "nb_visiteurs_jour")] = dict(self._visitors)
        if restored:
            self.post("vars_restored", value=restored)   # lot N3 (plain post: processed after the boot / reload)

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
        """A literal, `$utterance` (the sentence being handled, else the last one heard), `$<variable>` or (lot M4) a
        compiled value source `{get: ...}` (nanterino/properties: typed result, fallbacks, never raises)."""
        if isinstance(value, dict) and "get" in value:
            return properties.evaluate(self, kw, value)
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
        var = self._graph.variables.get(name) if self._graph is not None else None
        if (var is not None and isinstance(value, (int, float)) and not isinstance(value, bool)
                and any(lim is not None and value == lim for lim in (var.vmin, var.vmax))):
            self._changed("var_bound_reached", name=name, value=value)   # lot N3 (listened variables only)
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
            self._text_tick(now)       # lot N1: text_cleared
            self._expr_tick()          # lot N2: expression_changed when a set_expression expires
            self._audio_tick(now)      # lot N3: speech_started, loud_noise, robot_quiet_since
            self._persist_tick(now)    # lot L11: persisted variables -> var_store
            self.engine.tick(now)
        except Exception:
            if now - self._tick_err_at > 5:  # a systematic bug must not flood the log at 10 Hz
                self._tick_err_at = now
                log.exception("tick handling failed")
        try:
            self.body.tick(now)          # lot C3: motors / sim backend, after the graph (no graph event posted)
        except Exception:
            if now - self._body_err_at > 5:
                self._body_err_at = now
                log.exception("body tick failed")
        try:
            self.motion.tick(now)        # lot B1: gesture steps, base odometry, face tracking (after the body)
        except Exception:
            if now - self._motion_err_at > 5:
                self._motion_err_at = now
                log.exception("motion tick failed")
        try:
            self._sound_tick(now)        # lot C2: 360-degree sound, after the body (mono never posts)
        except Exception:
            if now - self._sound_err_at > 5:
                self._sound_err_at = now
                log.exception("sound tick failed")

    def _sound_tick(self, now: float):
        """Lot C2 (heartbeat): poll brain.sound; post sound_from_direction (value = sector of angles.SECTORS, plus
        azimuth / level_db / confidence) on a confident sound onset or sector change, only when listened to and not deaf.
        Anti-burst: at most one post per SOUND_EVENT_GAP_S; the same sector posts again only after SOUND_REARM_S
        without any direction. Sensor-like: external depth for the anti-loop."""
        self.sound.poll(now)
        sub = self._watch.get("sound_from_direction")
        if not sub or self.deaf:
            return
        d = self.sound.direction()
        if d is None:
            if now - self._snd_seen > SOUND_REARM_S:
                self._snd_sector = None
            return
        self._snd_seen = now
        sector = sector_of(d["azimuth_deg"])
        if sector == self._snd_sector or now - self._snd_posted_at < SOUND_EVENT_GAP_S:
            return
        self._snd_sector, self._snd_posted_at = sector, now
        if "*" in sub or sector in sub:
            self._changed("sound_from_direction", external=True, value=sector, azimuth=d["azimuth_deg"],
                          level_db=d["level_db"], confidence=d["confidence"])

    def _release_scheduled(self, now: float):
        with self._sched_lock:
            due = [x for x in self._scheduled if x[0] <= now]
            self._scheduled = [x for x in self._scheduled if x[0] > now]
        for x in due:
            event, gen = x[1], x[2]
            self.post(event, gen=gen, **(x[3] if len(x) > 3 else {}))  # dropped by the loop if a stop/off bumped gen meanwhile
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

    @staticmethod
    def song_path() -> str:
        """The pre-built song (song/build_song.py); lot N3 song_available reads its presence."""
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "media", "chanson-nanterino.wav")

    def _sing(self, gen: int):
        """Play the pre-built song (song/build_song.py) with line-by-line subtitles."""
        import json
        import wave
        path = self.song_path()
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
                self.post("song_finished", gen=gen, ok=False)   # lot N2 (like media_finished of an unreadable file)
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
            self.post("song_finished", gen=gen, ok=True)   # lot N2: before answer_done (is_singing false in its chain)
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
                self.last_said = " ".join(full)   # lot N3: said_contains (the answer so far)
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
