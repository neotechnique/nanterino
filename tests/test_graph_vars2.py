"""Tests of the variables v2 (lot L11, 2026-11-01): types, bounds, scopes, persistence, lists, dictionaries, time.

logging: robotlog via tests.test_brain_graph (imported through tests.test_graph_vars for the shared helpers).

Purpose
    Plan L11 "Tests": every new type (valid and invalid), min / max clamping and the out-of-bounds diagnostic, the
    conversation scope, persistence (temporary folder: round trip, corrupt file, type change, write rate limit, reset),
    the shuffle bag without repeats, history lists, dictionaries, the time conditions on the simulated clock,
    timer_reached once per start with its anti-loop, the new read-only system variables, the vocabulary the editor
    (lot L12) consumes and the visual round trip of the new keys.

Boundary
    Pure functions, the simulator and a non-threaded Brain on the fake world of nanterino/sim.py (manual monotonic
    clock + a wall clock derived from it, muted fake output, no thread). Files are only written under /tmp/test_graph_vars2.
    The live robot, its state/vars.json and nanterino.server are never touched (server.py is read as text).

How to run (repo root):
    .venv/bin/python -m tests.test_graph_vars2          # ~3 s
"""
import copy
import datetime
import json
import os
import shutil
import sys

sys.path.insert(0, "/opt/robot/lib")

from nanterino import graph as G, graph_visual as V, sim  # noqa: E402
from nanterino.brain import Brain  # noqa: E402
from nanterino.var_store import VarStore  # noqa: E402
from tests.test_graph_vars import CFG, TABLER, mini, parse, refused, run  # noqa: E402

TMP = "/tmp/test_graph_vars2"
MONDAY = "2026-11-02T10:00:00"   # a Monday ("lun")


# ---------------------------------------------------------------- helpers
def brain(raw, start=MONDAY, store=None):
    """Non-threaded Brain whose wall clock follows the manual clock from `start` (deterministic time)."""
    clock = sim.SimClock()
    t0, wall0 = clock.t, datetime.datetime.fromisoformat(start).timestamp()
    rec, tts = sim.Rec(), sim.FakeTTS()
    out = sim.FakeOut(rec, tts, clock)
    b = Brain(dict(CFG, power="on"), out, sim.FakeSTT(), sim.FakeLLM(rec), tts, sim.FakeCorpus(), clock=clock,
              wall=lambda: wall0 + (clock.t - t0), mic=sim.FakeIn(rec), graph=parse(raw), threaded=False,
              start_state="veille", var_store=store)
    b.rng.seed(0)
    b.pump()
    return b, clock


def adv(b, clock, seconds):
    """Advance virtual time in 0.1 s heartbeats (same path as the live 10 Hz tick)."""
    for _ in range(int(round(seconds / 0.1))):
        clock.t += 0.1
        b._on_tick({"t": clock.t})
        b.pump()


def act(b, call, kw=None, **args):
    b.engine.actions[call](kw or {}, **args)
    b.pump()


def guard(b, call, kw=None, **args):
    return bool(b.engine.guards[call](kw or {}, **args))


def tmpdir():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    return TMP


ALL = {"names": {
    "n": {"type": "integer", "value": 3, "min": 0, "max": 10, "step": 1},
    "x": {"type": "number", "value": 0.5, "min": -1, "max": 1, "step": 0.1},
    "pc": {"type": "percent", "value": 50},
    "rdv": {"type": "datetime", "value": "2026-11-02T09:00"},
    "vide": {"type": "datetime", "value": None},
    "chrono": {"type": "timer", "value": None},
    "mine": {"type": "expression", "value": "content"},
    "yeux": {"type": "gaze", "value": "errer"},
    "dit": {"type": "phrase", "value": "Bonjour à tous."},
    "son": {"type": "media", "value": "chanson.wav"},
    "qui": {"type": "intent_ref", "value": "question"},
    "laquelle": {"type": "list_ref", "value": "faq"},
    "ou": {"type": "state_ref", "value": "a"},
    "teinte": {"type": "color", "value": "#ff8800"},
    "p2": {"type": "vector2", "value": [1, 2.5]},
    "p3": {"type": "vector3", "value": [0, 0, 1]},
    "conv": {"type": "integer", "value": 0, "scope": "conversation"},
}, "lists": {
    "faq": {"kind": "dict", "type": "phrase", "items": {"horaires": "Ouvert de 10 h à 18 h.", "toilettes": "Au fond à gauche."}},
    "scores": {"kind": "dict", "type": "integer", "items": {"alice": 3}},
    "sac": {"type": "string", "items": ["a", "b", "c", "d"], "mode": "shuffle"},
    "derniers": {"type": "phrase", "items": [], "mode": "history", "max": 2},
    "court": {"type": "integer", "items": [1, 2], "max": 3},
    "points": {"type": "vector2", "items": [[0, 0], [1, 1]]},
    "visages": {"type": "expression", "items": ["content", "triste"]},
    "conv_l": {"type": "string", "items": ["x"], "scope": "conversation"},
}}


# ---------------------------------------------------------------- types
def test_every_new_type_is_validated():
    g = parse(mini(variables=ALL))
    assert {v.name: v.type for v in g.variables.values()}["p3"] == "vector3"
    assert g.variables["n"].vmax == 10 and g.variables["conv"].scope == "conversation"
    assert g.lists["faq"].kind == "dict" and dict(g.lists["faq"].items)["toilettes"] == "Au fond à gauche."
    assert g.lists["derniers"].mode == "history" and g.lists["derniers"].maxlen == 2
    # the raw view round-trips the new keys and nothing more for old-style variables
    raw = g.variables_raw()
    assert raw["names"]["n"] == {"type": "integer", "value": 3, "min": 0, "max": 10, "step": 1}
    assert raw["names"]["conv"] == {"type": "integer", "value": 0, "scope": "conversation"}
    assert raw["lists"]["faq"]["kind"] == "dict" and raw["lists"]["derniers"] == {"type": "phrase", "items": [], "mode": "history", "max": 2}
    assert parse(mini(variables=raw)).variables_raw() == raw
    bad = [({"names": {"v": {"type": "integer", "value": 1.5}}}, "not a valid integer"),
           ({"names": {"v": {"type": "integer", "value": True}}}, "not a valid integer"),
           ({"names": {"v": {"type": "percent", "value": 101}}}, "not a valid percent"),
           ({"names": {"v": {"type": "datetime", "value": "demain"}}}, "not a valid datetime"),
           ({"names": {"v": {"type": "datetime", "value": "2026-13-01T10:00"}}}, "not a valid datetime"),
           ({"names": {"v": {"type": "timer", "value": 12}}}, "not a valid timer"),
           ({"names": {"v": {"type": "expression", "value": "furieux"}}}, "not a valid expression"),
           ({"names": {"v": {"type": "gaze", "value": "loin"}}}, "not a valid gaze"),
           ({"names": {"v": {"type": "phrase", "value": "x" * 301}}}, "not a valid phrase"),
           ({"names": {"v": {"type": "media", "value": "../etc/passwd"}}}, "not a valid media"),
           ({"names": {"v": {"type": "intent_ref", "value": "personne"}}}, "not a valid intent_ref"),
           ({"names": {"v": {"type": "list_ref", "value": "aucune"}}}, "not a valid list_ref"),
           ({"names": {"v": {"type": "state_ref", "value": "nulle_part"}}}, "not a valid state_ref"),
           ({"names": {"v": {"type": "color", "value": "rouge"}}}, "not a valid color"),
           ({"names": {"v": {"type": "vector2", "value": [1, 2, 3]}}}, "not a valid vector2"),
           ({"names": {"v": {"type": "vector3", "value": [1, "2", 3]}}}, "not a valid vector3"),
           # bounds, scope, persist
           ({"names": {"v": {"type": "integer", "value": 20, "max": 10}}}, "outside [None, 10]"),
           ({"names": {"v": {"type": "integer", "value": 0, "min": 0.5}}}, "`min:` must be an integer"),
           ({"names": {"v": {"type": "number", "value": 0, "min": 2, "max": 1}}}, "`min:` is greater than `max:`"),
           ({"names": {"v": {"type": "number", "value": 0, "step": 0}}}, "`step:` must be a number > 0"),
           ({"names": {"v": {"type": "string", "value": "", "max": 3}}}, "only go with types integer, number"),
           ({"names": {"v": {"type": "bool", "value": True, "scope": "monde"}}}, "`scope:` must be one of"),
           ({"names": {"v": {"type": "bool", "value": True, "persist": "oui"}}}, "`persist:` must be true or false"),
           ({"names": {"v": {"type": "bool", "value": True, "scope": "conversation", "persist": True}}}, "needs `scope: global`"),
           # lists
           ({"lists": {"l": {"type": "timer", "items": []}}}, "type must be one of"),
           ({"lists": {"l": {"type": "choice", "items": []}}}, "type must be one of"),
           ({"lists": {"l": {"type": "vector2", "items": [[1, 2], [3]]}}}, "item #2"),
           ({"lists": {"l": {"type": "string", "items": [], "mode": "pile"}}}, "mode must be one of"),
           ({"lists": {"l": {"type": "string", "items": [], "mode": "history"}}}, "mode history needs `max:`"),
           ({"lists": {"l": {"type": "string", "items": ["a", "b"], "max": 1}}}, "more than `max:`"),
           ({"lists": {"l": {"type": "string", "items": [], "max": 0}}}, "`max:` must be an integer"),
           ({"lists": {"l": {"type": "string", "from": "refusal_words", "mode": "history", "max": 2}}}, "a bound list is read-only"),
           ({"lists": {"l": {"type": "string", "from": "refusal_words", "persist": True}}}, "a bound list is read-only"),
           ({"lists": {"l": {"kind": "table", "items": []}}}, "kind must be one of"),
           ({"lists": {"d": {"kind": "dict", "type": "string", "from": "refusal_words"}}}, "it cannot be bound"),
           ({"lists": {"d": {"kind": "dict", "type": "string", "items": ["a"]}}}, "must be a mapping"),
           ({"lists": {"d": {"kind": "dict", "type": "integer", "items": {"a": "un"}}}}, "not a valid integer"),
           ({"lists": {"d": {"kind": "dict", "type": "string", "items": {"$k": "v"}}}}, "not starting with $"),
           ({"lists": {"d": {"kind": "dict", "type": "string", "items": {}, "mode": "shuffle"}}}, "only go with kind list")]
    for block, frag in bad:
        refused(mini(variables=block), frag)
    # a bound list may use the shuffle bag (read-only, nothing else)
    assert parse(mini(variables={"lists": {"l": {"type": "string", "from": "refusal_words", "mode": "shuffle"}}})).lists["l"].mode == "shuffle"
    # references across types: numbers mix, texts mix, a text-like value feeds a string / phrase, not the reverse
    ok = mini(veille=[{"on": "start", "do": [{"set_var": {"name": "x", "value": "$n"}}, {"set_var": {"name": "dit", "value": "$mine"}},
                                              {"set_var": {"name": "pc", "value": "$chrono"}}]}], variables=ALL)
    parse(ok)
    refused(mini(veille=[{"on": "start", "do": [{"set_var": {"name": "mine", "value": "$dit"}}]}], variables=ALL), "variable 'dit' is phrase")
    refused(mini(veille=[{"on": "start", "do": [{"set_var": {"name": "chrono", "value": None}}]}], variables=ALL), "is a timer")
    refused(mini(veille=[{"on": "start", "when": [{"var_compare": {"name": "teinte", "op": "<", "value": "#000000"}}], "to": "a"}],
                 variables=ALL), "only compares numbers, durations or dates")
    parse(mini(veille=[{"on": "start", "when": [{"var_compare": {"name": "rdv", "op": "<", "value": "$heure"}}], "to": "a"}], variables=ALL))


def test_bounds_clamp_and_out_of_bounds_diagnostic():
    raw = mini(veille=[{"on": "start", "do": [{"set_var": {"name": "n", "value": 42}}]}], variables=ALL)
    g = parse(raw)
    assert [d[2] for d in g.diagnostics] == ["out_of_bounds"] and "outside [0, 10]" in g.diagnostics[0][1], g.diagnostics
    b, _c = brain(raw)
    b.post("start"); b.pump()
    assert b.vars["n"] == 10                                  # clamped to max
    act(b, "add_var", name="n", delta=-25)
    assert b.vars["n"] == 0                                   # clamped to min
    act(b, "add_var", name="n", delta=2.6)
    assert b.vars["n"] == 3 and isinstance(b.vars["n"], int)  # an integer stays an integer
    act(b, "add_var", name="pc", delta=80)
    assert b.vars["pc"] == 100                                # percent kept in 0..100
    act(b, "set_var", name="x", value=-7)
    assert b.vars["x"] == -1
    # the editor's dry-run check shows the constant as a non-blocking warning on its node
    doc = V.to_visual(raw)
    report = {}
    _r, _l, errs = V.from_visual(doc, CFG, report)
    assert not errs, errs
    w = [x for x in report["warnings"] if x["kind"] == "out_of_bounds"]
    assert len(w) == 1 and w[0]["node"] and "42" in w[0]["message"], report["warnings"]
    node = next(n for n in doc["nodes"] if n["id"] in w[0]["nodes"] and n["kind"] == "action")
    assert node["params"]["action"] == "set_var", node


def test_conversation_scope_resets_on_clear_conversation():
    b, _c = brain(mini(variables=ALL))
    act(b, "add_var", name="conv", delta=4)
    act(b, "list_add", list="conv_l", value="y")
    act(b, "add_var", name="n", delta=1)
    assert b.vars["conv"] == 4 and b.lists["conv_l"] == ["x", "y"]
    act(b, "clear_conversation")
    assert b.vars["conv"] == 0 and b.lists["conv_l"] == ["x"] and b.vars["n"] == 4   # global ones are kept


def test_persistence_roundtrip_rate_limit_corrupt_and_reset():
    d = tmpdir()
    path = os.path.join(d, "state", "vars.json")
    variables = {"names": {"compteur": {"type": "integer", "value": 0, "max": 100, "persist": True},
                           "rdv": {"type": "datetime", "value": None, "persist": True},
                           "chrono": {"type": "timer", "value": None, "persist": True},
                           "libre": {"type": "integer", "value": 0}},
                 "lists": {"notes": {"type": "string", "items": [], "persist": True},
                           "faq": {"kind": "dict", "type": "string", "items": {}, "persist": True}}}
    raw = mini(variables=variables)
    b, clock = brain(raw, store=VarStore(path))
    adv(b, clock, 3)
    assert not os.path.exists(path), "nothing changed: no file is created"
    act(b, "add_var", name="compteur", delta=5)
    act(b, "set_now", name="rdv")
    act(b, "timer_start", name="chrono")
    act(b, "list_add", list="notes", value="un")
    act(b, "dict_set", dict="faq", key="clé", value="valeur")
    act(b, "add_var", name="libre", delta=9)
    adv(b, clock, 0.1)
    st = b._store
    assert st.writes == 1 and os.path.exists(path)
    saved = json.load(open(path, encoding="utf-8"))
    assert saved["names"]["compteur"] == {"type": "integer", "value": 5} and "libre" not in saved["names"], saved
    assert saved["names"]["rdv"]["value"] == "2026-11-02T10:00:03" and saved["lists"]["faq"]["items"] == {"clé": "valeur"}
    assert not [f for f in os.listdir(os.path.dirname(path)) if f.endswith(".tmp")], "atomic write leaves no temp file"
    act(b, "add_var", name="compteur", delta=1)
    adv(b, clock, 1.0)
    assert st.writes == 1, "at most one write per 2 s"
    adv(b, clock, 1.1)
    assert st.writes == 2 and json.load(open(path, encoding="utf-8"))["names"]["compteur"]["value"] == 6
    # a new brain (service restart) reads the values back; the persisted timer keeps running on the wall clock
    b2, c2 = brain(raw, start="2026-11-02T10:01:00", store=VarStore(path))
    assert b2.vars["compteur"] == 6 and b2.vars["rdv"] == "2026-11-02T10:00:03" and b2.lists["notes"] == ["un"]
    assert b2.lists["faq"] == {"clé": "valeur"} and b2.vars["libre"] == 0
    assert 56 < b2.var_value("chrono") < 58, b2.var_value("chrono")
    adv(b2, c2, 2.5)
    assert b2._store.writes == 0, "reading back is not a change"
    # a saved value whose type no longer fits is ignored (warning + store info), the initial value is used
    raw3 = mini(variables=dict(variables, names=dict(variables["names"], compteur={"type": "string", "value": "", "persist": True})))
    b3, _c3 = brain(raw3, store=VarStore(path))
    assert b3.vars["compteur"] == "" and [x["name"] for x in b3.var_store_info()["ignored"]] == ["compteur"]
    # a saved value outside new bounds is clamped
    raw4 = mini(variables=dict(variables, names=dict(variables["names"], compteur={"type": "integer", "value": 0, "max": 3, "persist": True})))
    assert brain(raw4, store=VarStore(path))[0].vars["compteur"] == 3
    # reset = initial value + saved value forgotten
    assert b2.reset_var("compteur") and b2.vars["compteur"] == 0
    assert not b2.reset_var("inconnue") and not b2.reset_var("tours")
    adv(b2, c2, 2.1)
    assert "compteur" not in json.load(open(path, encoding="utf-8"))["names"]
    info = b2.var_store_info()
    assert info["enabled"] and info["persist"]["names"] == ["compteur", "rdv", "chrono"] and "compteur" not in info["saved"]["names"]
    # a corrupt file never stops the brain: empty store, warning, the next write replaces it
    with open(path, "w", encoding="utf-8") as f:
        f.write("{pas du json")
    b5, c5 = brain(raw, store=VarStore(path))
    assert b5.vars["compteur"] == 0
    act(b5, "add_var", name="compteur", delta=2)
    adv(b5, c5, 0.1)
    assert json.load(open(path, encoding="utf-8"))["names"]["compteur"]["value"] == 2
    # without a store (simulator, default) nothing is ever written
    b6, c6 = brain(raw)
    act(b6, "add_var", name="compteur", delta=1)
    adv(b6, c6, 2.5)
    assert b6.var_store_info()["enabled"] is False
    shutil.rmtree(TMP, ignore_errors=True)


# ---------------------------------------------------------------- lists and dictionaries
def test_shuffle_bag_history_and_max():
    b, _c = brain(mini(variables=ALL))
    said = []
    for _ in range(8):
        act(b, "say_random", list="sac")
        said.append(b.subtitle)
    assert sorted(said[:4]) == ["a", "b", "c", "d"] and sorted(said[4:]) == ["a", "b", "c", "d"], said   # no repeat per bag
    for text in ("premier", "deuxième", "troisième"):
        act(b, "remember_utterance", {"text": text}, list="derniers")
    assert b.lists["derniers"] == ["deuxième", "troisième"]          # history keeps the last N
    act(b, "remember_utterance", {"text": "   "}, list="derniers")
    assert b.lists["derniers"] == ["deuxième", "troisième"]          # an empty sentence is not remembered
    act(b, "list_add", list="court", value=3)
    act(b, "list_add", list="court", value=4)
    assert b.lists["court"] == [2, 3, 4]                              # max drops the oldest
    # a plain list keeps the old random draw (rng): unchanged behaviour
    plain = mini(variables={"lists": {"p": {"type": "string", "items": ["a", "b", "c", "d"]}}})
    b2, _c2 = brain(plain)
    seq = []
    for _ in range(8):
        act(b2, "say_random", list="p")
        seq.append(b2.subtitle)
    assert len(set(seq)) < 8 and seq != said


def test_dictionaries():
    raw = mini(veille=[{"on": "intent.question", "when": [{"dict_has": {"dict": "faq", "key": "$utterance"}}],
                        "do": [{"say_dict": {"dict": "faq", "key": "$utterance", "fallback": "Je ne sais pas."}}], "to": "a"}],
               variables=ALL)
    g = parse(raw)
    assert {"Ouvert de 10 h à 18 h.", "Au fond à gauche.", "Je ne sais pas.", "Bonjour à tous."} <= set(G.say_texts(g))
    b, _c = brain(raw)
    b._handle("utterance", {"text": "Où sont les toilettes ?"})
    b.pump()
    assert b.state == "a" and b.subtitle == "Au fond à gauche."
    assert guard(b, "dict_has", {"text": "quels horaires"}, dict="faq", key="$utterance")
    assert not guard(b, "dict_has", {"text": "bonjour"}, dict="faq", key="$utterance")
    act(b, "say_dict", dict="faq", key="absente", fallback="Repli.")
    assert b.subtitle == "Repli."
    act(b, "say_dict", dict="faq", key="absente", fallback="")
    assert b.subtitle == "Repli."                                     # empty fallback: nothing said
    act(b, "dict_set", dict="scores", key="bob", value=7)
    assert guard(b, "dict_value_compare", dict="scores", key="bob", op=">", value=5)
    assert not guard(b, "dict_value_compare", dict="scores", key="zoé", op=">", value=5)   # absent key = false
    act(b, "dict_remove", dict="scores", key="alice")
    assert b.lists["scores"] == {"bob": 7} and b.var_snapshot()["lists"]["scores"] == {"bob": 7}
    # validation of the dictionary calls
    refused(mini(veille=[{"on": "start", "do": [{"list_add": {"list": "faq", "value": "x"}}]}], variables=ALL), "is a dictionary")
    refused(mini(veille=[{"on": "start", "do": [{"dict_set": {"dict": "sac", "key": "k", "value": "v"}}]}], variables=ALL), "not a dictionary")
    refused(mini(veille=[{"on": "start", "do": [{"dict_set": {"dict": "scores", "key": "k", "value": "sept"}}]}], variables=ALL), "not a valid integer")
    refused(mini(veille=[{"on": "start", "do": [{"say_dict": {"dict": "scores", "key": "k", "fallback": ""}}]}], variables=ALL), "does not hold texts")
    refused(mini(veille=[{"on": "start", "do": [{"dict_remove": {"dict": "faq", "key": ""}}]}], variables=ALL), "expected a key text")


# ---------------------------------------------------------------- time
def test_time_conditions_on_the_simulated_clock():
    b, clock = brain(mini(variables=ALL), start="2026-11-02T21:59:00")
    assert b.var_value("jour") == "lun" and b.var_value("heure") == "2026-11-02T21:59:00"
    assert guard(b, "weekday_in", days=["lun", "mar"]) and not guard(b, "weekday_in", days=["dim"])
    assert not guard(b, "time_between", start="22:00", end="06:00")
    adv(b, clock, 61)
    assert guard(b, "time_between", start="22:00", end="06:00")          # range across midnight
    assert not guard(b, "time_between", start="09:00", end="18:00")
    assert guard(b, "elapsed_since", name="rdv", op=">", seconds=13 * 3600)   # rdv = 09:00 the same day
    assert not guard(b, "elapsed_since", name="vide", op=">=", seconds=0)     # empty date: false
    assert not guard(b, "elapsed_since", name="chrono", op=">=", seconds=0)   # stopped timer: false
    act(b, "timer_start", name="chrono")
    adv(b, clock, 5)
    assert guard(b, "elapsed_since", name="chrono", op=">=", seconds=5) and not guard(b, "elapsed_since", name="chrono", op=">", seconds=6)
    assert abs(b.var_snapshot()["names"]["chrono"] - 5.0) < 0.01          # a timer reads as elapsed seconds
    act(b, "timer_reset", name="chrono")
    assert b.var_value("chrono") is None
    assert guard(b, "date_compare", name="rdv", op="<", value="$heure")
    assert guard(b, "date_compare", name="rdv", op="=", value="2026-11-02T09:00:00")   # parsed, not compared as text
    assert not guard(b, "date_compare", name="vide", op="<", value="$heure")
    act(b, "set_now", name="vide")
    assert b.vars["vide"] == "2026-11-02T22:00:06" and guard(b, "var_compare", name="vide", op=">", value="$rdv")
    # validation
    refused(mini(veille=[{"on": "start", "when": [{"time_between": {"start": "25:00", "end": "06:00"}}], "to": "a"}]), "expected a time hh:mm")
    refused(mini(veille=[{"on": "start", "when": [{"weekday_in": {"days": ["lundi"]}}], "to": "a"}]), "expected distinct days")
    refused(mini(veille=[{"on": "start", "when": [{"elapsed_since": {"name": "n", "op": ">", "seconds": 1}}], "to": "a"}], variables=ALL),
            "expected datetime / timer")
    refused(mini(veille=[{"on": "start", "do": [{"set_now": {"name": "heure"}}]}], variables=ALL), "read-only system variable")
    # the simulator uses the same clock: a time condition depends on start_time only
    raw = mini(veille=[{"on": "start", "when": [{"time_between": {"start": "12:00", "end": "14:00"}}], "to": "a", "reason": "midi"}])
    assert run(raw, [{"event": "start"}], start_time="2026-11-02T12:30")["final"]["state"] == "a"
    assert run(raw, [{"event": "start"}], start_time="2026-11-02T15:30")["final"]["state"] == "veille"


def test_timer_reached_once_per_start_with_anti_loop():
    variables = {"names": {"chrono": {"type": "timer", "value": None}, "n": {"type": "integer", "value": 0},
                           "flag": {"type": "bool", "value": False}, "m": {"type": "integer", "value": 0}}}
    raw = mini(veille=[{"on": "start", "do": [{"timer_start": {"name": "chrono"}}]}],
               glob=[{"on": "timer_reached", "var": "chrono", "value": 3,
                      "do": [{"add_var": {"name": "n", "delta": 1}}, {"toggle_var": {"name": "flag"}}]},
                     {"on": "var_changed", "var": "flag", "do": [{"add_var": {"name": "m", "delta": 1}}],
                      "description": "would fire without the anti-loop"}],
               variables=variables)
    assert parse(raw).timer_watches() == (("chrono", 3),)
    b, clock = brain(raw)
    adv(b, clock, 10)
    assert b.vars["n"] == 0                                    # a stopped timer never fires
    b.post("start"); b.pump()
    adv(b, clock, 2.8)
    assert b.vars["n"] == 0
    adv(b, clock, 0.4)
    assert b.vars["n"] == 1 and b.vars["flag"] is True
    adv(b, clock, 10)
    assert b.vars["n"] == 1, "once per start"
    assert b.vars["m"] == 0, "a timer_reached chain does not trigger var_changed (anti-loop)"
    b.post("start"); b.pump()                                 # restart re-arms
    adv(b, clock, 3.2)
    assert b.vars["n"] == 2
    trace = [e["event"] for e in b.trace()]
    assert trace.count("timer_reached") == 2 and "var_changed" not in trace, trace
    # a direct var change still triggers var_changed (the anti-loop only cuts cascades)
    act(b, "toggle_var", name="flag")
    assert b.vars["m"] == 1
    # validation
    refused(mini(glob=[{"on": "timer_reached", "var": "n", "value": 3}], variables=variables), "needs `var:` = a timer variable")
    refused(mini(glob=[{"on": "timer_reached", "var": "chrono"}], variables=variables), "seconds > 0")
    refused(mini(glob=[{"on": "timer_reached", "var": "chrono", "value": 0}], variables=variables), "seconds > 0")
    refused(mini(veille=[{"on": "start", "do": [{"emit": {"event": "timer_reached"}}]}]), "unknown event")
    # the simulator drives it from its virtual heartbeat
    res = run(raw, [{"event": "start"}, {"wait_s": 4}], start_time=MONDAY)
    assert res["final"]["vars"]["names"]["n"] == 1 and [e["event"] for e in res["trace"]].count("timer_reached") == 1


# ---------------------------------------------------------------- system variables
def test_new_system_variables_are_read_only_views():
    for n in ("heure", "jour", "derniere_phrase", "visage_vu", "volume", "expression", "regard", "nb_visiteurs_jour"):
        assert n in G.SYSTEM_VARS
        refused(mini(variables={"names": {n: {"type": "bool", "value": True}}}), "not be a system variable")
    refused(mini(veille=[{"on": "start", "do": [{"set_var": {"name": "volume", "value": 10}}]}]), "read-only system variable")
    refused(mini(veille=[{"on": "start", "do": [{"add_var": {"name": "nb_visiteurs_jour", "delta": 1}}]}]), "read-only system variable")
    raw = mini(veille=[{"on": "start", "to": "a", "reason": "go"}], a=[{"on": "stop", "to": "veille", "reason": "back"}])
    b, clock = brain(raw, start="2026-11-02T23:59:50")
    snap = b.var_snapshot()["names"]
    assert snap["visage_vu"] is False and snap["volume"] == 80 and snap["expression"] == "neutre" and snap["regard"] == "suivre"
    assert snap["nb_visiteurs_jour"] == 0 and snap["derniere_phrase"] == "" and snap["jour"] == "lun"
    b.set_faces(1)
    b._handle("not_understood", {"text": "euh bonjour"})
    act(b, "set_expression", name="content", seconds=2)
    act(b, "gaze", mode="errer")
    snap = b.var_snapshot()["names"]
    assert snap["visage_vu"] is True and snap["derniere_phrase"] == "euh bonjour" and snap["expression"] == "content" and snap["regard"] == "errer"
    adv(b, clock, 2.1)
    assert b.var_value("expression") == "neutre"
    b.post("start"); b.pump(); b.post("stop"); b.pump(); b.post("start"); b.pump()
    assert b.var_value("nb_visiteurs_jour") == 2                      # two conversations started from veille
    adv(b, clock, 10)                                                 # midnight passes
    assert b.var_value("nb_visiteurs_jour") == 0 and b.var_value("jour") == "mar"
    # reading them is fine, including the new ones as `$` references
    parse(mini(veille=[{"on": "start", "when": [{"var_compare": {"name": "volume", "op": ">", "value": 50}},
                                                 {"var_true": {"name": "visage_vu"}}], "to": "a"}]))
    # the simulator leaves the wall-clock views out without a start time: same input, same result
    r1, r2 = run(raw, [{"event": "start"}]), run(raw, [{"event": "start"}])
    assert r1 == r2 and "heure" not in r1["final"]["vars"]["names"] and "volume" in r1["final"]["vars"]["names"]
    assert run(raw, [{"event": "start"}], start_time=MONDAY)["final"]["vars"]["names"]["heure"] == MONDAY


# ---------------------------------------------------------------- editor contract
def test_vocabulary_describes_the_new_types_for_the_editor():
    g = parse(mini(variables=ALL))
    v = G.vocabulary(CFG, g)
    themes = set(G.THEME_DOC)
    new_actions = {"set_now", "timer_start", "timer_reset", "say_var", "remember_utterance", "dict_set", "dict_remove", "say_dict"}
    new_guards = {"elapsed_since", "time_between", "weekday_in", "date_compare", "dict_has", "dict_value_compare"}
    for k, ids in (("actions", new_actions), ("guards", new_guards), ("events", {"timer_reached"})):
        got = {x["id"]: x for x in v[k] if x["id"] in ids}
        assert set(got) == ids, (k, set(got))
        for x in got.values():
            assert x["theme"] in themes and x["label"] and x["help"], x
            assert os.path.exists(os.path.join(TABLER, x["icon"] + ".svg")), x["icon"]
            assert all(a.get("help") for a in x.get("args", [])) or k == "events", x
    types = {t["id"]: t for t in v["var_types"]}
    assert list(types) == list(G.VAR_TYPES)
    assert types["integer"]["options"] == ["min", "max", "step"] and types["string"]["options"] == []
    assert types["datetime"]["ops"] == list(G.OPS) and types["color"]["ops"] == ["=", "!="] and v["op_sets"]["vector2"] == ["=", "!="]
    assert types["timer"]["item"] is False and types["vector3"]["size"] == 3 and types["percent"]["range"] == [0, 100]
    assert [c["id"] for c in types["expression"]["choices"]] == list(G.EXPRESSIONS)
    assert [c["id"] for c in types["state_ref"]["choices"]] == ["veille", "eteint", "a", "b"]
    assert [c["id"] for c in types["list_ref"]["choices"]] == list(ALL["lists"])
    assert types["intent_ref"]["choices"][-1]["id"] == "question" and isinstance(types["media"]["choices"], list)
    assert [s["id"] for s in v["scopes"]] == ["global", "conversation"] and [m["id"] for m in v["list_modes"]] == ["plain", "shuffle", "history"]
    assert [d["id"] for d in v["weekdays"]] == ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
    tr = next(e for e in v["events"] if e["id"] == "timer_reached")
    assert [(a["name"], a["type"]) for a in tr["args"]] == [("name", "var"), ("value", "number")] and tr["args"][0]["var_types"] == ["timer"]
    emit = next(a for a in v["actions"] if a["id"] == "emit")["args"][0]["options"]
    assert "timer_reached" not in emit and "var_changed" not in emit
    ds = {a["name"]: a for a in next(a for a in v["actions"] if a["id"] == "dict_set")["args"]}
    assert ds["dict"]["list_kinds"] == ["dict"] and ds["value"]["of"] == "dict" and ds["key"]["utterance"] is True
    wd = next(g_ for g_ in v["guards"] if g_["id"] == "weekday_in")["args"][0]
    assert wd["type"] == "multi" and wd["options"] == list(G.WEEKDAYS)
    la = {a["name"]: a for a in next(a for a in v["actions"] if a["id"] == "list_add")["args"]}
    assert la["list"]["list_kinds"] == ["list"]
    rows = {x["id"]: x for x in v["variables"]["names"]}
    assert rows["n"]["min"] == 0 and rows["n"]["max"] == 10 and rows["conv"]["scope"] == "conversation" and rows["n"]["persist"] is False
    assert rows["jour"]["choices"] == list(G.WEEKDAYS) and rows["heure"]["readonly"]
    lrows = {x["id"]: x for x in v["variables"]["lists"]}
    assert lrows["faq"]["kind"] == "dict" and lrows["faq"]["items"]["horaires"] and lrows["derniers"]["max"] == 2
    json.dumps(v)


def test_visual_roundtrip_of_the_new_keys():
    raw = mini(veille=[{"on": "start", "do": [{"timer_start": {"name": "chrono"}}, {"dict_set": {"dict": "scores", "key": "$utterance", "value": 2}}]}],
               glob=[{"on": "timer_reached", "var": "chrono", "value": 30, "do": [{"say_var": {"name": "dit"}}]}],
               a=[{"on": "ask", "when": [{"weekday_in": {"days": ["sam", "dim"]}}, {"time_between": {"start": "10:00", "end": "12:30"}}],
                   "do": [{"say_dict": {"dict": "faq", "key": "$utterance", "fallback": ""}}], "to": "b"}],
               variables=ALL)
    want = parse(raw).to_dict()
    doc = V.to_visual(copy.deepcopy(raw))
    trig = [n for n in doc["nodes"] if n["kind"] == "trigger" and n["params"].get("event") == "timer_reached"]
    assert trig and trig[0]["params"]["name"] == "chrono" and trig[0]["params"]["value"] == 30, trig
    # the editor may send the seconds as text
    trig[0]["params"]["value"] = "30"
    back, _layout, errs = V.from_visual(doc, CFG)
    assert not errs, errs
    got = parse(back).to_dict()
    assert got["variables"] == want["variables"]
    assert got == want, (got, want)
    # the YAML text keeps the dictionary items and the new keys
    d = tmpdir()
    gp, lp = os.path.join(d, "graph.yaml"), os.path.join(d, "graph.layout.json")
    ok, errs = V.save(doc, CFG, gp, lp)
    assert ok, errs
    assert parse(V.load_raw(gp)).to_dict() == want
    shutil.rmtree(TMP, ignore_errors=True)
    # a timer_reached trigger without its timer is refused on its node
    t = dict(trig[0], params=dict(trig[0]["params"], name=""))
    doc["nodes"] = [t if n["id"] == t["id"] else n for n in doc["nodes"]]
    errs = V.from_visual(doc, CFG)[2]
    assert any(e["node"] == t["id"] and "chrono" in e["message"] for e in errs), errs


def test_default_graph_examples_do_not_change_behaviour():
    raw = V.load_raw(G.DEFAULT_PATH)
    g = parse(raw)
    assert not [v for v in g.variables.values() if v.persist] and not [li for li in g.lists.values() if li.persist]
    assert g.lists["salutations"].mode == "shuffle" and not g.diagnostics
    used = {c.args.get("list") for s in g.states.values() for t in s.transitions for c in t.do + t.then}
    assert "salutations" not in used                       # the shuffle example is not spoken by the shipped graph
    assert not g.timer_watches()


def test_server_exposes_vars_reset_and_store():
    """server.py is read as text, never imported (importing builds the live Brain)."""
    import ast
    src = open(os.path.join(os.path.dirname(G.__file__), "server.py"), encoding="utf-8").read()
    ast.parse(src)
    assert '@app.post("/api/graph/vars/reset")' in src and "brain.reset_var" in src
    assert '"store": brain.var_store_info()' in src and "var_store=var_store" in src and "atexit.register(var_store.flush)" in src


TESTS = [test_every_new_type_is_validated, test_bounds_clamp_and_out_of_bounds_diagnostic,
         test_conversation_scope_resets_on_clear_conversation, test_persistence_roundtrip_rate_limit_corrupt_and_reset,
         test_shuffle_bag_history_and_max, test_dictionaries, test_time_conditions_on_the_simulated_clock,
         test_timer_reached_once_per_start_with_anti_loop, test_new_system_variables_are_read_only_views,
         test_vocabulary_describes_the_new_types_for_the_editor, test_visual_roundtrip_of_the_new_keys,
         test_default_graph_examples_do_not_change_behaviour, test_server_exposes_vars_reset_and_store]


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
    print("graph_vars2 tests: %d passed, %d failed" % (ran - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
