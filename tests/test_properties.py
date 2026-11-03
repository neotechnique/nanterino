"""Tests of the value sources and write targets (lot M4, 2026-11-01): nanterino/properties (get/ + set/).

logging: robotlog via tests.test_brain_graph (imported through tests.test_graph_vars for the shared helpers).

Purpose
    (1) discovery: every source / target is found, in order, with its declared output type; the vocabulary exposes
        `properties` and the per-argument `props` keys, and the goldens only GAINED keys: removing them from the
        current vocabulary gives tests/golden/vocab-*.pre-m4.json byte for byte;
    (2) each source's output type (static) and run-time value on a non-threaded Brain (seeded rng, simulated clock);
    (3) shorthand equivalence: `$x` == {get: variable, name: x} and `$utterance` == {get: utterance} (same compiled
        graph, same simulator trace);
    (4) refusals with clear messages (incompatible output type, unknown source / argument, references in a
        constant), nesting depth limit, division by zero (diagnostic + run-time 0);
    (5) set targets: clamp / round / bounds, list mode push, dictionary key handling; pre-resolved kinds (add_var
        delta, elapsed_since seconds, say_dict fallback);
    (6) YAML and visual round trips keep `{get: ...}` intact;
    (7) drop-a-file per family (temporary package copy imported in a subprocess) and broken modules per family;
    (8) a simulator scenario with properties in a set_var and a var_compare.

Boundary
    Pure functions, the simulator and non-threaded Brains on the fake world of nanterino/sim.py. Files only under
    /tmp/test_properties. nanterino.server is never imported; the live robot is never reached.

How to run (repo root):
    .venv/bin/python -m tests.test_properties            # ~10 s
    .venv/bin/python -m tests.test_properties test_calc   # one test
"""
import copy
import importlib
import json
import os
import shutil
import subprocess
import sys

import yaml

sys.path.insert(0, "/opt/robot/lib")

from nanterino import graph as G, graph_visual as V, properties as P  # noqa: E402
from nanterino.registry import RegistryError  # noqa: E402
from tests.test_graph_vars import CFG, mini, parse, run  # noqa: E402
from tests.test_graph_vars2 import adv, brain  # noqa: E402
from tests.test_nodes_registry import GOLDEN, golden_diff, vocab_dumps  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "nanterino")
TMP = "/tmp/test_properties"
GET_IDS = ["constant", "variable", "utterance", "list_item", "dict_value", "system", "random_number", "random_from_list",
           "intent_match", "config_value", "elapsed", "calc"]
SET_IDS = ["variable", "list_item", "dict_key"]

VARS = {"names": {"n": {"type": "integer", "value": 3, "min": 0, "max": 10},
                  "f": {"type": "number", "value": 2.5},
                  "pc": {"type": "percent", "value": 50},
                  "t": {"type": "string", "value": "a"},
                  "ph": {"type": "phrase", "value": "Bonjour."},
                  "ok": {"type": "bool", "value": False},
                  "dur": {"type": "duration", "value": 0},
                  "chrono": {"type": "timer", "value": None},
                  "quand": {"type": "datetime", "value": None},
                  "humeur": {"type": "choice", "value": "calme", "choices": ["calme", "joyeux"]}},
        "lists": {"nums": {"type": "integer", "items": [3, 4, 5]},
                  "vide": {"type": "integer", "items": []},
                  "mots": {"type": "string", "items": ["bonjour", "salut"]},
                  "hist": {"type": "integer", "items": [1, 2], "mode": "history", "max": 3},
                  "scores": {"kind": "dict", "type": "integer", "items": {"alice": 7, "bob": 2}},
                  "faq": {"kind": "dict", "type": "string", "items": {"horaires": "Neuf heures."}}}}
INTENTS = {"merci": {"description": "Remerciements", "words": ["merci"]}}


def graph_of(do=(), when=(), variables=VARS, intents=INTENTS):
    t = {"on": "start", "do": list(do), "to": "a"}
    if when:
        t["when"] = list(when)
    return mini(veille=[t], variables=variables, intents=intents)


def refused_with(raw, fragment):
    try:
        parse(raw)
    except G.GraphError as e:
        assert fragment in str(e), (fragment, str(e))
        return str(e)
    raise AssertionError("accepted although invalid: " + fragment)


def compiled(raw, i=0):
    """Compiled `value` (or the whole args) of the i-th action of the start transition."""
    return parse(raw).states["veille"].transitions[0].do[i].args


def fire(raw, kw=None, steps=0.0):
    """Non-threaded Brain on `raw` (seeded rng, wall clock = simulated clock); runs the start transition's actions
    through the engine's bound callables (the real path: pre-resolution included). Returns the brain."""
    b, clock = brain(raw)
    if steps:
        adv(b, clock, steps)
    for c in b._graph.states["veille"].transitions[0].do:
        b.engine.actions[c.name](dict(kw or {}), **c.args)
        b.pump()
    return b


def value_of(prop, field_var="f", kw=None, extra=(), steps=0.0):
    """Value written by set_var(field_var, prop) after the `extra` actions (and `steps` virtual seconds)."""
    b = fire(graph_of(list(extra) + [{"set_var": {"name": field_var, "value": prop}}]), kw, steps)
    return b.vars[field_var]


# ---------------------------------------------------------------- (1) discovery + vocabulary
def test_discovery_and_vocabulary():
    assert list(P.GETS) == GET_IDS, list(P.GETS)
    assert list(P.SETS) == SET_IDS, list(P.SETS)
    outs = {k: s.out for k, s in P.GETS.items()}
    assert outs == {"constant": "same", "variable": ("of", "name"), "utterance": "phrase", "list_item": ("of", "list"),
                    "dict_value": ("of", "dict"), "system": ("of", "name"), "random_number": "number",
                    "random_from_list": ("of", "list"), "intent_match": "bool", "config_value": ("of", "key"),
                    "elapsed": "duration", "calc": "number"}, outs
    v = G.vocabulary(CFG, parse(graph_of()))
    pv = v["properties"]
    assert [e["id"] for e in pv["get"]] == GET_IDS and [e["id"] for e in pv["set"]] == SET_IDS
    calc = next(e for e in pv["get"] if e["id"] == "calc")
    assert calc["out"] == "number" and [a["name"] for a in calc["args"]] == ["a", "op", "b"]
    assert calc["args"][0]["props"] == "number" and calc["args"][1]["options"] == list(P.CALC_OPS)
    li = next(e for e in pv["get"] if e["id"] == "list_item")
    assert li["out"] == {"of": "list"} and li["args"][1]["default"] == "first" and li["args"][2]["default"] == 1
    assert next(e for e in pv["get"] if e["id"] == "constant")["args"][0] == {"name": "value", "type": "value", "props": "same",
                                                                                "label": "Valeur"}
    cv = next(e for e in pv["get"] if e["id"] == "config_value")
    assert cv["args"][0]["options"] and "llm_url" not in cv["args"][0]["options"]
    for e in pv["get"] + pv["set"]:
        assert e["icon"] in G.all_icons() and e["label"] and e["help"], e
    args = {a["id"]: {x["name"]: x for x in a["args"]} for a in v["actions"]}
    assert args["set_var"]["value"]["props"] == "of" and "props" not in args["set_var"]["name"]
    assert args["add_var"]["delta"]["props"] == "number" and args["dict_set"]["key"]["props"] == "string"
    assert args["say_dict"]["fallback"]["props"] == "string" and "props" not in args["say_text"]["text"]
    assert "props" not in args["wait"]["seconds"] and "props" not in args["emit"]["event"]
    gargs = {g["id"]: {x["name"]: x for x in g["args"]} for g in v["guards"]}
    assert gargs["var_compare"]["value"]["props"] == "of" and gargs["elapsed_since"]["seconds"]["props"] == "number"
    assert gargs["list_contains"]["value"]["props"] == "of" and "props" not in gargs["var_compare"]["op"]
    assert all("props" not in a for e in v["events"] for a in e.get("args", [])), "trigger filters take no source"
    json.dumps(v)


from tests.test_nodes_n1 import strip_n1  # noqa: E402 (lot N1: its own additive golden check)


def strip_m4(v: dict) -> dict:
    """The vocabulary without the lot M4 keys (top-level `properties`, per-argument `props`), order preserved."""
    v = dict(v)
    v.pop("properties")
    v.pop("type_compat", None)   # lot M5 key (its own golden check: test_goldens_m5_only_gained_keys)
    for fam in ("actions", "guards"):
        v[fam] = [dict(a, args=[{k: x for k, x in arg.items() if k != "props"} for arg in a["args"]]) for a in v[fam]]
    return v


def test_goldens_only_gained_keys():
    dumps = vocab_dumps(G)
    assert not golden_diff(dumps), "the M4 goldens differ: %s" % golden_diff(dumps)
    for name, text in dumps.items():
        with open(os.path.join(GOLDEN, name.replace(".json", ".pre-m4.json")), "rb") as f:
            old = f.read()
        stripped = json.dumps(strip_m4(strip_n1(json.loads(text))), ensure_ascii=False, indent=1) + "\n"   # lot N1 entries first
        assert stripped.encode("utf-8") == old, "%s minus the M4 keys is not the pre-M4 golden" % name


def strip_m5(v: dict) -> dict:
    """The vocabulary without the lot M5 keys (top-level `type_compat`, `types` of the config_value key argument)."""
    v = dict(v)
    v.pop("type_compat")
    props = dict(v["properties"])
    props["get"] = [dict(e, args=[{k: x for k, x in a.items() if k != "types"} for a in e["args"]]) for e in props["get"]]
    v["properties"] = props
    return v


def test_goldens_m5_only_gained_keys():
    """Lot M5: the editor's source picker reads `type_compat` (= graph.compatible for every pair of types) and the
    output type of each readable config key; both are additive: without them the JSON is the pre-M5 golden byte for
    byte."""
    dumps = vocab_dumps(G)
    assert not golden_diff(dumps), "the M5 goldens differ: %s" % golden_diff(dumps)
    for name, text in dumps.items():
        with open(os.path.join(GOLDEN, name.replace(".json", ".pre-m5.json")), "rb") as f:
            old = f.read()
        cur = json.loads(text)
        stripped = json.dumps(strip_m5(strip_n1(cur)), ensure_ascii=False, indent=1) + "\n"   # lot N1 entries first
        assert stripped.encode("utf-8") == old, "%s minus the M5 keys is not the pre-M5 golden" % name
        assert list(cur)[-1] == "type_compat", "type_compat must be the last key"
    v = G.vocabulary(CFG)
    tc = v["type_compat"]
    assert set(tc) == set(G.VAR_TYPES), "one entry per variable type"
    for s_ in G.VAR_TYPES:
        for d in G.VAR_TYPES:
            assert (d in tc[s_]) == G.compatible(s_, d), "type_compat[%s] disagrees with compatible() on %s" % (s_, d)
    assert "number" in tc["integer"] and "integer" in tc["number"] and "bool" not in tc["number"]
    key = next(e for e in v["properties"]["get"] if e["id"] == "config_value")["args"][0]
    assert key["types"] and set(key["types"]) == set(key["options"]), key
    for k, t in key["types"].items():
        assert t == P.cfg_type(CFG[k]), (k, t)


# ---------------------------------------------------------------- (2) output types + run-time values
def test_constant_variable_utterance_system():
    assert value_of({"get": "constant", "value": 4.5}) == 4.5
    assert compiled(graph_of([{"set_var": {"name": "f", "value": {"get": "constant", "value": 4.5}}}]))["value"] == 4.5
    assert value_of({"get": "variable", "name": "n"}) == 3
    assert value_of({"get": "utterance"}, "ph", kw={"text": "Il fait beau."}) == "Il fait beau."
    assert value_of({"get": "utterance"}, "t", kw={}) == "", "no sentence heard yet: empty text"
    assert value_of({"get": "system", "name": "volume"}, "pc") == G.VARTYPES["percent"].clamp(int(round(CFG.get("volume", 0.8) * 100)))
    assert value_of({"get": "system", "name": "visage_vu"}, "ok") is False
    assert value_of({"get": "system", "name": "tours"}) == 0
    refused_with(graph_of([{"set_var": {"name": "ok", "value": {"get": "system", "name": "heure"}}}]),
                 "set_var.value: source system gives a datetime value, bool expected")
    refused_with(graph_of([{"set_var": {"name": "f", "value": {"get": "system", "name": "lune"}}}]),
                 "set_var.value.name: unknown system variable 'lune'")


def test_list_and_dict_sources():
    li = lambda **a: dict({"get": "list_item", "list": "nums"}, **a)   # noqa: E731
    assert value_of(li()) == 3 and value_of(li(pick="last")) == 5 and value_of(li(pick="index", index=2)) == 4
    assert value_of(li(pick="index", index=9)) == 0, "out of range: the item type's default"
    assert value_of({"get": "list_item", "list": "vide", "pick": "last"}) == 0, "empty list: default"
    assert value_of(li(pick="index", index={"get": "calc", "a": 1, "op": "+", "b": 2})) == 5, "nested index"
    r1, r2 = value_of(li(pick="random")), value_of(li(pick="random"))
    assert r1 == r2 and r1 in (3, 4, 5), "seeded rng: deterministic"
    rl = value_of({"get": "random_from_list", "list": "mots"}, "t")
    assert rl == value_of({"get": "random_from_list", "list": "mots"}, "t") and rl in ("bonjour", "salut")
    assert value_of({"get": "random_from_list", "list": "vide"}) == 0
    refused_with(graph_of([{"set_var": {"name": "n", "value": li(pick="index", index=0)}}]), "index must be an integer >= 1")
    refused_with(graph_of([{"set_var": {"name": "n", "value": li(pick="middle")}}]), "unknown position 'middle'")
    refused_with(graph_of([{"set_var": {"name": "n", "value": {"get": "list_item", "list": "scores"}}}]),
                 "'scores' is a dictionary, not a list")
    dv = lambda key: {"get": "dict_value", "dict": "scores", "key": key}   # noqa: E731
    assert value_of(dv("alice")) == 7 and value_of(dv("zoe")) == 0
    assert value_of(dv("$utterance"), kw={"text": "c'est bob qui parle"}) == 2, "$utterance key = first key contained"
    assert value_of(dv({"get": "variable", "name": "t"}), extra=[{"set_var": {"name": "t", "value": "bob"}}]) == 2
    refused_with(graph_of([{"set_var": {"name": "n", "value": {"get": "dict_value", "dict": "faq", "key": "horaires"}}}]),
                 "source dict_value gives a string value, integer expected")


def test_random_number_intent_config_elapsed():
    rn = {"get": "random_number", "min": 1, "max": 6}
    a, b = value_of(rn), value_of(rn)
    assert a == b and isinstance(a, (int, float)) and 1 <= a <= 6 and a == int(a), (a, b)
    x = value_of({"get": "random_number", "min": 0.5, "max": 1.5})
    assert 0.5 <= x <= 1.5 and isinstance(x, float)
    refused_with(graph_of([{"set_var": {"name": "f", "value": {"get": "random_number", "min": 6, "max": 1}}}]), "min 6 is above max 1")
    im = {"get": "intent_match", "intent": "merci"}
    assert value_of(im, "ok", kw={"text": "Merci beaucoup"}) is True
    assert value_of(im, "ok", kw={"text": "Bonjour"}) is False
    refused_with(graph_of([{"set_var": {"name": "ok", "value": {"get": "intent_match", "intent": "question"}}}]),
                 "`question` is the fallback intent")
    refused_with(graph_of([{"set_var": {"name": "ok", "value": {"get": "intent_match", "intent": "nope"}}}]), "unknown intent 'nope'")
    assert value_of({"get": "config_value", "key": "silence_relance_s"}) == CFG["silence_relance_s"]
    assert value_of({"get": "config_value", "key": "barge_in"}, "ok") is CFG["barge_in"]
    refused_with(graph_of([{"set_var": {"name": "f", "value": {"get": "config_value", "key": "greeting"}}}]),
                 "source config_value gives a string value, number expected")
    refused_with(graph_of([{"set_var": {"name": "t", "value": {"get": "config_value", "key": "llm_url"}}}]),
                 "'llm_url' is not a readable config key")
    # elapsed: timer started, 5 virtual seconds, read on the simulated clock
    b, clock = brain(graph_of([{"timer_start": {"name": "chrono"}}, {"set_now": {"name": "quand"}},
                               {"set_var": {"name": "dur", "value": {"get": "elapsed", "name": "chrono"}}},
                               {"set_var": {"name": "f", "value": {"get": "elapsed", "name": "quand"}}}]))
    do = b._graph.states["veille"].transitions[0].do
    for c in do[:2]:
        b.engine.actions[c.name]({}, **c.args)
    adv(b, clock, 5)
    for c in do[2:]:
        b.engine.actions[c.name]({}, **c.args)
    assert abs(b.vars["dur"] - 5) < 0.2 and abs(b.vars["f"] - 5) < 1.01, (b.vars["dur"], b.vars["f"])
    assert value_of({"get": "elapsed", "name": "chrono"}, "dur") == 0, "stopped timer: 0"
    refused_with(graph_of([{"set_var": {"name": "f", "value": {"get": "elapsed", "name": "n"}}}]), "expected datetime / timer")


def test_calc_ops_nesting_and_division_by_zero():
    c = lambda a, op, b: {"get": "calc", "a": a, "op": op, "b": b}   # noqa: E731
    for op, want in (("+", 8), ("-", -2), ("*", 15), ("/", 0.6), ("min", 3), ("max", 5)):
        got = value_of(c(3, op, 5))
        assert got == want, (op, got)
    assert value_of(c(6, "/", 3)) == 2 and isinstance(value_of(c(6, "/", 3)), int)
    assert value_of(c("$n", "*", {"get": "list_item", "list": "nums", "pick": "last"})) == 15
    assert value_of(c(c(c(c(1, "+", 1), "+", 1), "+", 1), "+", 1)) == 5, "4 levels deep is allowed"
    refused_with(graph_of([{"set_var": {"name": "f", "value": c(c(c(c(c(1, "+", 1), "+", 1), "+", 1), "+", 1), "+", 1)}}]),
                 "set_var.value.a.a.a.a: value sources nested deeper than 4 levels")
    refused_with(graph_of([{"set_var": {"name": "f", "value": c(1, "^", 2)}}]), "unknown operator '^'")
    refused_with(graph_of([{"set_var": {"name": "f", "value": c("$t", "+", 2)}}]), "variable 't' is string, expected number")
    refused_with(graph_of([{"set_var": {"name": "t", "value": c(1, "+", 2)}}]), "source calc gives a number value, string expected")
    raw = graph_of([{"set_var": {"name": "f", "value": c(4, "/", 0)}}])
    g = parse(raw)
    assert any(k == "division_by_zero" and "division by zero" in m for _w, m, k in g.diagnostics), g.diagnostics
    assert value_of(c(4, "/", 0)) == 0, "literal zero: 0 at run time"
    assert value_of(c(4, "/", {"get": "list_item", "list": "vide"})) == 0, "run-time zero: 0, no exception"
    assert not parse(graph_of([{"set_var": {"name": "f", "value": c(4, "/", "$n")}}])).diagnostics


# ---------------------------------------------------------------- (3) shorthand equivalence
def test_shorthand_equivalence():
    pairs = [({"set_var": {"name": "f", "value": "$n"}}, {"set_var": {"name": "f", "value": {"get": "variable", "name": "n"}}}),
             ({"set_var": {"name": "ph", "value": "$utterance"}}, {"set_var": {"name": "ph", "value": {"get": "utterance"}}}),
             ({"dict_set": {"dict": "scores", "key": "$utterance", "value": 1}},
              {"dict_set": {"dict": "scores", "key": {"get": "utterance"}, "value": {"get": "constant", "value": 1}}}),
             ({"list_add": {"list": "mots", "value": "$t"}}, {"list_add": {"list": "mots", "value": {"get": "variable", "name": "t"}}})]
    for short, long_ in pairs:
        a, b = graph_of([short]), graph_of([long_])
        assert parse(a).to_dict() == parse(b).to_dict(), (short, long_)
        assert compiled(a) == compiled(b)
        steps = [{"event": "start"}, {"say": "bonjour tout le monde"}]
        ra, rb = run(a, steps), run(b, steps)
        assert ra == rb, (short, long_)
    lc = lambda v: mini(veille=[{"on": "start", "when": [{"list_contains": {"list": "mots", "value": v}}], "to": "a"}],  # noqa: E731
                        variables=VARS)
    assert parse(lc("$utterance")).to_dict() == parse(lc({"get": "utterance"})).to_dict()
    # in a field that never took `$x` (a number), the long form stays a dict and still runs
    raw = graph_of([{"add_var": {"name": "n", "delta": {"get": "variable", "name": "n"}}}])
    assert compiled(raw)["delta"] == {"get": "variable", "name": "n"}
    assert fire(raw).vars["n"] == 6
    refused_with(graph_of([{"add_var": {"name": "n", "delta": "$n"}}]), "add_var.delta: expected a number")


# ---------------------------------------------------------------- (4) refusals
def test_refusals_are_clear():
    sv = lambda v, name="n": graph_of([{"set_var": {"name": name, "value": v}}])   # noqa: E731
    refused_with(sv({"get": "list_item", "list": "mots"}), "set_var.value: source list_item gives a string value, integer expected")
    refused_with(sv({"get": "nope"}), "set_var.value: unknown value source 'nope' (allowed: constant, variable")
    refused_with(sv({"get": "calc", "a": 1, "b": 2}), "set_var.value: source calc takes ['a', 'b', 'op'], got ['a', 'b']")
    refused_with(sv({"get": "constant", "value": "$t"}), "a constant cannot be a reference or another source")
    refused_with(sv({"get": "constant", "value": "triste"}, "humeur"), "set_var.value.value: 'triste' is not a valid choice value (choices: calme, joyeux)")
    refused_with(sv({"get": "variable", "name": "inconnue"}), "set_var.value.name: unknown variable 'inconnue'")
    refused_with(sv({"get": "calc", "a": {"x": 1}, "op": "+", "b": 1}, "f"), "set_var.value.a: expected a value or {get: ...}")
    refused_with(graph_of([{"add_var": {"name": "n", "delta": {"get": "utterance"}}}]), "add_var.delta: $utterance is a text, number expected")
    refused_with(mini(veille=[{"on": "start", "when": [{"var_compare": {"name": "n", "op": "<", "value": {"get": "list_item", "list": "mots"}}}],
                               "to": "a"}], variables=VARS), "var_compare.value: source list_item gives a string value, integer expected")
    refused_with(graph_of([{"say_text": {"text": {"get": "utterance"}}}]), "say_text.text: expected a non-empty text")


def test_constant_bounds_diagnostic():
    g = parse(graph_of([{"set_var": {"name": "n", "value": {"get": "constant", "value": 99}}}]))
    assert any(k == "out_of_bounds" for _w, _m, k in g.diagnostics), g.diagnostics
    assert parse(graph_of([{"set_var": {"name": "humeur", "value": {"get": "constant", "value": "joyeux"}}}]))


# ---------------------------------------------------------------- (5) set targets + pre-resolved kinds
def test_set_targets_clamp_push_and_keys():
    assert value_of({"get": "calc", "a": 50, "op": "*", "b": 2}, "n") == 10, "integer max 10 clamps"
    assert value_of({"get": "calc", "a": 26, "op": "/", "b": 10}, "n") == 3, "integer rounding"
    assert value_of({"get": "calc", "a": 80, "op": "+", "b": 50}, "pc") == 100, "percent range"
    b = fire(graph_of([{"list_add": {"list": "hist", "value": {"get": "calc", "a": 2.6, "op": "+", "b": 1}}},
                       {"list_add": {"list": "hist", "value": 9}}]))
    assert b.lists["hist"] == [2, 4, 9], ("history max 3 drops the oldest; integer item rounded", b.lists["hist"])
    b = fire(graph_of([{"dict_set": {"dict": "scores", "key": {"get": "variable", "name": "t"}, "value": {"get": "calc", "a": 1.4, "op": "+", "b": 1}}},
                       {"dict_set": {"dict": "scores", "key": "  zoe  ", "value": {"get": "list_item", "list": "nums"}}}]))
    assert b.lists["scores"] == {"alice": 7, "bob": 2, "a": 2, "zoe": 3}, b.lists["scores"]
    # targets used directly (lot M5 may expose them as fields): check() gives the written type
    assert P.SETS["variable"].check(P.Checker(parse_ctx(), "w", "x"), name="n") == "integer"
    assert P.SETS["list_item"].check(P.Checker(parse_ctx(), "w", "x"), list="mots") == "string"
    assert P.SETS["dict_key"].check(P.Checker(parse_ctx(), "w", "x"), dict="scores", key="k") == "integer"


class _Ctx:
    """The parser attributes a target's check() reads (vars, lists, var_info)."""

    def __init__(self, g):
        self.vars, self.lists = dict(g.variables), dict(g.lists)

    def var_info(self, name):
        v = self.vars.get(name)
        return (v.type, v.choices) if v is not None else None


def parse_ctx():
    return _Ctx(parse(graph_of()))


def test_pre_resolved_kinds():
    b = fire(graph_of([{"add_var": {"name": "n", "delta": {"get": "calc", "a": 2, "op": "*", "b": 2}}}]))
    assert b.vars["n"] == 7
    raw = mini(veille=[{"on": "start", "do": [{"timer_start": {"name": "chrono"}}]},
                       {"on": "ask", "when": [{"elapsed_since": {"name": "chrono", "op": ">=", "seconds": {"get": "calc", "a": 1, "op": "+", "b": 1}}}],
                        "to": "a"}], variables=VARS)
    assert run(raw, [{"event": "start"}, {"wait_s": 1}, {"event": "ask"}])["final"]["state"] == "veille"
    assert run(raw, [{"event": "start"}, {"wait_s": 3}, {"event": "ask"}])["final"]["state"] == "a"
    raw = graph_of([{"say_dict": {"dict": "faq", "key": "rien", "fallback": {"get": "variable", "name": "t"}}}])
    said = []
    b, _clock = brain(raw)
    b._speak_then = lambda text, done=None: said.append(text)
    c = b._graph.states["veille"].transitions[0].do[0]
    b.engine.actions[c.name]({}, **c.args)
    assert said == ["a"], said


# ---------------------------------------------------------------- (6) round trips
def test_yaml_and_visual_roundtrip():
    prop = {"get": "calc", "a": {"get": "list_item", "list": "nums", "pick": "random"}, "op": "+", "b": "$n"}
    raw = mini(veille=[{"on": "start", "do": [{"set_var": {"name": "f", "value": prop}},
                                             {"dict_set": {"dict": "scores", "key": {"get": "utterance"}, "value": {"get": "constant", "value": 2}}}],
                        "to": "a"}],
               a=[{"on": "ask", "when": [{"var_compare": {"name": "f", "op": ">", "value": {"get": "random_number", "min": 1, "max": 3}}}],
                   "do": [{"add_var": {"name": "n", "delta": {"get": "system", "name": "tours"}}}], "to": "b"}],
               variables=VARS, intents=INTENTS)
    text = V.dump_yaml(copy.deepcopy(raw))
    back = yaml.load(text, Loader=G._Loader)
    assert back["states"]["veille"]["transitions"][0]["do"][0]["set_var"]["value"] == prop
    assert parse(back).to_dict() == parse(raw).to_dict()
    want = parse(raw).to_dict()
    doc = V.to_visual(copy.deepcopy(raw))
    acts = [n["params"] for n in doc["nodes"] if n["kind"] == "action"]
    assert any(p["args"].get("value") == prop for p in acts), acts
    vback, _layout, errs = V.from_visual(doc, CFG)
    assert not errs, errs
    assert vback["states"]["veille"]["transitions"][0]["do"][0] == {"set_var": {"name": "f", "value": prop}}
    assert parse(vback).to_dict() == want
    os.makedirs(TMP, exist_ok=True)
    gp, lp = os.path.join(TMP, "graph.yaml"), os.path.join(TMP, "graph.layout.json")
    ok, errs = V.save(doc, CFG, gp, lp)
    assert ok, errs
    saved = V.load_raw(gp)
    assert saved["states"]["veille"]["transitions"][0]["do"][0]["set_var"]["value"] == prop
    assert parse(saved).to_dict() == want
    shutil.rmtree(TMP, ignore_errors=True)


# ---------------------------------------------------------------- (7) drop-a-file + broken modules
PROBE = r'''
import json, os, sys
sys.path.insert(0, "/opt/robot/lib")
root = os.path.dirname(os.path.abspath(__file__))
import nanterino
assert os.path.dirname(os.path.abspath(nanterino.__file__)) == os.path.join(root, "nanterino"), nanterino.__file__
try:
    from nanterino import graph as G, properties as P
except Exception as e:
    print("IMPORT_ERROR %s: %s" % (type(e).__name__, e)); sys.exit(3)
v = G.vocabulary({"media_dir": "/nonexistent"})
res = {"gets": list(P.GETS), "sets": list(P.SETS), "vocab_gets": [e["id"] for e in v["properties"]["get"]],
       "vocab_sets": [e["id"] for e in v["properties"]["set"]]}
raw = {"states": {"veille": {"transitions": [{"on": "start", "to": "eteint", "do": [
    {"set_var": {"name": "n", "value": {"get": "forty_two"}}}]}]}, "eteint": {}},
    "variables": {"names": {"n": {"type": "number", "value": 0}}}}
if "forty_two" in P.GETS:
    g = G.parse_graph(raw, {}, "<probe>")
    res["compiled"] = dict(g.states["veille"].transitions[0].do[0].args)
print("RESULT " + json.dumps(res, ensure_ascii=False))
'''

FORTY_TWO = '''"""Test-only value source dropped into a temporary package copy (tests/test_properties.py)."""
from nanterino.properties import GetSource


class FortyTwo(GetSource):
    id = "forty_two"
    order = 500
    label = "Quarante-deux"
    help = "Toujours 42."
    icon = "square"
    out = "number"
    args = {}

    def get(self, ctx):
        return 42
'''

NOTE = '''"""Test-only write target (tests/test_properties.py)."""
from nanterino.nodes.base import Arg
from nanterino.properties import SetTarget


class Note(SetTarget):
    id = "note"
    order = 500
    label = "Note"
    help = "Cible de test."
    icon = "square"
    args = {"name": Arg("wvar", "Variable")}

    def check(self, parser, name):
        return "string"

    def write(self, ctx, value, name):
        ctx.brain._set_var(name, value)
'''


def package_copy(tag: str) -> str:
    root = os.path.join(TMP, tag)
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(PKG, os.path.join(root, "nanterino"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.npz", "*.onnx", "*.engine"))
    with open(os.path.join(root, "probe.py"), "w", encoding="utf-8") as f:
        f.write(PROBE)
    return root


def run_probe(root: str) -> tuple:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    p = subprocess.run([sys.executable, os.path.join(root, "probe.py")], cwd=root, env=env, capture_output=True, text=True,
                       timeout=120)
    return p.returncode, p.stdout + p.stderr


def probe_result(out: str) -> dict:
    line = next((x for x in out.splitlines() if x.startswith("RESULT ")), None)
    assert line, out[-2000:]
    return json.loads(line[len("RESULT "):])


def test_drop_a_file_per_family():
    root = package_copy("drop")
    for rel, src in (("properties/get/forty_two.py", FORTY_TWO), ("properties/set/note.py", NOTE)):
        with open(os.path.join(root, "nanterino", rel), "w", encoding="utf-8") as f:
            f.write(src)
    rc, out = run_probe(root)
    assert rc == 0, out[-2000:]
    r = probe_result(out)
    assert r["gets"] == GET_IDS + ["forty_two"] == r["vocab_gets"], r
    assert r["sets"] == SET_IDS + ["note"] == r["vocab_sets"], r
    assert r["compiled"] == {"name": "n", "value": {"get": "forty_two"}}, r
    assert "forty_two" not in P.GETS and "note" not in P.SETS, "production registries must not see the copy"
    # removing a source file from a copy removes it from the vocabulary (no hidden second list)
    root = package_copy("mutant")
    os.remove(os.path.join(root, "nanterino", "properties", "get", "calc.py"))
    rc, out = run_probe(root)
    assert rc == 0, out[-2000:]
    assert "calc" not in probe_result(out)["vocab_gets"]
    shutil.rmtree(os.path.join(TMP, "drop"), ignore_errors=True)
    shutil.rmtree(os.path.join(TMP, "mutant"), ignore_errors=True)


def temp_family(tag: str, files: dict) -> str:
    pkg = "m4tmp_" + tag
    d = os.path.join(TMP, "fam", pkg)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "__init__.py"), "w").close()
    for name, src in files.items():
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(src)
    importlib.invalidate_caches()   # the folder is new: refresh the path finders
    if os.path.join(TMP, "fam") not in sys.path:
        sys.path.insert(0, os.path.join(TMP, "fam"))
    return pkg


def expect_error(family: str, files: dict, tag: str, needle: str):
    pkg = temp_family(tag, files)
    try:
        P.scan(family, pkg)
    except RegistryError as e:
        assert needle in str(e), "message %r lacks %r" % (str(e), needle)
        return
    raise AssertionError("no RegistryError for %s" % tag)


def test_broken_modules_fail_clearly():
    expect_error("get", {"forty_two.py": FORTY_TWO.replace("def get(self, ctx):", "def get(self, ctx:")}, "g_syntax",
                 "property module properties/get/forty_two.py failed to import: SyntaxError")
    expect_error("get", {"forty_two.py": '"""no class"""\n'}, "g_none", "properties/get/forty_two.py: expected exactly one GetSource subclass, found 0")
    expect_error("get", {"quarante.py": FORTY_TWO}, "g_idname", "id 'forty_two' must equal the file name 'quarante'")
    expect_error("get", {"forty_two.py": FORTY_TWO.replace("args = {}", "args = {'x': __import__('nanterino.nodes.base', fromlist=['Arg']).Arg('colour', 'X')}")},
                 "g_kind", "forty_two.x: unknown argument kind 'colour'")
    expect_error("get", {"forty_two.py": FORTY_TWO.replace("def get(self, ctx):", "def get(self, ctx, extra):")}, "g_sig",
                 "forty_two.get() must take (ctx, )")
    expect_error("get", {"forty_two.py": FORTY_TWO.replace('out = "number"', 'out = ("of", "list")')}, "g_out",
                 "forty_two.out must be a type id")
    expect_error("get", {"forty_two.py": FORTY_TWO.replace('help = "Toujours 42."', 'help = ""')}, "g_help", "forty_two.help must be a non-empty string")
    expect_error("set", {"note.py": NOTE.replace("def write(self, ctx, value, name):", "def write(self, ctx, name):")}, "s_sig",
                 "note.write() must take (ctx, value, name)")
    expect_error("set", {"note.py": NOTE.replace('id = "note"', 'id = "Note"')}, "s_id", "properties/set/note.py: id 'Note' is not a lower snake case name")
    expect_error("set", {"note.py": '"""two"""\nfrom nanterino.properties import SetTarget\n\n\nclass A(SetTarget):\n    id = "note"\n\n\nclass B(SetTarget):\n    id = "b"\n'},
                 "s_two", "expected exactly one SetTarget subclass, found 2")
    try:   # an icon that is not vendored is refused by the graph-side check
        P.check_registry({"x": type("X", (P.GetSource,), {"id": "x", "icon": "rocket", "out": "number"})()}, {}, G.all_icons(), G.VAR_TYPES)
    except RegistryError as e:
        assert "x.icon 'rocket' is not a vendored icon" in str(e), str(e)
    else:
        raise AssertionError("bad icon accepted")
    shutil.rmtree(os.path.join(TMP, "fam"), ignore_errors=True)


def test_production_scan_is_closed():
    assert P.PACKAGES == {"get": "nanterino.properties.get", "set": "nanterino.properties.set"}
    src = open(P.__file__, encoding="utf-8").read()
    assert "GETS = scan(\"get\")" in src and "SETS = scan(\"set\")" in src and "eval(" not in src
    for d in ("get", "set"):
        for f in os.listdir(os.path.join(PKG, "properties", d)):
            if f.endswith(".py"):
                body = open(os.path.join(PKG, "properties", d, f), encoding="utf-8").read()
                assert "eval(" not in body and "exec(" not in body, f


# ---------------------------------------------------------------- (8) simulator scenario
def test_simulator_scenario_with_properties():
    raw = mini(veille=[{"on": "start", "do": [{"set_var": {"name": "n", "value": {"get": "calc", "a": "$n", "op": "+",
                                                                                   "b": {"get": "list_item", "list": "nums", "pick": "last"}}}}],
                        "to": "a"}],
               a=[{"on": "ask", "when": [{"var_compare": {"name": "n", "op": ">=", "value": {"get": "calc", "a": 4, "op": "*", "b": 2}}}],
                   "do": [{"set_var": {"name": "ph", "value": {"get": "utterance"}}}], "to": "b"},
                  {"on": "ask", "to": "veille"}],
               variables=VARS, intents=INTENTS)
    steps = [{"event": "start"}, {"say": "une question"}, {"event": "ask"}]
    r1, r2 = run(raw, steps), run(raw, steps)
    assert r1 == r2, "deterministic"
    assert r1["final"]["state"] == "b", r1["final"]["state"]
    assert r1["final"]["vars"]["names"]["n"] == 8
    # the same graph with a bigger threshold takes the other branch
    raw2 = copy.deepcopy(raw)
    raw2["states"]["a"]["transitions"][0]["when"][0]["var_compare"]["value"]["b"] = 3
    assert run(raw2, steps)["final"]["state"] == "veille"
    # the shipped graph is unchanged and still valid
    g = G.load_graph(G.DEFAULT_PATH, CFG)
    assert not [d for d in g.diagnostics if d[2] == "division_by_zero"]


TESTS = [test_discovery_and_vocabulary, test_goldens_only_gained_keys, test_goldens_m5_only_gained_keys, test_constant_variable_utterance_system,
         test_list_and_dict_sources, test_random_number_intent_config_elapsed, test_calc_ops_nesting_and_division_by_zero,
         test_shorthand_equivalence, test_refusals_are_clear, test_constant_bounds_diagnostic,
         test_set_targets_clamp_push_and_keys, test_pre_resolved_kinds, test_yaml_and_visual_roundtrip,
         test_drop_a_file_per_family, test_broken_modules_fail_clearly, test_production_scan_is_closed,
         test_simulator_scenario_with_properties]


def main(only):
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
    print("properties tests: %d passed, %d failed" % (ran - failed, failed))
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
