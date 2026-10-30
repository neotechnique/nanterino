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

How to run (repo root, venv python; pytest is not installed):
    python -m tests.test_brain_graph --record     # write the baseline trace (old brain only)
    python -m tests.test_brain_graph              # compare with the baseline (+ graph tests if present)
    python -m tests.test_brain_graph --only a,b   # subset;  --out FILE  write the traces elsewhere
"""
import functools
import json
import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, "/opt/robot/lib")
from robotlog import get_logger  # noqa: E402

from nanterino import brain as brain_mod  # noqa: E402
from nanterino import config  # noqa: E402

log = get_logger("test_brain_graph")
HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.join(HERE, "brain-trace-baseline.json")

PHRASE_KEYS = ("greeting", "relance", "goodbye", "repair_text")
BASE_CFG = {
    "silence_relance_s": 3.0, "silence_cloture_s": 3.0, "cloture_to_veille_s": 0.3,
    "auto_greet_on_face": True, "barge_in": False, "power": "on", "deaf": False,
    "refusal_words": ["non merci", "stop", "au revoir", "arrête", "arrete"],
}


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
    """Output that is 'busy' for `dur` seconds after play(); hold mode = long dur until release()."""
    level, muted, preroll_ms, last_play_preroll = 0.0, True, 0, False

    def __init__(self, rec, tts):
        self.rec, self.tts, self.dur, self.song_dur, self._until = rec, tts, 0.1, 0.25, 0.0
        self.keys = {}

    def play(self, pcm, rate):
        if len(pcm) > 100:
            label, d = "song", (self.dur if self.dur > 1 else self.song_dur)
        else:
            text = self.tts.texts[int(pcm[0])]
            label, d = self.keys.get(text, text), self.dur
        self.rec.add("play", label)
        self._until = time.monotonic() + d

    def stop(self):
        self.rec.add("cancel"); self._until = 0.0

    def release(self):
        self._until = 0.0

    @property
    def busy(self):
        return time.monotonic() < self._until


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


class FakeCorpus:
    sheets = []

    def search(self, *a, **k):
        return []


class H:
    """One scenario run: fake world + a real Brain + step helpers."""

    def __init__(self, over):
        self.rec = Rec()
        cfg = dict(config.DEFAULTS); cfg.update(BASE_CFG); cfg.update(over)
        self.cfg = cfg
        self.tts, self.stt = FakeTTS(), FakeSTT()
        self.out = FakeOut(self.rec, self.tts)
        self.out.keys = {cfg[k]: k for k in PHRASE_KEYS}
        self.llm = FakeLLM(self.rec)
        brain_mod.AudioIn = functools.partial(FakeIn, self.rec)
        brain_mod.find_device = lambda *a, **k: None
        self.brain = brain_mod.Brain(cfg, self.out, self.stt, self.llm, self.tts, FakeCorpus())
        orig = self.brain._go

        def go(state, reason):
            self.rec.add("go", self.brain.state, state, reason)  # recorded BEFORE the entry effects
            orig(state, reason)
        self.brain._go = go
        self.wait(lambda: len(self.brain._phrases) >= 4 and self.rec.events, 5)

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
    h.post("start"); h.settle(); h.say("Enchanté de vous voir"); h.settle(); h.at("end")


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
        for i in range(3):
            h.say("Question %d" % i); h.settle(); h.at("turn_%d" % i)
        h.wait_state("veille"); h.settle(); h.at("end")
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


def main(argv):
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
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
