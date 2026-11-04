"""Tests of the lot N3 nodes (2026-11-02): Triggers = Actions = Conditions in EVERY theme (durable user rule).

logging: robotlog via tests.test_brain_graph (imported through tests.test_graph_vars / tests.test_nodes_n1 helpers).

Purpose
    One behaviour test per new node on a non-threaded Brain of the fake world (nanterino/sim.py): each TRIGGER is posted
    by the real brain code path (Brain._audio_tick, _on_speech_start, _clock_tick, reset_var / _reset_scope, _set_var,
    _load_persisted, list_touched, dict_key_events, the action modules) and a global transition reacting to it adds 1 to
    a counter; each ACTION's effect on the brain / config; each CONDITION reading the real state. Also: the three theme
    moves (THEME_MOVES), the parser's refusals of the new watch triggers / media_is, the visual round trip, and the
    vocabulary goldens changing only additively (pre-N3 copies; the moved entries differ in `theme` only, restored by
    strip_n3). The per-theme parity rule itself is tests.test_nodes_registry.test_node_parity.

Boundary
    Fake output (muted FakeOut), fake mic (FakeIn), temporary var stores under /tmp/test_nodes_n3: the live robot's
    audio, mic, config and state/vars.json are never touched, and nanterino.server is never imported.

How to run (repo root):
    .venv/bin/python -m tests.test_nodes_n3            # ~3 s; --only name1,name2
"""
import copy
import datetime
import json
import logging
import os
import shutil
import sys

sys.path.insert(0, "/opt/robot/lib")

from nanterino import brain as brain_mod, graph as G, graph_visual as V, nodes, sim, var_store  # noqa: E402
from nanterino.brain import Brain  # noqa: E402
from nanterino.log import log  # noqa: E402
from tests.test_graph_vars import CFG, mini, parse, refused  # noqa: E402
from tests.test_nodes_n1 import (GOLDEN, LISTS, MONDAY, act, adv, brain, counter, guard, ints, media_dir,  # noqa: E402
                                 strip_ids)

TMP = "/tmp/test_nodes_n3"

# The lot N3 node ids (strip them, restore THEME_MOVES, and the vocabulary is the pre-N3 golden byte for byte).
N3 = {
    "triggers": ["speech_started", "voice_detected", "loud_noise", "var_reset", "var_bound_reached", "random_drawn",
                 "vars_restored", "list_emptied", "list_filled", "dict_key_set", "dict_key_removed", "dict_emptied",
                 "hour_changed", "day_changed", "schedule_cancelled"],
    "actions": ["reset_turns", "forget_last_exchange", "set_barge_in", "clear_text", "reset_expression", "set_auto_greet",
                "set_face_scale", "reset_var", "schedule_cancel", "reset_idle", "shift_date", "clear_notifications",
                "clear_errors", "log_state", "save_vars_now"],
    "conditions": ["repair_prepared", "said_contains", "robot_quiet_since", "media_is", "song_available",
                   "speaker_level_compare", "phrase_ready", "subtitle_contains", "no_face_since", "var_is_initial",
                   "var_at_bound", "list_is_full", "graph_update_waiting", "uptime_compare", "notification_count_compare"],
}
# Honest theme moves of lot N3 (family, id): (old theme, new theme). The relance and the « répétez » phrase are steps of
# the conversation (THEME_DOC: « demandes de répétition »; relance_done was already a conversation trigger); « Je vous
# écoute » is a text on the face screen like show_text (vision: « le visage affiché à l'écran »).
THEME_MOVES = {("actions", "speak_relance"): ("parole", "conversation"),
               ("actions", "set_relance_text"): ("parole", "conversation"),
               ("actions", "subtitle_listening"): ("micro", "vision")}
# Palette per theme after N3 (T, A, C): every row equal. Lot C2 (2026-11-04) adds the sound triad to micro (6 -> 7;
# tests.test_sound.C2), totals 65 -> 66.
EXPECTED = {"conversation": 10, "parole": 11, "micro": 7, "vision": 8, "variables": 5, "listes": 9, "temps": 8,
            "systeme": 7, "evenements": 1}


def strip_n3(v: dict) -> dict:
    """The vocabulary without the N3 entries and with the moved nodes back in their pre-N3 theme (order kept). The
    entries of the later lot C2 leave first (tests.test_sound.strip_c2), so every older additive check keeps working."""
    from tests.test_sound import strip_c2   # lazy: tests.test_sound imports the N1 helpers
    v = strip_ids(strip_c2(v), N3)
    fam_key = {"actions": "actions", "conditions": "guards", "triggers": "events"}
    for (fam, nid), (old, _new) in THEME_MOVES.items():
        v[fam_key[fam]] = [dict(e, theme=old) if e["id"] == nid else e for e in v[fam_key[fam]]]
    return v


def fresh_tmp():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    return TMP


def brain_store(raw, store, **cfg):
    """Like tests.test_nodes_n1.brain, with a var store (persistence)."""
    clock = sim.SimClock()
    t0, wall0 = clock.t, datetime.datetime.fromisoformat(MONDAY).timestamp()
    rec, tts = sim.Rec(), sim.FakeTTS()
    out = sim.FakeOut(rec, tts, clock)
    b = Brain(dict(CFG, power="on", **cfg), out, sim.FakeSTT(), sim.FakeLLM(rec), tts, sim.FakeCorpus(), clock=clock,
              wall=lambda: wall0 + (clock.t - t0), mic=sim.FakeIn(rec), graph=parse(raw), threaded=False,
              start_state="veille", var_store=store)
    b.rng.seed(0)
    b.pump()
    return b, clock, rec


def tick(b, clock, seconds):
    """One heartbeat after a clock jump (hour / day changes without 36000 small steps)."""
    clock.t += seconds
    b._on_tick({"t": clock.t})
    b.pump()


def spy(b):
    """Record the payloads of the next posts (end with unspy(), which queues them for real)."""
    ev = []
    b.post = lambda kind, **kw: ev.append((kind, kw))
    return ev


def unspy(b, ev):
    del b.post
    for kind, kw in ev:
        b.post(kind, **kw)
    b.pump()


def cond(c):
    return mini(veille=[{"on": "start", "when": [c], "to": "a"}])


# ---------------------------------------------------------------- parole
def test_speech_started_quiet_and_said():
    raw = mini(glob=[counter("speech_started", "s")], variables=ints("s"))
    b, clock, rec = brain(raw)
    b.out.dur = 1.0
    assert guard(b, "robot_quiet_since", op=">=", seconds=0) and not guard(b, "said_contains", text="bonjour")
    act(b, "say_text", text="Bonjour à tous.")
    adv(b, clock, 0.3)
    assert b.vars["s"] == 1 and b.out.busy, "rising edge of out.busy seen by the heartbeat"
    assert guard(b, "robot_quiet_since", op="=", seconds=0), "0 while the speaker plays"
    assert guard(b, "said_contains", text="BONJOUR") and not guard(b, "said_contains", text="revoir")
    assert not guard(b, "said_contains", text="  ")
    adv(b, clock, 0.6)
    assert b.vars["s"] == 1, "one event per sound, not per beat"
    adv(b, clock, 1.6)
    assert not b.out.busy and guard(b, "robot_quiet_since", op=">", seconds=1.0)
    assert not guard(b, "robot_quiet_since", op=">", seconds=2.0)
    act(b, "start_answer", kw={"text": "x", "t_end": 0})   # simulator answer: last_said is its text
    assert guard(b, "said_contains", text="réponse simulée")
    act(b, "say_text", text="Encore.")
    adv(b, clock, 0.2)
    assert b.vars["s"] == 2


def test_speaker_level_and_phrase_ready():
    b, clock, rec = brain(mini())
    b.out.dur, b.out.level = 1.0, 0.5
    assert not guard(b, "speaker_level_compare", op=">", percent=0), "silent speaker reads 0"
    act(b, "say_text", text="Niveau.")
    assert guard(b, "speaker_level_compare", op="=", percent=50) and guard(b, "speaker_level_compare", op=">=", percent=40)
    assert guard(b, "phrase_ready", text=CFG["greeting"]), "config phrases are synthesised at graph load"
    assert not guard(b, "phrase_ready", text="Jamais calculé.") and not guard(b, "phrase_ready", text="")
    b._phrases.pop(CFG["greeting"])
    assert not guard(b, "phrase_ready", text=CFG["greeting"])


def test_media_is_and_song_available():
    md = media_dir()
    b, clock, rec = brain(mini(), media_dir=md)
    assert not guard(b, "media_is", file="bip.wav")
    act(b, "play_media", file="bip.wav")
    assert guard(b, "media_is", file="bip.wav") and not guard(b, "media_is", file="autre.wav")
    adv(b, clock, 0.5)
    assert not guard(b, "media_is", file="bip.wav")
    parse(cond({"media_is": {"file": "bip.wav"}}))
    refused(cond({"media_is": {"file": "../x.wav"}}), "expected a .wav file name")
    song = os.path.join(fresh_tmp(), "chanson.wav")
    b.song_path = lambda: song
    assert not guard(b, "song_available")
    open(song, "wb").close()
    assert guard(b, "song_available")
    b2, _c, _r = brain(mini())
    assert guard(b2, "song_available") == os.path.isfile(Brain.song_path()), "the real path of _sing"


# ---------------------------------------------------------------- micro
def test_voice_detected_and_loud_noise():
    raw = mini(glob=[counter("voice_detected", "v"), counter("loud_noise", "l")], variables=ints("v", "l"))
    b, clock, rec = brain(raw)
    b._on_speech_start()                   # AudioIn's VAD callback (mic thread on the robot)
    b.pump()
    assert b.vars["v"] == 1
    act(b, "mic_on")
    b.mic.level = 0.7
    adv(b, clock, 0.3)
    assert b.vars["l"] == 1, "fired once while it stays loud"
    b.mic.level = 0.4                      # still above the re-arm level
    adv(b, clock, 0.2)
    b.mic.level = 0.8
    adv(b, clock, 0.2)
    assert b.vars["l"] == 1
    b.mic.level = 0.1                      # quiet again: re-armed
    adv(b, clock, 0.2)
    b.mic.level = 0.9
    ev = spy(b)
    b._on_tick({"t": clock.t})
    unspy(b, ev)
    assert ("loud_noise", {"depth": 1, "value": 90}) in ev and b.vars["l"] == 2, ev
    b.mic.level = 0.0
    adv(b, clock, 0.2)
    act(b, "mic_off")
    b.mic.level = 0.95                     # a closed (or deaf) mic reads 0: never loud
    adv(b, clock, 0.3)
    assert b.vars["l"] == 2, b.vars


def test_set_barge_in():
    raw = mini(glob=[counter("barge_in", "n")], variables=ints("n"))
    raw["states"][brain_mod.REPONSE] = {"description": "état de réponse (test)"}
    b, clock, rec = brain(raw, barge_in=False)
    act(b, "set_barge_in", mode="on")
    assert b.cfg["barge_in"] is True and guard(b, "barge_in")
    b.state = brain_mod.REPONSE            # the brain's real reader: _on_speech_start during an answer
    b._on_speech_start()
    b.pump()
    assert b.vars["n"] == 1
    act(b, "set_barge_in", mode="off")
    b._on_speech_start()
    b.pump()
    assert b.vars["n"] == 1 and not guard(b, "barge_in")
    refused(mini(veille=[{"on": "start", "do": [{"set_barge_in": {"mode": "peut-être"}}]}]), "expected on or off")


# ---------------------------------------------------------------- vision
def test_text_expression_and_face_nodes():
    raw = mini(glob=[counter("text_cleared", "c"), counter("expression_changed", "e")], variables=ints("c", "e"))
    b, clock, rec = brain(raw)
    act(b, "show_text", text="Salut les amis", seconds=30)
    assert guard(b, "subtitle_contains", text="LES AMIS") and not guard(b, "subtitle_contains", text="")
    act(b, "clear_text")
    assert b.subtitle == "" and not guard(b, "subtitle_contains", text="salut")
    adv(b, clock, 0.2)
    assert b.vars["c"] == 1, "text_cleared follows on the next beat"
    act(b, "set_expression", name="content", seconds=30)
    assert guard(b, "expression_is", name="content") and b.vars["e"] == 1
    act(b, "reset_expression")
    assert guard(b, "expression_is", name="neutre") and b.vars["e"] == 2
    act(b, "reset_expression")                     # already neutral: nothing
    assert b.vars["e"] == 2
    act(b, "set_auto_greet", mode="on")
    assert b.cfg["auto_greet_on_face"] is True and guard(b, "auto_greet_on_face")
    act(b, "set_auto_greet", mode="off")
    assert not guard(b, "auto_greet_on_face")
    for pct, want in ((120, 1.2), (999, 1.6), (10, 0.5)):
        act(b, "set_face_scale", percent=pct)
        assert abs(b.cfg["face_scale"] - want) < 1e-9, (pct, b.cfg["face_scale"])


def test_no_face_since():
    b, clock, rec = brain(mini())
    adv(b, clock, 1.0)
    assert guard(b, "no_face_since", op=">=", seconds=0.9), "no face yet: counted from the start"
    b.set_faces(1)
    adv(b, clock, 1.0)
    assert guard(b, "no_face_since", op="=", seconds=0)
    b.set_faces(0)
    adv(b, clock, 2.0)
    assert guard(b, "no_face_since", op=">=", seconds=1.9) and not guard(b, "no_face_since", op=">", seconds=2.5)
    b.set_faces(0)                                  # same count again: the absence keeps its start
    assert guard(b, "no_face_since", op=">=", seconds=1.9)


# ---------------------------------------------------------------- conversation
def test_conversation_nodes():
    b, clock, rec = brain(mini())
    act(b, "count_turn")
    act(b, "count_turn")
    assert b.turns == 2
    act(b, "reset_turns")
    assert b.turns == 0 and guard(b, "first_turn")
    pair = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "r1"}]
    b.history = pair + [{"role": "user", "content": "q2"}, {"role": "assistant", "content": "r2"}]
    act(b, "forget_last_exchange")
    assert b.history == pair
    b.history = [{"role": "user", "content": "seule"}]
    act(b, "forget_last_exchange")                  # no complete pair at the end: nothing removed
    assert len(b.history) == 1
    assert not guard(b, "repair_prepared")
    act(b, "set_relance_text")
    assert guard(b, "repair_prepared")
    act(b, "speak_relance")
    assert not guard(b, "repair_prepared"), "the relance said it (one-shot)"


# ---------------------------------------------------------------- variables
def var_graph(glob=()):
    names = dict(ints("k", "m", "kc")["names"], n={"type": "integer", "value": 3, "min": 0, "max": 5},
                 c={"type": "integer", "value": 0, "scope": "conversation"})
    return mini(glob=list(glob), variables={"names": names})


def test_var_reset_triad():
    raw = var_graph([counter("var_reset", "k", var="n"), counter("var_reset", "kc", var="c")])
    b, clock, rec = brain(raw)
    assert guard(b, "var_is_initial", name="n")
    act(b, "set_var", name="n", value=4)
    assert not guard(b, "var_is_initial", name="n")
    act(b, "reset_var", name="n")
    assert b.vars["n"] == 3 and b.vars["k"] == 1 and guard(b, "var_is_initial", name="n")
    act(b, "reset_var", name="n")                   # unchanged: no event
    assert b.vars["k"] == 1
    act(b, "set_var", name="n", value=1)
    assert b.reset_var("n") and b.vars["n"] == 3    # the dashboard variable manager
    b.pump()
    assert b.vars["k"] == 2
    act(b, "set_var", name="c", value=2)
    act(b, "clear_conversation")                    # conversation scope: back to 0
    assert b.vars["c"] == 0 and b.vars["kc"] == 1
    refused(mini(glob=[{"on": "var_reset", "var": "absent"}]), "a declared variable")
    refused(mini(veille=[{"on": "start", "do": [{"reset_var": {"name": "tours"}}]}]), "read-only system variable")


def test_var_bound_triad():
    raw = var_graph([counter("var_bound_reached", "m", var="n")])
    b, clock, rec = brain(raw)
    assert not guard(b, "var_at_bound", name="n") and not guard(b, "var_at_bound", name="k")
    ev = spy(b)
    act(b, "add_var", name="n", delta=10)           # clamped to the max
    unspy(b, ev)
    assert ("var_bound_reached", {"depth": 1, "name": "n", "value": 5}) in ev, ev
    b.pump()
    assert b.vars["n"] == 5 and b.vars["m"] == 1 and guard(b, "var_at_bound", name="n")
    act(b, "add_var", name="n", delta=1)            # still 5: no change, no event
    assert b.vars["m"] == 1
    act(b, "set_var", name="n", value=0)            # the min
    assert b.vars["m"] == 2 and guard(b, "var_at_bound", name="n")
    act(b, "set_var", name="n", value=2)
    assert not guard(b, "var_at_bound", name="n")
    refused(var_graph([{"on": "var_bound_reached", "var": "k"}]), "has no min / max")


def test_random_drawn():
    raw = mini(glob=[counter("random_drawn", "d")], variables=ints("d", "x"))
    b, clock, rec = brain(raw)
    ev = spy(b)
    act(b, "random_choice", name="x", count=6)
    unspy(b, ev)
    drawn = [kw["value"] for k, kw in ev if k == "random_drawn"]
    assert drawn == [b.vars["x"]] and 1 <= drawn[0] <= 6, (ev, b.vars)
    b.pump()
    assert b.vars["d"] == 1


def persisted_graph(glob=()):
    return mini(glob=list(glob), variables={"names": dict(ints("k")["names"],
                                                          p={"type": "integer", "value": 0, "persist": True})})


def test_vars_restored_and_save_now():
    path = os.path.join(fresh_tmp(), "vars.json")
    raw = persisted_graph([counter("vars_restored", "k")])
    b, clock, rec = brain_store(raw, var_store.VarStore(path, clock=lambda: 0.0))
    assert b.vars["k"] == 0, "nothing saved yet: no event"
    act(b, "set_var", name="p", value=7)
    act(b, "save_vars_now")                         # written now, without waiting for the heartbeat
    assert json.load(open(path))["names"]["p"]["value"] == 7
    b2, _c, _r = brain_store(raw, var_store.VarStore(path, clock=lambda: 0.0))
    assert b2.vars["p"] == 7 and b2.vars["k"] == 1, b2.vars
    b3, _c, _r = brain(raw)
    act(b3, "save_vars_now")                        # no store (simulator): nothing, no error


# ---------------------------------------------------------------- listes
def test_list_emptied_and_filled():
    lists = dict(LISTS, hist={"type": "integer", "items": [], "max": 2})
    raw = mini(glob=[counter("list_emptied", "e", var="nums"), counter("list_filled", "f", var="hist")],
               variables=ints("e", "f", **lists))
    b, clock, rec = brain(raw)
    act(b, "list_add", list="hist", value=1)
    assert b.vars["f"] == 0 and not guard(b, "list_is_full", list="hist")
    act(b, "list_add", list="hist", value=2)
    assert b.vars["f"] == 1 and guard(b, "list_is_full", list="hist")
    act(b, "list_add", list="hist", value=3)        # beyond max: the oldest goes, still full, no new event
    assert b.lists["hist"] == [2, 3] and b.vars["f"] == 1
    act(b, "list_remove", list="hist", value=2)
    act(b, "list_add", list="hist", value=4)        # full again
    assert b.vars["f"] == 2
    assert not guard(b, "list_is_full", list="nums"), "no max: never full"
    act(b, "list_remove", list="nums", value=3)
    assert b.vars["e"] == 0
    act(b, "list_clear", list="nums")
    assert b.vars["e"] == 1
    act(b, "list_clear", list="nums")               # already empty: nothing
    assert b.vars["e"] == 1
    act(b, "list_add", list="nums", value=5)
    act(b, "list_remove", list="nums", value=5)     # the last item leaves through list_remove too
    assert b.vars["e"] == 2
    refused(mini(glob=[{"on": "list_filled", "var": "nums"}], variables={"lists": LISTS}), "needs a list with `max:`")
    refused(mini(glob=[{"on": "list_emptied", "var": "faq"}], variables={"lists": LISTS}), "a declared list")


def test_dict_key_triads():
    raw = mini(glob=[counter("dict_key_set", "ks", var="faq"), counter("dict_key_removed", "kr", var="faq"),
                     counter("dict_emptied", "de", var="faq")], variables=ints("ks", "kr", "de", **LISTS))
    b, clock, rec = brain(raw)
    ev = spy(b)
    act(b, "dict_set", dict="faq", key="b", value="y")
    unspy(b, ev)
    assert ("dict_key_set", {"depth": 1, "name": "faq", "value": "b"}) in ev, ev
    b.pump()
    assert b.vars["ks"] == 1
    act(b, "dict_set", dict="faq", key="b", value="y")   # same value: nothing changed
    assert b.vars["ks"] == 1
    act(b, "dict_set", dict="faq", key="a", value="z")   # changed value
    assert b.vars["ks"] == 2
    act(b, "dict_remove", dict="faq", key="b")
    act(b, "dict_remove", dict="faq", key="zz")          # absent: nothing
    assert b.vars["kr"] == 1 and b.vars["de"] == 0
    act(b, "dict_remove", dict="faq", key="a")           # last key
    assert b.vars["kr"] == 2 and b.vars["de"] == 1
    act(b, "dict_set", dict="faq", key="a", value="x")
    act(b, "dict_clear", dict="faq")
    assert b.vars["de"] == 2
    refused(mini(glob=[{"on": "dict_key_set", "var": "nums"}], variables={"lists": LISTS}), "a declared dictionary")


# ---------------------------------------------------------------- temps
def test_hour_and_day_changed():
    raw = mini(glob=[counter("hour_changed", "h"), counter("day_changed", "d")], variables=ints("h", "d"))
    b, clock, rec = brain(raw)                      # wall clock: Monday 2026-11-02 10:00
    adv(b, clock, 1.2)
    assert b.vars == {"h": 0, "d": 0}, "the first check only reads the clock"
    tick(b, clock, 1800)                            # 10:30
    assert b.vars["h"] == 0
    ev = spy(b)
    tick(b, clock, 1800)                            # 11:00
    unspy(b, ev)
    assert ("hour_changed", {"value": 11}) in ev, ev
    b.pump()
    tick(b, clock, 14 * 3600)                       # Tuesday 01:00
    assert b.vars == {"h": 2, "d": 1}, b.vars
    assert b._weekday() == "mar"


def test_schedule_cancel_triad():
    raw = mini(glob=[counter("schedule_cancelled", "sc")],
               veille=[{"on": "start", "do": [{"add_var": {"name": "n", "delta": 1}}]}], variables=ints("sc", "n"))
    b, clock, rec = brain(raw)
    act(b, "schedule", event="start", delay=2)
    act(b, "schedule", event="stop", delay=5)
    act(b, "schedule_cancel", event="start")
    assert b.vars["sc"] == 1 and not guard(b, "scheduled_pending", event="start") and guard(b, "scheduled_pending", event="stop")
    adv(b, clock, 3.0)
    assert b.vars["n"] == 0, "the cancelled event never fires"
    act(b, "schedule_cancel", event="start")        # nothing waiting: no event
    assert b.vars["sc"] == 1


def test_reset_idle_and_shift_date():
    raw = mini(glob=[counter("inactivite_longue", "i")],
               variables={"names": dict(ints("i")["names"], d={"type": "datetime", "value": "2026-11-02T10:00:00"})})
    b, clock, rec = brain(raw, idle_long_s=5)
    adv(b, clock, 4.0)
    act(b, "reset_idle")
    adv(b, clock, 4.0)
    assert b.vars["i"] == 0, "the idle clock restarted"
    adv(b, clock, 1.5)
    assert b.vars["i"] == 1
    act(b, "shift_date", name="d", seconds=3600)
    assert b.vars["d"] == "2026-11-02T11:00:00", b.vars["d"]
    act(b, "shift_date", name="d", seconds=-86400)
    assert b.vars["d"] == "2026-11-01T11:00:00"
    b.vars["d"] = ""
    act(b, "shift_date", name="d", seconds=60)      # empty date stays empty
    assert b.vars["d"] == ""


# ---------------------------------------------------------------- systeme
def test_systeme_nodes():
    b, clock, rec = brain(mini())
    b.notify("un", "info")
    b.notify("deux", "warning")
    assert guard(b, "notification_count_compare", op="=", count=2)
    act(b, "clear_notifications")
    assert guard(b, "notification_count_compare", op="=", count=0) and not guard(b, "notification_pending")
    b.note_journal("warning", "robot")
    b.note_journal("error", "robot")
    assert guard(b, "recent_error", seconds=60)
    act(b, "clear_errors")
    assert not guard(b, "recent_error", seconds=60) and [x[1] for x in b.journal_notes] == ["warning"]
    seen = []
    handler = logging.Handler()
    handler.emit = lambda r: seen.append(r.getMessage())
    log.addHandler(handler)
    try:
        b.last_text = "secret du visiteur"
        act(b, "log_state")
    finally:
        log.removeHandler(handler)
    msg = [m for m in seen if m.startswith("graph state:")]
    assert msg and "etat=veille" in msg[0] and "secret" not in " ".join(seen), seen
    # G3 (daily / hourly summary): visitor counters and the journal's errors / warnings (clear_errors left the warning)
    assert "visiteurs_jour=0 visiteurs_veille=? erreurs_24h=0 avertissements_24h=1" in msg[0], msg[0]
    assert b.journal_notes[-1][1] == "info"
    assert not guard(b, "graph_update_waiting")
    b.graph_pending = True
    assert guard(b, "graph_update_waiting")
    adv(b, clock, 2.0)
    assert guard(b, "uptime_compare", op=">=", seconds=1.9) and not guard(b, "uptime_compare", op=">", seconds=5)


# ---------------------------------------------------------------- registry, parser, editor, goldens
def test_theme_moves_and_per_theme_counts():
    for (fam, nid), (_old, new) in THEME_MOVES.items():
        assert getattr(nodes, fam.upper())[nid].theme == new, nid
    from tests.test_nodes_n1 import counts
    c = counts()
    for theme, n in EXPECTED.items():
        assert [c[f]["themes"].get(theme, 0) for f in ("triggers", "actions", "conditions")] == [n] * 3, (theme, c)
    assert all(c[f]["total"] == 66 for f in c)   # 65 at N3, 66 since C2
    for fam, ids in N3.items():
        assert all(i in getattr(nodes, fam.upper()) for i in ids), fam


def test_visual_roundtrip():
    lists = dict(LISTS, hist={"type": "integer", "items": [], "max": 2})
    raw = mini(glob=[counter("list_filled", "n", var="hist"), counter("dict_key_set", "n", var="faq"),
                     counter("speech_started", "n"), counter("hour_changed", "n")],
               veille=[{"on": "start", "when": [{"said_contains": {"text": "parc"}}, {"not": "song_available"},
                                                 {"no_face_since": {"op": ">", "seconds": 3}},
                                                 {"list_is_full": {"list": "hist"}}], "to": "a"}],
               variables=ints("n", **lists))
    want = parse(raw).to_dict()
    back, _layout, errs = V.from_visual(V.to_visual(copy.deepcopy(raw)), CFG)
    assert not errs, errs
    assert parse(back).to_dict() == want


def test_vocabulary_of_the_new_nodes():
    v = G.vocabulary(CFG)
    emit = next(a for a in v["actions"] if a["id"] == "emit")["args"][0]["options"]
    for t in N3["triggers"]:
        assert (t in emit) == (t not in G.WATCH_EVENTS), t
    gd = {g["id"]: g for g in v["guards"]}
    assert gd["media_is"]["args"][0]["type"] == "enum"
    assert [a["name"] for a in gd["robot_quiet_since"]["args"]] == ["op", "seconds"]
    for fam, key in (("events", "triggers"), ("actions", "actions"), ("guards", "conditions")):
        ids = [x["id"] for x in v[fam]]
        assert all(i in ids for i in N3[key]), (fam, set(N3[key]) - set(ids))


def test_goldens_n3_only_gained_entries():
    from tests.test_nodes_registry import golden_diff, vocab_dumps
    dumps = vocab_dumps(G)
    assert not golden_diff(dumps), "the N3 goldens differ: %s" % golden_diff(dumps)
    for name, text in dumps.items():
        with open(os.path.join(GOLDEN, name.replace(".json", ".pre-n3.json")), "rb") as f:
            old = f.read()
        stripped = json.dumps(strip_n3(json.loads(text)), ensure_ascii=False, indent=1) + "\n"
        assert stripped.encode("utf-8") == old, "%s minus the N3 entries (moved themes restored) is not the pre-N3 golden" % name


def test_shipped_graph_uses_only_g3_n3_nodes():
    """Lot N3 left graph.yaml unchanged; the user approved G3 (2026-11-02, tests/golden/behaviour-changes-G3.md), which
    uses exactly these N3 nodes, and no other (replaces test_shipped_graph_uses_no_n3_node). The trigger voice_detected
    is deliberately NOT used: Brain._on_speech_start already restarts the silence clock (a rule would double count)."""
    text = open(G.DEFAULT_PATH, encoding="utf-8").read()
    used = [i for ids in N3.values() for i in ids if i in text]
    assert sorted(used) == ["day_changed", "hour_changed", "log_state", "loud_noise", "no_face_since",
                            "robot_quiet_since", "var_at_bound"], used


TESTS = [test_speech_started_quiet_and_said, test_speaker_level_and_phrase_ready, test_media_is_and_song_available,
         test_voice_detected_and_loud_noise, test_set_barge_in, test_text_expression_and_face_nodes, test_no_face_since,
         test_conversation_nodes, test_var_reset_triad, test_var_bound_triad, test_random_drawn,
         test_vars_restored_and_save_now, test_list_emptied_and_filled, test_dict_key_triads, test_hour_and_day_changed,
         test_schedule_cancel_triad, test_reset_idle_and_shift_date, test_systeme_nodes,
         test_theme_moves_and_per_theme_counts, test_visual_roundtrip, test_vocabulary_of_the_new_nodes,
         test_goldens_n3_only_gained_entries, test_shipped_graph_uses_only_g3_n3_nodes]


def main(argv):
    from tests.test_nodes_n1 import report_counts
    only = argv[argv.index("--only") + 1].split(",") if "--only" in argv else None
    failed = 0
    for fn in TESTS:
        if only and fn.__name__ not in only:
            continue
        try:
            fn()
            print("PASS", fn.__name__, flush=True)
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print("FAIL", fn.__name__, "%s: %s" % (type(e).__name__, e), flush=True)
    ran = len([f for f in TESTS if not only or f.__name__ in only])
    print(report_counts())
    print("nodes_n3 tests: %d passed, %d failed" % (ran - failed, failed))
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
