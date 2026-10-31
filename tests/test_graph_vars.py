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
           ({"names": {"x": {"type": "color", "value": "#fff"}}}, "type must be one of"),
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


TESTS = [test_each_type_is_validated, test_system_variables_are_read_only, test_set_var_fires_var_changed_with_anti_loop,
         test_list_contains_with_utterance_and_list_actions, test_say_random_is_cached_and_stays_muted,
         test_used_variable_cannot_be_deleted, test_wire_into_trigger_is_refused, test_old_hub_layout_migrates,
         test_multi_state_condition_duplicates_with_one_fan, test_user_var_changed_trigger_roundtrips,
         test_simulator_returns_vars_per_step, test_vocabulary_icons_are_vendored, test_live_snapshot_shape,
         test_default_graph_has_no_crossing]


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
