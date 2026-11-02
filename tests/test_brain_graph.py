"""Brain transition-trace parity test (baseline of the YAML state graph refactor).

Purpose: drive the real `nanterino.brain.Brain` with fake STT / LLM / TTS / AudioIn / AudioOut and
record a deterministic *trace* per scenario: every `_go(state, reason)`, every mic on/off, every
played clip (by phrase key), LLM answer start, cancel (out.stop) and a few state snapshots.
`tests/brain-trace-baseline.json` holds the traces of the hard-coded state machine; after the
refactor the same scenarios must give identical traces.

Boundary: only public-ish seams are used (Brain constructor, post(), _on_utterance(),
_on_speech_start(), _go wrapper, module attrs AudioIn/find_device). No hardware, no network, muted by
construction (fake output). Time is REAL but scaled: timers are shortened through cfg
(silence_relance_s ...), and every step waits for a quiet period, so traces carry no timestamps.

Invariants: traces must not depend on thread timing (each scenario is run twice when recording).
Known, documented divergence: `ask` typed while in veille now goes through `_go` (see
normalize_new); that pair of trace lines is dropped from the new trace before comparing.

Re-baseline (lot G1, 2026-11-02): when the SHIPPED graph changes behaviour on purpose, never re-record the whole
file blindly. Run the changed / new scenarios with `--only a,b --out /tmp/x.json` (twice: identical output), review
each diff and write one line per changed scenario in tests/golden/behaviour-changes-<lot>.md, keep the previous file
as tests/golden/brain-trace-baseline.pre-<lot>.json, then merge the reviewed traces into brain-trace-baseline.json
(json.dump(..., ensure_ascii=False, indent=0, sort_keys=True)). G1 changed no existing trace and added 3 scenarios.
G2 (2026-11-02) changed no existing trace either and added 4 (g2_*); since G2 the brain's rng is seeded (H), because the
shipped graph draws at random (greeting choice, shuffle bags).
G3 (2026-11-02) changed one existing trace on purpose (not_understood_x3: the help phrase at the repair bound) and added
10 (g3_*); previous file tests/golden/brain-trace-baseline.pre-g3.json, review in tests/golden/behaviour-changes-G3.md.

How to run (repo root, venv python; pytest is not installed):
    python -m tests.test_brain_graph --record     # write the baseline trace (old brain only)
    python -m tests.test_brain_graph              # compare with the baseline (+ graph tests if present)
    python -m tests.test_brain_graph --only a,b   # subset;  --out FILE  write the traces elsewhere
"""
import datetime
import functools
import json
import logging
import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, "/opt/robot/lib")
from robotlog import get_logger  # noqa: E402

from nanterino import brain as brain_mod  # noqa: E402
from nanterino import config  # noqa: E402
from nanterino.log import log as nlog  # noqa: E402  (G3 journal summary scenario: the robot's own logger)
from nanterino.sim import FakeCorpus, FakeIn, FakeLLM, FakeOut, FakeSTT, FakeTTS, Rec  # noqa: E402,F401

log = get_logger("test_brain_graph")
HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.join(HERE, "brain-trace-baseline.json")

# Graph file the scenarios run on. Default: a path that does not exist, i.e. the packaged graph.yaml
# (hermetic: a live override in /opt/robot/nanterino/graph.yaml must not change test results).
# tests/test_graph_visual.py sets it to a COMPILED graph to rerun the same 68 traces on it.
GRAPH_FILE = os.environ.get("NANTERINO_TEST_GRAPH") or "/nonexistent/graph.yaml"

PHRASE_KEYS = ("greeting", "relance", "goodbye", "repair_text")
BASE_CFG = {
    "silence_relance_s": 3.0, "silence_cloture_s": 3.0, "cloture_to_veille_s": 0.3,
    "auto_greet_on_face": True, "barge_in": False, "power": "on", "deaf": False,
    "refusal_words": ["non merci", "stop", "au revoir", "arrête", "arrete"],
}


# The fake world (Rec, FakeIn, FakeOut, FakeTTS, FakeSTT, FakeLLM, FakeCorpus) lives in nanterino/sim.py, shared
# with the graph simulator of the editor's "Tester" mode; re-exported here under the same names.


class H:
    """One scenario run: fake world + a real Brain + step helpers."""

    def __init__(self, over):
        self.rec = Rec()
        cfg = dict(config.DEFAULTS); cfg.update(BASE_CFG); cfg["graph_file"] = GRAPH_FILE; cfg.update(over)
        self.cfg = cfg
        self.tts, self.stt = FakeTTS(), FakeSTT()
        self.out = FakeOut(self.rec, self.tts)
        self.out.keys = {cfg[k]: k for k in PHRASE_KEYS}
        self.llm = FakeLLM(self.rec)
        brain_mod.AudioIn = functools.partial(FakeIn, self.rec)
        brain_mod.find_device = lambda *a, **k: None
        self.brain = brain_mod.Brain(cfg, self.out, self.stt, self.llm, self.tts, FakeCorpus())
        # G2: the shipped graph draws at random (random_chance, say_random shuffle bags); a fixed seed makes every
        # trace reproducible (draws only happen on the brain loop thread, in event order). Same seed as sim.simulate.
        self.brain.rng.seed(0)
        orig = self.brain._go

        def go(state, reason):
            self.rec.add("go", self.brain.state, state, reason)  # recorded BEFORE the entry effects
            orig(state, reason)
        self.brain._go = go
        # boot is done when the phrases are ready and veille opened the mic (a deaf robot never opens it: G1)
        self.wait(lambda: len(self.brain._phrases) >= 4 and (self.rec.events or cfg.get("deaf")), 5)

    # -- helpers
    def wait(self, pred, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred():
                return True
            time.sleep(0.01)
        raise AssertionError("timeout waiting for condition; trace tail=%r" % (self.rec.events[-6:],))

    def wait_state(self, state, timeout=8.0):
        self.wait(lambda: self.brain.state == state, timeout)

    def settle(self, quiet=0.45, timeout=20.0):
        """Wait until the trace has been unchanged for `quiet` seconds."""
        last, t_last, end = -1, time.monotonic(), time.monotonic() + timeout
        while time.monotonic() < end:
            n = len(self.rec.events)
            if n != last:
                last, t_last = n, time.monotonic()
            elif time.monotonic() - t_last >= quiet:
                return
            time.sleep(0.02)
        raise AssertionError("never settled")

    def post(self, kind, **kw):
        self.brain.post(kind, **kw)

    def say(self, text):
        """Final transcript from the (fake) microphone path; text=None exercises the STT call."""
        if text is None:
            self.stt.text = "Où est la bibliothèque ?"
        self.brain._on_utterance(np.zeros(160, np.int16), time.monotonic(), text=text)

    def speech_start(self):
        self.brain._on_speech_start()

    def hold(self):
        self.out.dur = 30.0

    def unhold(self):
        self.out.dur = 0.1; self.out.release()

    def at(self, label):
        b = self.brain
        self.rec.add("at", label, b.state, bool(b.mic.active), b.turns, b.repairs, len(b.history))

    def close(self):
        trace = [list(e) for e in self.rec.events]
        stop = getattr(self.brain, "shutdown", None)
        if stop:
            stop()
        else:
            self.brain.post("off")  # old brain has no shutdown: park it in eteint (idle)
        return trace


SCENARIOS = {}


def sc(name, **over):
    def deco(fn):
        SCENARIOS[name] = (fn, over)
        return fn
    return deco


def reach(h, target):
    """Bring the brain to `target`; speaking states are held (fake output stays busy)."""
    if target == "veille":
        return
    if target == "eteint":
        h.post("off"); h.settle(); return
    if target == "accueil":
        h.hold(); h.post("start"); h.wait_state("accueil"); h.settle(); return
    h.post("start"); h.wait_state("ecoute"); h.settle()
    if target == "ecoute":
        return
    h.hold()
    if target == "reponse":
        h.say("Quelle heure ouvre le musée ?"); h.wait_state("reponse")
    elif target == "relance":
        h.say("euh"); h.wait_state("relance")
    elif target == "cloture":
        h.say("au revoir"); h.wait_state("cloture")
    h.settle()


STATES = ("veille", "accueil", "ecoute", "reponse", "relance", "cloture", "eteint")


def _matrix(state, action):
    @sc("%s_in_%s" % (action, state))
    def _(h):
        reach(h, state); h.at("reached")
        h.post(action); h.settle(); h.at("after_action")
        h.unhold(); h.settle(0.8); h.at("end")


for _s in STATES:
    for _a in ("stop", "off", "on", "hush"):
        _matrix(_s, _a)


@sc("boot_veille")
def _(h):
    h.settle(); h.at("end")


@sc("boot_power_off", power="off")
def _(h):
    h.settle(); h.at("end")


@sc("face_question_answer")
def _(h):
    h.post("visage"); h.settle(); h.at("after_greeting")
    h.say("Où est le parc ?"); h.settle(); h.at("after_answer")


@sc("start_default_source")
def _(h):
    h.post("start"); h.settle(); h.at("end")


@sc("start_custom_source")
def _(h):
    h.post("start", source="tap"); h.settle(); h.at("end")


@sc("start_from_eteint")
def _(h):
    h.post("off"); h.settle(); h.post("start"); h.settle(); h.at("end")


@sc("on_from_eteint")
def _(h):
    h.post("off"); h.settle(); h.post("on"); h.settle(); h.at("end")


@sc("start_in_ecoute_ignored")
def _(h):
    h.post("start"); h.settle(); h.post("start"); h.settle(); h.at("end")


@sc("visage_ignored_in_ecoute_and_eteint")
def _(h):
    h.post("start"); h.settle(); h.post("visage"); h.settle(); h.at("ecoute")
    h.post("off"); h.settle(); h.post("visage"); h.settle(); h.at("eteint")


@sc("timers_relance_cloture", silence_relance_s=0.6, silence_cloture_s=1.0)
def _(h):
    h.post("start"); h.wait_state("ecoute"); h.wait_state("relance", 6); h.settle(0.5); h.at("relance_done")
    h.wait_state("cloture", 6); h.wait_state("veille", 6); h.settle(); h.at("end")


@sc("au_revoir_in_ecoute")
def _(h):
    h.post("start"); h.settle(); h.say("Au revoir"); h.wait_state("veille"); h.settle(); h.at("end")


@sc("refusal_word_stop_in_ecoute")
def _(h):
    h.post("start"); h.settle(); h.say("stop"); h.wait_state("veille"); h.settle(); h.at("end")


@sc("refusal_in_relance")
def _(h):
    h.post("start"); h.settle(); h.say("euh"); h.wait_state("relance"); h.settle(); h.at("relance")
    h.say("non merci"); h.wait_state("veille"); h.settle(); h.at("end")


@sc("question_in_relance")
def _(h):
    h.post("start"); h.settle(); h.say("euh"); h.wait_state("relance"); h.settle()
    h.say("Où est le parc ?"); h.settle(); h.at("end")


@sc("sing_word_in_ecoute")
def _(h):
    h.post("start"); h.settle(); h.say("Tu peux chanter ?"); h.settle(0.6); h.at("end")


@sc("enchante_is_not_the_song")
def _(h):
    h.post("start"); h.settle(); h.say("Quel enchanteur, bravo"); h.settle(); h.at("end")


@sc("sing_ui_in_veille")
def _(h):
    h.post("sing"); h.settle(0.6); h.at("end")


@sc("sing_ui_in_eteint_ignored")
def _(h):
    h.post("off"); h.settle(); h.post("sing"); h.settle(); h.at("end")


@sc("sing_during_answer")
def _(h):
    reach(h, "reponse"); h.post("sing"); h.settle(0.6); h.at("sung")
    h.unhold(); h.settle(0.6); h.at("end")


@sc("sing_then_stop")
def _(h):
    h.hold(); h.post("sing"); h.wait_state("reponse"); h.settle(); h.at("singing")
    h.post("stop"); h.settle(); h.at("stopped"); h.unhold(); h.settle(0.6); h.at("end")


@sc("appel_word_in_veille")
def _(h):
    h.say("Bonjour Nanterino"); h.settle(); h.at("end")


@sc("veille_text_without_call_word_ignored")
def _(h):
    h.say("au revoir"); h.settle(); h.say("chante une chanson"); h.settle(); h.say("quelle heure"); h.settle(); h.at("end")


@sc("text_in_accueil_ignored")
def _(h):
    reach(h, "accueil"); h.say("Où est le parc ?"); h.settle(); h.at("end")


@sc("text_via_stt_path")
def _(h):
    h.post("start"); h.settle(); h.say(None); h.settle(); h.at("end")


@sc("phantom_text_rejected")
def _(h):
    h.post("start"); h.settle(); h.say("Sous-titres réalisés par la communauté d'Amara.org"); h.settle(); h.at("end")


@sc("not_understood_x3")
def _(h):
    h.post("start"); h.settle()
    for i in range(3):
        h.say("euh"); h.settle(); h.at("after_%d" % i)
    h.post("off"); h.settle()


@sc("not_understood_in_veille_ignored")
def _(h):
    h.say("euh"); h.settle(); h.at("end")


@sc("not_understood_while_speaking")
def _(h):
    reach(h, "relance"); h.say("euh"); h.settle(); h.at("end"); h.unhold(); h.settle(0.6)


@sc("repair_counter_reset_by_question")
def _(h):
    h.post("start"); h.settle()
    h.say("euh"); h.settle(); h.say("euh"); h.settle(); h.at("two_repairs")
    h.say("Où est le parc ?"); h.settle(); h.at("answered")
    h.say("euh"); h.settle(); h.at("repair_again")


@sc("max_turns")
def _(h):
    old = brain_mod.MAX_TURNS
    brain_mod.MAX_TURNS = 2
    try:
        h.post("start"); h.settle()
        for i in range(2):
            h.say("Question %d" % i); h.settle(); h.at("turn_%d" % i)
        # Third question exceeds MAX_TURNS -> cloture -> veille. No snapshot in between: the
        # cloture pause (~0.5 s) is as long as settle()'s quiet period, so it would race.
        h.say("Question 2"); h.wait_state("veille"); h.settle(); h.at("end")
    finally:
        brain_mod.MAX_TURNS = old


@sc("ask_veille_question")
def _(h):
    h.post("ask", text="Où est la mairie ?"); h.settle(); h.at("end")


@sc("ask_in_ecoute")
def _(h):
    h.post("start"); h.settle(); h.post("ask", text="Où est la mairie ?"); h.settle(); h.at("end")


@sc("ask_refusal_in_ecoute")
def _(h):
    h.post("start"); h.settle(); h.post("ask", text="stop"); h.wait_state("veille"); h.settle(); h.at("end")


@sc("ask_in_accueil_ignored")
def _(h):
    reach(h, "accueil"); h.post("ask", text="Où est la mairie ?"); h.settle(); h.at("end")


@sc("ask_in_eteint_ignored")
def _(h):
    h.post("off"); h.settle(); h.post("ask", text="Où est la mairie ?"); h.settle(); h.at("end")


@sc("barge_in_enabled", barge_in=True)
def _(h):
    reach(h, "reponse"); h.speech_start(); h.settle(); h.at("after_barge"); h.unhold(); h.settle(0.6)


@sc("barge_in_disabled", barge_in=False)
def _(h):
    reach(h, "reponse"); h.speech_start(); h.settle(); h.at("after_speech"); h.unhold(); h.settle(0.6); h.at("end")


@sc("barge_in_enabled_answer_keeps_mic", barge_in=True)
def _(h):
    h.post("start"); h.settle(); h.say("Où est le parc ?"); h.settle(); h.at("end")


@sc("stale_answer_done_ignored")
def _(h):
    reach(h, "reponse"); h.post("answer_done", gen=h.brain.gen - 1); h.settle(); h.at("stale")
    h.post("answer_done", gen=h.brain.gen); h.settle(); h.at("fresh"); h.unhold(); h.settle(0.6)


@sc("stop_during_cloture_pause", cloture_to_veille_s=1.0)
def _(h):
    h.post("start"); h.settle(); h.say("au revoir"); h.settle(0.45); h.at("pause")
    h.post("stop"); h.settle(); time.sleep(1.3); h.at("end")


# ---- lot G1 (2026-11-02): deaf robot (microphone forced off) never stays out of veille; see
# tests/golden/behaviour-changes-G1.md. Recorded into the baseline by merging (old traces untouched).
@sc("deaf_face_ignored_in_veille", deaf=True)
def _(h):
    h.post("visage"); h.settle(); h.at("end")


@sc("deaf_start_returns_to_veille", deaf=True, silence_relance_s=0.6, silence_cloture_s=1.0)
def _(h):
    h.post("start"); h.wait_state("relance", 6); h.settle(0.5); h.at("relance")
    h.wait_state("cloture", 6); h.wait_state("veille", 6); h.settle(); h.at("end")


@sc("deaf_question_then_silence", deaf=True, silence_relance_s=0.6, silence_cloture_s=1.0)
def _(h):
    h.post("start"); h.wait_state("ecoute"); h.post("ask", text="Où est le parc ?"); h.wait_state("reponse")
    h.wait_state("relance", 6); h.wait_state("veille", 8); h.settle(); h.at("end")


# ---- lot G2 (2026-11-02): richer greeting (conversation_started), opening hours; see
# tests/golden/behaviour-changes-G2.md. Seeded rng (H): the picks below are the same on every run.
@sc("g2_greetings_vary")
def _(h):
    for i in range(9):   # nine conversations: config greeting first, then the draws (varied phrases never repeat in a bag)
        h.post("start"); h.wait_state("ecoute"); h.settle(); h.at("greeted_%d" % i)
        h.post("stop"); h.wait_state("veille"); h.settle()


@sc("g2_group_greeting")
def _(h):
    h.brain.set_faces(2); h.settle()   # two visitors: personnes_multiples is posted after 1 s (no rule uses it)
    h.post("visage"); h.wait_state("ecoute"); h.settle(); h.at("group_greeted")


HOURS = {"lun-dim": "09:00-18:00"}


def _wall_at(h, hour):
    """Pin the brain's wall clock (opening hours read it) to a fixed local day at `hour`: never the real time."""
    t = datetime.datetime(2026, 11, 2, hour, 0).timestamp()
    h.brain.wall = lambda: t
    h.settle()


@sc("g2_face_outside_hours", opening_hours=HOURS)
def _(h):
    _wall_at(h, 20)
    h.post("visage"); h.settle(); h.at("closed")          # only a journal note, the robot stays in veille
    h.post("start"); h.wait_state("ecoute"); h.settle(); h.at("start_still_greets")


@sc("g2_face_inside_hours", opening_hours=HOURS)
def _(h):
    _wall_at(h, 10)
    h.post("visage"); h.wait_state("ecoute"); h.settle(); h.at("open")


# ---- lot G3 (2026-11-02): visitor left, voice / transcription aware relance, loud noise, journal summary, repair help;
# see tests/golden/behaviour-changes-G3.md. Real (scaled) time like every scenario: the 20 s without a face is set on
# the brain's own time base (_faces_zero_since, what no_face_since reads), the 11 s silence of the visitor-left rule is
# really waited (it is a graph constant, not a config delay). Faces: set_faces never posts `visage` (no auto greeting).
def _no_face_for(h, seconds):
    """The camera has seen no face for `seconds` already (no_face_since), without waiting for it."""
    h.brain.set_faces(0)
    h.brain._faces_zero_since = h.brain.now() - seconds


@sc("g3_visitor_left_in_ecoute")
def _(h):
    _no_face_for(h, 30)
    h.post("start"); h.wait_state("ecoute"); h.settle(); h.at("listening")
    time.sleep(4.0); h.at("no_relance_for_an_empty_room")     # silence_relance_s (3 s) passed: no relance
    h.wait_state("cloture", 12); h.wait_state("veille", 6); h.settle(); h.at("end")


@sc("g3_face_back_relances")
def _(h):
    _no_face_for(h, 30)
    h.post("start"); h.wait_state("ecoute"); h.settle()
    time.sleep(4.0); h.at("waiting")                          # relance held back: no face for 20 s
    h.brain.set_faces(1); h.wait_state("relance", 3); h.settle(); h.at("relanced")   # a face again: relance at once
    h.post("stop"); h.wait_state("veille"); h.settle()


@sc("g3_visitor_left_in_relance", silence_cloture_s=20.0)
def _(h):
    h.brain.set_faces(1)
    h.post("start"); h.wait_state("relance", 8); h.settle(); h.at("relance_open")   # a face: the usual relance
    _no_face_for(h, 30)                                       # ... then the visitor walks away
    h.wait_state("cloture", 14); h.wait_state("veille", 6); h.settle(); h.at("end")


@sc("g3_visitor_talking_is_not_cut")
def _(h):
    _no_face_for(h, 30)
    h.post("start"); h.wait_state("ecoute"); h.settle()
    time.sleep(8.0); h.speech_start(); h.at("voice")         # a voice off camera: the silence clock restarts
    time.sleep(1.0); h.brain._busy = True                     # ... and its utterance is being transcribed (slow STT)
    time.sleep(11.5); h.at("still_listening")                 # 12.5 s after the voice: not cut while transcribing
    h.brain._busy = False
    h.say("Où est le parc ?"); h.wait_state("reponse", 3); h.wait_state("ecoute", 5); h.settle(); h.at("answered")
    h.post("stop"); h.wait_state("veille"); h.settle()


@sc("g3_relance_voice_restarts_delay")
def _(h):
    h.brain.set_faces(1)
    h.post("start"); h.wait_state("relance", 8); h.settle()   # relance said, mic open again (relance_done)
    time.sleep(2.0); h.speech_start()
    time.sleep(2.0); h.at("voice_kept")                       # 4 s after relance_done (> 3 s) but 2 s after the voice
    h.wait_state("cloture", 4); h.wait_state("veille", 6); h.settle(); h.at("end")


@sc("g3_relance_waits_transcription")
def _(h):
    h.brain.set_faces(1)
    h.post("start"); h.wait_state("relance", 8); h.settle()
    h.speech_start(); time.sleep(0.5); h.brain._busy = True   # the visitor answers; the STT is slow
    time.sleep(4.0); h.at("busy_kept")                        # silence_cloture_s (3 s) passed during the transcription
    h.brain._busy = False
    h.say("Où est le parc ?"); h.wait_state("reponse", 3); h.wait_state("ecoute", 5); h.settle(); h.at("answered")
    h.post("stop"); h.wait_state("veille"); h.settle()


def _noise(h):
    """One loud noise on the open mic: level 0.7 for three heartbeat ticks, then quiet (loud_noise re-arms below 0.3)."""
    h.brain.mic.level = 0.7; time.sleep(0.3)
    h.brain.mic.level = 0.0; time.sleep(0.3)


def _var(h, name):
    h.rec.add("var", name, h.brain.vars.get(name))


@sc("g3_loud_noise_bounded")
def _(h):
    h.brain.set_faces(1)
    h.post("start"); h.wait_state("ecoute"); h.settle()
    time.sleep(1.5); _noise(h); _var(h, "bruits_forts")        # 1st noise: silence delay restarted
    time.sleep(1.5); _noise(h); _var(h, "bruits_forts")        # 2nd: restarted again (bound reached)
    h.at("two_noises")                                         # > 3 s in ecoute, still listening
    time.sleep(1.0); _noise(h); _var(h, "bruits_forts")        # 3rd: only a note, the delay keeps running
    h.wait_state("relance", 4); h.settle(); h.at("relanced")
    h.post("stop"); h.wait_state("veille"); h.settle(); _var(h, "bruits_forts")   # conversation scope: back to 0


def _wall_dt(h, *dt):
    t = datetime.datetime(*dt).timestamp()
    h.brain.wall = lambda: t


SUMMARY_KEYS = ("etat", "visiteurs_jour", "visiteurs_veille", "erreurs_24h", "avertissements_24h")


def _summary(msg):
    """The counters of a log_state line (or the midnight note), never anything a visitor said."""
    if msg.startswith("graph note: Nouveau jour"):
        return "note nouveau jour"
    fields = dict(p.split("=", 1) for p in msg[len("graph state: "):].replace(" (", "_(").split(" ") if "=" in p)
    return " ".join("%s=%s" % (k, fields.get(k)) for k in SUMMARY_KEYS)


@sc("g3_journal_summary")
def _(h):
    lines = []
    handler = logging.Handler()
    handler.emit = lambda r: lines.append(r.getMessage())
    nlog.addHandler(handler)
    try:
        _wall_dt(h, 2026, 11, 2, 10, 0, 5); time.sleep(1.3)     # the clock check has seen 10:00 (first check: no event)
        h.post("start"); h.wait_state("ecoute"); h.post("stop"); h.wait_state("veille"); h.settle()   # 1 visitor today
        _wall_dt(h, 2026, 11, 2, 11, 0, 5); time.sleep(1.3)     # hour_changed 11: hourly state line
        _wall_dt(h, 2026, 11, 3, 0, 0, 5); time.sleep(1.3)      # midnight: hour 0 skipped, day_changed: note + line
    finally:
        nlog.removeHandler(handler)
    for m in lines:
        if m.startswith("graph state:") or m.startswith("graph note: Nouveau jour"):
            h.rec.add("journal", _summary(m))


@sc("g3_repair_help_in_relance")
def _(h):
    h.post("start"); h.settle()
    for i in range(2):
        h.say("euh"); h.settle(); h.at("repeat_%d" % i)      # two « répétez » (relance)
    h.say("euh"); h.settle(); h.at("help")                    # bound: one help phrase, mic closed then reopened
    h.say("euh"); h.settle(); h.at("silent_after_help")       # later ones: silent
    h.post("stop"); h.wait_state("veille"); h.settle()


@sc("g3_repair_help_in_ecoute")
def _(h):
    h.post("start"); h.settle()
    h.say("euh"); h.settle(); h.say("euh"); h.settle()        # two « répétez »: the counter is at its bound
    h.post("hush"); h.wait_state("ecoute"); h.settle()        # « tais-toi » in relance: back to ecoute, counter kept
    h.say("euh"); h.settle(); h.at("help")                    # the help phrase in ecoute
    h.say("euh"); h.settle(); h.at("silent_after_help")
    h.post("stop"); h.wait_state("veille"); h.settle()


def run_scenario(name):
    fn, over = SCENARIOS[name]
    h = H(over)
    try:
        fn(h)
        h.settle()
    finally:
        trace = h.close()
    return trace


def normalize_new(name, trace):
    """Drop the documented new-only lines: `ask` in veille now enters ecoute through _go."""
    if not name.startswith("ask_veille"):
        return trace
    out = list(trace)
    for i, e in enumerate(out):
        if e == ["go", "veille", "ecoute", "ask"]:
            del out[i]
            if i < len(out) and out[i] == ["mic", "on"]:
                del out[i]
            break
    return out


def run_all(names):
    return {n: run_scenario(n) for n in names}


def compare(baseline, new):
    bad = []
    for n, tr in new.items():
        if n not in baseline:
            bad.append((n, "not in baseline")); continue
        t = normalize_new(n, tr)
        if t != baseline[n]:
            i = next((k for k, (a, b) in enumerate(zip(t, baseline[n])) if a != b), min(len(t), len(baseline[n])))
            bad.append((n, "first diff at #%d new=%r base=%r" % (i, t[i:i + 3], baseline[n][i:i + 3])))
    return bad


# ------------------------------------------------------------------ graph / heartbeat tests (new code only)
def _graph_mod():
    try:
        from nanterino import graph
        return graph
    except ImportError:
        return None


def _write(tmp_name, text):
    path = os.path.join("/tmp", tmp_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _default_text():
    with open(os.path.join(os.path.dirname(HERE), "nanterino", "graph.yaml"), encoding="utf-8") as f:
        return f.read()


def test_default_graph_valid():
    g = _graph_mod().load_graph(_graph_mod().DEFAULT_PATH, dict(config.DEFAULTS))
    assert not g.warnings, g.warnings            # every state / transition / intent has a French description
    assert set(g.states) == set(STATES), sorted(g.states)
    assert [i.name for i in g.intents] == ["appel", "au_revoir", "chanson"]


def test_invalid_graphs_rejected():
    gm, cfg = _graph_mod(), dict(config.DEFAULTS)
    base = _default_text()
    cases = {
        "unknown state 'nowhere'": base.replace("to: ecoute\n        description: \"Salutation", "to: nowhere\n        description: \"Salutation"),
        "unknown action": base.replace("on_enter: [clear_conversation, reset_repairs, mic_on]", "on_enter: [clear_conversation, fly_away]"),
        # G1: the visage guard is now a list (auto greet AND not deaf); G2 adds the opening-hours guard
        "unknown guard": base.replace("when: [auto_greet_on_face, {not: is_deaf}, dans_les_horaires]", "when: moon_is_full"),
        "unknown event": base.replace("- on: visage\n", "- on: nobody_home\n"),
        "required state": base.replace("  eteint:\n", "  eteint_renamed:\n"),
        "not a config key": base.replace("text: greeting,", "text: no_such_key,"),
        "neither a number nor": base.replace("after: silence_relance_s", "after: silence_typo_s"),
        "unknown key": base.replace("version: 1", "version: 1\nsurprise: true"),
    }
    for needle, text in cases.items():
        assert text != base, "case did not change the file: " + needle
        try:
            gm.load_graph(_write("g_bad.yaml", text), cfg)
        except gm.GraphError as e:
            assert needle in str(e), (needle, str(e)[:300])
        else:
            raise AssertionError("graph accepted although invalid: " + needle)


def test_invalid_override_falls_back_and_robot_starts():
    path = _write("g_override_bad.yaml", _default_text().replace("to: accueil\n        description: \"Un visage", "to: atlantis\n        description: \"Un visage"))
    h = H({"graph_file": path})
    try:
        assert h.brain.graph_error and "atlantis" in h.brain.graph_error, h.brain.graph_error
        h.post("start"); h.wait_state("accueil")             # the default graph is running
        h.settle(); assert h.brain.state == "ecoute"
        with open("/var/log/robot/errors.log", encoding="utf-8", errors="replace") as f:
            assert "graph override invalid" in f.read()[-20000:], "error not in errors.log"
    finally:
        h.close()


def test_valid_override_and_reload_rules():
    h = H({"graph_file": "/tmp/g_override_ok.yaml"})            # file does not exist yet -> default
    try:
        h.post("start"); h.wait_state("accueil"); h.settle()
        h.post("stop"); h.wait_state("veille")
        _write("g_override_ok.yaml", _default_text().replace(
            "  veille:\n    description: \"Le robot attend", "  veille:\n    description: \"Variante : le robot attend", 1)
            .replace("      - on: start\n        to: accueil\n        reason: $source\n        description: \"Bouton Démarrer du tableau",
                     "      - on: start\n        to: ecoute\n        reason: $source\n        description: \"Bouton Démarrer du tableau", 1))
        ok, err = h.brain.reload_graph()
        assert ok and err is None and h.brain.engine.graph.source == "/tmp/g_override_ok.yaml", (ok, err)
        h.post("start"); h.settle()
        assert h.brain.state == "ecoute", h.brain.state     # the edited file changed the behaviour
        assert h.brain.reload_graph() == (False, "busy")     # refused while a conversation is running
    finally:
        h.close()
        try:
            os.remove("/tmp/g_override_ok.yaml")
        except OSError:
            pass


def test_visage_perdu_is_ignored_by_default_graph():
    h = H({})
    try:
        h.post("start"); h.settle(); h.post("visage_perdu"); h.settle()
        assert h.brain.state == "ecoute"
    finally:
        h.close()


DEAF_BOUND_S = 12.0   # relance 0.6 s + relance clip + cloture 1.0 s + goodbye clip + 0.3 s pause, with margin


def test_deaf_never_traps():
    """Lot G1: deaf (mic forced off), no input at all: from every conversation state the robot reaches veille within
    DEAF_BOUND_S, and a face seen afterwards does not take it out of veille. `eteint` is excluded on purpose: it is
    the operator's off switch and only « on » / « start » leave it."""
    # G2: + "groupe" = a conversation started by the button in front of two faces (group greeting chain)
    for state in [s for s in STATES if s != "eteint"] + ["groupe"]:
        h = H({"deaf": True, "silence_relance_s": 0.6, "silence_cloture_s": 1.0})
        try:
            if state == "groupe":
                h.brain.set_faces(2); h.settle()
            if state in ("veille", "groupe"):
                h.post("start"); h.wait_state("accueil")          # a conversation started by the button
            else:
                reach(h, state)
            assert not h.brain.mic.active, "deaf robot opened its microphone in %s" % state
            h.unhold()
            t0 = time.monotonic()
            h.wait_state("veille", DEAF_BOUND_S)
            took = time.monotonic() - t0
            h.settle()
            h.post("visage"); h.settle(0.6)
            assert h.brain.state == "veille", "%s: a face took the deaf robot out of veille (%s)" % (state, h.brain.state)
            print("  deaf no-trap from %-8s -> veille in %.1fs" % (state, took), flush=True)
        except AssertionError as e:
            raise AssertionError("from %s: %s" % (state, e)) from None
        finally:
            h.close()


def test_g2_greeting_never_traps():
    """Lot G2: the accueil greeting now starts on conversation_started. Every new chain must end in ecoute / veille:
    (a) accueil entered WITHOUT a conversation start (an edited graph moving there from ecoute): the safety delay
    still leaves it; (b) an emptied salutations list still ends (say_random posts say_done, L27); (c) a deaf group
    greeting returns to veille like any deaf conversation; (d) a face outside the opening hours leaves the robot in
    veille, and Start still works."""
    h = H({"silence_relance_s": 3.0, "silence_cloture_s": 1.0})
    try:   # (a)
        h.post("start"); h.wait_state("ecoute"); h.settle()
        # force the move the shipped graph never makes, on the brain loop thread (defer runs from the heartbeat)
        h.brain.defer(0.0, lambda: h.brain._go("accueil", "test_sans_debut"))
        h.wait_state("accueil", 3)
        t0 = time.monotonic()
        h.wait_state("ecoute", 6)
        took = time.monotonic() - t0
        assert took >= 0.9, "left accueil before the safety delay (%.1fs): something else moved it" % took
        assert any(e[:4] == ["go", "accueil", "ecoute", "accueil_secours"] for e in h.rec.events), h.rec.events[-6:]
        print("  accueil without a conversation start -> ecoute in %.1fs (accueil_secours)" % took, flush=True)
    finally:
        h.close()
    h = H({})
    try:   # (b)
        h.post("start"); h.wait_state("ecoute"); h.post("stop"); h.wait_state("veille"); h.settle()
        h.brain.vars["choix_salutation"] = 2
        h.brain.lists["salutations"] = []
        h.post("start"); h.wait_state("ecoute", 3)
        assert any(e[:4] == ["go", "accueil", "ecoute", "say_done"] for e in h.rec.events), h.rec.events[-6:]
    finally:
        h.close()
    h = H({"deaf": True, "silence_relance_s": 0.6, "silence_cloture_s": 1.0})
    try:   # (c)
        h.brain.set_faces(3); h.settle()
        h.post("start"); h.wait_state("accueil"); h.wait_state("veille", DEAF_BOUND_S)
        assert any(e[0] == "play" and ("à tous" in e[1] or "vous tous" in e[1]) for e in h.rec.events), h.rec.events
    finally:
        h.close()
    h = H({"opening_hours": {"lun-dim": "09:00-18:00"}})
    try:   # (d)
        _wall_at(h, 22)
        h.post("visage"); h.settle(0.6)
        assert h.brain.state == "veille", h.brain.state
        h.post("start"); h.wait_state("ecoute", 3)
    finally:
        h.close()


G3_BOUND_S = 18.0   # visitor-left 11 s (a graph constant) + goodbye clip + 0.3 s pause, or relance 0.6 s + micro_ferme 1 s


def test_g3_never_traps():
    """Lot G3: every new chain ends. (a) deaf, no face for 20 s: from every conversation state the robot reaches veille
    within G3_BOUND_S (the ecoute relance waits for the visitor-left rule, which needs no mic); (b) the help phrase is
    cut by « tais-toi » in ecoute (no say_done, mic left closed): the relance delay still runs, the robot ends in
    veille; (c) a loud noise every second in ecoute: two silence restarts at most, the robot still relances and
    concludes (bruits_forts bound); (d) after the help phrase nothing else comes: back to veille by the usual delays."""
    for state in [s for s in STATES if s != "eteint"]:   # (a)
        h = H({"deaf": True, "silence_relance_s": 0.6, "silence_cloture_s": 1.0})
        try:
            _no_face_for(h, 30)
            if state == "veille":
                h.post("start"); h.wait_state("accueil")
            else:
                reach(h, state)
            h.unhold()
            t0 = time.monotonic()
            h.wait_state("veille", G3_BOUND_S)
            print("  G3 deaf, no face, from %-8s -> veille in %.1fs" % (state, time.monotonic() - t0), flush=True)
        except AssertionError as e:
            raise AssertionError("(a) from %s: %s" % (state, e)) from None
        finally:
            h.close()
    h = H({"silence_relance_s": 1.0, "silence_cloture_s": 1.0})
    try:   # (b)
        h.post("start"); h.settle()
        h.say("euh"); h.settle(); h.say("euh"); h.settle()
        h.post("hush"); h.wait_state("ecoute"); h.settle()
        h.hold()                                  # the help phrase keeps playing ...
        h.say("euh"); h.wait(lambda: h.brain.out.busy, 3)
        h.post("hush")                            # ... and is cut: no say_done, the mic stays closed
        h.out.dur = 0.1
        h.wait_state("veille", G3_BOUND_S)
        assert any(e[:4] == ["go", "relance", "cloture", "silence"] for e in h.rec.events), h.rec.events[-8:]
    finally:
        h.close()
    h = H({"silence_relance_s": 2.0, "silence_cloture_s": 2.0})
    try:   # (c)
        h.brain.set_faces(1)
        h.post("start"); h.wait_state("ecoute"); h.settle()
        t0, end = time.monotonic(), time.monotonic() + 30
        while h.brain.state != "veille" and time.monotonic() < end:
            _noise(h); time.sleep(0.4)            # one loud noise per second, the whole time
        took = time.monotonic() - t0
        assert h.brain.state == "veille", "a noisy hall kept the robot in %s" % h.brain.state
        assert h.brain.vars.get("bruits_forts") == 0, h.brain.vars.get("bruits_forts")
        print("  G3 loud noise every second -> veille in %.1fs" % took, flush=True)
    finally:
        h.close()
    h = H({"silence_relance_s": 1.0, "silence_cloture_s": 1.0})
    try:   # (d)
        h.post("start"); h.settle()
        for _ in range(3):
            h.say("euh"); h.settle()
        assert any(e[0] == "play" and e[1].startswith("Je n'arrive pas") for e in h.rec.events), h.rec.events[-6:]
        h.wait_state("veille", G3_BOUND_S)
    finally:
        h.close()


def test_heartbeat_rate_and_lag():
    h = H({})
    try:
        lags = []
        for _ in range(40):
            time.sleep(0.1)
            lags.append(h.brain.snapshot()["heartbeat"]["lag_ms"])
        hb = h.brain.snapshot()["heartbeat"]
        assert 8.0 <= hb["hz"] <= 12.0, hb
        assert hb["trips"] == 0 and hb["age_ms"] < 500, hb
        assert max(lags) < 20, "heartbeat lag too high: max %.1f ms" % max(lags)
        snap = h.brain.snapshot()
        assert "state_age_s" in snap and "turns" in snap
    finally:
        h.close()


def test_watchdog_trips_once_and_recovers():
    h = H({"watchdog_s": 5})
    try:
        blocked = threading.Event()
        real_stop = h.brain.mic.stop

        def slow_stop():            # runs in the brain loop thread: the loop is stuck for 6 s
            blocked.set()
            time.sleep(6.0)
            real_stop()
        h.brain.mic.stop = slow_stop
        h.post("start")             # veille -> accueil: on_enter calls mic_off -> blocks
        assert blocked.wait(3)
        h.wait(lambda: h.brain.snapshot()["heartbeat"]["trips"] >= 1, 9)
        h.brain.mic.stop = real_stop
        h.wait_state("veille", 10)  # the priority stop ran once the handler returned
        h.settle(0.5)
        hb = h.brain.snapshot()["heartbeat"]
        assert hb["trips"] == 1, hb
        assert h.brain._loop_thread.is_alive()
        time.sleep(0.5)
        assert h.brain.snapshot()["heartbeat"]["age_ms"] < 500       # beats flow again
        h.post("start"); h.wait_state("ecoute", 5)                   # and the robot works normally
        with open("/var/log/robot/errors.log", encoding="utf-8", errors="replace") as f:
            assert "watchdog: no heartbeat processed" in f.read()[-20000:]
    finally:
        h.close()


EXTRA_TESTS = [test_default_graph_valid, test_invalid_graphs_rejected,
               test_invalid_override_falls_back_and_robot_starts, test_valid_override_and_reload_rules,
               test_visage_perdu_is_ignored_by_default_graph, test_deaf_never_traps, test_g2_greeting_never_traps,
               test_g3_never_traps, test_heartbeat_rate_and_lag,
               test_watchdog_trips_once_and_recovers]


def run_extras():
    if _graph_mod() is None:
        print("graph module absent: extra tests skipped (baseline brain)")
        return 0
    failed = 0
    for fn in EXTRA_TESTS:
        try:
            fn()
            print("PASS", fn.__name__, flush=True)
        except Exception as e:  # report every failure, not just the first
            failed += 1
            print("FAIL", fn.__name__, "%s: %s" % (type(e).__name__, e), flush=True)
    print("extra tests: %d passed, %d failed" % (len(EXTRA_TESTS) - failed, failed))
    return failed


def main(argv):
    if "--extras-only" in argv:
        return 1 if run_extras() else 0
    names = list(SCENARIOS)
    if "--only" in argv:
        names = argv[argv.index("--only") + 1].split(",")
    out = argv[argv.index("--out") + 1] if "--out" in argv else None
    t0 = time.monotonic()
    traces = run_all(names)
    print("ran %d scenarios in %.0fs" % (len(traces), time.monotonic() - t0), flush=True)
    if "--record" in argv or out:
        path = out or BASELINE
        with open(path, "w", encoding="utf-8") as f:
            json.dump(traces, f, ensure_ascii=False, indent=0, sort_keys=True)
        print("traces written to", path)
        return 0
    with open(BASELINE, encoding="utf-8") as f:
        base = json.load(f)
    bad = compare(base, traces)
    for n, why in bad:
        print("DIFF", n, why)
    print("trace parity: %d scenarios, %d different" % (len(traces), len(bad)))
    failed = run_extras() if "--only" not in argv else 0
    return 1 if (bad or failed) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
