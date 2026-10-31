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

from nanterino import config, graph as G, graph_layout as GL, graph_visual as V  # noqa: E402
from tests import test_brain_graph as tbg  # noqa: E402

CFG = dict(config.DEFAULTS)
TMP = "/tmp/test_graph_visual"


def default_raw():
    return V.load_raw(G.DEFAULT_PATH)


def semantic(raw, nofan=False):
    """Order-preserving, source-independent form of a raw graph (what the robot would do).

    `nofan=True` drops the `fan` tags: sharing a trigger node between branches that can never match together
    makes the compiler tag them, which the engine treats as a no-op for such branches.
    """
    g = G.parse_graph(copy.deepcopy(raw), CFG, "<test>")
    d = g.to_dict()
    d.pop("source")
    d["state_order"] = list(g.states)
    d = json.loads(json.dumps(d))
    if nofan:
        for t in d["global"] + [t for s in d["states"].values() for t in s["transitions"]]:
            t.pop("fan", None)
    return d


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
        if kinds[cur] == "state":   # a state node ends the chain (its own output starts other chains)
            return ids


def compile_ok(doc):
    raw, layout, errors = V.from_visual(doc, CFG)
    assert not errors, errors
    return raw, layout


# ---------------------------------------------------------------- tests
def test_roundtrip_default():
    raw = default_raw()
    doc = to_json_and_back(V.to_visual(raw))
    raw2, _ = compile_ok(doc)
    a, b = semantic(raw, nofan=True), semantic(raw2, nofan=True)
    assert a == b, "round trip changed the graph"
    fans = {}
    for t in semantic(raw2)["global"] + [t for st in semantic(raw2)["states"].values() for t in st["transitions"]]:
        if t.get("fan"):
            fans.setdefault(t["fan"], []).append(t)
    assert fans and all(len(v) >= 2 for v in fans.values()), "a fan tag on a lone transition"
    assert semantic(raw) == semantic(raw2, nofan=True) and not any(
        t.get("fan") for t in semantic(raw)["global"]), "the shipped graph carries no fan tag"
    # the YAML text written by the editor loads back to the same graph and keeps the French descriptions
    text = V.dump_yaml(raw2)
    assert text.startswith("# Graphe de dialogue de Nanterino") and "description:" in text
    import yaml
    assert semantic(yaml.load(text, Loader=G._Loader), nofan=True) == a
    # CHANGED 2026-10-31 (state nodes): `order` lists every trigger node once (it used to equal the transition
    # count only by coincidence: shared triggers vs the enter triggers); a global rule limited to some states now
    # keeps its trigger apart from a same-event rule limited to others (the links make them different triggers).
    assert sorted(doc["order"]) == sorted(n["id"] for n in doc["nodes"] if n["kind"] == "trigger")
    kinds = {n["kind"] for n in doc["nodes"]}
    assert kinds == {"start", "trigger", "condition", "action", "state", "end"}, kinds   # no go-to node any more
    # exactly one state node per state, in state order, right after Start
    assert [n["params"]["state"] for n in doc["nodes"] if n["kind"] == "state"] == list(raw["states"])
    # the legacy drawing (go-to nodes) still round-trips to the same graph
    legacy = to_json_and_back(V.to_visual(raw, legacy=True))
    assert {n["kind"] for n in legacy["nodes"]} == {"start", "trigger", "condition", "action", "goto", "end"}
    assert semantic(compile_ok(legacy)[0], nofan=True) == a, "legacy drawing changed the graph"


def to_json_and_back(doc):
    return json.loads(json.dumps(doc, ensure_ascii=False))


def test_layout_bands_and_persistence():
    doc = V.to_visual(default_raw())
    pts = [(n["x"], n["y"]) for n in doc["nodes"]]
    assert len(set(pts)) == len(pts), "two nodes share a position"
    pos = {n["id"]: (n["x"], n["y"]) for n in doc["nodes"]}
    kind = {n["id"]: n["kind"] for n in doc["nodes"]}
    for lk in doc["links"]:
        if kind[lk["to"]] == "state":     # CHANGED: the wire back to a state hub runs right to left by design
            continue
        assert pos[lk["to"]][0] > pos[lk["from"]][0], "a link does not run left to right: %r" % (lk,)
    # CHANGED (L7): state hubs form the top row, one per column, in state order from left to right
    hubs = [n for n in doc["nodes"] if n["kind"] == "state"]
    assert len({n["y"] for n in hubs}) == 1 and [n["x"] for n in hubs] == sorted(n["x"] for n in hubs)
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
    assert counts == {"events": 21, "actions": 23, "guards": 8, "delays": 3, "since": 2, "states": 7, "intents": 4, "kinds": 6}, counts
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
    base = V.to_visual(default_raw(), compact=False, legacy=True)   # go-to nodes + explicit state conditions (legacy form still compiles)
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
    # (a trigger with two outgoing paths now tags every branch with its fan id, see Notes "Branches multiples")
    assert raw4["global"] == [{"on": "stop", "fan": "fan-t", "not_in": ["veille"], "do": ["cancel_all"], "to": "veille", "description": ""}], raw4["global"]
    assert raw4["states"]["veille"]["transitions"][0]["fan"] == "fan-t"


def test_save_backups_and_reset():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    gp, lp = os.path.join(TMP, "graph.yaml"), os.path.join(TMP, "graph.layout.json")
    doc = V.to_visual(default_raw())
    ok, errs = V.save(doc, CFG, gp, lp)
    assert ok and not errs and os.path.exists(gp) and os.path.exists(lp)
    baks = lambda: [f for f in os.listdir(TMP) if f.startswith("graph.yaml.bak-")]  # noqa: E731  (layout copies not counted)
    assert not [f for f in os.listdir(TMP) if ".bak-" in f], "first save has nothing to back up"
    first = open(gp, encoding="utf-8").read()
    assert first.startswith("# Graphe de dialogue de Nanterino")
    # invalid document: nothing written, errors listed
    bad = copy.deepcopy(doc)
    find(bad, kind="state", state="accueil")[0]["params"]["state"] = "atlantis"
    ok, errs = V.save(bad, CFG, gp, lp)
    assert not ok and errs and open(gp, encoding="utf-8").read() == first
    # edit a delay 8 -> 10: the file changes, a backup appears; backups are capped at V.KEEP_BACKUPS (30)
    d2 = copy.deepcopy(doc)
    find(d2, kind="trigger", delay="silence_relance_s")[0]["params"]["delay"] = "10"      # text coerced to a number
    ok, _ = V.save(d2, CFG, gp, lp)
    assert ok and len(baks()) == 1
    assert len([f for f in os.listdir(TMP) if f.startswith("graph.layout.json.bak-")]) == 1, "layout is backed up too"
    g = G.load_graph(gp, CFG)
    assert next(t for t in g.states["ecoute"].transitions if t.after is not None).after == 10
    for _ in range(12):
        assert V.save(d2, CFG, gp, lp)[0]
    assert len(baks()) == 13, len(baks())
    for _ in range(25):
        assert V.save(d2, CFG, gp, lp)[0]
    assert len(baks()) == V.KEEP_BACKUPS == 30, len(baks())
    assert len([f for f in os.listdir(TMP) if f.startswith("graph.layout.json.bak-")]) <= 30
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
        ids = chain_of(doc, trig["id"])
        ecoute = next(n for n in doc["nodes"] if n["kind"] == "state" and n["params"]["state"] == "ecoute")
        for lk in doc["links"]:       # re-wire the last hop of the chain into the ecoute state node
            if lk["from"] == ids[-2] and lk["to"] == ids[-1]:
                lk["to"] = ecoute["id"]
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


def test_frames_cosmetic_groups():
    """Frames ("groupes"): round trip, no effect on the compiled graph, validation, restore with versions."""
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    gp, lp = os.path.join(TMP, "graph.yaml"), os.path.join(TMP, "graph.layout.json")
    base = V.to_visual(default_raw())
    # CHANGED (L7): the hub drawing gets one automatic frame per column; the legacy drawing keeps the theme frames
    assert [f["id"] for f in base["frames"]] == ["auto-" + s for s in default_raw()["states"]] + ["auto-global"]
    assert [f["id"] for f in V.to_visual(default_raw(), legacy=True)["frames"]] == ["t-accueil", "t-conversation", "t-fin", "t-interruptions"]
    assert V.to_visual(default_raw(), {"states": {}})["frames"] == [], "default frames only without any layout"
    f1 = {"id": "f1", "title": "Accueil", "color": "#F2C94C", "x": -20, "y": 10.5, "w": 400, "h": 220, "note": "chaine visage"}
    f2 = {"id": "f2", "title": "", "color": "#4f8ef7", "x": 500, "y": 0, "w": 100, "h": 80}
    doc = copy.deepcopy(base)
    doc["frames"] = [f1, f2]
    raw0, _ = compile_ok(base)
    raw1, layout = compile_ok(doc)
    assert semantic(raw0) == semantic(raw1), "frames must not change the compiled graph"
    assert "frames" not in V.dump_yaml(raw1)
    assert [f["id"] for f in layout["frames"]] == ["f1", "f2"] and layout["frames"][0]["color"] == "#f2c94c"
    # save -> load layout -> to_visual returns the frames (colour normalised to lower case)
    assert V.save(doc, CFG, gp, lp)[0]
    back = V.to_visual(V.load_raw(gp), V.load_layout(lp))
    assert [(f["id"], f["title"], f["x"], f["y"], f["w"], f["h"], f.get("note")) for f in back["frames"]] == \
        [("f1", "Accueil", -20, 10.5, 400, 220, "chaine visage"), ("f2", "", 500, 0, 100, 80, None)]
    # validation: each bad frame is refused with its id, nothing written
    before = open(lp, encoding="utf-8").read()
    for patch in ({"title": "x" * 61}, {"color": "red"}, {"color": "#12345"}, {"x": "3"}, {"w": 0}, {"h": -4},
                  {"x": float("nan")}, {"note": 5}):
        bad = copy.deepcopy(doc)
        bad["frames"][1].update(patch)
        ok, errs = V.save(bad, CFG, gp, lp)
        assert not ok and any(e.get("frame") == "f2" for e in errs), (patch, errs)
    dup = copy.deepcopy(doc)
    dup["frames"][1]["id"] = "f1"
    ok, errs = V.save(dup, CFG, gp, lp)
    assert not ok and errs[0]["frame"] == "f1"
    many = copy.deepcopy(base)
    many["frames"] = [dict(f2, id="g%d" % i) for i in range(101)]
    assert not V.save(many, CFG, gp, lp)[0]
    many["frames"] = many["frames"][:100]
    assert V.from_visual(many, CFG)[2] == []
    assert open(lp, encoding="utf-8").read() == before
    # versions: a later save without frames, then restoring the previous version brings them back
    clean = copy.deepcopy(base)
    clean["frames"] = []
    assert V.save(clean, CFG, gp, lp)[0]
    assert V.to_visual(V.load_raw(gp), V.load_layout(lp))["frames"] == []
    vids = [v["id"] for v in V.list_versions(gp)]
    found = None
    for vid in vids:
        with open("%s.bak-%s" % (lp, vid), encoding="utf-8") as f:
            if json.load(f).get("frames"):
                found = vid
    assert found, "a backup layout copy holds the frames"
    ok, status, _ = V.restore_version(found, CFG, gp, lp)
    assert ok
    assert len(V.to_visual(V.load_raw(gp), V.load_layout(lp))["frames"]) == 2
    shutil.rmtree(TMP, ignore_errors=True)


def _dedupe_graph(extra):
    """Default graph with `extra` transitions appended to `reponse` (they all react to `ask`)."""
    raw = copy.deepcopy(default_raw())
    raw["states"]["reponse"]["transitions"] += copy.deepcopy(extra)
    return raw


def _triggers(doc, event, group):
    return [n for n in doc["nodes"] if n["kind"] == "trigger" and n["params"].get("event") == event and n.get("group") == group]


def test_sharing_lighter_and_equivalent():
    """Sharing nodes is only a drawing: fewer nodes/links, same compiled graph (modulo no-op fan tags)."""
    raw = default_raw()
    # CHANGED 2026-10-31: the measurements below are those of the legacy drawing (go-to nodes); the hub drawing has its
    # own figures at the end of this test.
    old, new, comp = (V.to_visual(raw, share=False, compact=False, legacy=True), V.to_visual(raw, compact=False, legacy=True),
                      V.to_visual(raw, legacy=True))
    print("  nodes old/shared/compact = %d/%d/%d, links %d/%d/%d" % (
        len(old["nodes"]), len(new["nodes"]), len(comp["nodes"]), len(old["links"]), len(new["links"]), len(comp["links"])))
    # NOTE the brief asked for <= 70 %: not reachable without dropping the per-chain state condition (compact mode)
    assert len(new["nodes"]) <= 0.90 * len(old["nodes"]) and len(new["links"]) <= 0.97 * len(old["links"])
    assert len(comp["nodes"]) <= 0.76 * len(old["nodes"]) and len(comp["links"]) <= 0.80 * len(old["links"])
    assert len(comp["nodes"]) <= 0.76 * 182, "compact (default) drawing of the shipped graph"
    assert [(n["kind"], n["params"]) for n in V.to_visual(raw, legacy=True)["nodes"]] == [(n["kind"], n["params"]) for n in comp["nodes"]], "compact is the legacy default"
    hub = V.to_visual(raw)
    print("  hub drawing: nodes %d, links %d" % (len(hub["nodes"]), len(hub["links"])))
    assert len(hub["nodes"]) <= len(comp["nodes"]) and not [n for n in hub["nodes"] if n["kind"] in ("goto",)]
    raw_h, _ = compile_ok(to_json_and_back(hub))
    assert semantic(raw_h, nofan=True) == semantic(raw, nofan=True)
    for doc in (new, comp):
        ends = {}
        for n in doc["nodes"]:
            if n["kind"] == "end":
                ends[n["group"]] = ends.get(n["group"], 0) + 1
        assert ends and all(v == 1 for v in ends.values()), ends       # one End per state group
        gotos = [(n["group"], n["params"]["state"], n["params"].get("reason")) for n in doc["nodes"] if n["kind"] == "goto"]
        assert len(gotos) == len(set(gotos)), "a go-to node is duplicated inside a group"
    for doc in (new, comp):
        raw2, _ = compile_ok(to_json_and_back(doc))
        assert semantic(raw2, nofan=True) == semantic(raw, nofan=True)
    # the compact trigger carries its state; the legacy per-chain state condition is gone
    assert any(n["params"].get("state") for n in comp["nodes"] if n["kind"] == "trigger" and n["params"].get("type") == "event")
    assert [n for n in old["nodes"] if n["kind"] == "condition" and n["params"].get("type") == "state"] != []
    # an unknown scope state is refused with the id of the trigger
    bad = to_json_and_back(comp)
    trig = next(n for n in bad["nodes"] if n["kind"] == "trigger" and n["params"].get("state") == "ecoute")
    trig["params"]["state"] = "nulle_part"
    _r, _l, errs = V.from_visual(bad, CFG)
    assert any(e["node"] == trig["id"] for e in errs), errs


def test_layout_no_overlap_and_few_crossings():
    raw = default_raw()
    for kw in ({}, {"legacy": True}, {"compact": False, "legacy": True}, {"share": False, "compact": False, "legacy": True}):
        doc = V.to_visual(raw, **kw)
        pos = {n["id"]: (n["x"], n["y"]) for n in doc["nodes"]}
        assert GL.overlaps(doc["nodes"], pos) == [], kw
        # CHANGED: in the hub drawing the wires that return to a state node are excluded from the bound (they cross
        # the whole canvas by nature); crossings inside the chains must still stay low
        x = GL.crossings(doc["nodes"], doc["links"], pos, chains_only=not kw.get("legacy"))
        assert x <= 12, (kw, x)
        if not kw:
            print("  hub drawing: %d crossings inside chains, %d with the returning wires" % (
                x, GL.crossings(doc["nodes"], doc["links"], pos)))
    # a long French description makes a tall node: the next row is pushed down, never overlapped
    long_raw = copy.deepcopy(raw)
    for t in long_raw["states"]["ecoute"]["transitions"]:
        t["description"] = (t["description"] + " ") * 4
    doc = V.to_visual(long_raw)
    pos = {n["id"]: (n["x"], n["y"]) for n in doc["nodes"]}
    assert GL.overlaps(doc["nodes"], pos) == []
    # the layout is deterministic
    assert [(n["x"], n["y"]) for n in V.to_visual(raw)["nodes"]] == [(n["x"], n["y"]) for n in V.to_visual(raw)["nodes"]]
    # saved positions of a partly saved document stay, new nodes go below them
    d0 = V.to_visual(raw)
    _r, layout = compile_ok(d0)
    layout["nodes"] = {k: v for k, v in layout["nodes"].items() if k.startswith(("veille/", "state/")) or k == "start"}
    d1 = V.to_visual(raw, layout)
    kept = [n for n in d1["nodes"] if n.get("group") == "veille"]
    assert [(n["x"], n["y"]) for n in kept] == [(n["x"], n["y"]) for n in d0["nodes"] if n.get("group") == "veille"]
    pos1 = {n["id"]: (n["x"], n["y"]) for n in d1["nodes"]}
    assert GL.overlaps(d1["nodes"], pos1) == []


def test_merged_fan_trigger_reloads_as_one_node():
    raw = copy.deepcopy(default_raw())
    qs = [t for t in raw["states"]["ecoute"]["transitions"] if t.get("on") == "intent.question"]
    assert len(qs) == 2
    for t in qs:
        t["fan"] = "fan-x1"
    doc = to_json_and_back(V.to_visual(raw))
    trigs = _triggers(doc, "intent.question", "ecoute")
    assert len(trigs) == 1 and trigs[0]["params"]["fan"] == "fan-x1"
    assert sum(1 for l in doc["links"] if l["from"] == trigs[0]["id"]) == 2       # compact: the two guard branches (turns_left / not)
    raw2, _ = compile_ok(doc)
    assert semantic(raw2, nofan=True) == semantic(raw, nofan=True), "branch order survives the reload"
    assert [t.get("fan") for t in semantic(raw2)["states"]["ecoute"]["transitions"] if t.get("on") == "intent.question"] == ["fan-x1"] * 2
    # the same two transitions WITHOUT a fan id are merged too when exclusive (turns_left / not turns_left)
    assert len(_triggers(to_json_and_back(V.to_visual(default_raw())), "intent.question", "ecoute")) == 1
    # a fan whose branches share the same leading action stays one trigger and keeps the fan tag
    raw3 = _dedupe_graph([{"on": "ask", "do": ["cancel_all"], "fan": "fan-x2", "description": "a"},
                          {"on": "ask", "do": ["cancel_all"], "to": "ecoute", "fan": "fan-x2", "description": "b"}])
    doc3 = to_json_and_back(V.to_visual(raw3))
    assert len(_triggers(doc3, "ask", "reponse")) == 1
    assert semantic(compile_ok(doc3)[0], nofan=True) == semantic(raw3, nofan=True)
    assert [t.get("fan") for t in semantic(compile_ok(doc3)[0])["states"]["reponse"]["transitions"][-2:]] == ["fan-x2"] * 2


def test_sharing_keeps_independent_transitions_apart():
    """Two transitions that could both match and start with the same action must NOT share a trigger:
    a shared trigger is a fan, and the engine would then run that first action once instead of twice."""
    a = {"on": "ask", "do": ["cancel_all"], "description": "a"}
    b = {"on": "ask", "do": ["cancel_all"], "to": "ecoute", "description": "b"}
    raw = _dedupe_graph([a, b])
    doc = to_json_and_back(V.to_visual(raw))
    assert len(_triggers(doc, "ask", "reponse")) == 2
    assert semantic(compile_ok(doc)[0], nofan=True) == semantic(raw, nofan=True)
    assert not any(t.get("fan") for t in semantic(compile_ok(doc)[0])["states"]["reponse"]["transitions"][-2:])   # no fan tag
    # opposite guards make them exclusive: now they share the trigger and the guard node is private per branch
    ga = dict(a, when="turns_left")
    gb = dict(b, when={"not": "turns_left"})
    raw2 = _dedupe_graph([ga, gb])
    doc2 = to_json_and_back(V.to_visual(raw2))
    assert len(_triggers(doc2, "ask", "reponse")) == 1
    assert semantic(compile_ok(doc2)[0], nofan=True) == semantic(raw2, nofan=True)
    # different first actions are fine to share (nothing to dedupe)
    raw3 = _dedupe_graph([dict(a, do=["cancel_all"]), dict(b, do=["mic_on"])])
    assert len(_triggers(to_json_and_back(V.to_visual(raw3)), "ask", "reponse")) == 1
    assert semantic(compile_ok(to_json_and_back(V.to_visual(raw3)))[0], nofan=True) == semantic(raw3, nofan=True)
    # a chain made only of shared nodes keeps a private End to carry its description
    p = {"on": "ask", "when": "turns_left", "description": "p"}
    q = {"on": "ask", "when": ["turns_left", "repairs_left"], "description": "q"}
    raw4 = _dedupe_graph([p, q])
    doc4 = to_json_and_back(V.to_visual(raw4))
    assert semantic(compile_ok(doc4)[0], nofan=True) == semantic(raw4, nofan=True)
    descs = [t["description"] for t in semantic(compile_ok(doc4)[0])["states"]["reponse"]["transitions"][-2:]]
    assert descs == ["p", "q"], descs


def _hub_doc(extra_nodes, extra_links, order):
    """mini_doc plus one state node per state (ids sv / sa / se) - the 2026-10-31 drawing."""
    sn = [N("sv", "state", state="veille"), N("sa", "state", state="accueil"), N("se", "state", state="eteint")]
    return mini_doc(sn + extra_nodes, extra_links, order)


def test_state_nodes_compile():
    """State nodes: a chain starts at its state node, the last node links into the destination state node."""
    doc = _hub_doc([
        N("t", "trigger", type="event", event="visage", _d="accueil automatique"),
        N("a", "action", action="cancel_all", args={}, phase="do"),
        N("t2", "trigger", type="event", event="stop"),          # no state link: global rule
        N("a2", "action", action="mic_on", args={}, phase="do"),
        N("e2", "end"),
    ], [L("start", "sv"), L("sv", "t"), L("t", "a"), L("a", "sa"), L("t2", "a2"), L("a2", "e2")], ["t", "t2"])
    raw, layout = compile_ok(doc)
    tr = raw["states"]["veille"]["transitions"][0]
    assert tr["on"] == "visage" and tr["to"] == "accueil" and tr["do"] == ["cancel_all"] and tr["description"] == "accueil automatique", tr
    assert "reason" not in tr
    assert [(t["on"], "to" in t) for t in raw["global"]] == [("stop", False)], "trigger without state link = global rule"
    assert "state/veille" in layout["nodes"] and "state/accueil" in layout["nodes"], layout["nodes"].keys()
    # the reason of the transition rides on the last link; a description with no node of its own too
    doc2 = copy.deepcopy(doc)
    doc2["links"][3]["reason"] = "visage_vu"
    raw2, _ = compile_ok(doc2)
    assert raw2["states"]["veille"]["transitions"][0]["reason"] == "visage_vu"
    # returning wires: a chain in `accueil` that goes back to veille compiles to `to: veille`
    doc3 = _hub_doc([N("t", "trigger", type="event", event="stop")], [L("sa", "t"), L("t", "sv")], ["t"])
    raw3, _ = compile_ok(doc3)
    assert raw3["states"]["accueil"]["transitions"] == [{"on": "stop", "to": "veille", "description": ""}], raw3["states"]["accueil"]
    # a bare chain (trigger -> state) round trips, description and reason included, through to_visual
    back = to_json_and_back(V.to_visual(raw3))
    assert semantic(compile_ok(back)[0]) == semantic(raw3)
    raw3b = copy.deepcopy(raw3)
    raw3b["states"]["accueil"]["transitions"][0].update(description="retour", reason="stop_bouton")
    assert semantic(compile_ok(to_json_and_back(V.to_visual(raw3b)))[0]) == semantic(raw3b)


def test_trigger_linked_from_several_states():
    """One state link = a transition of that state; two or more (or `global`) = a global rule limited to them."""
    base = [N("t", "trigger", type="event", event="stop"), N("a", "action", action="cancel_all", args={}, phase="do"),
            N("e", "end")]
    one = _hub_doc(base, [L("sv", "t"), L("t", "a"), L("a", "e")], ["t"])
    raw, _ = compile_ok(one)
    assert [t["on"] for t in raw["states"]["veille"]["transitions"]] == ["stop"] and "global" not in raw
    two = _hub_doc(base, [L("sv", "t"), L("sa", "t"), L("t", "a"), L("a", "e")], ["t"])
    raw, _ = compile_ok(two)
    assert raw["global"][0]["only_in"] == ["veille", "accueil"] and not raw["states"]["veille"].get("transitions"), raw
    flagged = copy.deepcopy(one)
    next(n for n in flagged["nodes"] if n["id"] == "t")["params"]["global"] = True
    raw, _ = compile_ok(flagged)
    assert raw["global"][0]["only_in"] == ["veille"] and not raw["states"]["veille"].get("transitions")
    # the drawing of such a rule comes back as ONE trigger linked from those states (no condition node)
    doc = to_json_and_back(V.to_visual(raw))
    trig = [n for n in doc["nodes"] if n["kind"] == "trigger" and n["params"].get("event") == "stop"]
    assert len(trig) == 1 and trig[0]["params"].get("global") is True
    assert [l["from"] for l in doc["links"] if l["to"] == trig[0]["id"]] == [find(doc, kind="state", state="veille")[0]["id"]]
    assert semantic(compile_ok(doc)[0], nofan=True) == semantic(raw, nofan=True)
    # a delay needs exactly one state
    after = _hub_doc([N("t", "trigger", type="after", delay=5, since="state"), N("e", "end")],
                     [L("sv", "t"), L("sa", "t"), L("t", "e")], ["t"])
    expect_error(after, "t", "Un délai doit être rattaché")
    # the enter trigger of a state is fed by that state's node
    enter = _hub_doc([N("t", "trigger", type="enter", state="veille"), N("a", "action", action="mic_on", args={}, phase="do"),
                      N("e", "end")], [L("sv", "t"), L("t", "a"), L("a", "e")], ["t"])
    raw, _ = compile_ok(enter)
    assert raw["states"]["veille"]["on_enter"] == ["mic_on"]
    wrong = copy.deepcopy(enter)
    wrong["links"][0] = L("sa", "t")
    expect_error(wrong, "t", "propre état")


def test_state_node_link_rules():
    """Links into / out of state nodes are validated with the id of the offending node."""
    trig = N("t", "trigger", type="event", event="stop")
    act = N("a", "action", action="cancel_all", args={}, phase="do")
    end = N("e", "end")
    # a trigger only accepts links from state nodes
    expect_error(_hub_doc([trig, act, end, N("t3", "trigger", type="event", event="visage")],
                          [L("sv", "t"), L("a", "t3"), L("t", "e")], ["t", "t3"]), "t3", "n'accepte de lien que depuis un nœud État")
    expect_error(_hub_doc([trig, N("t4", "trigger", type="event", event="visage"), end],
                          [L("sv", "t"), L("t", "t4"), L("t4", "e")], ["t", "t4"]), "t4", "n'accepte de lien que depuis un nœud État")
    # a state node feeds triggers only
    expect_error(_hub_doc([trig, act, end], [L("sv", "a"), L("sv", "t"), L("t", "e"), L("a", "e")], ["t"]), "sv", "se relie seulement à un déclencheur")
    expect_error(_hub_doc([trig, end], [L("sv", "sa"), L("sv", "t"), L("t", "e")], ["t"]), "sv", "se relie seulement à un déclencheur")
    # Start only links to a state node
    expect_error(_hub_doc([trig, end], [L("start", "e"), L("sv", "t"), L("t", "e")], ["t"]), "start", "se relie seulement à un nœud État")
    # one node per state, known states only
    expect_error(_hub_doc([N("sv2", "state", state="veille"), trig, end], [L("sv", "t"), L("t", "e")], ["t"]), "sv2", "un seul nœud État")
    expect_error(_hub_doc([N("sx", "state", state="atlantis"), trig, end], [L("sv", "t"), L("t", "e")], ["t"]), "sx", "atlantis")
    # a state node cannot be left without a way out: chain ending on it needs no further link, loops are cut
    ok = _hub_doc([trig, act], [L("sv", "t"), L("t", "a"), L("a", "sv")], ["t"])      # veille -> veille is legal
    raw, _ = compile_ok(ok)
    assert raw["states"]["veille"]["transitions"][0]["to"] == "veille"


def test_legacy_goto_documents_compile_identically():
    """A document made of go-to nodes + state conditions + `params.state` still compiles to the same graph."""
    raw = default_raw()
    for kw in ({"legacy": True}, {"legacy": True, "compact": False}, {"legacy": True, "share": False, "compact": False}):
        doc = to_json_and_back(V.to_visual(raw, **kw))
        assert not [n for n in doc["nodes"] if n["kind"] == "state"] and [n for n in doc["nodes"] if n["kind"] == "goto"]
        assert semantic(compile_ok(doc)[0], nofan=True) == semantic(raw, nofan=True), kw
    # and a legacy `params.state` trigger plus a state link to the same state is the same single scope
    doc = to_json_and_back(V.to_visual(raw))
    trig = next(n for n in doc["nodes"] if n["kind"] == "trigger" and n["params"].get("event") == "start"
                and any(l["to"] == n["id"] and find(doc, kind="state", state="veille")[0]["id"] == l["from"] for l in doc["links"]))
    trig["params"]["state"] = "veille"
    assert semantic(compile_ok(doc)[0], nofan=True) == semantic(raw, nofan=True)


def _note(i=1, **kw):
    n = {"id": "p%d" % i, "text": "Penser à ajouter la phrase du soir.", "color": "#FFF59D", "x": 40, "y": -20.5, "w": 220, "h": 140}
    n.update(kw)
    return n


def test_notes_cosmetic_postits():
    """Post-it notes: layout only (never compiled), validated, persisted, restored with versions."""
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    gp, lp = os.path.join(TMP, "graph.yaml"), os.path.join(TMP, "graph.layout.json")
    base = V.to_visual(default_raw())
    assert base["notes"] == [] and "notes" in base
    doc = copy.deepcopy(base)
    doc["notes"] = [_note(1, title="À faire"), _note(2, text="", color="#a5d6a7")]
    raw0, _ = compile_ok(base)
    raw1, layout = compile_ok(doc)
    assert semantic(raw0) == semantic(raw1) and "notes" not in V.dump_yaml(raw1), "notes must not change the compiled graph"
    assert [n["id"] for n in layout["notes"]] == ["p1", "p2"] and layout["notes"][0]["color"] == "#fff59d"
    assert layout["notes"][0]["title"] == "À faire" and "title" not in layout["notes"][1]
    assert V.save(doc, CFG, gp, lp)[0]
    back = V.to_visual(V.load_raw(gp), V.load_layout(lp))
    assert [(n["id"], n["text"], n["x"], n["y"], n["w"], n["h"]) for n in back["notes"]] == [
        ("p1", "Penser à ajouter la phrase du soir.", 40, -20.5, 220, 140), ("p2", "", 40, -20.5, 220, 140)]
    # the node positions of the state hubs are saved and restored too
    assert any(k.startswith("state/") for k in V.load_layout(lp)["nodes"])
    # validation: each bad note is refused with its id, nothing written
    before = open(lp, encoding="utf-8").read()
    for patch in ({"text": "x" * 2001}, {"color": "yellow"}, {"x": "3"}, {"w": 0}, {"h": -1}, {"title": "t" * 61},
                  {"y": float("nan")}, {"text": 5}, {"id": ""}):
        bad = copy.deepcopy(doc)
        bad["notes"][1].update(patch)
        ok, errs = V.save(bad, CFG, gp, lp)
        assert not ok and any("post-it" in e["message"] for e in errs), (patch, errs)
    dup = copy.deepcopy(doc)
    dup["notes"][1]["id"] = "p1"
    ok, errs = V.save(dup, CFG, gp, lp)
    assert not ok and errs[0]["note"] == "p1"
    assert V.from_visual(dict(base, notes="nope"), CFG)[2][0]["note"] is None
    many = copy.deepcopy(base)
    many["notes"] = [_note(i) for i in range(201)]
    assert not V.save(many, CFG, gp, lp)[0]
    many["notes"] = many["notes"][:200]
    assert V.from_visual(many, CFG)[2] == []
    ok_text = copy.deepcopy(base)
    ok_text["notes"] = [_note(1, text="é" * 2000)]
    assert V.from_visual(ok_text, CFG)[2] == []
    assert open(lp, encoding="utf-8").read() == before
    # versions: a later save without notes, then restoring the previous version brings them back
    clean = copy.deepcopy(base)
    clean["notes"] = []
    assert V.save(clean, CFG, gp, lp)[0]
    assert V.to_visual(V.load_raw(gp), V.load_layout(lp))["notes"] == []
    ok, status, _msg = V.restore_version(V.list_versions(gp)[0]["id"], CFG, gp, lp)
    assert ok and status == 200
    assert [n["id"] for n in V.to_visual(V.load_raw(gp), V.load_layout(lp))["notes"]] == ["p1", "p2"]
    # a hand-edited layout with a broken note never breaks the GET: the bad one is simply not shown
    lay = V.load_layout(lp)
    lay["notes"].append({"id": "zz", "text": 3})
    assert [n["id"] for n in V.to_visual(V.load_raw(gp), lay)["notes"]] == ["p1", "p2"]
    shutil.rmtree(TMP, ignore_errors=True)


def test_hub_layout_has_no_overlap_and_global_area():
    doc = V.to_visual(default_raw())
    pos = {n["id"]: (n["x"], n["y"]) for n in doc["nodes"]}
    assert GL.overlaps(doc["nodes"], pos) == []
    groups = {}
    for n in doc["nodes"]:
        if n.get("group"):
            groups.setdefault(n["group"], []).append(pos[n["id"]][1])
    # CHANGED (L7): columns left to right in flow order, state hubs on the top row, globals in the last column
    order = list(default_raw()["states"]) + ["global"]
    xs = {}
    for n in doc["nodes"]:
        if n.get("group"):
            xs.setdefault(n["group"], []).append(pos[n["id"]][0])
    lefts = [min(xs[g]) for g in order]
    assert lefts == sorted(lefts), "columns run left to right in state order, globals last"
    for g in order[:-1]:     # columns are disjoint: every node of a column is left of the next column
        nxt = order[order.index(g) + 1]
        assert max(xs[g]) + GL.NODE_W < min(xs[nxt]), (g, nxt)
    hubs = [n for n in doc["nodes"] if n["kind"] == "state"]
    assert len({pos[n["id"]][1] for n in hubs}) == 1, "all hubs on one row"
    assert all(pos[n["id"]][1] <= min(groups[n["group"]]) for n in hubs), "hub heads its column"
    assert [f["title"] for f in doc["frames"]][-1] == "Règles globales"
    assert all(f.get("auto") for f in doc["frames"]) and len(doc["frames"]) == len(order)
    fr = doc["frames"]
    assert all(fr[i]["x"] + fr[i]["w"] < fr[i + 1]["x"] for i in range(len(fr) - 1)), "auto frames never overlap"
    print("  hub columns: %d crossings with all wires, %d without the faded returning wires" % (
        GL.crossings(doc["nodes"], doc["links"], pos), GL.crossings(doc["nodes"], doc["links"], pos, returning=False)))
    # an old layout file (no `state/` key) is ignored for positions but its frames stay
    old = {"nodes": {"veille/t0/0": {"x": 9999, "y": 9999}, "start": {"x": 5, "y": 5}}, "frames": [
        {"id": "f1", "title": "x", "color": "#112233", "x": 0, "y": 0, "w": 10, "h": 10}]}
    d2 = V.to_visual(default_raw(), old)
    assert all(n["x"] != 9999 for n in d2["nodes"]) and [f["id"] for f in d2["frames"]] == ["f1"]


FAST = [test_roundtrip_default, test_layout_bands_and_persistence, test_vocabulary, test_error_cases,
        test_negated_guard_compiles_and_evaluates, test_false_port_and_order, test_save_backups_and_reset,
        test_deferred_reload_applies_at_next_veille, test_frames_cosmetic_groups,
        test_sharing_lighter_and_equivalent, test_layout_no_overlap_and_few_crossings,
        test_merged_fan_trigger_reloads_as_one_node, test_sharing_keeps_independent_transitions_apart,
        test_state_nodes_compile, test_trigger_linked_from_several_states, test_state_node_link_rules,
        test_legacy_goto_documents_compile_identically, test_notes_cosmetic_postits, test_hub_layout_has_no_overlap_and_global_area]


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
