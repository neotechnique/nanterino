"""Tests of the lot N1 concept triads (2026-11-02): media, volume, mute, deaf, shown text, lists, dictionaries, timers,
robot journal, dashboard notifications, random choice.

logging: robotlog via tests.test_brain_graph (imported through tests.test_graph_vars for the shared helpers).

Purpose
    One behaviour test per new node: each ACTION's effect on a non-threaded Brain of the fake world (nanterino/sim.py),
    each TRIGGER posted by the real brain code path (a graph transition reacting to it changes a variable), each
    CONDITION reading the real state; the anti-loop of the new state-change triggers; the parser's refusals; the visual
    round trip of the new trigger filters; the vocabulary goldens changing only additively (pre-N1 copies); the server
    routes (read as text). `report_counts()` prints the node counts per family and per theme (the parity rule of
    Notes/HOWTO-add-node.md is enforced since lot N2 by tests.test_nodes_registry.test_node_parity).

Boundary
    Fake output (muted, FakeOut) and fake mic only: the live robot's audio, mute and deaf flags are never touched, and
    nanterino.server is never imported. Media files are written under /tmp/test_nodes_n1.

How to run (repo root):
    .venv/bin/python -m tests.test_nodes_n1            # ~3 s; --only name1,name2 ; --counts prints the table only
"""
import collections
import copy
import datetime
import json
import os
import shutil
import sys
import wave

sys.path.insert(0, "/opt/robot/lib")

import numpy as np  # noqa: E402

from nanterino import graph as G, graph_visual as V, journal as J, nodes, sim  # noqa: E402
from nanterino.brain import Brain  # noqa: E402
from nanterino.log import log  # noqa: E402
from tests.test_graph_vars import CFG, mini, parse, refused  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN = os.path.join(ROOT, "tests", "golden")
TMP = "/tmp/test_nodes_n1"
MONDAY = "2026-11-02T10:00:00"

# The lot N1 node ids (strip them and the vocabulary is the pre-N1 golden byte for byte).
N1 = {
    "actions": ["play_media", "set_volume", "set_mute", "set_deaf", "show_text", "say_list_item", "list_shuffle",
                "list_sort", "dict_clear", "log_note", "notify_dashboard", "random_choice"],
    "triggers": ["media_started", "media_finished", "volume_changed", "mute_changed", "deaf_changed", "text_shown",
                 "text_cleared", "list_item_said", "list_changed", "dict_changed", "timer_stopped", "notification_clicked",
                 "journal_entry"],
    "conditions": ["media_playing", "volume_compare", "is_muted", "is_deaf", "text_displayed", "list_index_exists",
                   "list_sorted", "list_count_compare", "dict_empty", "timer_running", "recent_error",
                   "notification_pending", "random_chance"],
}


# ---------------------------------------------------------------- report helper
def counts() -> dict:
    """Palette counts: {family: {"total": n, "themes": {theme: n}}}; triggers count the visible ones (not internal)."""
    out = {}
    for fam, reg in (("triggers", nodes.TRIGGERS), ("actions", nodes.ACTIONS), ("conditions", nodes.CONDITIONS)):
        vis = [n for n in reg.values() if not getattr(n, "internal", False)]
        out[fam] = {"total": len(vis), "themes": dict(collections.Counter(n.theme for n in vis))}
    return out


def report_counts() -> str:
    c = counts()
    themes = list(G.THEME_DOC)
    lines = ["%-14s %4s %4s %4s" % ("theme", "T", "A", "C")]
    for t in themes:
        row = [c[f]["themes"].get(t, 0) for f in ("triggers", "actions", "conditions")]
        if any(row):
            lines.append("%-14s %4d %4d %4d" % (t, *row))
    lines.append("%-14s %4d %4d %4d" % ("TOTAL", c["triggers"]["total"], c["actions"]["total"], c["conditions"]["total"]))
    return "\n".join(lines)


# ---------------------------------------------------------------- helpers
def media_dir():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    with wave.open(os.path.join(TMP, "bip.wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(np.zeros(2 * 4000, dtype=np.int16).tobytes())   # 0.5 s of stereo silence
    open(os.path.join(TMP, "notes.json"), "w").close()
    return TMP


def brain(raw, **cfg):
    clock = sim.SimClock()
    t0, wall0 = clock.t, datetime.datetime.fromisoformat(MONDAY).timestamp()
    rec, tts = sim.Rec(), sim.FakeTTS()
    out = sim.FakeOut(rec, tts, clock)
    b = Brain(dict(CFG, power="on", **cfg), out, sim.FakeSTT(), sim.FakeLLM(rec), tts, sim.FakeCorpus(), clock=clock,
              wall=lambda: wall0 + (clock.t - t0), mic=sim.FakeIn(rec), graph=parse(raw), threaded=False,
              start_state="veille")
    b.rng.seed(0)
    b.pump()
    return b, clock, rec


def adv(b, clock, seconds):
    for _ in range(int(round(seconds / 0.1))):
        clock.t += 0.1
        b._on_tick({"t": clock.t})
        b.pump()


def act(b, call, kw=None, **args):
    b.engine.actions[call](kw or {}, **args)
    b.pump()


def guard(b, call, kw=None, **args):
    return bool(b.engine.guards[call](kw or {}, **args))


def counter(event, counted, **extra):
    """A global transition that adds 1 to `var` each time `event` fires (proof that the trigger was posted)."""
    return dict({"on": event, "do": [{"add_var": {"name": counted, "delta": 1}}], "description": "compte " + event}, **extra)


def ints(*names, **lists):
    v = {"names": {n: {"type": "integer", "value": 0} for n in names}}
    if lists:
        v["lists"] = lists
    return v


def fired(b, event):
    return [e["event"] for e in b.trace()].count(event)


# ---------------------------------------------------------------- media
def test_play_media_triad():
    md = media_dir()
    raw = mini(glob=[counter("media_started", "s"), counter("media_finished", "f")], variables=ints("s", "f"))
    b, clock, rec = brain(raw, media_dir=md)
    assert not guard(b, "media_playing")
    act(b, "play_media", file="bip.wav")
    assert ("play", "song") in [tuple(e[:2]) for e in rec.events], rec.events[-3:]   # the speech output played it
    assert b.vars["s"] == 1 and b.vars["f"] == 0 and guard(b, "media_playing")
    adv(b, clock, 0.5)
    assert b.vars["f"] == 1 and not guard(b, "media_playing"), (b.vars, b._media)
    # unreadable / missing file: media_finished at once, no media_started
    act(b, "play_media", file="absent.wav")
    assert b.vars["s"] == 1 and b.vars["f"] == 2
    # the speech output busy with a phrase is not a media
    act(b, "say_text", text="Bonjour.")
    assert b.out.busy and not guard(b, "media_playing")
    adv(b, clock, 0.5)
    # stop cancels: no media_finished afterwards
    act(b, "play_media", file="bip.wav")
    b._cancel_all()
    adv(b, clock, 1.0)
    assert b.vars["s"] == 2 and b.vars["f"] == 2 and not guard(b, "media_playing")
    # validation: a .wav name of media/ only
    for bad in ("../x.wav", "son.mp3", ""):
        refused(mini(veille=[{"on": "start", "do": [{"play_media": {"file": bad}}]}]), "expected a .wav file name")
    # vocabulary: the field lists the playable files only
    v = G.vocabulary(dict(CFG, media_dir=md))
    a = next(x for x in v["actions"] if x["id"] == "play_media")["args"][0]
    assert a["type"] == "enum" and a["options"] == ["bip.wav"], a


# ---------------------------------------------------------------- volume / mute / deaf
def test_volume_triad_and_anti_loop():
    raw = mini(glob=[counter("volume_changed", "n"),
                     {"on": "volume_changed", "do": [{"set_volume": {"percent": 10}}], "description": "re-règle (anti-boucle)"}],
               variables=ints("n"))
    b, clock, rec = brain(raw)
    hook = []
    act(b, "set_volume", percent=40)
    assert b.var_value("volume") == 10, "the chain ran its set_volume (first match order)"
    assert b.vars["n"] == 1, "volume_changed fired once: the change made by its own chain posts nothing"
    assert guard(b, "volume_compare", op="<=", percent=10) and not guard(b, "volume_compare", op=">", percent=10)
    act(b, "set_volume", percent=10)            # unchanged: no event
    assert b.vars["n"] == 1
    b.volume_hook = hook.append               # server.py: through the speaker profile
    b.set_volume(0.55, external=True)         # the dashboard slider
    b.pump()
    assert hook == [0.55] and b.vars["n"] == 1, "the hook replaced out.volume (fake profile did not apply it)"
    b.volume_hook = None
    b.set_volume(0.55, external=True)
    b.pump()
    assert b.vars["n"] == 2 and b.var_value("volume") == 10, "dashboard change: event, then the chain re-set it"
    b2, _c, _r = brain(mini())
    act(b2, "set_volume", percent=250)
    assert b2.var_value("volume") == 100 and b2.out.volume == 1.0
    act(b2, "set_volume", percent=-5)
    assert b2.var_value("volume") == 0


def test_mute_triad():
    raw = mini(glob=[counter("mute_changed", "n")], variables=ints("n"))
    b, clock, rec = brain(raw)
    saved = []
    b.flag_hook = lambda k, v: saved.append((k, v))
    assert guard(b, "is_muted"), "the fake output starts muted"
    act(b, "set_mute", mode="on")              # already muted: nothing
    assert b.vars["n"] == 0 and saved == []
    act(b, "set_mute", mode="off")
    assert b.out.muted is False and not guard(b, "is_muted") and b.vars["n"] == 1 and saved == [("muted", False)]
    act(b, "set_mute", mode="on")
    assert b.out.muted is True and guard(b, "is_muted") and b.vars["n"] == 2 and ("cancel",) in [tuple(e[:1]) for e in rec.events]
    b.set_muted(False, external=True)          # dashboard button: event, no persistence by the brain
    b.pump()
    assert b.vars["n"] == 3 and len(saved) == 2
    refused(mini(veille=[{"on": "start", "do": [{"set_mute": {"mode": "oui"}}]}]), "expected on or off")


def test_deaf_triad():
    raw = mini(glob=[counter("deaf_changed", "n")], variables=ints("n"))
    b, clock, rec = brain(raw)
    saved = []
    b.flag_hook = lambda k, v: saved.append((k, v))
    assert not guard(b, "is_deaf")
    act(b, "set_deaf", mode="on")
    assert b.deaf is True and guard(b, "is_deaf") and b.vars["n"] == 1 and saved == [("deaf", True)]
    assert rec.events[-1][:2] == ["mic", "off"] or tuple(rec.events[-1][:2]) == ("mic", "off"), rec.events[-2:]
    act(b, "set_deaf", mode="on")
    assert b.vars["n"] == 1
    act(b, "set_deaf", mode="off")
    assert b.deaf is False and b.vars["n"] == 2 and saved[-1] == ("deaf", False)
    b.set_deaf(True)                           # server.py's call (dashboard): external, still posts
    b.pump()
    assert b.vars["n"] == 3


# ---------------------------------------------------------------- shown text
def test_show_text_triad():
    raw = mini(glob=[counter("text_shown", "s"), counter("text_cleared", "c")], variables=ints("s", "c"))
    b, clock, rec = brain(raw)
    act(b, "show_text", text="Bienvenue !", seconds=1)
    assert b.subtitle == "Bienvenue !" and guard(b, "text_displayed") and b.vars == {"s": 1, "c": 0}
    assert not [e for e in rec.events if e[0] == "play"], "show_text is silent"
    adv(b, clock, 0.5)
    assert guard(b, "text_displayed") and b.vars["c"] == 0
    adv(b, clock, 0.7)
    assert b.subtitle == "" and not guard(b, "text_displayed") and b.vars["c"] == 1
    act(b, "show_text", text="Autre", seconds=30)
    b.subtitle = "Je vous écoute."             # speech replaced it
    adv(b, clock, 0.2)
    assert b.vars["c"] == 2 and b.subtitle == "Je vous écoute." and not guard(b, "text_displayed")
    refused(mini(veille=[{"on": "start", "do": [{"show_text": {"text": "x", "seconds": 0}}]}]), "expected a number of seconds")


# ---------------------------------------------------------------- lists
LISTS = {"phrases": {"type": "phrase", "items": ["Un.", "Deux.", "Trois."]},
         "nums": {"type": "integer", "items": [3, 1, 2]},
         "mots": {"type": "string", "items": ["b", "A", "c"]},
         "autre": {"type": "integer", "items": []},
         "faq": {"kind": "dict", "type": "string", "items": {"a": "x"}}}


def test_say_list_item_triad():
    raw = mini(glob=[counter("list_item_said", "n")], variables=ints("n", **LISTS))
    b, clock, rec = brain(raw)
    act(b, "say_list_item", list="phrases", index=2)
    assert b.subtitle == "Deux." and b.vars["n"] == 0
    adv(b, clock, 0.5)
    assert b.vars["n"] == 1
    act(b, "say_list_item", list="phrases", index=-1)
    assert b.subtitle == "Trois."
    adv(b, clock, 0.5)
    act(b, "say_list_item", list="phrases", index=4)   # out of range: nothing said, list_item_said anyway (lot L27)
    adv(b, clock, 0.5)
    assert b.subtitle == "Trois." and b.vars["n"] == 3
    for i, ok in ((1, True), (3, True), (-3, True), (4, False), (0, False), (1.5, False), (-4, False)):
        assert guard(b, "list_index_exists", list="phrases", index=i) is ok, i
    refused(mini(veille=[{"on": "start", "do": [{"say_list_item": {"list": "nums", "index": 1}}]}], variables=ints(**LISTS)),
            "does not hold texts")


def test_list_change_triad():
    raw = mini(glob=[counter("list_changed", "n", var="nums")], variables=ints("n", **LISTS))
    g = parse(raw)
    b, clock, rec = brain(raw)
    assert b._watch["list_changed"] == frozenset({"nums"})
    assert not guard(b, "list_sorted", list="nums")
    act(b, "list_sort", list="nums")
    assert b.lists["nums"] == [1, 2, 3] and b.vars["n"] == 1 and guard(b, "list_sorted", list="nums")
    act(b, "list_sort", list="nums")             # already sorted: no event
    assert b.vars["n"] == 1
    act(b, "list_shuffle", list="nums")
    assert sorted(b.lists["nums"]) == [1, 2, 3]
    assert b.vars["n"] == (2 if b.lists["nums"] != [1, 2, 3] else 1)
    act(b, "list_sort", list="mots")             # texts without case, an unwatched list: no event
    assert b.lists["mots"] == ["A", "b", "c"] and guard(b, "list_sorted", list="mots")
    n = b.vars["n"]
    act(b, "list_add", list="autre", value=5)
    assert b.vars["n"] == n and not [e for e in list(b.events.queue) if e[2] == "list_changed"]
    act(b, "list_add", list="nums", value=9)
    act(b, "list_remove", list="nums", value=9)
    act(b, "list_remove", list="nums", value=42)  # nothing removed: no event
    assert b.vars["n"] == n + 2
    act(b, "list_clear", list="nums")
    act(b, "list_clear", list="nums")
    assert b.vars["n"] == n + 3 and b.lists["nums"] == []
    # counts (any list, every operator: a count is a number)
    assert guard(b, "list_count_compare", items="mots", op=">=", count=3)
    assert not guard(b, "list_count_compare", items="nums", op=">", count=0)
    parse(mini(veille=[{"on": "start", "when": [{"list_count_compare": {"items": "mots", "op": "<", "count": 2}}]}],
               variables=ints(**LISTS)))
    refused(mini(veille=[{"on": "start", "when": [{"var_compare": {"name": "n", "op": "<", "value": "x"}}]}],
                 variables={"names": {"n": {"type": "string", "value": ""}}}), "only compares")
    # validation of the trigger filter
    refused(mini(glob=[{"on": "list_changed", "var": "faq"}], variables=ints(**LISTS)), "needs `var:` = a declared list")
    refused(mini(glob=[{"on": "list_changed"}], variables=ints(**LISTS)), "needs `var:` = a declared list")
    refused(mini(glob=[{"on": "list_changed", "var": "nums", "value": 1}], variables=ints(**LISTS)), "takes no `value:`")
    refused(mini(veille=[{"on": "start", "do": [{"emit": {"event": "list_changed"}}]}]), "unknown event")
    assert g.states["veille"] is not None


def test_dict_change_triad():
    raw = mini(glob=[counter("dict_changed", "n", var="faq")], variables=ints("n", **LISTS))
    b, clock, rec = brain(raw)
    assert not guard(b, "dict_empty", dict="faq")
    act(b, "dict_clear", dict="faq")
    assert b.lists["faq"] == {} and b.vars["n"] == 1 and guard(b, "dict_empty", dict="faq")
    act(b, "dict_clear", dict="faq")
    assert b.vars["n"] == 1
    act(b, "dict_set", dict="faq", key="k", value="v")
    act(b, "dict_set", dict="faq", key="k", value="v")   # same value: no event
    act(b, "dict_remove", dict="faq", key="k")
    assert b.vars["n"] == 3 and guard(b, "dict_empty", dict="faq")
    refused(mini(glob=[{"on": "dict_changed", "var": "nums"}], variables=ints(**LISTS)), "a declared dictionary")


# ---------------------------------------------------------------- timers
def test_timer_stop_triad():
    v = ints("n")
    v["names"]["chrono"] = {"type": "timer", "value": None}
    raw = mini(glob=[counter("timer_stopped", "n", var="chrono")], variables=v)
    b, clock, rec = brain(raw)
    assert not guard(b, "timer_running", name="chrono")
    act(b, "timer_reset", name="chrono")          # not running: nothing stops
    assert b.vars["n"] == 0
    act(b, "timer_start", name="chrono")
    adv(b, clock, 0.3)
    assert guard(b, "timer_running", name="chrono")
    act(b, "timer_reset", name="chrono")
    assert b.vars["n"] == 1 and not guard(b, "timer_running", name="chrono")
    refused(mini(glob=[{"on": "timer_stopped", "var": "n"}], variables=v), "a timer variable")


# ---------------------------------------------------------------- robot journal
def test_journal_triad():
    raw = mini(glob=[counter("journal_entry", "err", value="error"), counter("journal_entry", "tous"),
                     {"on": "journal_entry", "do": [{"log_note": {"level": "info", "text": "relance (anti-boucle)"}}],
                      "description": "would loop without the anti-loop"}],
               variables=ints("err", "tous"))
    b, clock, rec = brain(raw)
    assert b._watch["journal_entry"] == frozenset({"error", "*"})
    act(b, "log_note", level="info", text="essai")
    assert b.vars == {"err": 0, "tous": 1}, b.vars     # first match: the unfiltered counter; the loop chain never runs again
    assert not guard(b, "recent_error", seconds=60)
    act(b, "log_note", level="error", text="panne simulée")
    assert b.vars["err"] == 1 and guard(b, "recent_error", seconds=5)
    adv(b, clock, 6)
    assert not guard(b, "recent_error", seconds=5) and guard(b, "recent_error", seconds=60)
    # the live robot's own warnings / errors through the log tap (attached explicitly: test brains stay detached)
    J.attach(b)
    robot = lambda: [e for e in b.journal_notes if e[2] == "robot"]   # noqa: E731
    try:
        tous = b.vars["tous"]
        log.error("test_nodes_n1: synthetic error for the journal tap (ignore)")
        b.pump()
        assert [e[1] for e in robot()] == ["error"], list(b.journal_notes)
        assert b.vars["err"] == 2 and b.vars["tous"] == tous + 1, b.vars
        log.warning("test_nodes_n1: second record within 0.2 s (ignore)")
        b.pump()
        assert [e[1] for e in robot()] == ["error", "warning"] and b.vars["tous"] == tous + 1, "kept but not posted (burst gap)"
        adv(b, clock, 0.3)
        log.warning("test_nodes_n1: third record after the gap (ignore)")
        b.pump()
        assert b.vars["tous"] == tous + 2 and b.vars["err"] == 2, b.vars
    finally:
        J.detach(b)
    n = len(robot())
    log.error("test_nodes_n1: detached brain sees nothing (ignore)")
    assert len(robot()) == n
    refused(mini(glob=[{"on": "journal_entry", "value": "fatal"}]), "must be one of")
    refused(mini(glob=[{"on": "journal_entry", "var": "x"}], variables=ints("x")), "takes no `var:`")


# ---------------------------------------------------------------- notifications
def test_notification_triad():
    raw = mini(glob=[counter("notification_clicked", "n")], variables=ints("n"))
    b, clock, rec = brain(raw)
    assert not guard(b, "notification_pending")
    act(b, "notify_dashboard", text="Batterie faible", level="warning")
    act(b, "notify_dashboard", text="Tout va bien", level="info")
    view = b.notifications_view()
    assert [n["text"] for n in view] == ["Batterie faible", "Tout va bien"] and guard(b, "notification_pending")
    assert b.click_notification(view[0]["id"]) is True
    b.pump()
    assert b.vars["n"] == 1 and len(b.notifications_view()) == 1
    assert b.click_notification(999) is False
    b.click_notification(view[1]["id"])
    b.pump()
    assert b.vars["n"] == 2 and not guard(b, "notification_pending")
    for i in range(25):
        b.notify("n%d" % i, "info")
    assert len(b.notifications_view()) == 20 and b.notifications_view()[0]["text"] == "n5"


# ---------------------------------------------------------------- random
def test_random_choice_and_chance():
    raw = mini(glob=[counter("var_changed", "m", var="pick")], variables=ints("pick", "m"))
    b, clock, rec = brain(raw)
    seen = set()
    for _ in range(60):
        act(b, "random_choice", name="pick", count=3)
        seen.add(b.vars["pick"])
    assert seen == {1, 2, 3}, seen
    assert b.vars["m"] >= 2, "random_choice writes through the variable target (var_changed)"
    act(b, "random_choice", name="pick", count=0)
    assert b.vars["pick"] == 1
    assert not any(guard(b, "random_chance", percent=0) for _ in range(2000)), "0 % never"
    assert all(guard(b, "random_chance", percent=100) for _ in range(50))
    hits = sum(guard(b, "random_chance", percent=50) for _ in range(400))
    assert 140 < hits < 260, hits


# ---------------------------------------------------------------- editor, vocabulary, server
def test_visual_roundtrip_of_new_trigger_filters():
    raw = mini(glob=[counter("list_changed", "n", var="nums"), counter("journal_entry", "n", value="warning"),
                     counter("journal_entry", "n"), counter("mute_changed", "n")],
               veille=[{"on": "start", "do": [{"play_media": {"file": "bip.wav"}}, {"set_mute": {"mode": "on"}},
                                              {"show_text": {"text": "Salut", "seconds": 3}}], "to": "a"}],
               variables=ints("n", **LISTS))
    want = parse(raw).to_dict()
    doc = V.to_visual(copy.deepcopy(raw))
    trig = [n["params"] for n in doc["nodes"] if n["kind"] == "trigger" and n["params"].get("event") == "journal_entry"]
    assert sorted(json.dumps(p, sort_keys=True) for p in trig) and all("name" not in p for p in trig), trig
    back, _layout, errs = V.from_visual(doc, CFG)
    assert not errs, errs
    assert parse(back).to_dict() == want


def test_vocabulary_of_the_new_kinds():
    v = G.vocabulary(CFG)
    acts = {a["id"]: a for a in v["actions"]}
    assert acts["set_mute"]["args"][0]["options"] == ["on", "off"] and acts["log_note"]["args"][0]["options"] == ["info", "warning", "error"]
    ev = {e["id"]: e for e in v["events"]}
    assert ev["journal_entry"]["args"][0]["name"] == "value" and ev["list_changed"]["args"][0]["type"] == "list"
    assert all(e not in [o for a in acts["emit"]["args"] for o in a["options"]] for e in G.WATCH_EVENTS)
    gd = {g["id"]: g for g in v["guards"]}
    assert [a["name"] for a in gd["list_count_compare"]["args"]] == ["items", "op", "count"]
    for fam, key in (("actions", "actions"), ("guards", "conditions"), ("events", "triggers")):
        ids = [x["id"] for x in v[fam]]
        assert all(i in ids for i in N1[key]), (fam, set(N1[key]) - set(ids))


def strip_ids(v: dict, ids: dict) -> dict:
    """The vocabulary without the given node ids ({"triggers"|"actions"|"conditions": [...]}; trigger ids also leave
    the event option lists), order kept."""
    v = dict(v)
    for fam, key in (("events", "triggers"), ("actions", "actions"), ("guards", "conditions")):
        v[fam] = [e for e in v[fam] if e["id"] not in ids.get(key, ())]
    for fam in ("actions", "guards"):
        v[fam] = [dict(e, args=[dict(a, options=[o for o in a["options"] if o not in ids.get("triggers", ())]) if "options" in a else a
                                for a in e["args"]]) for e in v[fam]]
    return v


def strip_n1(v: dict) -> dict:
    """The vocabulary without the lot N1 entries AND the entries of the later lots (N2: tests.test_nodes_n2.N2), so the
    pre-N1 / pre-M4 / pre-M5 additive checks keep comparing against their frozen copies."""
    from tests.test_nodes_n2 import N2   # lazy: test_nodes_n2 imports this module's helpers
    return strip_ids(strip_ids(v, N2), N1)


def test_goldens_n1_only_gained_entries():
    from tests.test_nodes_registry import golden_diff, vocab_dumps
    dumps = vocab_dumps(G)
    assert not golden_diff(dumps), "the N1 goldens differ: %s" % golden_diff(dumps)
    for name, text in dumps.items():
        with open(os.path.join(GOLDEN, name.replace(".json", ".pre-n1.json")), "rb") as f:
            old = f.read()
        stripped = json.dumps(strip_n1(json.loads(text)), ensure_ascii=False, indent=1) + "\n"
        assert stripped.encode("utf-8") == old, "%s minus the N1 entries is not the pre-N1 golden" % name


def test_server_routes_and_controls():
    src = open(os.path.join(ROOT, "nanterino", "server.py"), encoding="utf-8").read()
    for needle in ('@app.get("/api/notifications")', '@app.post("/api/notifications/click")',
                   '"notifications": brain.notifications_view()', "brain.set_muted(", "brain.set_volume(",
                   "brain.volume_hook =", "brain.flag_hook ="):
        assert needle in src, needle
    import ast
    ast.parse(src)


def test_ids_and_counts():
    for fam, reg in (("actions", nodes.ACTIONS), ("conditions", nodes.CONDITIONS), ("triggers", nodes.TRIGGERS)):
        assert all(i in reg for i in N1[fam]), (fam, set(N1[fam]) - set(reg))
    # CHANGED (lot N2): the totals are no longer pinned here (36 / 50 / 31 at N1); the parity rule T == A == C is
    # enforced by tests.test_nodes_registry.test_node_parity.
    c = counts()
    assert c["triggers"]["total"] == c["actions"]["total"] == c["conditions"]["total"], c
    print(report_counts())


# ---------------------------------------------------------------- lot L27: speaking actions always complete
def _spy(b):
    """Record every posted (kind, fields) of a simulator brain (scheduled events go through post too)."""
    seen, orig = [], b.post

    def post(kind, **kw):
        seen.append((kind, kw))
        orig(kind, **kw)
    b.post = post
    return seen


def test_speaking_actions_complete_with_nothing_to_say():
    lists = dict(LISTS, vide={"type": "phrase", "items": []})
    names = {n: {"type": "integer", "value": 0} for n in ("d", "li", "fin")}
    names["texte"] = {"type": "string", "value": ""}
    raw = mini(glob=[counter("say_done", "d"), counter("list_item_said", "li"), counter("answer_done", "fin")],
               variables={"names": names, "lists": lists})
    md = media_dir()
    b, clock, rec = brain(raw, media_dir=md)
    seen = _spy(b)
    cases = [("say_random", {"list": "vide"}, "say_done", "d"),
             ("say_list_item", {"list": "phrases", "index": 9}, "list_item_said", "li"),
             ("say_list_item", {"list": "vide", "index": 1}, "list_item_said", "li"),
             ("say_dict", {"dict": "faq", "key": "absente", "fallback": ""}, "say_done", "d"),
             ("say_var", {"name": "texte"}, "say_done", "d"),
             ("say_text", {"text": "  "}, "say_done", "d"),
             ("speak_phrase", {"text": "pas_de_cle", "done": "answer_done"}, "answer_done", "fin")]
    for call, args, event, var in cases:
        before, notes, n_play = b.vars[var], len(b.journal_notes), len([e for e in rec.events if e[0] == "play"])
        del seen[:]
        act(b, call, **args)
        assert b.vars[var] == before, (call, "the end event is delayed like a zero-length phrase")
        adv(b, clock, 0.3)
        assert b.vars[var] == before + 1, (call, b.vars)
        posted = [kw for k, kw in seen if k == event]
        assert len(posted) == 1 and posted[0].get("ok") is False and posted[0].get("reason"), (call, seen)
        assert [e[1:] for e in list(b.journal_notes)[notes:]] == [("warning", "graph")], (call, list(b.journal_notes))
        assert len([e for e in rec.events if e[0] == "play"]) == n_play, (call, "nothing is said")
    # stop / off in between drops it (gen bump), like any scheduled event
    act(b, "say_random", list="vide")
    b._cancel_all()
    d = b.vars["d"]
    adv(b, clock, 0.5)
    assert b.vars["d"] == d
    # play_media of an unreadable file: media_finished ok=False at once + a journal warning
    del seen[:]
    notes = len(b.journal_notes)
    act(b, "play_media", file="absent.wav")
    mf = [kw for k, kw in seen if k == "media_finished"]
    assert len(mf) == 1 and mf[0]["ok"] is False and mf[0]["reason"] == "unreadable", seen
    assert [e[1] for e in list(b.journal_notes)[notes:]] == ["warning"]
    # show_text with an empty text: text_shown / text_cleared still follow, with a journal warning
    del seen[:]
    notes = len(b.journal_notes)
    act(b, "show_text", text="", seconds=0.3)
    adv(b, clock, 0.5)
    assert [k for k, _kw in seen if k in ("text_shown", "text_cleared")] == ["text_shown", "text_cleared"], seen
    assert [e[1] for e in list(b.journal_notes)[notes:]] == ["warning"]


def test_empty_list_chain_does_not_trap():
    """Simulator scenario: state a says a phrase of an empty list and waits for say_done to go back to veille."""
    raw = mini(veille=[{"on": "intent.question", "to": "a"}],
               a=[{"on": "say_done", "to": "veille"}],
               variables={"lists": {"vide": {"type": "phrase", "items": []}}})
    raw["states"]["a"]["on_enter"] = [{"say_random": {"list": "vide"}}]
    b, clock, rec = brain(raw)
    b.engine.enter("a")
    b.state = "a"
    b.pump()
    adv(b, clock, 0.5)
    assert b.state == "veille", b.state
    # a state that re-enters itself on say_done does not spin the loop: one event per 0.15 s at most
    raw2 = mini(veille=[{"on": "say_done", "do": [{"say_random": {"list": "vide"}}]}],
                variables={"lists": {"vide": {"type": "phrase", "items": []}}})
    b2, clock2, _rec2 = brain(raw2)
    act(b2, "say_random", list="vide")
    adv(b2, clock2, 1.0)    # pump() would raise RuntimeError on an endless burst
    assert 4 <= fired(b2, "say_done") <= 10, fired(b2, "say_done")


def test_empty_list_diagnostic():
    lists = {"vide": {"type": "phrase", "items": []}, "rempli": {"type": "phrase", "items": []},
             "pleine": {"type": "phrase", "items": ["Oui."]}}
    raw = mini(veille=[{"on": "start", "do": [{"say_random": {"list": "vide"}}, {"say_random": {"list": "pleine"}},
                                               {"say_list_item": {"list": "rempli", "index": 1}}]},
                       {"on": "intent.question", "do": [{"list_add": {"list": "rempli", "value": "Bonjour."}}]}],
               a=[{"on": "start", "do": [{"say_list_item": {"list": "vide", "index": 2}}]}],
               variables={"lists": lists})
    g = parse(raw)
    d = [x for x in g.diagnostics if x[2] == "empty_list"]
    assert len(d) == 2 and all("'vide'" in x[1] for x in d), g.diagnostics
    assert {x[1].split(".")[0] for x in d} == {"say_random", "say_list_item"}, d
    # the editor path: a warning on the faulty action node (`at`) from /api/graph/check's from_visual
    doc = V.to_visual(raw)
    report = {}
    _r, _l, errors = V.from_visual(doc, CFG, report)
    ws = [w for w in report["warnings"] if w["kind"] == "empty_list"]
    assert not errors and len(ws) == 2, (errors, report["warnings"])
    for w in ws:
        node = next(n for n in doc["nodes"] if n["id"] == w["at"])
        assert node["params"]["action"] in ("say_random", "say_list_item") and node["params"]["args"]["list"] == "vide", node
    # the shipped graph uses no empty, never-filled list
    shipped = G.load_graph(G.DEFAULT_PATH, CFG)
    assert not [x for x in shipped.diagnostics if x[2] == "empty_list"], shipped.diagnostics


TESTS = [test_play_media_triad, test_volume_triad_and_anti_loop, test_mute_triad, test_deaf_triad,
         test_show_text_triad, test_say_list_item_triad, test_list_change_triad, test_dict_change_triad,
         test_timer_stop_triad, test_journal_triad, test_notification_triad, test_random_choice_and_chance,
         test_visual_roundtrip_of_new_trigger_filters, test_vocabulary_of_the_new_kinds, test_goldens_n1_only_gained_entries,
         test_server_routes_and_controls, test_ids_and_counts,
         test_speaking_actions_complete_with_nothing_to_say, test_empty_list_chain_does_not_trap, test_empty_list_diagnostic]


def main(argv):
    if "--counts" in argv:
        print(report_counts())
        return 0
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
    shutil.rmtree(TMP, ignore_errors=True)
    ran = len([f for f in TESTS if not only or f.__name__ in only])
    print("nodes_n1 tests: %d passed, %d failed" % (ran - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
