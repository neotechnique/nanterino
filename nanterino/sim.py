"""Fake engines + graph simulator (logging: robotlog via nanterino.log).

Purpose
    1. The fake world used by the tests (fake microphone, speaker, TTS, STT, LLM, corpus, trace recorder),
       moved here from tests/test_brain_graph.py so the editor's "Tester" mode and the test-suite share ONE
       implementation (the tests import these names; trace parity is unchanged).
    2. `simulate()`: run a graph given as a raw dict in an ISOLATED Brain (no audio, no microphone, no thread,
       a manual clock) and return what happened: the chains that fired, the state changes, the effects.

Boundary
    - Nothing here touches the live robot: the simulated Brain gets its own cfg copy, an in-memory Graph (no
      file is read or written), fake devices and its own queue. The live `Brain`, `config.json`, `graph.yaml`
      and the sound output are never reached. `simulate()` takes the cfg as an argument, it never imports
      config or server.
    - Time is virtual: `wait_s` steps advance a manual monotonic clock in 0.1 s ticks, calling the same
      `Brain._on_tick` the 10 Hz heartbeat calls; speaking / answering / singing take fixed virtual durations
      (SPEAK_S, brain.SIM_ANSWER_S, brain.SIM_SONG_S).
    - Lot L1 (variables): every trace entry carries `vars` (values after its step, system variables included) and
      `final.vars`; `say_random` uses the brain's rng seeded with 0.
    - Lot L11 (variables v2): time conditions, timers and `timer_reached` read the simulated wall clock
      (`start_time` + virtual seconds), never the real one; the simulator has no var_store (persist = memory only).
      Without `start_time` the wall-clock system views (heure, jour) are left out of `vars`, so two runs with the
      same steps still give the same result.

Invariants
    - Lot B1: the result carries `body` (brain.motion.snapshot() of the simulated body after the last step).
    - Same inputs give the same trace (no real time, no randomness, no threads).
    - At most MAX_STEPS steps and MAX_VIRTUAL_S virtual seconds per call; an event loop in the graph is cut
      after 5000 events and reported as an error.
    - `cfg` overrides are limited to CFG_OVERRIDES keys.

How to test
    python -m tests.test_graph_features   (simulator cases)  /  python -m tests.test_brain_graph (fakes)
"""
import copy
import datetime
import threading
import time

import numpy as np

from . import graph as G
from .brain import Brain

PHRASE_KEYS = ("greeting", "relance", "goodbye", "repair_text")
SPEAK_S = 1.5                  # virtual duration of one spoken phrase
TICK_S = 0.1                   # virtual heartbeat period
MAX_STEPS, MAX_VIRTUAL_S = 100, 3600
CFG_OVERRIDES = ("auto_greet_on_face", "barge_in", "silence_relance_s", "silence_cloture_s", "cloture_to_veille_s",
                 "opening_hours", "idle_long_s", "refusal_words")


# ---------------------------------------------------------------- fake world (shared with the tests)
class Rec:
    """Thread-safe append-only trace."""

    def __init__(self):
        self.events, self._lock = [], threading.Lock()

    def add(self, *e):
        with self._lock:
            self.events.append(list(e))


class FakeIn:
    def __init__(self, rec, *a, **k):
        self.rec, self.active, self.level = rec, False, 0.0

    def start(self):
        self.rec.add("mic", "on"); self.active = True

    def stop(self):
        self.rec.add("mic", "off"); self.active = False


class FakeOut:
    """Output that is 'busy' for `dur` seconds after play(); hold mode = long dur until release().

    `clock` defaults to real time (tests); the simulator passes its manual clock.
    """
    level, muted, preroll_ms, last_play_preroll = 0.0, True, 0, False

    def __init__(self, rec, tts, clock=time.monotonic):
        self.rec, self.tts, self.dur, self.song_dur, self._until = rec, tts, 0.1, 0.25, 0.0
        self.keys = {}
        self.clock = clock

    def play(self, pcm, rate):
        if len(pcm) > 100:
            label, d = "song", (self.dur if self.dur > 1 else self.song_dur)
        else:
            text = self.tts.texts[int(pcm[0])]
            label, d = self.keys.get(text, text), self.dur
        self.rec.add("play", label)
        self._until = self.clock() + d

    def stop(self):
        self.rec.add("cancel"); self._until = 0.0

    def release(self):
        self._until = 0.0

    @property
    def busy(self):
        return self.clock() < self._until


class FakeTTS:
    rate = 22050

    def __init__(self):
        self.texts = []

    def synth(self, text):
        if text not in self.texts:
            self.texts.append(text)
        return np.full(4, self.texts.index(text), dtype=np.int16)


class FakeSTT:
    prompt = ""

    def __init__(self):
        self.text = ""

    def transcribe(self, pcm):
        return self.text


class FakeLLM:
    def __init__(self, rec):
        self.rec, self.delay = rec, 0.05

    def sentences(self, messages):
        self.rec.add("llm")
        for s in ("Réponse un.", "Réponse deux.", "Réponse trois."):
            time.sleep(self.delay)
            yield s

    def simulate_answer(self):
        """Simulator only: a non-threaded Brain does not iterate sentences(), it just records the start."""
        self.rec.add("llm")


class FakeCorpus:
    sheets = []

    def search(self, *a, **k):
        return []


# ---------------------------------------------------------------- simulator
class SimError(Exception):
    """Invalid simulation request; `.errors` = [{"step": index | None, "message": str}] (French)."""

    def __init__(self, errors):
        super().__init__("; ".join(e["message"] for e in errors))
        self.errors = errors


class SimClock:
    """Manual monotonic clock (starts away from 0 so `now - base` arithmetic behaves like the real one)."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _check_steps(steps, graph) -> list:
    errs, total = [], 0.0
    if not isinstance(steps, list):
        return [{"step": None, "message": "`steps` doit être une liste."}]
    if len(steps) > MAX_STEPS:
        errs.append({"step": None, "message": "Trop d'étapes (%d au plus)." % MAX_STEPS})
    intent_events = {"intent." + i.name for i in graph.intents} | {"intent.question"}
    for i, st in enumerate(steps[:MAX_STEPS]):
        if not isinstance(st, dict) or len(st) != 1:
            errs.append({"step": i, "message": "Une étape est {\"event\":...}, {\"say\":...}, {\"wait_s\":...} ou {\"faces\":...}."})
            continue
        (k, v), = st.items()
        if k == "event":
            if v == "var_changed" or not (v in G.EVENTS - G.INTERNAL_EVENTS or v in intent_events):
                errs.append({"step": i, "message": "Événement inconnu : %r." % (v,)})
        elif k == "say":
            if not (isinstance(v, str) and v.strip()):
                errs.append({"step": i, "message": "« say » attend un texte."})
        elif k == "wait_s":
            if not (isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v <= MAX_VIRTUAL_S):
                errs.append({"step": i, "message": "« wait_s » attend un nombre de secondes entre 0 et %d." % MAX_VIRTUAL_S})
            else:
                total += v
        elif k == "faces":
            if not (isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 20):
                errs.append({"step": i, "message": "« faces » attend un entier entre 0 et 20."})
        else:
            errs.append({"step": i, "message": "Étape inconnue : %r." % (k,)})
    if total > MAX_VIRTUAL_S:
        errs.append({"step": None, "message": "Trop de temps simulé (%d s au plus)." % MAX_VIRTUAL_S})
    return errs


def _effect(e) -> str | None:
    return None if e[0] == "go" else " ".join(str(x) for x in e)


def simulate(raw_graph: dict, cfg: dict, start_state: str = "veille", steps=(), start_time: str | None = None,
             overrides: dict | None = None) -> dict:
    """Run `steps` against `raw_graph` in an isolated Brain. Returns {"trace": [...], "final": {...}}.

    Raises graph.GraphError (invalid graph) or SimError (invalid steps / options / event loop).
    """
    cfg2 = dict(cfg)
    cfg2.update(auto_greet_on_face=True, power="on")   # the simulated visitor is meant to be greeted
    for k, v in (overrides or {}).items():
        if k not in CFG_OVERRIDES:
            raise SimError([{"step": None, "message": "Réglage non simulable : %r." % (k,)}])
        cfg2[k] = v
    graph = G.parse_graph(copy.deepcopy(raw_graph), cfg2, "<simulate>")
    if start_state not in graph.states:
        raise SimError([{"step": None, "message": "État de départ inconnu : %r." % (start_state,)}])
    if not isinstance(steps, (list, tuple)):
        raise SimError([{"step": None, "message": "`steps` doit être une liste."}])
    steps = list(steps)
    errs = _check_steps(steps, graph)
    if errs:
        raise SimError(errs)
    try:
        wall0 = datetime.datetime.fromisoformat(start_time).timestamp() if start_time else time.time()
    except (TypeError, ValueError):
        raise SimError([{"step": None, "message": "start_time doit être une date ISO (AAAA-MM-JJTHH:MM)."}])

    clock = SimClock()
    t0 = clock.t
    rec, tts = Rec(), FakeTTS()
    out = FakeOut(rec, tts, clock)
    out.dur = SPEAK_S
    out.keys = {cfg2[k]: k for k in PHRASE_KEYS if cfg2.get(k)}
    marks, cur = [], {"step": -1}            # (journal entry, number of recorded effects when it started, step)

    brain = Brain(cfg2, out, FakeSTT(), FakeLLM(rec), tts, FakeCorpus(), clock=clock,
                  wall=lambda: wall0 + (clock.t - t0), mic=FakeIn(rec), graph=graph, threaded=False,
                  start_state=start_state)
    brain.rng.seed(0)                                     # say_random: same inputs, same trace
    marks.extend((e, 0, -1) for e in brain.journal)       # chains fired by the boot entry itself (emit in on_enter)
    step_vars = {}                                        # step -> variable values after it (lot L1)
    volatile = bool(start_time)                           # lot L11: heure / jour only with a fixed start time
    brain.journal_hook = lambda e: marks.append((e, len(rec.events), cur["step"]))

    def tick_for(seconds):
        for _ in range(max(1, int(round(seconds / TICK_S)))):
            clock.t += TICK_S
            brain._on_tick({"t": clock.t})
            brain.pump()

    try:
        brain.pump()
        step_vars[-1] = brain.var_snapshot(volatile)
        for i, st in enumerate(steps):
            cur["step"] = i
            (k, v), = st.items()
            if k == "event":
                brain.post(v)
            elif k == "say":
                brain._on_utterance(np.zeros(160, np.int16), brain.now(), text=v)
            elif k == "faces":
                brain.set_faces(v)
            if k == "wait_s":
                tick_for(v)
            else:
                brain.pump()
            step_vars[i] = brain.var_snapshot(volatile)
    except RuntimeError as e:
        raise SimError([{"step": cur["step"], "message": str(e)}])

    trace = [{"step": -1, "t": 0.0, "event": None, "from": None, "to": start_state, "moved": False, "reason": "start",
              "chain": start_state + "/enter", "actions": [c.label() for c in graph.states[start_state].on_enter],
              "effects": [x for x in map(_effect, rec.events[:marks[0][1] if marks else len(rec.events)]) if x],
              "vars": step_vars.get(-1)}]
    for n, (e, at, step) in enumerate(marks):
        end = marks[n + 1][1] if n + 1 < len(marks) else len(rec.events)
        trace.append({"step": step, "t": round(e["mono"] - t0, 2), "event": e["event"], "from": e["from"],
                      "to": e["to"], "moved": e["moved"], "reason": e["reason"], "chain": e["chain"],
                      "actions": list(e["actions"]), **({"conflict": True} if e.get("conflict") else {}),
                      "effects": [x for x in map(_effect, rec.events[at:end]) if x], "vars": step_vars.get(step)})
    snap = brain.snapshot()
    # lot B1 (additive key, outside `final`): the SIMULATED body after the last step (positions in logical units,
    # estop, gesture / base move in progress); the live body is never touched by a simulation.
    return {"trace": trace, "final": {"state": brain.state, "turns": brain.turns,
                                      "expression": snap["expression"], "gaze_mode": snap["gaze_mode"],
                                      "vars": brain.var_snapshot(volatile)},
            "body": brain.motion.snapshot()}
