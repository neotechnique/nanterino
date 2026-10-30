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
        cfg = dict(config.DEFAULTS); cfg.update(BASE_CFG); cfg["graph_file"] = GRAPH_FILE; cfg.update(over)
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
        "unknown guard": base.replace("when: auto_greet_on_face", "when: moon_is_full"),
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
               test_visage_perdu_is_ignored_by_default_graph, test_heartbeat_rate_and_lag,
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
