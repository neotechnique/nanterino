"""Tests of the lot N2 parity nodes (2026-11-02): one trigger and one condition per action concept where it makes sense.

logging: robotlog via tests.test_brain_graph (imported through tests.test_graph_vars / tests.test_nodes_n1 helpers).

Purpose
    One behaviour test per new node, on a non-threaded Brain of the fake world (nanterino/sim.py): each TRIGGER is posted
    by the real brain code path (Brain.mic_set, set_expression / _expr_tick, set_gaze / _go, start_song / _sing,
    set_faces, the action modules) and a global transition reacting to it adds 1 to a counter; each CONDITION reads the
    real state (mic, face, song, conversation clock, last sentence, scheduled events, event times, wall clock); the
    anti-loop of the new state-change triggers; the parser's refusals of the new condition kinds (expression, gaze
    mode, event); the visual round trip; the vocabulary goldens changing only additively (pre-N2 copies). The parity
    rule itself (T == A == C) is tests.test_nodes_registry.test_node_parity.

Boundary
    Fake output (muted FakeOut) and fake mic (FakeIn) only: the live robot's audio, mic, mute and deaf flags are never
    touched, and nanterino.server is never imported.

How to run (repo root):
    .venv/bin/python -m tests.test_nodes_n2            # ~3 s; --only name1,name2
"""
import copy
import json
import os
import sys

sys.path.insert(0, "/opt/robot/lib")

from nanterino import brain as brain_mod, graph as G, graph_visual as V  # noqa: E402
from tests.test_graph_vars import CFG, mini, parse, refused  # noqa: E402
from tests.test_nodes_n1 import (GOLDEN, LISTS, act, adv, brain, counter, guard, ints, report_counts,  # noqa: E402
                                 strip_ids)

# The lot N2 node ids (strip them and the vocabulary is the pre-N2 golden byte for byte).
N2 = {
    "actions": [],
    "triggers": ["mic_opened", "mic_closed", "expression_changed", "gaze_changed", "song_started", "song_finished",
                 "answer_started", "conversation_cleared", "conversation_started", "conversation_ended", "turn_counted",
                 "list_item_added", "list_item_removed", "face_count_changed"],
    "conditions": ["is_singing", "conversation_active", "conversation_duration", "first_turn", "turns_compare",
                   "utterance_contains", "is_question", "utterance_length", "expression_is", "gaze_is", "face_visible",
                   "face_count_compare", "is_on", "state_age", "scheduled_pending", "month_compare", "event_recent",
                   "mic_level_compare", "silence_since"],
}


def queued(b, event):
    return [e for e in list(b.events.queue) if e[2] == event]


# ---------------------------------------------------------------- micro
def test_mic_triad_and_anti_loop():
    raw = mini(glob=[counter("mic_opened", "o"), counter("mic_closed", "c"),
                     {"on": "mic_closed", "do": ["mic_on"], "description": "rouvre (anti-boucle)"}],
               variables=ints("o", "c"))
    b, clock, rec = brain(raw)
    assert not b.mic.active and not guard(b, "mic_active")
    act(b, "mic_on")
    assert b.mic.active and b.vars == {"o": 1, "c": 0}, b.vars
    act(b, "mic_on")                       # already open: the real state did not change, nothing posted
    assert b.vars["o"] == 1
    act(b, "mic_off")                      # closed: counted; the re-open chain (depth 1) opens it, mic_opened dropped
    assert b.vars == {"o": 1, "c": 1} and b.mic.active, b.vars
    b.set_deaf(True)                       # the dashboard's deaf button closes it through the same path
    b.pump()
    assert b.vars["c"] == 2 and not b.mic.active, "the re-open chain cannot bypass the deaf mode"
    act(b, "mic_on")                       # deaf: never opens, nothing posted
    assert b.vars["o"] == 1 and not b.mic.active
    b.set_deaf(False, external=True)       # back in veille: the mic opens again
    b.pump()
    assert b.mic.active and b.vars["o"] == 2, b.vars


def test_mic_anti_loop():
    raw = mini(glob=[{"on": "mic_closed", "do": ["mic_on"], "description": "rouvre"},
                     {"on": "mic_opened", "do": ["mic_off"], "description": "referme"}])
    b, clock, rec = brain(raw)
    act(b, "mic_on")                       # opened -> chain closes (depth 1) -> mic_closed dropped: no ping-pong
    assert not b.mic.active and not queued(b, "mic_closed") and not queued(b, "mic_opened")


def test_mic_level_and_silence():
    b, clock, rec = brain(mini())
    b.mic.level = 0.42
    assert not guard(b, "mic_level_compare", op=">", percent=0), "closed mic reads 0"
    act(b, "mic_on")
    assert guard(b, "mic_level_compare", op=">=", percent=42) and not guard(b, "mic_level_compare", op=">", percent=42)
    b.mic.level = 3.0
    assert guard(b, "mic_level_compare", op="=", percent=100), "capped at 100 like the dashboard bar"
    act(b, "reset_silence")
    adv(b, clock, 2.0)
    assert guard(b, "silence_since", op=">=", seconds=1.9) and not guard(b, "silence_since", op=">=", seconds=3)
    act(b, "reset_silence")
    assert guard(b, "silence_since", op="<", seconds=0.5)


# ---------------------------------------------------------------- vision
def test_expression_triad():
    raw = mini(glob=[counter("expression_changed", "n")], variables=ints("n"))
    b, clock, rec = brain(raw)
    assert guard(b, "expression_is", name="neutre") and not guard(b, "expression_is", name="content")
    act(b, "set_expression", name="content", seconds=1)
    assert b.vars["n"] == 1 and guard(b, "expression_is", name="content")
    act(b, "set_expression", name="content", seconds=1)   # same visible expression: no event
    assert b.vars["n"] == 1
    adv(b, clock, 1.3)                                    # expiry on the heartbeat: back to neutre, one more event
    assert b.vars["n"] == 2 and guard(b, "expression_is", name="neutre"), b.vars
    adv(b, clock, 1.0)
    assert b.vars["n"] == 2


def test_gaze_triad():
    raw = mini(veille=[{"on": "start", "to": "a"}], a=[{"on": "stop", "to": "veille"}],
               glob=[counter("gaze_changed", "n")], variables=ints("n"))
    b, clock, rec = brain(raw)
    assert guard(b, "gaze_is", mode="suivre")
    act(b, "gaze", mode="errer")
    assert b.vars["n"] == 1 and guard(b, "gaze_is", mode="errer") and not guard(b, "gaze_is", mode="suivre")
    act(b, "gaze", mode="errer")
    assert b.vars["n"] == 1
    b.post("start")
    b.pump()
    act(b, "gaze", mode="devant")
    b.post("stop")                       # back in veille: gaze returns to suivre (real path: Brain._go)
    b.pump()
    assert b.state == "veille" and guard(b, "gaze_is", mode="suivre") and b.vars["n"] == 3, (b.state, b.vars)


def test_face_count_triad():
    raw = mini(glob=[counter("face_count_changed", "n")], variables=ints("n"))
    b, clock, rec = brain(raw)
    assert not guard(b, "face_visible") and guard(b, "face_count_compare", op="=", count=0)
    b.set_faces(1)                       # the vision thread's callback (external: depth 1)
    b.pump()
    assert b.vars["n"] == 1 and guard(b, "face_visible")
    b.set_faces(1)
    b.pump()
    assert b.vars["n"] == 1, "same count: no event"
    b.set_faces(3)
    b.pump()
    assert b.vars["n"] == 2 and guard(b, "face_count_compare", op=">=", count=2)
    b.set_faces(0)
    b.pump()
    assert b.vars["n"] == 3 and not guard(b, "face_visible") and not guard(b, "face_count_compare", op=">", count=0)


# ---------------------------------------------------------------- parole
def test_song_triad():
    raw = mini(glob=[counter("song_started", "s"), counter("song_finished", "f"), counter("answer_done", "d")],
               variables=ints("s", "f", "d"))
    b, clock, rec = brain(raw)
    assert not guard(b, "is_singing")
    act(b, "start_sing")
    assert b.vars["s"] == 1 and guard(b, "is_singing")
    adv(b, clock, brain_mod.SIM_SONG_S + 0.2)
    assert b.vars == {"s": 1, "f": 1, "d": 1} and not guard(b, "is_singing"), b.vars
    act(b, "start_sing")
    b._cancel_all()                      # stop / hush / off: no song_finished, not singing any more
    assert not guard(b, "is_singing")
    adv(b, clock, brain_mod.SIM_SONG_S + 0.2)
    assert b.vars == {"s": 2, "f": 1, "d": 1}, b.vars


# ---------------------------------------------------------------- conversation
def test_conversation_start_end_and_clock():
    raw = mini(veille=[{"on": "start", "to": "a"}], a=[{"on": "stop", "to": "veille"}, {"on": "off", "to": "eteint"}],
               glob=[counter("conversation_started", "s"), counter("conversation_ended", "e")], variables=ints("s", "e"))
    b, clock, rec = brain(raw)
    assert not guard(b, "conversation_active") and guard(b, "is_on")
    assert not guard(b, "conversation_duration", op=">=", seconds=0), "no conversation: false"
    b.post("start")
    b.pump()
    assert b.state == "a" and b.vars["s"] == 1 and guard(b, "conversation_active")
    adv(b, clock, 2.0)
    assert guard(b, "conversation_duration", op=">=", seconds=1.9) and not guard(b, "conversation_duration", op=">", seconds=3)
    assert guard(b, "state_age", op=">=", seconds=1.9) and not guard(b, "state_age", op=">=", seconds=3)
    b.post("stop")
    b.pump()
    assert b.state == "veille" and b.vars == {"s": 1, "e": 1} and not guard(b, "conversation_active")
    assert guard(b, "state_age", op="<", seconds=0.5), "the state clock restarted"
    b.post("start")
    b.pump()
    b.post("off")
    b.pump()
    assert b.state == "eteint" and b.vars == {"s": 2, "e": 2} and not guard(b, "is_on")


def test_answer_turn_and_clear_triads():
    raw = mini(glob=[counter("answer_started", "a"), counter("turn_counted", "t"), counter("conversation_cleared", "c")],
               variables=ints("a", "t", "c"))
    b, clock, rec = brain(raw)
    act(b, "start_answer", kw={"text": "Où est le musée ?", "t_end": 0.0})
    assert b.vars["a"] == 1
    assert guard(b, "first_turn") and guard(b, "turns_compare", op="=", count=0)
    act(b, "count_turn")
    act(b, "count_turn")
    assert b.vars["t"] == 2 and not guard(b, "first_turn") and guard(b, "turns_compare", op=">=", count=2)
    assert not guard(b, "turns_compare", op=">", count=2)
    act(b, "clear_conversation")
    assert b.vars["c"] == 1 and guard(b, "first_turn")


def test_utterance_conditions():
    b, clock, rec = brain(mini())
    kw = {"text": "Où sont les toilettes"}
    assert guard(b, "is_question", kw=kw), "question word without ?"
    assert guard(b, "utterance_contains", kw=kw, text="TOILETTES") and not guard(b, "utterance_contains", kw=kw, text="musée")
    assert not guard(b, "utterance_contains", kw=kw, text="  "), "empty text: false"
    assert guard(b, "utterance_length", kw=kw, op="=", count=4) and not guard(b, "utterance_length", kw=kw, op=">", count=4)
    assert not guard(b, "is_question", kw={"text": "Je cherche le parc."})
    assert guard(b, "is_question", kw={"text": "Le parc, c'est loin ?"})
    assert guard(b, "is_question", kw={"text": "Qu'est-ce que c'est"})
    assert guard(b, "utterance_length", op="=", count=0), "nothing heard yet: 0 words"
    b.post("ask", text="Bonjour robot")       # the real path keeps the last sentence ($utterance) for later chains
    b.pump()
    assert guard(b, "utterance_contains", text="robot") and guard(b, "utterance_length", op="=", count=2)


# ---------------------------------------------------------------- listes
def test_list_item_triads():
    raw = mini(glob=[counter("list_item_added", "a", var="nums"), counter("list_item_removed", "r", var="nums"),
                     {"on": "list_item_added", "var": "mots", "do": [{"set_var": {"name": "dernier", "value": "$utterance"}}],
                      "description": "unused (other list)"}],
               variables={"names": dict(ints("a", "r")["names"], dernier={"type": "string", "value": ""}), "lists": LISTS})
    b, clock, rec = brain(raw)
    assert b._watch["list_item_added"] == frozenset({"nums", "mots"}) and b._watch["list_item_removed"] == frozenset({"nums"})
    act(b, "list_add", list="nums", value=7)
    assert b.vars["a"] == 1 and b.lists["nums"][-1] == 7
    ev = []
    b.post = lambda kind, **kw: ev.append((kind, kw))   # observe the payload of the next posts
    act(b, "list_add", list="nums", value=8)
    del b.post
    assert ("list_item_added", {"depth": 1, "name": "nums", "value": 8}) in ev, ev
    b.pump()
    act(b, "list_remove", list="nums", value=7)
    act(b, "list_remove", list="nums", value=99)       # absent: nothing removed, no event
    assert b.vars["r"] == 1, b.vars
    act(b, "list_add", list="autre", value=1)          # unwatched list: never posted
    assert not queued(b, "list_item_added")
    refused(mini(glob=[{"on": "list_item_added"}]), "needs `var:`")
    refused(mini(glob=[{"on": "list_item_removed", "var": "faq"}], variables={"lists": LISTS}), "a declared list")


def test_remember_utterance_posts_item_added():
    raw = mini(glob=[counter("list_item_added", "a", var="mots")], variables=ints("a", **LISTS))
    b, clock, rec = brain(raw)
    act(b, "remember_utterance", kw={"text": "Bonjour"}, list="mots")
    assert b.vars["a"] == 1 and b.lists["mots"][-1] == "Bonjour"


# ---------------------------------------------------------------- temps / evenements / systeme
def test_scheduled_pending_and_event_recent():
    raw = mini(veille=[{"on": "start", "do": [{"add_var": {"name": "n", "delta": 1}}]}], variables=ints("n"))
    b, clock, rec = brain(raw)
    assert not guard(b, "scheduled_pending", event="start") and not guard(b, "event_recent", event="start", seconds=60)
    act(b, "schedule", event="start", delay=2)
    assert guard(b, "scheduled_pending", event="start") and not guard(b, "scheduled_pending", event="stop")
    adv(b, clock, 2.2)
    assert b.vars["n"] == 1 and not guard(b, "scheduled_pending", event="start")
    assert guard(b, "event_recent", event="start", seconds=0.5)
    adv(b, clock, 1.0)
    assert not guard(b, "event_recent", event="start", seconds=0.5) and guard(b, "event_recent", event="start", seconds=2)
    act(b, "schedule", event="start", delay=2)
    b._cancel_all()                      # a stop / off cancels it: not pending any more
    assert not guard(b, "scheduled_pending", event="start")
    act(b, "emit", event="sing")         # emitted events count too (they bypass the queue)
    assert guard(b, "event_recent", event="sing", seconds=0)


def test_month_compare():
    b, clock, rec = brain(mini())        # wall clock: Monday 2026-11-02
    assert guard(b, "month_compare", op="=", count=11) and guard(b, "month_compare", op=">=", count=9)
    assert not guard(b, "month_compare", op="<", count=11)


# ---------------------------------------------------------------- parser, editor, vocabulary
def test_parser_refuses_bad_enum_arguments():
    def cond(c):
        return mini(veille=[{"on": "start", "when": [c], "to": "a"}])
    parse(cond({"expression_is": {"name": "content"}}))
    parse(cond({"not": {"gaze_is": {"mode": "errer"}}}))
    parse(cond({"event_recent": {"event": "visage", "seconds": 5}}))
    refused(cond({"expression_is": {"name": "furieux"}}), "unknown expression 'furieux'")
    refused(cond({"gaze_is": {"mode": "loucher"}}), "unknown gaze mode 'loucher'")
    refused(cond({"scheduled_pending": {"event": "tick"}}), "unknown event 'tick'")
    refused(cond({"scheduled_pending": {"event": "list_changed"}}), "unknown event 'list_changed'")
    refused(cond({"event_recent": {"event": "nope", "seconds": 1}}), "unknown event 'nope'")
    refused(cond({"turns_compare": {"op": "<<", "count": 1}}), "unknown operator")
    refused(cond({"state_age": {"op": ">", "seconds": -1}}), "seconds >= 0")


def test_visual_roundtrip():
    raw = mini(glob=[counter("list_item_added", "n", var="nums"), counter("mic_opened", "n"),
                     counter("conversation_started", "n")],
               veille=[{"on": "start", "when": [{"expression_is": {"name": "triste"}}, {"not": {"gaze_is": {"mode": "errer"}}},
                                                 {"event_recent": {"event": "visage", "seconds": 3}}, "is_question",
                                                 {"utterance_contains": {"text": "parc"}}, {"turns_compare": {"op": ">", "count": 2}}],
                        "to": "a"}],
               variables=ints("n", **LISTS))
    want = parse(raw).to_dict()
    doc = V.to_visual(copy.deepcopy(raw))
    back, _layout, errs = V.from_visual(doc, CFG)
    assert not errs, errs
    assert parse(back).to_dict() == want


def test_vocabulary_of_the_new_conditions():
    v = G.vocabulary(CFG)
    gd = {g["id"]: g for g in v["guards"]}
    assert gd["expression_is"]["args"][0]["options"] == list(G.EXPRESSIONS)
    assert gd["gaze_is"]["args"][0]["options"] == list(G.GAZE_MODES)
    ev_opts = gd["event_recent"]["args"][0]["options"]
    emit = next(a for a in v["actions"] if a["id"] == "emit")["args"][0]["options"]
    assert ev_opts == emit and "conversation_started" in ev_opts and "list_item_added" not in ev_opts
    assert [a["name"] for a in gd["utterance_contains"]["args"]] == ["text"] and gd["utterance_contains"]["args"][0]["props"] == "string"
    for fam, key in (("events", "triggers"), ("guards", "conditions")):
        ids = [x["id"] for x in v[fam]]
        assert all(i in ids for i in N2[key]), (fam, set(N2[key]) - set(ids))


def test_goldens_n2_only_gained_entries():
    from tests.test_nodes_registry import golden_diff, vocab_dumps
    dumps = vocab_dumps(G)
    assert not golden_diff(dumps), "the N2 goldens differ: %s" % golden_diff(dumps)
    for name, text in dumps.items():
        with open(os.path.join(GOLDEN, name.replace(".json", ".pre-n2.json")), "rb") as f:
            old = f.read()
        from tests.test_nodes_n3 import strip_n3   # lot N3: its entries out, the moved themes restored first
        stripped = json.dumps(strip_ids(strip_n3(json.loads(text)), N2), ensure_ascii=False, indent=1) + "\n"
        assert stripped.encode("utf-8") == old, "%s minus the N2 entries is not the pre-N2 golden" % name


def test_shipped_graph_uses_no_n2_node():
    """The shipped graph.yaml was unchanged by N2 (the user decides where to use the new nodes); the user approved G2
    (2026-11-02, tests/golden/behaviour-changes-G2.md), which uses exactly these N2 nodes, and no other."""
    text = open(G.DEFAULT_PATH, encoding="utf-8").read()
    used = [i for i in N2["triggers"] + N2["conditions"] if i in text]
    assert sorted(used) == ["conversation_ended", "conversation_started", "face_count_compare"], used


TESTS = [test_mic_triad_and_anti_loop, test_mic_anti_loop, test_mic_level_and_silence, test_expression_triad,
         test_gaze_triad, test_face_count_triad, test_song_triad, test_conversation_start_end_and_clock,
         test_answer_turn_and_clear_triads, test_utterance_conditions, test_list_item_triads,
         test_remember_utterance_posts_item_added, test_scheduled_pending_and_event_recent, test_month_compare,
         test_parser_refuses_bad_enum_arguments, test_visual_roundtrip, test_vocabulary_of_the_new_conditions,
         test_goldens_n2_only_gained_entries, test_shipped_graph_uses_no_n2_node]


def main(argv):
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
    print("nodes_n2 tests: %d passed, %d failed" % (ran - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
