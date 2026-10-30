"""Tests of the visual graph editor backend: nanterino/graph_visual.py, graph.vocabulary(), negated guards,
deferred reload.

logging: robotlog via tests.test_brain_graph (get_logger).

Purpose: prove that the node document is a faithful drawing of graph.yaml. (1) default graph -> visual ->
compiled gives the same graph; (2) the 68 parity scenarios of tests/test_brain_graph.py pass on the COMPILED
graph (the real Brain runs it); (3) invalid documents are refused with the id of the offending node;
(4) negated guards and `false` ports behave; (5) saving writes backups / layout; (6) a graph saved while a
conversation runs is applied at the next veille.

Boundary: uses the fake-world harness of tests/test_brain_graph.py (no hardware, muted); files go to /tmp.

How to run (repo root):
    .venv/bin/python -m tests.test_graph_visual               # everything (~160 s, mostly the parity run)
    .venv/bin/python -m tests.test_graph_visual --no-parity   # fast part only (~10 s)
"""
import copy
import json
import os
import shutil
import sys
import time
import types

sys.path.insert(0, "/opt/robot/lib")

from nanterino import config, graph as G, graph_visual as V  # noqa: E402
from tests import test_brain_graph as tbg  # noqa: E402

CFG = dict(config.DEFAULTS)
TMP = "/tmp/test_graph_visual"


def default_raw():
    return V.load_raw(G.DEFAULT_PATH)


def semantic(raw):
    """Order-preserving, source-independent form of a raw graph (what the robot would do)."""
    g = G.parse_graph(copy.deepcopy(raw), CFG, "<test>")
    d = g.to_dict()
    d.pop("source")
    d["state_order"] = list(g.states)
    return json.loads(json.dumps(d))


def find(doc, **kw):
    return [n for n in doc["nodes"] if all(n.get(k) == v or n["params"].get(k) == v for k, v in kw.items())]


def chain_of(doc, trigger_id):
    """Linear chain of node ids starting at a trigger (follows the first link of each node)."""
    nxt = {(l["from"], l["port"]): l["to"] for l in doc["links"]}
    ids, cur = [trigger_id], trigger_id
    kinds = {n["id"]: n["kind"] for n in doc["nodes"]}
    while True:
        port = "true" if kinds[cur] == "condition" else "out"
        if (cur, port) not in nxt:
            return ids
        cur = nxt[(cur, port)]
        ids.append(cur)


def compile_ok(doc):
    raw, layout, errors = V.from_visual(doc, CFG)
    assert not errors, errors
    return raw, layout


# ---------------------------------------------------------------- tests
def test_roundtrip_default():
    raw = default_raw()
    doc = to_json_and_back(V.to_visual(raw))
    raw2, _ = compile_ok(doc)
    a, b = semantic(raw), semantic(raw2)
    assert a == b, "round trip changed the graph"
    # the YAML text written by the editor loads back to the same graph and keeps the French descriptions
    text = V.dump_yaml(raw2)
    assert text.startswith("# Graphe de dialogue de Nanterino") and "description:" in text
    import yaml
    assert semantic(yaml.load(text, Loader=G._Loader)) == a
    assert len(doc["order"]) == len(raw["global"]) + sum(len(s.get("transitions") or []) for s in raw["states"].values())
    kinds = {n["kind"] for n in doc["nodes"]}
    assert kinds == {"start", "trigger", "condition", "action", "goto", "end"}, kinds


def to_json_and_back(doc):
    return json.loads(json.dumps(doc, ensure_ascii=False))


def test_layout_bands_and_persistence():
    doc = V.to_visual(default_raw())
    pts = [(n["x"], n["y"]) for n in doc["nodes"]]
    assert len(set(pts)) == len(pts), "two nodes share a position"
    for n in doc["nodes"]:
        if n["kind"] == "trigger":
            ids = chain_of(doc, n["id"])
            ys = {next(x for x in doc["nodes"] if x["id"] == i)["y"] for i in ids}
            xs = [next(x for x in doc["nodes"] if x["id"] == i)["x"] for i in ids]
            assert len(ys) == 1 and xs == sorted(xs) and len(set(xs)) == len(xs), "chain is not one left-to-right band"
    # bands of one state are contiguous and the state colours are distinct
    assert len({s["color"] for s in doc["states"]}) == len(doc["states"])
    # a moved node comes back where the user put it, through the structural layout keys
    doc2 = copy.deepcopy(doc)
    trig = find(doc2, kind="trigger", event="stop")[0]
    trig["x"], trig["y"] = 4321, 8765
    raw, layout = compile_ok(doc2)
    assert not (set(layout["nodes"]) - {"start"} - {k for k in layout["nodes"]}) and layout["nodes"]
    doc3 = V.to_visual(raw, layout)
    moved = find(doc3, kind="trigger", event="stop")[0]
    assert (moved["x"], moved["y"]) == (4321, 8765), moved
    pts3 = [(n["x"], n["y"]) for n in doc3["nodes"]]
    assert len(set(pts3)) == len(pts3)


def test_vocabulary():
    g = G.load_graph(G.DEFAULT_PATH, CFG)
    v = G.vocabulary(CFG, g)
    counts = {k: len(x) for k, x in v.items()}
    assert counts == {"events": 16, "actions": 19, "guards": 7, "delays": 3, "since": 2, "states": 7, "intents": 4}, counts
    assert {a["id"] for a in v["actions"]} == set(G.ACTION_SPECS)
    assert {x["id"] for x in v["guards"]} == set(G.GUARDS)
    assert {e["id"] for e in v["events"]} == set(G.EVENTS) - set(G.INTERNAL_EVENTS)
    for k in ("events", "actions", "guards"):
        for x in v[k]:
            assert x["label"].strip() and x["help"].strip(), (k, x)
    for s in v["states"]:
        assert s["label"] and s["description"], s
    sp = next(a for a in v["actions"] if a["id"] == "speak_phrase")
    assert [a["name"] for a in sp["args"]] == ["text", "done"] and sp["args"][0]["options"] == list(G.PHRASE_KEYS)
    assert next(d for d in v["delays"] if d["key"] == "silence_relance_s")["value"] == 8
    assert [i["event"] for i in v["intents"]] == ["intent.appel", "intent.au_revoir", "intent.chanson", "intent.question"]
    json.dumps(v)


def expect_error(doc, node, fragment):
    raw, _layout, errors = V.from_visual(doc, CFG)
    assert raw is None and errors, "document was accepted although invalid: " + fragment
    hit = [e for e in errors if e["node"] == node and fragment in e["message"]]
    assert hit, "expected error on %r containing %r, got %r" % (node, fragment, errors)


def test_error_cases():
    base = V.to_visual(default_raw())
    # chain without target: cut the link into the final goto of the `visage` transition
    d = copy.deepcopy(base)
    trig = find(d, kind="trigger", event="stop")[0]
    ids = chain_of(d, trig["id"])
    d["links"] = [l for l in d["links"] if not (l["from"] == ids[-2] and l["to"] == ids[-1])]
    d["nodes"] = [n for n in d["nodes"] if n["id"] != ids[-1]]
    expect_error(d, ids[-2], "sans cible")
    # unknown state in a goto
    d = copy.deepcopy(base)
    goto = find(d, kind="goto", state="accueil")[0]
    goto["params"]["state"] = "atlantis"
    expect_error(d, goto["id"], "atlantis")
    # unknown action
    d = copy.deepcopy(base)
    act = find(d, kind="action", action="cancel_all")[0]
    act["params"]["action"] = "fly_away"
    expect_error(d, act["id"], "fly_away")
    # unknown guard
    d = copy.deepcopy(base)
    cond = find(d, kind="condition", guard="turns_left")[0]
    cond["params"]["guard"] = "moon_is_full"
    expect_error(d, cond["id"], "moon_is_full")
    # unknown event
    d = copy.deepcopy(base)
    trig = find(d, kind="trigger", event="stop")[0]
    trig["params"]["event"] = "nobody_home"
    expect_error(d, trig["id"], "nobody_home")
    # enter-trigger finishing on a goto
    d = copy.deepcopy(base)
    enter = find(d, kind="trigger", type="enter", state="veille")[0]
    ids = chain_of(d, enter["id"])
    goto_id = "n9999"
    d["nodes"].append({"id": goto_id, "kind": "goto", "x": 0, "y": 0, "description": "", "params": {"state": "ecoute"}})
    d["links"] = [l for l in d["links"] if l["from"] != ids[-2]] + [{"from": ids[-2], "port": "out", "to": goto_id}]
    d["nodes"] = [n for n in d["nodes"] if n["id"] != ids[-1]]
    expect_error(d, goto_id, "ne peut pas changer d'état")
    # delay trigger without a single state
    d = copy.deepcopy(base)
    trig = find(d, kind="trigger", type="after")[0]
    ids = chain_of(d, trig["id"])
    st = next(n for n in d["nodes"] if n["id"] == ids[1])
    assert st["params"]["type"] == "state"
    st["params"]["negate"] = True
    expect_error(d, trig["id"], "Un délai doit être rattaché")
    # orphan node and condition after an action
    d = copy.deepcopy(base)
    d["nodes"].append({"id": "n_orphan", "kind": "action", "x": 0, "y": 0, "description": "", "params": {"action": "mic_on", "args": {}, "phase": "do"}})
    expect_error(d, "n_orphan", "non relié")
    # a non-numeric delay is caught by the real validator and mapped back to its trigger
    d = copy.deepcopy(base)
    trig = find(d, kind="trigger", type="after")[0]
    trig["params"]["delay"] = "silence_typo_s"
    expect_error(d, trig["id"], "neither a number")
    # missing arguments of an action are mapped to the trigger of the chain
    d = copy.deepcopy(base)
    act = find(d, kind="action", action="speak_phrase")[0]
    act["params"]["args"] = {"text": "greeting"}
    raw, _l, errors = V.from_visual(d, CFG)
    assert raw is None and any(e["node"] for e in errors), errors


def mini_doc(extra_nodes, extra_links, order):
    states = [{"id": s, "description": "d " + s, "color": "#000000"} for s in ("veille", "accueil", "eteint")]
    nodes = [{"id": "start", "kind": "start", "x": 0, "y": 0, "description": "", "params": {"state": "veille"}}] + extra_nodes
    return {"version": 1, "nodes": nodes, "links": extra_links, "states": states, "intents": {}, "order": order}


def N(i, kind, **params):
    return {"id": i, "kind": kind, "x": 0, "y": 0, "description": params.pop("_d", ""), "params": params}


def L(a, b, port="out"):
    return {"from": a, "port": port, "to": b}


def test_negated_guard_compiles_and_evaluates():
    # veille: on visage, when NOT auto_greet_on_face -> accueil
    doc = mini_doc([
        N("t", "trigger", type="event", event="visage", _d="visage sans accueil auto"),
        N("s", "condition", type="state", states=["veille"], negate=False),
        N("g", "condition", type="guard", guard="auto_greet_on_face", negate=True),
        N("go", "goto", state="accueil"),
    ], [L("t", "s"), L("s", "g", "true"), L("g", "go", "true")], ["t"])
    raw, _ = compile_ok(doc)
    tr = raw["states"]["veille"]["transitions"][0]
    assert tr["when"] == [{"not": "auto_greet_on_face"}] and tr["to"] == "accueil", tr
    g = G.parse_graph(raw, CFG, "<t>")
    assert [c.label() for c in g.states["veille"].transitions[0].when] == ["not auto_greet_on_face"]
    # evaluate with a stub brain: guard false -> negated condition passes
    for guard_value, expected in ((False, "accueil"), (True, "veille")):
        brain = types.SimpleNamespace(state="veille", since=0.0, last_speech=0.0)
        moves = []
        brain._go = lambda s, r, b=brain: (moves.append((s, r)), setattr(b, "state", s))
        acts = {n: (lambda kw, **a: None) for n in G.ACTION_SPECS}
        guards = {n: (lambda kw: False) for n in G.GUARDS}
        guards["auto_greet_on_face"] = lambda kw, v=guard_value: v
        eng = G.GraphEngine(g, brain, acts, guards, CFG)
        eng.dispatch("visage", {})
        assert brain.state == expected, (guard_value, brain.state)
    # the YAML form `when: [{not: g}]` and `when: {not: g}` both load
    import yaml
    text = V.dump_yaml(raw)
    assert "not: auto_greet_on_face" in text
    assert semantic(yaml.load(text, Loader=G._Loader)) == semantic(raw)


def test_false_port_and_order():
    # one condition, two branches: true -> accueil, false -> mic_on + end; order of branches = first match
    doc = mini_doc([
        N("t", "trigger", type="event", event="visage"),
        N("s", "condition", type="state", states=["veille"], negate=False),
        N("g", "condition", type="guard", guard="auto_greet_on_face", negate=False),
        N("go", "goto", state="accueil", reason="visage"),
        N("a", "action", action="mic_on", args={}, phase="do"),
        N("e", "end"),
        N("t2", "trigger", type="event", event="start"),
        N("s2", "condition", type="state", states=["veille"], negate=False),
        N("e2", "end"),
    ], [L("t", "s"), L("s", "g", "true"), L("g", "go", "true"), L("g", "a", "false"), L("a", "e"), L("t2", "s2"), L("s2", "e2", "true")],
        ["t2", "t"])
    raw, _ = compile_ok(doc)
    trs = raw["states"]["veille"]["transitions"]
    assert [(x["on"], x.get("when"), x.get("to"), x.get("do")) for x in trs] == [
        ("start", None, None, None),
        ("visage", ["auto_greet_on_face"], "accueil", None),
        ("visage", [{"not": "auto_greet_on_face"}], None, ["mic_on"]),
    ], trs
    # `order` decides; without it the position (y then x) decides
    doc2 = copy.deepcopy(doc)
    doc2["order"] = ["t", "t2"]
    raw2, _ = compile_ok(doc2)
    assert [x["on"] for x in raw2["states"]["veille"]["transitions"]] == ["visage", "visage", "start"]
    doc3 = copy.deepcopy(doc)
    del doc3["order"]
    for n in doc3["nodes"]:
        n["y"] = {"t2": 0, "t": 50}.get(n["id"], n["y"])
    raw3, _ = compile_ok(doc3)
    assert [x["on"] for x in raw3["states"]["veille"]["transitions"]][0] == "start"
    # false port of the STATE condition -> a global transition with not_in
    doc4 = mini_doc([
        N("t", "trigger", type="event", event="stop"),
        N("s", "condition", type="state", states=["veille"], negate=False),
        N("e", "end"),
        N("a", "action", action="cancel_all", args={}, phase="do"),
        N("go", "goto", state="veille"),
    ], [L("t", "s"), L("s", "e", "true"), L("s", "a", "false"), L("a", "go")], ["t"])
    raw4, _ = compile_ok(doc4)
    assert raw4["states"]["veille"]["transitions"][0]["on"] == "stop"
    assert raw4["global"] == [{"on": "stop", "not_in": ["veille"], "do": ["cancel_all"], "to": "veille", "description": ""}], raw4["global"]


def test_save_backups_and_reset():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    gp, lp = os.path.join(TMP, "graph.yaml"), os.path.join(TMP, "graph.layout.json")
    doc = V.to_visual(default_raw())
    ok, errs = V.save(doc, CFG, gp, lp)
    assert ok and not errs and os.path.exists(gp) and os.path.exists(lp)
    assert not [f for f in os.listdir(TMP) if ".bak-" in f], "first save has nothing to back up"
    first = open(gp, encoding="utf-8").read()
    assert first.startswith("# Graphe de dialogue de Nanterino")
    # invalid document: nothing written, errors listed
    bad = copy.deepcopy(doc)
    find(bad, kind="goto", state="accueil")[0]["params"]["state"] = "atlantis"
    ok, errs = V.save(bad, CFG, gp, lp)
    assert not ok and errs and open(gp, encoding="utf-8").read() == first
    # edit a delay 8 -> 10: the file changes, a backup appears; 13 saves keep the 10 newest backups
    d2 = copy.deepcopy(doc)
    find(d2, kind="trigger", delay="silence_relance_s")[0]["params"]["delay"] = "10"      # text coerced to a number
    ok, _ = V.save(d2, CFG, gp, lp)
    assert ok and len([f for f in os.listdir(TMP) if ".bak-" in f]) == 1
    g = G.load_graph(gp, CFG)
    assert next(t for t in g.states["ecoute"].transitions if t.after is not None).after == 10
    for _ in range(12):
        assert V.save(d2, CFG, gp, lp)[0]
    assert len([f for f in os.listdir(TMP) if ".bak-" in f]) == 10
    made = V.reset(gp, lp)
    assert made and not os.path.exists(gp) and not os.path.exists(lp)
    shutil.rmtree(TMP, ignore_errors=True)


def test_deferred_reload_applies_at_next_veille():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    gp, lp = os.path.join(TMP, "graph.yaml"), os.path.join(TMP, "graph.layout.json")
    h = tbg.H({"graph_file": gp})                      # file absent: packaged default runs
    try:
        h.post("start"); h.wait_state("ecoute"); h.settle()
        doc = V.to_visual(default_raw())
        # variant: the dashboard `start` in veille now goes straight to ecoute
        trig = next(n for n in doc["nodes"] if n["kind"] == "trigger" and n["params"].get("event") == "start"
                    and n["group"] == "veille")
        goto = next(n for n in doc["nodes"] if n["id"] == chain_of(doc, trig["id"])[-1])
        goto["params"]["state"] = "ecoute"
        assert V.save(doc, h.cfg, gp, lp)[0]
        assert h.brain.request_graph_reload() is False and h.brain.graph_pending is True
        assert h.brain.engine.graph.source != gp, "must not swap graphs mid-conversation"
        h.post("stop"); h.wait_state("veille"); h.settle()
        assert h.brain.graph_pending is False and h.brain.engine.graph.source == gp, h.brain.engine.graph.source
        h.post("start"); h.settle()
        assert h.brain.state == "ecoute", h.brain.state       # the saved variant is live
        assert h.brain.request_graph_reload() is False         # busy again
    finally:
        h.close()
        shutil.rmtree(TMP, ignore_errors=True)


FAST = [test_roundtrip_default, test_layout_bands_and_persistence, test_vocabulary, test_error_cases,
        test_negated_guard_compiles_and_evaluates, test_false_port_and_order, test_save_backups_and_reset,
        test_deferred_reload_applies_at_next_veille]


def parity_on_compiled_graph():
    """The 68 trace scenarios of test_brain_graph, run by the real Brain on default -> visual -> YAML."""
    raw, _ = compile_ok(to_json_and_back(V.to_visual(default_raw())))
    path = "/tmp/g_compiled_parity.yaml"
    with open(path, "w", encoding="utf-8") as f:
        f.write(V.dump_yaml(raw))
    tbg.GRAPH_FILE = path
    t0 = time.monotonic()
    traces = tbg.run_all(list(tbg.SCENARIOS))
    with open(tbg.BASELINE, encoding="utf-8") as f:
        base = json.load(f)
    bad = tbg.compare(base, traces)
    for n, why in bad:
        print("DIFF", n, why)
    print("compiled-graph parity: %d scenarios in %.0fs, %d different" % (len(traces), time.monotonic() - t0, len(bad)), flush=True)
    return len(traces) - len(bad), len(bad)


def main(argv):
    failed = 0
    for fn in FAST:
        try:
            fn()
            print("PASS", fn.__name__, flush=True)
        except Exception as e:  # report every failure
            failed += 1
            import traceback
            traceback.print_exc()
            print("FAIL", fn.__name__, "%s: %s" % (type(e).__name__, e), flush=True)
    if "--no-parity" not in argv:
        ok, bad = parity_on_compiled_graph()
        print("parity %d/%d" % (ok, ok + bad))
        failed += 1 if bad else 0
    print("graph_visual tests: %d failed" % failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
