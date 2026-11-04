"""Tests of lot S2 "repli qui libère la place": region grid packing and the repair of overlapping saved layouts.

logging: robotlog via nanterino.log (imported by nanterino.graph_visual; this file only prints PASS / FAIL lines).

Purpose : prove that graph_layout.pack_positions / repack_regions (mirror of web/editor/domains/domains.js packPositions /
          packRegions) are deterministic and safe: the shipped default grid packs to itself, a shrunk region (fold)
          packed then grown back (unfold) restores every position, a saved layout whose regions overlap (hand mapping,
          layout written before S1) is repaired on load with every item moved WITH its region (nodes keep their offset
          to their column frame), a layout without overlap is never touched, folded cards and the domain post-it give
          the drawn region size, and the compiled graph never changes.
Boundary: pure functions on dicts (no Brain, no server, never imports nanterino.server); no file written.
How to run (repo root):
    .venv/bin/python -m tests.test_graph_repack      (about 5 s; prints `graph_repack tests: n/n passed`, exit 1 on failure)
"""
import copy
import json
import os
import sys

sys.path.insert(0, "/opt/robot/lib")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nanterino import config, graph as G, graph_layout as GL, graph_visual as V  # noqa: E402

CFG = dict(config.DEFAULTS)
results = []


def check(name, ok, info=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  " + str(info)[:600]), flush=True)


def raw():
    return V.load_raw(G.DEFAULT_PATH)


def semantic(r):
    g = G.parse_graph(copy.deepcopy(r), CFG, "<test>")
    d = g.to_dict()
    d.pop("source")
    return json.loads(json.dumps(d))


def items(rects, doc):
    order = [d["id"] for d in doc["domains"] if d["id"] in rects]
    return [dict(rects[i], id=i, i=k) for k, i in enumerate(order)]


def col_offsets(doc):
    """{node id: (dx, dy)} of each node to its column frame."""
    fr = {f["id"][5:]: f for f in doc["frames"] if f.get("auto")}
    return {n["id"]: (n["x"] - fr[n["group"]]["x"], n["y"] - fr[n["group"]]["y"]) for n in doc["nodes"] if n.get("group") in fr}


def inside(box, r):
    return r["x"] <= box[0] and r["y"] <= box[1] and box[2] <= r["x"] + r["w"] and box[3] <= r["y"] + r["h"]


def regions_sane(doc, label):
    rects = GL.region_boxes(doc)
    check(label + ": no two regions overlap", GL.overlapping_regions(rects) == [], rects)
    cols = {f["id"][5:]: f for f in doc["frames"] if f.get("auto")}
    out = [g for g, f in cols.items() if not inside((f["x"], f["y"], f["x"] + f["w"], f["y"] + f["h"]), rects[GL._dom_of(doc, g)])]
    check(label + ": every column frame inside its region", not out, out)
    nout = [n["id"] for n in doc["nodes"] if n.get("group") in cols and not inside(
        (n["x"], n["y"], n["x"] + GL.NODE_W, n["y"] + GL.node_height(n)), rects[GL._dom_of(doc, n["group"])])]
    check(label + ": every node inside its region", not nout, nout[:5])


def test_default_packs_to_itself():
    doc = V.to_visual(raw())
    rects = GL.region_boxes(doc)
    check("default: 4 drawn regions", sorted(rects) == sorted(["dialogue", "comportement", "mouvement", "systeme"]), rects)
    check("default: no overlap (nothing to repair)", GL.overlapping_regions(rects) == [])
    pos = GL.pack_positions(items(rects, doc))
    check("default grid packs to itself (server grid = editor grid)", all(pos[i] == (rects[i]["x"], rects[i]["y"]) for i in rects),
          {i: (pos[i], (rects[i]["x"], rects[i]["y"])) for i in rects})
    before = json.dumps(doc, sort_keys=True)
    check("repack of a layout without overlap is a no-op", GL.repack_regions(doc) == 0 and json.dumps(doc, sort_keys=True) == before)


def test_fold_unfold_restores():
    doc = V.to_visual(raw())
    rects = GL.region_boxes(doc)
    for fold in rects:
        it = items(rects, doc)
        shrunk = [dict(r, w=GL.FOLD_DOM_W, h=GL.FOLD_DOM_H) if r["id"] == fold else r for r in it]
        p1 = GL.pack_positions(shrunk)
        moved = [dict(r, x=p1[r["id"]][0], y=p1[r["id"]][1]) for r in shrunk]
        disjoint = GL.overlapping_regions({r["id"]: r for r in moved}) == []
        grown = [dict(r, w=rects[r["id"]]["w"], h=rects[r["id"]]["h"]) for r in moved]
        p2 = GL.pack_positions(grown)
        check("fold %s: packed regions disjoint, unfold restores every position" % fold,
              disjoint and all(p2[i] == (rects[i]["x"], rects[i]["y"]) for i in rects), (p1, p2))
    # the default grid: Dialogue alone on row 1, then Comportement, Mouvement, Système; folding Dialogue pulls row 2 up,
    # widening Comportement (unfold) pushes Mouvement and Système right
    p = GL.pack_positions([dict(r, w=GL.FOLD_DOM_W, h=GL.FOLD_DOM_H) if r["id"] == "dialogue" else r for r in items(rects, doc)])
    check("folding reclaims space: the next row moves up by the height the fold gave up",
          p["comportement"][1] == rects["dialogue"]["y"] + GL.FOLD_DOM_H + GL.DOM_GAP < rects["comportement"]["y"], (p, rects))
    p = GL.pack_positions([dict(r, w=3000) if r["id"] == "comportement" else r for r in items(rects, doc)])
    check("a grown region pushes the regions right of it in its row", p["mouvement"][0] == rects["comportement"]["x"] + 3000 + GL.DOM_GAP, p)


def test_repack_deterministic_rows():
    rs = [{"id": "a", "x": 0, "y": 0, "w": 1000, "h": 3000, "i": 0}, {"id": "b", "x": 1300, "y": 40, "w": 500, "h": 500, "i": 1},
          {"id": "c", "x": 0, "y": 3260, "w": 900, "h": 480, "i": 2}]
    p = GL.pack_positions(rs)
    check("rows: tops within ROW_TOL share a row, aligned on its top", p["a"] == (0, 0) and p["b"] == (1000 + GL.DOM_GAP, 0) and p["c"] == (0, 3000 + GL.DOM_GAP), p)
    check("pack is deterministic (same input, same output; input order does not matter)", p == GL.pack_positions(list(reversed(rs))))
    small = [dict(r, h=250) if r["id"] == "a" else r for r in rs]
    p2 = GL.pack_positions(small)
    check("a shrunk tall region pulls the next row up (by the height it gave up)", p2["c"] == (0, 500 + GL.DOM_GAP), p2)


def test_overlap_repaired_on_load():
    r = raw()
    doc = V.to_visual(r)
    doc["columns"]["relance"] = {"domain": "comportement"}     # hand mapping: the frame did not move -> overlap
    raw2, layout, errs = V.from_visual(doc, CFG)
    check("hand-mapped document compiles", not errs, errs)
    pre = copy.deepcopy(doc)
    check("the saved document really has overlapping regions", GL.overlapping_regions(GL.region_boxes(pre)) != [])
    lay = json.loads(json.dumps(layout))
    d2 = V.to_visual(raw2, copy.deepcopy(lay))
    regions_sane(d2, "hand mapping repaired")
    check("hand mapping: every node keeps its offset to its column frame", col_offsets(d2) == col_offsets(pre))
    check("hand mapping: post-its moved with their column (offset to the frame kept)", all(
        (n["x"] - fr["x"], n["y"] - fr["y"]) == (o["x"] - fo["x"], o["y"] - fo["y"])
        for n in d2["notes"] for o in pre["notes"] if n["id"] == o["id"] and str(n.get("auto", "")).startswith("state:")
        for fr in d2["frames"] for fo in pre["frames"] if fr["id"] == fo["id"] == "auto-" + n["auto"][6:]))
    d3 = V.to_visual(raw2, copy.deepcopy(lay))
    check("repair is deterministic (two loads, same document)", json.dumps(d2, sort_keys=True) == json.dumps(d3, sort_keys=True))
    raw3, lay3, e3 = V.from_visual(d2, CFG)
    check("repaired document compiles to the same graph", not e3 and semantic(raw3) == semantic(raw2))
    d4 = V.to_visual(raw3, json.loads(json.dumps(lay3)))
    check("saved after repair: reload does not move anything again", {n["id"]: (n["x"], n["y"]) for n in d4["nodes"]} == {n["id"]: (n["x"], n["y"]) for n in d2["nodes"]})


def test_pre_s1_layout_repaired():
    r = raw()
    doc = V.to_visual(r)
    # a pre-S1 drawing: the global column sat inside the Dialogue rows (one wrap for the whole robot)
    g = next(f for f in doc["frames"] if f["id"] == "auto-global")
    dia = [f for f in doc["frames"] if f.get("auto") and f["id"] != "auto-global"]
    tx, ty = dia[0]["x"] + 200, dia[0]["y"] + 300
    dx, dy = tx - g["x"], ty - g["y"]
    sub = {g["id"]} | {f["id"] for f in doc["frames"] if f.get("parent") == g["id"]}
    for f in doc["frames"]:
        if f["id"] in sub:
            f["x"] += dx; f["y"] += dy
    for n in doc["notes"]:
        if n.get("parent") in sub:
            n["x"] += dx; n["y"] += dy
    for n in doc["nodes"]:
        if n.get("group") == "global":
            n["x"] += dx; n["y"] += dy
    _raw, layout, errs = V.from_visual(doc, CFG)
    check("pre-S1 style document compiles", not errs, errs)
    lay = json.loads(json.dumps(layout))
    lay.pop("domains", None); lay.pop("columns", None)
    lay["notes"] = [n for n in lay.get("notes", []) if not str(n.get("auto", "")).startswith("domain:")]
    d2 = V.to_visual(r, lay)
    regions_sane(d2, "pre-S1 layout")
    check("pre-S1 layout: nodes keep their offset to their column", col_offsets(d2) == col_offsets(doc))


def test_drawn_sizes():
    doc = V.to_visual(raw())
    full = GL.region_boxes(doc)
    d = copy.deepcopy(doc)
    next(x for x in d["domains"] if x["id"] == "dialogue")["folded"] = True
    r = GL.region_boxes(d)
    check("folded domain = its FOLD_DOM card at the region's top-left", r["dialogue"] == {"x": full["dialogue"]["x"], "y": full["dialogue"]["y"], "w": GL.FOLD_DOM_W, "h": GL.FOLD_DOM_H}, r["dialogue"])
    check("full=True ignores folds", GL.region_boxes(d, full=True)["dialogue"] == full["dialogue"])
    d = copy.deepcopy(doc)
    mine = [f for f in d["frames"] if f.get("auto") and GL._dom_of(d, f["id"][5:]) == "dialogue"]
    right = max(mine, key=lambda f: f["x"] + f["w"])
    d["columns"][right["id"][5:]] = {"domain": "dialogue", "folded": True}
    r = GL.region_boxes(d)
    edge = max([f["x"] + f["w"] for f in mine if f is not right] + [right["x"] + GL.FOLD_COL_W])
    check("folded column counts as its card in the region width", r["dialogue"]["w"] == edge + GL.DOM_PAD - full["dialogue"]["x"]
          and r["dialogue"]["w"] <= full["dialogue"]["w"], (r["dialogue"], full["dialogue"]))
    d = copy.deepcopy(doc)
    rel = next(f for f in d["frames"] if f["id"] == "auto-relance")
    d["columns"]["relance"] = {"domain": "comportement"}
    note = next(n for n in d["notes"] if n.get("auto") == "domain:comportement")
    note["x"], note["y"] = rel["x"] + rel["w"] + 150, rel["y"]
    r = GL.region_boxes(d)
    check("the domain post-it beside its columns is inside the drawn region",
          inside((note["x"], note["y"], note["x"] + note["w"], note["y"] + note["h"]), r["comportement"]), (note, r["comportement"]))


def main():
    for t in (test_default_packs_to_itself, test_fold_unfold_restores, test_repack_deterministic_rows, test_overlap_repaired_on_load,
              test_pre_s1_layout_repaired, test_drawn_sizes):
        try:
            t()
        except Exception as e:  # report and keep going
            import traceback
            traceback.print_exc()
            check(t.__name__ + " completed", False, repr(e))
    ok = sum(1 for _n, v in results if v)
    print("graph_repack tests: %d/%d passed" % (ok, len(results)))
    sys.exit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    main()
