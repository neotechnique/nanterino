"""Tests of the graph variables and of the trigger-without-input visual form (lot L1, 2026-10-31).

logging: robotlog via tests.test_brain_graph (imported for the shared fake world and BASE_CFG).

Purpose
    Plan "Vérification 2": every variable type is validated; set_var fires var_changed with the anti-loop; list_contains
    works with $utterance; say_random phrases are cached at load and stay muted; system variables are read-only; a
    variable still used cannot be deleted (save refused = HTTP 400); a wire into a trigger is refused; an old layout
    with state hubs migrates to the variables drawing. Plus: etat in [A, B] duplicates the chain under each state with
    one fan id, the simulator returns the variables per step, the vocabulary only names vendored icons.

Boundary
    Pure functions, the simulator and a non-threaded Brain on the fake world of nanterino/sim.py (virtual clock,
    muted fake output, no thread, no file but /tmp/test_graph_vars). The live robot and server are never touched.

How to run (repo root):
    .venv/bin/python -m tests.test_graph_vars          # ~5 s
"""
import copy
import json
import os
import shutil
import sys

sys.path.insert(0, "/opt/robot/lib")

from nanterino import config, graph as G, graph_layout as GL, graph_visual as V, sim  # noqa: E402
from nanterino.brain import Brain  # noqa: E402
from tests import test_brain_graph as tbg  # noqa: E402

CFG = dict(config.DEFAULTS)
CFG.update(tbg.BASE_CFG)
TMP = "/tmp/test_graph_vars"
TABLER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "vendor", "tabler")


# ---------------------------------------------------------------- helpers
def mini(veille=(), a=(), b=(), glob=(), variables=None, intents=None):
    """Tiny raw graph: veille (start), eteint, a, b; each argument is a list of raw transitions."""
    def st(trs):
        d = {"description": "état de test"}
        if trs:
            d["transitions"] = [dict(t, description=t.get("description", "test")) for t in trs]
        return d
    raw = {"version": 1, "states": {"veille": st(veille), "eteint": st([]), "a": st(a), "b": st(b)}}
    if glob:
        raw["global"] = [dict(t, description=t.get("description", "test")) for t in glob]
    if variables is not None:
        raw["variables"] = variables
    if intents:
        raw["intents"] = intents
    return raw


def parse(raw):
    return G.parse_graph(copy.deepcopy(raw), CFG, "<test>")


def refused(raw, fragment):
    try:
        parse(raw)
    except G.GraphError as e:
        assert fragment in str(e), (fragment, str(e))
        return
    raise AssertionError("accepted although invalid: " + fragment)


def run(raw, steps, **kw):
    return sim.simulate(copy.deepcopy(raw), dict(CFG), kw.pop("start_state", "veille"), steps, **kw)


def sim_brain(raw):
    """Non-threaded Brain on the fake world (same wiring as sim.simulate) for direct inspection."""
    clock = sim.SimClock()
    rec, tts = sim.Rec(), sim.FakeTTS()
    out = sim.FakeOut(rec, tts, clock)
    cfg = dict(CFG, power="on")
    b = Brain(cfg, out, sim.FakeSTT(), sim.FakeLLM(rec), tts, sim.FakeCorpus(), clock=clock, mic=sim.FakeIn(rec),
              graph=parse(raw), threaded=False, start_state="veille")
    b.rng.seed(0)
    b.pump()
    return b, rec, tts, clock


def N(i, kind, **params):
    return {"id": i, "kind": kind, "x": 0, "y": 0, "description": "", "params": params}


def L(a, b, port="out"):
    return {"from": a, "port": port, "to": b}


def etat(op, value, **extra):
    return dict({"type": "guard", "guard": "var_compare", "args": {"name": "etat", "op": op, "value": value}, "negate": False}, **extra)


def vdoc(nodes, links, order, variables=None):
    """Hand-made document of the variables drawing (no state / goto node)."""
    states = [{"id": s, "description": "d " + s, "color": "#000000"} for s in ("veille", "eteint", "a", "b")]
    return {"version": 1, "nodes": [N("start", "start", state="veille")] + nodes, "links": links, "states": states,
            "intents": {}, "order": order, **({"variables": variables} if variables is not None else {})}


VARS = {"names": {"score": {"type": "number", "value": 0}, "ok": {"type": "bool", "value": False},
                  "humeur": {"type": "choice", "value": "calme", "choices": ["calme", "joyeux"]},
                  "nom": {"type": "string", "value": ""}, "pause": {"type": "duration", "value": 2.5}},
        "lists": {"mots": {"type": "string", "items": ["bonjour", "salut"]},
                  "phrases": {"type": "string", "items": ["Phrase un.", "Phrase deux."]},
                  "refus": {"type": "string", "from": "refusal_words"}}}


# ---------------------------------------------------------------- tests
def test_each_type_is_validated():
    g = parse(mini(variables=VARS))
    assert {v.name: v.type for v in g.variables.values()} == {"score": "number", "ok": "bool", "humeur": "choice",
                                                               "nom": "string", "pause": "duration"}
    assert g.lists["refus"].source == ("cfg", "refusal_words") and g.lists["refus"].items == tuple(CFG["refusal_words"])
    assert g.to_dict()["variables"]["lists"]["refus"] == {"type": "string", "from": "refusal_words"}
    bad = [({"names": {"x": {"type": "bool", "value": 1}}}, "not a valid bool"),
           ({"names": {"x": {"type": "number", "value": "3"}}}, "not a valid number"),
           ({"names": {"x": {"type": "duration", "value": -1}}}, "not a valid duration"),
           ({"names": {"x": {"type": "string", "value": "x" * 301}}}, "not a valid string"),
           ({"names": {"x": {"type": "choice", "value": "z", "choices": ["a", "b"]}}}, "not a valid choice"),
           ({"names": {"x": {"type": "choice", "value": "a"}}}, "needs `choices:`"),
           # CHANGED (lot L11): `color` became a real type (tests/test_graph_vars2.py), an unknown type is still refused
           ({"names": {"x": {"type": "texture", "value": "#fff"}}}, "type must be one of"),
           ({"names": {"x": {"type": "bool"}}}, "`value:` (initial value) is required"),
           ({"names": {"tours": {"type": "number", "value": 0}}}, "not be a system variable"),
           ({"names": {"Bad-Name": {"type": "number", "value": 0}}}, "must match"),
           ({"names": {"x": {"type": "number", "value": 0}}, "lists": {"x": {"items": []}}}, "differ from every variable"),
           ({"lists": {"l": {"type": "number", "items": [1, "deux"]}}}, "item #2"),
           ({"lists": {"l": {"type": "string", "from": "nope_key"}}}, "not a config key holding a list"),
           ({"lists": {"l": {"type": "string", "intent": "nobody"}}}, "unknown intent"),
           ({"lists": {"l": {"type": "string"}}}, "exactly one of items / from"),
           ({"names": {"x": {"type": "number", "value": 0, "colour": 1}}}, "unknown key 'colour'")]
    for block, frag in bad:
        refused(mini(variables=block), frag)
    # values used by actions / conditions follow the variable's type
    refused(mini(veille=[{"on": "start", "do": [{"set_var": {"name": "ok", "value": "yes"}}]}], variables=VARS), "not a valid bool")
    refused(mini(veille=[{"on": "start", "do": [{"set_var": {"name": "humeur", "value": "triste"}}]}], variables=VARS), "choices: calme, joyeux")
    refused(mini(veille=[{"on": "start", "do": [{"add_var": {"name": "ok", "delta": 1}}]}], variables=VARS), "not a number or duration")
    refused(mini(veille=[{"on": "start", "when": [{"var_compare": {"name": "nom", "op": "<", "value": "a"}}], "to": "a"}],
                 variables=VARS), "only compares numbers")
    refused(mini(veille=[{"on": "start", "do": [{"list_add": {"list": "refus", "value": "x"}}]}], variables=VARS), "read-only")
    refused(mini(veille=[{"on": "start", "do": [{"set_var": {"name": "inconnue", "value": 1}}]}], variables=VARS), "unknown variable")
    refused(mini(veille=[{"on": "start", "do": [{"set_var": {"name": "score", "value": "$nom"}}]}], variables=VARS), "is string, expected number")
    parse(mini(veille=[{"on": "start", "do": [{"set_var": {"name": "score", "value": "$tours"}}]}], variables=VARS))
    # the editor may send typed values as text: the compiler converts them with the variable's type
    assert G.coerce_value("number", "3") == 3 and G.coerce_value("duration", "2.5") == 2.5
    assert G.coerce_value("bool", "vrai") is True and G.coerce_value("string", "3") == "3"


def test_system_variables_are_read_only():
    for name in ("tours", "max_tours", "reparations", "max_reparations"):
        refused(mini(veille=[{"on": "start", "do": [{"set_var": {"name": name, "value": 1}}]}]), "read-only system variable")
    refused(mini(veille=[{"on": "start", "do": [{"set_var": {"name": "etat", "value": "a"}}]}]), "change the state with `to:`")
    refused(mini(veille=[{"on": "start", "when": [{"var_compare": {"name": "etat", "op": "=", "value": "a"}}], "to": "a"}]),
            "only_in / not_in")
    refused(mini(veille=[{"on": "var_changed", "var": "etat", "to": "a"}]), "use the state's on_enter")
    # reading a system variable is fine (tours < max_tours = the display of turns_left)
    parse(mini(veille=[{"on": "start", "when": [{"var_compare": {"name": "tours", "op": "<", "value": "$max_tours"}}], "to": "a"}]))
    v = G.vocabulary(CFG, parse(mini()))
    assert next(g for g in v["guards"] if g["id"] == "turns_left")["as_vars"] == "tours < max_tours"
    sysv = [x for x in v["variables"]["names"] if x["system"]]
    assert [x["id"] for x in sysv] == list(G.SYSTEM_VARS) and all(x["readonly"] for x in sysv)
    assert sysv[0]["choices"] == ["veille", "eteint", "a", "b"]
    # in the editor: set_var on a system counter is refused on its node; set_var(etat) compiles to `to:`
    doc = vdoc([N("t", "trigger", type="event", event="start"), N("c", "condition", **etat("=", "veille")),
                N("x", "action", action="set_var", args={"name": "tours", "value": 3}, phase="do")],
               [L("t", "c"), L("c", "x", "true")], ["t"])
    _r, _l, errs = V.from_visual(doc, CFG)
    assert any(e["node"] == "x" and "lecture seule" in e["message"] for e in errs), errs
    doc["nodes"][-1]["params"] = {"action": "set_var", "args": {"name": "etat", "value": "a"}, "phase": "do", "reason": "bouton"}
    raw, _l, errs = V.from_visual(doc, CFG)
    assert not errs and raw["states"]["veille"]["transitions"] == [{"on": "start", "to": "a", "reason": "bouton", "description": ""}], raw


def test_set_var_fires_var_changed_with_anti_loop():
    raw = mini(veille=[{"on": "start", "do": [{"set_var": {"name": "score", "value": 1}}, {"toggle_var": {"name": "ok"}}]}],
               a=[{"on": "ask", "when": [{"var_compare": {"name": "score", "op": ">=", "value": 2}}, {"var_true": {"name": "ok"}}],
                   "do": [{"add_var": {"name": "pause", "delta": -10}}], "to": "b", "reason": "compte"}],
               glob=[{"on": "var_changed", "var": "score", "do": [{"add_var": {"name": "score", "delta": 1}}],
                      "description": "would loop forever without the anti-loop"},
                     {"on": "var_changed", "var": "score", "value": 1, "to": "a", "reason": "score1"}],
               variables=VARS)
    res = run(raw, [{"event": "start"}, {"event": "ask"}])
    fired = [(e["event"], e["chain"]) for e in res["trace"] if e["event"] == "var_changed"]
    # score 0 -> 1 posts ONE var_changed: both global chains react; the +1 they cause is a cascade and is dropped
    assert fired == [("var_changed", "global/t0"), ("var_changed", "global/t1")], fired
    assert [(e["from"], e["to"], e["reason"]) for e in res["trace"] if e["moved"]] == [("veille", "a", "score1"), ("a", "b", "compte")]
    names = res["final"]["vars"]["names"]
    assert names["score"] == 2 and names["ok"] is True and names["pause"] == 0, names    # a duration never goes below 0
    assert names["etat"] == "b" and res["final"]["state"] == "b"
    # without the watcher nothing is posted at all (no event noise on the live robot)
    quiet = mini(veille=[{"on": "start", "do": [{"set_var": {"name": "score", "value": 5}}]}], variables=VARS)
    r2 = run(quiet, [{"event": "start"}])
    assert not [e for e in r2["trace"] if e["event"] == "var_changed"] and r2["final"]["vars"]["names"]["score"] == 5


def test_list_contains_with_utterance_and_list_actions():
    raw = mini(veille=[{"on": "intent.question", "when": [{"list_contains": {"list": "mots", "value": "$utterance"}}],
                        "do": [{"list_add": {"list": "phrases", "value": "$utterance"}}], "to": "a", "reason": "mot"},
                       {"on": "intent.question", "when": [{"not": {"list_contains": {"list": "mots", "value": "$utterance"}}}],
                        "to": "b", "reason": "autre"}],
               a=[{"on": "ask", "when": [{"list_contains": {"list": "phrases", "value": "Salut robot"}}],
                   "do": [{"list_remove": {"list": "mots", "value": "salut"}}, {"list_clear": {"list": "phrases"}}]},
                  {"on": "stop", "when": [{"list_empty": {"list": "phrases"}}], "to": "veille", "reason": "vide"}],
               variables=VARS)
    res = run(raw, [{"say": "Salut robot"}, {"event": "ask"}, {"event": "stop"}])
    assert [e["reason"] for e in res["trace"] if e["moved"]] == ["mot", "vide"], res["trace"]
    lists = res["final"]["vars"]["lists"]
    assert lists["mots"] == ["bonjour"] and lists["phrases"] == [] and lists["refus"] == CFG["refusal_words"], lists
    assert [e["reason"] for e in run(raw, [{"say": "Rien de tout cela"}])["trace"] if e["moved"]] == ["autre"]


def test_say_random_is_cached_and_stays_muted():
    raw = mini(veille=[{"on": "start", "do": [{"say_random": {"list": "phrases"}}], "to": "a"}],
               a=[{"on": "say_done", "to": "b", "reason": "dit"}], variables=VARS)
    assert G.say_texts(parse(raw)) == ["Phrase un.", "Phrase deux."]
    b, rec, tts, clock = sim_brain(raw)
    assert {"Phrase un.", "Phrase deux."} <= set(b._phrases), "list phrases synthesised at graph load"
    calls = []
    real = tts.synth
    tts.synth = lambda t: (calls.append(t), real(t))[1]
    b.post("start"); b.pump()
    played = [e[1] for e in rec.events if e[0] == "play"]
    assert len(played) == 1 and played[0] in ("Phrase un.", "Phrase deux.") and calls == [], (played, calls)
    assert b.out.muted is True, "a muted robot stays muted"
    for _ in range(30):
        clock.t += 0.1
        b._on_tick({"t": clock.t}); b.pump()
    assert b.state == "b"
    # same input, same pick in the simulator (rng seeded)
    r1, r2 = run(raw, [{"event": "start"}, {"wait_s": 3}]), run(raw, [{"event": "start"}, {"wait_s": 3}])
    assert r1 == r2 and r1["final"]["state"] == "b"


def test_used_variable_cannot_be_deleted():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    gp, lp = os.path.join(TMP, "graph.yaml"), os.path.join(TMP, "graph.layout.json")
    doc = vdoc([N("t", "trigger", type="event", event="start"), N("c", "condition", **etat("=", "veille")),
                N("x", "action", action="set_var", args={"name": "score", "value": "4"}, phase="do")],
               [L("t", "c"), L("c", "x", "true")], ["t"], copy.deepcopy(VARS))
    raw, _l, errs = V.from_visual(doc, CFG)
    assert not errs and raw["states"]["veille"]["transitions"][0]["do"] == [{"set_var": {"name": "score", "value": 4}}]
    del doc["variables"]["names"]["score"]
    ok, errs = V.save(doc, CFG, gp, lp)          # the server answers 400 with these errors
    assert not ok and any(e["node"] == "t" and "unknown variable 'score'" in e["message"] for e in errs), errs
    assert not os.path.exists(gp), "nothing written"
    # an unused one can go
    doc2 = copy.deepcopy(doc)
    doc2["variables"]["names"]["score"] = {"type": "number", "value": 0}
    del doc2["variables"]["names"]["nom"]
    assert V.save(doc2, CFG, gp, lp)[0]
    assert V.load_layout(lp)["form"] == "vars"
    shutil.rmtree(TMP, ignore_errors=True)


def test_wire_into_trigger_is_refused():
    doc = vdoc([N("t", "trigger", type="event", event="start"), N("c", "condition", **etat("=", "veille")),
                N("x", "action", action="mic_on", args={}, phase="do"), N("t2", "trigger", type="event", event="stop")],
               [L("t", "c"), L("c", "x", "true"), L("x", "t2"), L("t2", "x")], ["t", "t2"])
    _r, _l, errs = V.from_visual(doc, CFG)
    assert any(e["node"] == "t2" and "n'a pas d'entrée" in e["message"] for e in errs), errs
    # every trigger of the default drawing has no incoming wire and the vocabulary says so
    d = V.to_visual(V.load_raw(G.DEFAULT_PATH))
    trig = {n["id"] for n in d["nodes"] if n["kind"] == "trigger"}
    assert trig and not [l for l in d["links"] if l["to"] in trig]
    assert next(k for k in G.vocabulary(CFG)["kinds"] if k["id"] == "trigger")["inputs"] == 0


def test_old_hub_layout_migrates():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    gp, lp = os.path.join(TMP, "graph.yaml"), os.path.join(TMP, "graph.layout.json")
    raw = V.load_raw(G.DEFAULT_PATH)
    hub = json.loads(json.dumps(V.to_visual(raw, form="hub")))       # what the L6-L8 editor saved
    trig = next(n for n in hub["nodes"] if n["kind"] == "trigger" and n["params"].get("event") == "stop")
    trig["x"], trig["y"] = 7777, 7777
    hub["frames"].append({"id": "mine", "title": "Mon groupe", "color": "#112233", "x": 1, "y": 2, "w": 30, "h": 40})
    assert V.save(hub, CFG, gp, lp)[0]
    old = V.load_layout(lp)
    assert any(k.startswith("state/") for k in old["nodes"]) and "form" not in old
    new = V.to_visual(V.load_raw(gp), old)                           # the next GET after the update
    assert not [n for n in new["nodes"] if n["kind"] in ("state", "goto")]
    assert all((n["x"], n["y"]) != (7777, 7777) for n in new["nodes"]), "old positions do not fit the new drawing"
    ids = [f["id"] for f in new["frames"]]
    assert ids[0] == "mine" and ids[1:] == ["auto-" + s for s in raw["states"]] + ["auto-global"], ids
    a = G.parse_graph(V.load_raw(gp), CFG, "x").to_dict()
    raw2, layout2, errs = V.from_visual(json.loads(json.dumps(new)), CFG)
    assert not errs and layout2["form"] == "vars"
    b = G.parse_graph(raw2, CFG, "x").to_dict()
    for d in (a, b):
        d.pop("source")
        for t in d["global"] + [t for s in d["states"].values() for t in s["transitions"]]:
            t.pop("fan", None)
    assert a == b, "migration changed the graph"
    shutil.rmtree(TMP, ignore_errors=True)


def test_multi_state_condition_duplicates_with_one_fan():
    nodes = [N("t", "trigger", type="event", event="stop"), N("c", "condition", **etat("in", ["veille", "a"])),
             N("x", "action", action="cancel_all", args={}, phase="do"),
             N("m", "action", action="set_var", args={"name": "etat", "value": "b"}, phase="do", reason="dup"),
             N("y", "action", action="mic_on", args={}, phase="do")]
    links = [L("t", "c"), L("c", "x", "true"), L("x", "m"), L("m", "y")]
    raw, _l, errs = V.from_visual(vdoc(nodes, links, ["t"]), CFG)
    assert not errs, errs
    va, vb = raw["states"]["veille"]["transitions"], raw["states"]["a"]["transitions"]
    assert va == vb and len(va) == 1 and "global" not in raw and va[0]["fan"] == "fan-t"
    assert va[0]["do"] == ["cancel_all"] and va[0]["to"] == "b" and va[0]["then"] == ["mic_on"], va  # after the move = then
    for start in ("veille", "a"):
        assert run(raw, [{"event": "stop"}], start_state=start)["final"]["state"] == "b"
    # `global: true` keeps a global only_in rule; not_in / != make a global not_in rule
    nodes[1] = N("c", "condition", **etat("in", ["veille", "a"], **{"global": True}))
    raw, _l, errs = V.from_visual(vdoc(nodes, links, ["t"]), CFG)
    assert not errs and raw["global"][0]["only_in"] == ["veille", "a"] and not raw["states"]["veille"].get("transitions")
    nodes[1] = N("c", "condition", **etat("!=", "eteint"))
    raw, _l, errs = V.from_visual(vdoc(nodes, links, ["t"]), CFG)
    assert not errs and raw["global"][0]["not_in"] == ["eteint"]
    # a delay may now be shared by several states (one copy each)
    after = [N("t", "trigger", type="after", delay=2, since="state"), N("c", "condition", **etat("in", ["a", "b"])),
             N("m", "action", action="set_var", args={"name": "etat", "value": "veille"}, phase="do")]
    raw, _l, errs = V.from_visual(vdoc(after, [L("t", "c"), L("c", "m", "true")], ["t"]), CFG)
    assert not errs and raw["states"]["a"]["transitions"][0]["after"] == 2 and raw["states"]["b"]["transitions"][0]["to"] == "veille"
    # two moves in one chain are refused; on_enter (etat becomes X) cannot move
    two = vdoc(nodes[:1] + [N("c", "condition", **etat("=", "veille")), nodes[3],
                            N("m2", "action", action="set_var", args={"name": "etat", "value": "a"}, phase="do")],
               [L("t", "c"), L("c", "m", "true"), L("m", "m2")], ["t"])
    assert any("Un seul changement d'état" in e["message"] for e in V.from_visual(two, CFG)[2])
    ent = vdoc([N("t", "trigger", type="event", event="var_changed", name="etat", value="a", enabled=True),
                N("m", "action", action="set_var", args={"name": "etat", "value": "b"}, phase="do")], [L("t", "m")], ["t"])
    assert any(e["node"] == "m" for e in V.from_visual(ent, CFG)[2])
    ent["nodes"][-1]["params"] = {"action": "mic_on", "args": {}, "phase": "do"}
    raw, _l, errs = V.from_visual(ent, CFG)
    assert not errs and raw["states"]["a"]["on_enter"] == ["mic_on"]


def test_user_var_changed_trigger_roundtrips():
    raw = mini(veille=[{"on": "start", "do": [{"set_var": {"name": "humeur", "value": "joyeux"}}]}],
               glob=[{"on": "var_changed", "var": "humeur", "value": "joyeux", "to": "a", "reason": "humeur"}], variables=VARS)
    doc = json.loads(json.dumps(V.to_visual(raw)))
    trig = next(n for n in doc["nodes"] if n["params"].get("event") == "var_changed" and n["params"].get("name") == "humeur")
    assert trig["params"]["value"] == "joyeux" and doc["variables"] == VARS
    raw2, _l, errs = V.from_visual(doc, CFG)
    assert not errs and parse(raw2).to_dict()["global"] == parse(raw).to_dict()["global"]
    assert "var: humeur" in V.dump_yaml(raw2) and "variables:" in V.dump_yaml(raw2)
    assert run(raw2, [{"event": "start"}])["final"]["state"] == "a"


def test_simulator_returns_vars_per_step():
    res = run(V.load_raw(G.DEFAULT_PATH), [{"event": "start"}, {"wait_s": 3}, {"say": "Où sont les toilettes ?"}])
    assert all("vars" in e for e in res["trace"])
    seen = [e["vars"]["names"]["etat"] for e in res["trace"]]
    assert seen[0] == "veille" and "ecoute" in seen, seen
    assert res["final"]["vars"]["names"]["tours"] == 1 and res["final"]["vars"]["names"]["max_tours"] == 12
    assert sorted(res["final"]["vars"]["lists"]) == ["mots_appel", "mots_refus", "salutations"]
    assert res["final"]["vars"]["lists"]["mots_appel"] == ["nanter"]


def test_vocabulary_icons_are_vendored():
    v = G.vocabulary(CFG, parse(mini(variables=VARS)))
    icons = {x["icon"] for k in ("events", "actions", "guards", "kinds") for x in v[k]}
    missing = [i for i in sorted(icons | set(G.all_icons())) if not os.path.exists(os.path.join(TABLER, i + ".svg"))]
    assert not missing, missing
    sv = next(a for a in v["actions"] if a["id"] == "set_var")
    assert [(a["name"], a["type"]) for a in sv["args"]] == [("name", "var"), ("value", "value")] and sv["args"][0]["writable"]
    lc = next(g for g in v["guards"] if g["id"] == "list_contains")
    assert lc["args"][1]["utterance"] is True and lc["args"][0]["type"] == "list"
    assert next(e for e in v["events"] if e["id"] == "var_changed")["args"][1]["optional"] is True
    assert "var_changed" not in next(a for a in v["actions"] if a["id"] == "emit")["args"][0]["options"]
    names = {x["id"]: x for x in v["variables"]["names"]}
    assert names["humeur"]["choices"] == ["calme", "joyeux"] and not names["humeur"]["readonly"]
    lists = {x["id"]: x for x in v["variables"]["lists"]}
    assert lists["refus"]["readonly"] and lists["refus"]["source"] == {"cfg": "refusal_words"} and not lists["mots"]["readonly"]
    json.dumps(v)


def test_live_snapshot_shape():
    b, _rec, _tts, _clock = sim_brain(mini(variables=VARS))
    snap = b.var_snapshot()                                          # what GET /api/graph/vars returns
    assert list(snap) == ["names", "lists"]
    assert snap["names"]["etat"] == "veille" and snap["names"]["score"] == 0 and snap["names"]["pause"] == 2.5
    assert snap["lists"]["mots"] == ["bonjour", "salut"]
    json.dumps(snap)
    # a reload resets the user values to the YAML ones
    b.vars["score"] = 9
    ok, _err = b.reload_graph()
    assert ok and b.var_snapshot()["names"]["score"] == 0


def test_default_graph_has_no_crossing():
    raw = V.load_raw(G.DEFAULT_PATH)
    doc = V.to_visual(raw)
    pos = {n["id"]: (n["x"], n["y"]) for n in doc["nodes"]}
    x = GL.crossings(doc["nodes"], doc["links"], pos)
    print("  variables drawing of the shipped graph: %d nodes, %d links, %d crossings" % (len(doc["nodes"]), len(doc["links"]), x))
    assert x == 0 and GL.overlaps(doc["nodes"], pos) == []
    # every link stays inside its column (group)
    grp = {n["id"]: n.get("group") for n in doc["nodes"]}
    assert all(grp[l["from"]] == grp[l["to"]] for l in doc["links"])


def _nofan(d):
    """Graph.to_dict() without the no-op `fan` tags (exclusive branches of one drawn trigger carry one)."""
    d = copy.deepcopy(d)
    for t in [t for s in d["states"].values() for t in s.get("transitions") or []] + list(d.get("global") or []):
        t.pop("fan", None)
    return d


def test_if_else_is_one_condition():
    """Lot L3: a transition pair `g` / `{not: g}` (same trigger and leading guards, adjacent) is ONE condition node
    whose Vrai output carries the first chain and Faux the second; it compiles back to the same two transitions."""
    raw = V.load_raw(G.DEFAULT_PATH)
    doc = json.loads(json.dumps(V.to_visual(raw)))
    by = {n["id"]: n for n in doc["nodes"]}
    negs = [n for n in doc["nodes"] if n["kind"] == "condition" and n["params"].get("negate")]
    false = [l for l in doc["links"] if l["port"] == "false"]
    assert negs == [], "a negated twin condition is still drawn: %s" % [(n["group"], n["params"]) for n in negs]
    assert sorted((by[l["from"]]["group"], by[l["from"]]["params"]["guard"]) for l in false) == [
        ("ecoute", "repairs_left"), ("ecoute", "turns_left"), ("relance", "repairs_left"), ("relance", "turns_left")], false
    for l in false:   # each Faux output belongs to a condition whose Vrai output is used too
        assert any(k["from"] == l["from"] and k["port"] == "true" for k in doc["links"]), l
    raw2, _l, errs = V.from_visual(doc, CFG)
    assert not errs, errs
    assert _nofan(parse(raw2).to_dict()) == _nofan(parse(raw).to_dict()), "if/else drawing changed the compiled graph"
    for st in ("ecoute", "relance"):   # the exact transitions (order, guards, actions) of the pairs, fan aside
        # (the compiler always writes `when` as a list; graph.yaml spells a single guard as a scalar)
        want = [dict(t, when=V._aslist(t["when"])) for t in raw["states"][st]["transitions"] if t.get("on") in ("intent.question", "not_understood")]
        got = [{k: v for k, v in t.items() if k != "fan"} for t in raw2["states"][st]["transitions"] if t.get("on") in ("intent.question", "not_understood")]
        assert got == want, (st, got, want)
    # redrawing the recompiled graph gives the same drawing (stable round trip)
    doc2 = V.to_visual(raw2)
    assert len(doc2["nodes"]) == len(doc["nodes"]) and len(doc2["links"]) == len(doc["links"])
    assert sum(1 for l in doc2["links"] if l["port"] == "false") == 4


def test_hand_wired_false_branch_compiles():
    """A Faux output wired by hand compiles to the negated-guard transition, right after the Vrai branch."""
    nodes = [N("t", "trigger", type="event", event="visage"), N("c", "condition", **etat("=", "a")),
             N("g", "condition", type="guard", guard="not_speaking", negate=False),
             N("r", "condition", type="guard", guard="repairs_left", negate=False),
             N("x", "action", action="count_repair", args={}, phase="do"),
             N("m", "action", action="set_var", args={"name": "etat", "value": "b"}, phase="do", reason="r"),
             N("y", "action", action="reset_repairs", args={}, phase="do"),
             N("u", "trigger", type="event", event="stop"), N("cu", "condition", **etat("=", "a")),
             N("z", "action", action="cancel_all", args={}, phase="do")]
    links = [L("t", "c"), L("c", "g", "true"), L("g", "r", "true"), L("r", "x", "true"), L("x", "m"), L("r", "y", "false"),
             L("u", "cu"), L("cu", "z", "true")]
    raw, _l, errs = V.from_visual(vdoc(nodes, links, ["t", "u"]), CFG)
    assert not errs, errs
    assert raw["states"]["a"]["transitions"] == [
        {"on": "visage", "fan": "fan-t", "when": ["not_speaking", "repairs_left"], "do": ["count_repair"], "to": "b", "reason": "r", "description": ""},
        {"on": "visage", "fan": "fan-t", "when": ["not_speaking", {"not": "repairs_left"}], "do": ["reset_repairs"], "description": ""},
        {"on": "stop", "do": ["cancel_all"], "description": ""}], raw["states"]["a"]["transitions"]
    assert run(raw, [{"event": "visage"}], start_state="a")["final"]["state"] == "b"   # repairs left at start: Vrai wins
    # redrawn: one repairs_left node again, Faux wired, no negated twin; compiles to the same transitions
    doc2 = json.loads(json.dumps(V.to_visual(raw)))
    assert sum(1 for l in doc2["links"] if l["port"] == "false") == 1
    assert not [n for n in doc2["nodes"] if n["kind"] == "condition" and n["params"].get("negate")]
    raw2, _l, errs = V.from_visual(doc2, CFG)
    assert not errs and _nofan(parse(raw2).to_dict()) == _nofan(parse(raw).to_dict())
    # g / not g / g: the third transition may NOT go back to the Vrai port (it would compile before the second one)
    raw3 = mini(a=[{"on": "visage", "when": "repairs_left", "do": ["count_repair"]},
                   {"on": "visage", "when": {"not": "repairs_left"}, "do": ["reset_repairs"]},
                   {"on": "visage", "when": "repairs_left", "do": ["cancel_all"]}])
    doc3 = json.loads(json.dumps(V.to_visual(raw3)))
    assert sum(1 for l in doc3["links"] if l["port"] == "false") == 1
    raw4, _l, errs = V.from_visual(doc3, CFG)
    assert not errs and _nofan(parse(raw4).to_dict()) == _nofan(parse(raw3).to_dict()), raw4["states"]["a"]
    # a condition that is itself negated: its Faux output gives the positive guard
    nodes[3] = N("r", "condition", type="guard", guard="repairs_left", negate=True)
    raw, _l, errs = V.from_visual(vdoc(nodes, links, ["t", "u"]), CFG)
    assert not errs and [t.get("when") for t in raw["states"]["a"]["transitions"]] == [
        ["not_speaking", {"not": "repairs_left"}], ["not_speaking", "repairs_left"], None]
    # hoisting the actions both branches share (reset_repairs, count_turn in the shipped graph) before the condition
    # is not a drawing the compiler accepts: a condition may not follow an action (guards are evaluated first)
    hoist = vdoc([N("t", "trigger", type="event", event="visage"), N("c", "condition", **etat("=", "a")),
                  N("x", "action", action="reset_repairs", args={}, phase="do"),
                  N("r", "condition", type="guard", guard="turns_left", negate=False),
                  N("m", "action", action="set_var", args={"name": "etat", "value": "b"}, phase="do")],
                 [L("t", "c"), L("c", "x", "true"), L("x", "r"), L("r", "m", "true")], ["t"])
    assert any(e["node"] == "r" and "après une action" in e["message"] for e in V.from_visual(hoist, CFG)[2])


# ---------------------------------------------------------------- lot L5 (2026-11-01): node menu themes, check node ids, post-it modes
def test_every_vocab_item_has_a_valid_theme():
    v = G.vocabulary(CFG, parse(mini(variables=VARS)))
    ids = [t["id"] for t in v["themes"]]
    assert ids == list(G.THEME_DOC) and [t["order"] for t in v["themes"]] == list(range(len(ids)))
    assert all(t["label"] and t["help"] and os.path.exists(os.path.join(TABLER, t["icon"] + ".svg")) for t in v["themes"])
    for k in ("events", "actions", "guards"):
        for x in v[k]:
            assert x.get("theme") in ids, (k, x["id"], x.get("theme"))
    assert set(v["theme_slots"]) == {"intent", "after", "state_enter", "state_test", "state_move"}
    assert set(v["theme_slots"].values()) <= set(ids)
    # every theme is used by at least one entry (registry or slot): no theme can only ever be empty
    used = {x["theme"] for k in ("events", "actions", "guards") for x in v[k]} | set(v["theme_slots"].values())
    assert used == set(ids), set(ids) - used
    # shared themes: at least one theme holds triggers, actions and conditions
    per = {k: {x["theme"] for x in v[k]} for k in ("events", "actions", "guards")}
    assert per["events"] & per["actions"] & per["guards"], per
    # argument help for the inspector tooltips
    assert all(a.get("help") for a in next(x for x in v["actions"] if x["id"] == "set_var")["args"])
    assert all(a.get("help") for g in v["guards"] for a in g["args"])


def test_vocab_endpoint_exposes_themes():
    """GET /api/graph/vocab returns graph.vocabulary(brain.cfg, active graph) verbatim (server.graph_vocab).

    server.py is read as text, never imported: importing it builds the live Brain (engines, audio)."""
    import ast
    tree = ast.parse(open(os.path.join(os.path.dirname(V.__file__), "server.py"), encoding="utf-8").read())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "graph_vocab")
    src = ast.unparse(fn)
    assert "'/api/graph/vocab'" in src and "return graph_mod.vocabulary(brain.cfg, brain.engine.graph)" in src, src
    v = G.vocabulary(CFG, G.load_graph(G.DEFAULT_PATH, CFG))
    body = json.loads(json.dumps(v))                     # what the endpoint serialises
    assert body["themes"] and body["theme_slots"] and all("theme" in e for e in body["events"])


def test_check_returns_node_ids_for_errors():
    doc = vdoc([N("t", "trigger", type="event", event="start"), N("c", "condition", **etat("=", "veille")),
                N("g", "condition", type="guard", guard="var_compare", args={"name": "score", "op": ">", "value": 1}, negate=False),
                N("x", "action", action="set_var", args={"name": "ok", "value": True}, phase="do"),
                N("y", "action", action="speak_phrase", args={"done": "greeting_done"}, phase="do")],
               [L("t", "c"), L("c", "g", "true"), L("g", "x", "true"), L("x", "y")], ["t"], copy.deepcopy(VARS))
    raw, _l, errs = V.from_visual(doc, CFG)
    assert raw is None and errs
    assert any(e["node"] == "t" and e.get("at") == "y" and e.get("nodes") == ["t", "y"] and "speak_phrase" in e["message"] for e in errs), errs
    del doc["variables"]["names"]["score"]
    doc["nodes"][-1]["params"]["args"]["text"] = "greeting"
    errs = V.from_visual(doc, CFG)[2]
    assert any(e["node"] == "t" and e.get("at") == "g" and "unknown variable 'score'" in e["message"] for e in errs), errs
    # two set_var nodes in one chain: the one whose argument is named in the message wins
    doc2 = vdoc([N("t", "trigger", type="event", event="start"), N("c", "condition", **etat("=", "veille")),
                 N("a", "action", action="set_var", args={"name": "ok", "value": True}, phase="do"),
                 N("b", "action", action="set_var", args={"name": "perdue", "value": 1}, phase="do")],
                [L("t", "c"), L("c", "a", "true"), L("a", "b")], ["t"], copy.deepcopy(VARS))
    errs = V.from_visual(doc2, CFG)[2]
    assert any(e.get("at") == "b" and "perdue" in e["message"] for e in errs), errs
    # every structural error already names its node
    bad = vdoc([N("t", "trigger", type="event", event="start")], [], ["t"])
    assert all(e["node"] == "t" for e in V.from_visual(bad, CFG)[2])


def test_note_display_mode_roundtrips():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    gp, lp = os.path.join(TMP, "graph.yaml"), os.path.join(TMP, "graph.layout.json")
    doc = vdoc([N("t", "trigger", type="event", event="start"), N("c", "condition", **etat("=", "veille")),
                N("x", "action", action="mic_on", args={}, phase="do")], [L("t", "c"), L("c", "x", "true")], ["t"])
    note = {"id": "p1", "text": "a\nb", "color": "#fff59d", "x": 0, "y": 0, "w": 220, "h": 160}
    doc["notes"] = [dict(note, display="compact"), dict(note, id="p2"), dict(note, id="p3", display="full")]
    assert V.save(doc, CFG, gp, lp)[0]
    stored = {n["id"]: n for n in V.load_layout(lp)["notes"]}
    assert stored["p1"]["display"] == "compact" and "display" not in stored["p2"] and "display" not in stored["p3"]
    back = V.to_visual(V.load_raw(gp), V.load_layout(lp))
    assert {n["id"]: n.get("display") for n in back["notes"]} == {"p1": "compact", "p2": None, "p3": None}
    doc["notes"] = [dict(note, display="tiny")]
    ok, errs = V.save(doc, CFG, gp, lp)
    assert not ok and any(e.get("note") == "p1" for e in errs), errs
    shutil.rmtree(TMP, ignore_errors=True)


TESTS = [test_each_type_is_validated, test_system_variables_are_read_only, test_set_var_fires_var_changed_with_anti_loop,
         test_list_contains_with_utterance_and_list_actions, test_say_random_is_cached_and_stays_muted,
         test_used_variable_cannot_be_deleted, test_wire_into_trigger_is_refused, test_old_hub_layout_migrates,
         test_multi_state_condition_duplicates_with_one_fan, test_user_var_changed_trigger_roundtrips,
         test_simulator_returns_vars_per_step, test_vocabulary_icons_are_vendored, test_live_snapshot_shape,
         test_default_graph_has_no_crossing, test_if_else_is_one_condition, test_hand_wired_false_branch_compiles,
         test_every_vocab_item_has_a_valid_theme, test_vocab_endpoint_exposes_themes, test_check_returns_node_ids_for_errors,
         test_note_display_mode_roundtrips]


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
    print("graph_vars tests: %d passed, %d failed" % (ran - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
