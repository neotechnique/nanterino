"""Tests of lot S3 "bigworld": the synthetic 10x document and the server caps that let such a graph through.

logging: robotlog via nanterino.log (imported by nanterino.graph_visual; this file only prints PASS / FAIL lines).

Purpose : prove that (1) the 10x generator (tests/bigworld_gen.py) is deterministic, leaves the shipped part untouched and
          produces a document the robot compiles with 0 errors and 0 warnings; (2) a graph of that size keeps every group
          and post-it through to_visual / from_visual (caps MAX_FRAMES / MAX_NOTES raised from 100 / 200 to 1000, they used
          to truncate silently on GET and to refuse on POST); (3) the automatic layout of a graph without saved layout
          draws every column (84 in one domain, MAX_ROWS rows) with 0 node overlaps, regions disjoint, deterministically,
          and the shipped graph's layout is byte-identical under the old and the new caps.
Boundary: pure functions on dicts (no Brain, no server, never imports nanterino.server); no file is written.
How to run (repo root):
    .venv/bin/python -m tests.test_graph_bigworld      (about 25 s; prints `graph_bigworld tests: n/n passed`, exit 1 on failure)
"""
import copy
import json
import os
import sys
import time

sys.path.insert(0, "/opt/robot/lib")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nanterino import config, graph as G, graph_layout as GL, graph_visual as V  # noqa: E402
from tests.bigworld_gen import dialogue_states, replicate  # noqa: E402

CFG = dict(config.DEFAULTS)
COPIES = 12
results = []


def check(name, ok, info=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  " + str(info)[:600]), flush=True)


def disjoint(a, b):
    return a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"] or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"]


def main():
    raw = V.load_raw(G.DEFAULT_PATH)
    base = V.to_visual(raw)
    frozen = json.dumps(base, sort_keys=True)
    big = replicate(base, COPIES)
    # ---- generator
    check("generator leaves its input untouched", json.dumps(base, sort_keys=True) == frozen)
    check("generator is deterministic", json.dumps(replicate(base, COPIES), sort_keys=True) == json.dumps(big, sort_keys=True))
    n0 = len(base["nodes"])
    check("the shipped document is the first part of the 10x one, unchanged",
          big["nodes"][:n0] == base["nodes"] and big["links"][:len(base["links"])] == base["links"]
          and big["frames"][:len(base["frames"])] == base["frames"] and big["notes"][:len(base["notes"])] == base["notes"])
    dia = [s for s in dialogue_states(base)]
    per = sum(1 for n in base["nodes"] if n.get("group") in dia)
    check("size: %d nodes (about 10x), %d states, %d domains, %d groups, %d post-its" % (
        len(big["nodes"]), len(big["states"]), len(big["domains"]), len(big["frames"]), len(big["notes"])),
        len(big["nodes"]) == n0 + (COPIES - 1) * per and 2200 <= len(big["nodes"]) <= 2400 and len(big["domains"]) == 4 + COPIES - 1
        and len(big["states"]) == len(base["states"]) + (COPIES - 1) * len(dia) and len(big["frames"]) > 400 and len(big["notes"]) > 400)
    ids = [n["id"] for n in big["nodes"]]
    check("node, frame and post-it ids are unique", len(set(ids)) == len(ids) and len({f["id"] for f in big["frames"]}) == len(big["frames"])
          and len({n["id"] for n in big["notes"]}) == len(big["notes"]))
    # ---- it compiles
    rep = {}
    t0 = time.time()
    raw2, lay2, errs = V.from_visual(big, CFG, rep)
    check("10x document compiles: 0 errors, 0 warnings (%.1f s)" % (time.time() - t0), not errs and not rep["warnings"], (errs[:3], rep["warnings"][:3]))
    try:
        g = G.parse_graph(copy.deepcopy(raw2), CFG, "<bigworld>")
        ok = bool(g.to_dict())
    except Exception as e:  # the validator raises on an invalid graph
        ok = False
        print("   ", repr(e)[:300])
    check("the compiled graph passes the YAML validator (parse_graph)", ok)
    # ---- caps: nothing truncated through the saved layout
    check("caps raised: MAX_FRAMES and MAX_NOTES are at least 1000", V.MAX_FRAMES >= 1000 and V.MAX_NOTES >= 1000, (V.MAX_FRAMES, V.MAX_NOTES))
    check("the layout written by a save keeps every group and post-it", len(lay2["frames"]) == len(big["frames"]) and len(lay2["notes"]) == len(big["notes"]),
          (len(lay2["frames"]), len(big["frames"]), len(lay2["notes"]), len(big["notes"])))
    d2 = V.to_visual(raw2, lay2)
    check("GET after that save returns every node, group, post-it and domain (nothing truncated)",
          len(d2["nodes"]) == len(big["nodes"]) and len(d2["frames"]) == len(big["frames"]) and len(d2["notes"]) == len(big["notes"])
          and len(d2["domains"]) == len(big["domains"]))
    over = copy.deepcopy(big)
    over["frames"] = (over["frames"] * 3)[:V.MAX_FRAMES + 1]
    for i, f in enumerate(over["frames"]):
        f["id"] = "x%d" % i
        f.pop("parent", None)
    check("one group over the cap is refused", any("Trop de groupes" in e["message"] for e in V.from_visual(over, CFG)[2]))
    # ---- automatic layout (no saved layout): every column drawn, no overlap, deterministic
    t0 = time.time()
    d3 = V.to_visual(raw2)
    dt = time.time() - t0
    cols = [f for f in d3["frames"] if f.get("auto") and f["id"].startswith("auto-")]
    check("auto layout of the 10x graph (%.1f s): one frame per column (%d), more groups than the old cap (%d), none dropped" % (dt, len(cols), len(d3["frames"])),
          len(cols) == len(big["states"]) + 1 and len(d3["frames"]) > 100 and len(d3["notes"]) > 200 and len(d3["nodes"]) == len(big["nodes"]) and dt < 30,
          (len(cols), len(big["states"])))
    check("auto layout: 84 Dialogue columns in one domain, regions disjoint",
          sum(1 for c in d3["columns"].values() if c["domain"] == "dialogue") == 84
          and all(disjoint(a, b) for i, a in enumerate(d3["domains"]) for b in d3["domains"][i + 1:]))
    pos = {n["id"]: (n["x"], n["y"]) for n in d3["nodes"]}
    t0 = time.time()
    ov = GL.overlaps(d3["nodes"], pos)
    check("auto layout: 0 node overlaps (%.1f s)" % (time.time() - t0), ov == [], ov[:3])
    check("auto layout is deterministic", json.dumps(V.to_visual(raw2), sort_keys=True) == json.dumps(d3, sort_keys=True))
    # ---- the shipped graph is drawn exactly as before the cap change
    new_caps = json.dumps(V.to_visual(raw), sort_keys=True)
    old = (V.MAX_FRAMES, V.MAX_NOTES)
    V.MAX_FRAMES, V.MAX_NOTES = 100, 200
    try:
        old_caps = json.dumps(V.to_visual(raw), sort_keys=True)
    finally:
        V.MAX_FRAMES, V.MAX_NOTES = old
    check("the shipped graph's layout is identical under the old caps (100 / 200) and the new ones", new_caps == old_caps)
    bad = [r for r, ok in results if not ok]
    ok = sum(1 for _r, o in results if o)
    print("graph_bigworld tests: %d/%d passed" % (ok, len(results)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
