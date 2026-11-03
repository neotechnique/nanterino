"""Tests of lot S1 "domaines": the level above the state columns (graph_layout.domain_layout, graph_visual.domain_doc).

logging: robotlog via nanterino.log (imported by nanterino.graph_visual; this file only prints PASS / FAIL lines).

Purpose : prove that domains are organisation only and drawn safely: every column (state + global) sits in exactly one
          domain, default regions never overlap and hold their columns and nodes, the per-domain layout keeps 0 link
          crossings and 0 node overlaps, domains / columns / fold flags round-trip through from_visual -> to_visual,
          a layout written before S1 still loads (defaults), invalid domains / columns are refused, the compiled graph
          never changes, empty domains show their explanatory post-it.
Boundary: pure functions on dicts (no Brain, no server, never imports nanterino.server); files only under /tmp.
How to run (repo root):
    .venv/bin/python -m tests.test_graph_domains      (about 5 s; prints `graph_domains tests: n/n passed`, exit 1 on failure)
"""
import copy
import json
import os
import sys

sys.path.insert(0, "/opt/robot/lib")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nanterino import config, graph as G, graph_layout as GL, graph_visual as V  # noqa: E402

CFG = dict(config.DEFAULTS)
ICONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "vendor", "tabler")
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


def inside(inner, outer):
    return (outer["x"] <= inner[0] and outer["y"] <= inner[1] and inner[2] <= outer["x"] + outer["w"]
            and inner[3] <= outer["y"] + outer["h"])


def disjoint(a, b):
    return a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"] or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"]


def regions_ok(doc, label):
    """Regions pairwise disjoint; every column frame and every node inside the region of its domain."""
    doms = {d["id"]: d for d in doc["domains"]}
    ds = doc["domains"]
    bad = [(a["id"], b["id"]) for i, a in enumerate(ds) for b in ds[i + 1:] if not disjoint(a, b)]
    check(label + ": regions never overlap", not bad, bad)
    cols = {f["id"][5:]: f for f in doc["frames"] if f.get("auto")}
    out = [g for g, f in cols.items() if not inside((f["x"], f["y"], f["x"] + f["w"], f["y"] + f["h"]), doms[doc["columns"][g]["domain"]])]
    check(label + ": each column frame inside its domain region", not out, out)
    nout = [n["id"] for n in doc["nodes"] if n.get("group") and not inside(
        (n["x"], n["y"], n["x"] + GL.NODE_W, n["y"] + GL.node_height(n)), doms[doc["columns"][n["group"]]["domain"]])]
    check(label + ": each node inside its domain region", not nout, nout[:5])
    pos = {n["id"]: (n["x"], n["y"]) for n in doc["nodes"]}
    x = GL.crossings(doc["nodes"], doc["links"], pos)
    check(label + ": 0 link crossings with the per-domain layout", x == 0, x)
    check(label + ": no node overlaps", GL.overlaps(doc["nodes"], pos) == [])


def test_default_domains():
    doc = V.to_visual(raw())
    groups = list(raw()["states"]) + ["global"]
    check("every column in exactly one domain", sorted(doc["columns"]) == sorted(groups)
          and all(set(e) <= {"domain", "folded"} for e in doc["columns"].values()), doc["columns"])
    check("states default to dialogue, global to systeme",
          all(doc["columns"][g]["domain"] == ("systeme" if g == "global" else "dialogue") for g in groups), doc["columns"])
    check("domain table = 4 defaults in order", [d["id"] for d in doc["domains"]] == ["dialogue", "comportement", "mouvement", "systeme"]
          and [d["order"] for d in doc["domains"]] == sorted(d["order"] for d in doc["domains"]), doc["domains"])
    check("domain icons are vendored icons", all(os.path.exists(os.path.join(ICONS, d["icon"] + ".svg")) for d in doc["domains"]),
          [d["icon"] for d in doc["domains"]])
    check("no private key leaks into the document", not any(k.startswith("_") for d in doc["domains"] for k in d))
    regions_ok(doc, "default")
    notes = {n.get("auto"): n for n in doc["notes"]}
    doms = {d["id"]: d for d in doc["domains"]}
    for d in ("comportement", "mouvement"):
        n = notes.get("domain:" + d)
        check("empty domain %s has its explanatory post-it inside its region" % d,
              n is not None and inside((n["x"], n["y"], n["x"] + n["w"], n["y"] + n["h"]), doms[d]) and n["text"], n)
    check("non-empty domains get no domain post-it", "domain:dialogue" not in notes and "domain:systeme" not in notes)
    check("t-* theme frames gone from the variables drawing", not any(f["id"].startswith("t-") for f in doc["frames"]))


def test_roundtrip_and_fold():
    r = raw()
    doc = V.to_visual(r)
    doc["columns"]["relance"] = {"domain": "comportement", "folded": True}
    next(d for d in doc["domains"] if d["id"] == "mouvement")["folded"] = True
    next(d for d in doc["domains"] if d["id"] == "systeme")["label"] = "Global"
    raw2, layout, errs = V.from_visual(doc, CFG)
    check("document with domains compiles", not errs, errs)
    plain, _l0, _e0 = V.from_visual({k: v for k, v in doc.items() if k not in ("domains", "columns")}, CFG)
    check("compiled graph unchanged by domains / fold", semantic(raw2) == semantic(plain) and raw2 == plain)
    check("dumped YAML never mentions a domain", "domain" not in V.dump_yaml(raw2) and "folded" not in V.dump_yaml(raw2))
    check("layout keeps columns + domains", layout.get("columns", {}).get("relance") == {"domain": "comportement", "folded": True}
          and any(d["id"] == "mouvement" and d.get("folded") for d in layout.get("domains", [])), layout.get("columns"))
    lay = json.loads(json.dumps(layout))
    doc2 = V.to_visual(raw2, lay)
    check("reload: column domain + fold kept", doc2["columns"]["relance"] == {"domain": "comportement", "folded": True}, doc2["columns"])
    check("reload: domain fold + label kept", next(d for d in doc2["domains"] if d["id"] == "mouvement").get("folded") is True
          and next(d for d in doc2["domains"] if d["id"] == "systeme")["label"] == "Global")
    check("reload: node positions kept", {n["id"]: (n["x"], n["y"]) for n in doc2["nodes"]} == {n["id"]: (n["x"], n["y"]) for n in doc["nodes"]})
    _r3, lay3, e3 = V.from_visual(doc2, CFG)
    # region rectangles are derived from the column frames (the mapping alone moved relance: its frame did not move,
    # so the comportement region now wraps it); everything else of the table is kept as is
    norect = lambda ds: [{k: v for k, v in d.items() if k not in ("x", "y", "w", "h")} for d in ds]
    check("second round trip identical columns + domain table", not e3 and lay3.get("columns") == lay.get("columns")
          and norect(lay3.get("domains")) == norect(lay.get("domains")), (e3,))


def test_per_domain_server_layout():
    """A column mapped to another domain is drawn inside that domain's region (server layout, no saved positions)."""
    r = raw()
    nodes_doc = V.to_visual(r)
    regions = []
    col_dom = {"relance": "comportement", "eteint": "mouvement"}
    pos = GL.domain_layout(nodes_doc["nodes"], nodes_doc["links"], col_dom, head={}, note_h=V.column_note_height,
                           regions_out=regions)
    reg = {x["id"]: x for x in regions}
    check("per-domain layout: one region per domain, all non-empty now", [x["id"] for x in regions] == ["dialogue", "comportement", "mouvement", "systeme"]
          and not any(x["empty"] for x in regions), regions)
    bad = [(a["id"], b["id"]) for i, a in enumerate(regions) for b in regions[i + 1:] if not disjoint(a, b)]
    check("per-domain layout: regions disjoint", not bad, bad)
    out = [n["id"] for n in nodes_doc["nodes"] if n.get("group") and not inside(
        (pos[n["id"]][0], pos[n["id"]][1], pos[n["id"]][0] + GL.NODE_W, pos[n["id"]][1] + GL.node_height(n)),
        reg[col_dom.get(n["group"]) or GL.default_domain(n["group"])])]
    check("per-domain layout: nodes inside their (moved) domain", not out, out[:5])
    check("per-domain layout: 0 crossings, 0 overlaps", GL.crossings(nodes_doc["nodes"], nodes_doc["links"], pos) == 0
          and GL.overlaps(nodes_doc["nodes"], pos) == [])
    # through to_visual: a layout that only lends the column map (older form) redraws with it
    doc = V.to_visual(r, {"columns": {"relance": {"domain": "comportement"}}, "frames": [
        {"id": "auto-veille", "title": "x", "color": "#112233", "x": 0, "y": 0, "w": 10, "h": 10, "auto": True}]})
    check("to_visual honours a saved column domain", doc["columns"]["relance"]["domain"] == "comportement")
    regions_ok(doc, "moved column")


def test_legacy_layout_and_errors():
    r = raw()
    doc = V.to_visual(r)
    _raw, layout, _e = V.from_visual(doc, CFG)
    old = {k: v for k, v in layout.items() if k not in ("domains", "columns")}   # graph.layout.json written before S1
    doc2 = V.to_visual(r, json.loads(json.dumps(old)))
    check("legacy layout without domains loads with the defaults", doc2["columns"] == doc["columns"]
          and [d["id"] for d in doc2["domains"]] == [d["id"] for d in doc["domains"]])
    check("legacy layout: every domain has a region", all(all(k in d for k in ("x", "y", "w", "h")) for d in doc2["domains"]))
    _r2, _l2, e2 = V.from_visual({k: v for k, v in doc.items() if k not in ("domains", "columns")}, CFG)
    check("document without domains / columns still compiles", not e2, e2)
    bad = copy.deepcopy(doc)
    bad["columns"]["veille"] = {"domain": "nulle_part"}
    _r, _l, e = V.from_visual(bad, CFG)
    check("column in an unknown domain refused", any("domaine inconnu" in x["message"] for x in e), e)
    bad = copy.deepcopy(doc)
    bad["domains"][0]["color"] = "bleu"
    _r, _l, e = V.from_visual(bad, CFG)
    check("domain with a bad colour refused", any(x.get("domain") == "dialogue" for x in e), e)
    bad = copy.deepcopy(doc)
    bad["domains"].append(dict(bad["domains"][0]))
    _r, _l, e = V.from_visual(bad, CFG)
    check("duplicate domain id refused", any("double" in x["message"] for x in e), e)
    hand = {"form": "vars", "domains": [{"id": "BAD"}], "columns": {"veille": {"domain": "nope"}, "x": 3}}
    d3 = V.to_visual(r, hand)
    check("hand-edited bad domains ignored on GET (defaults)", d3["columns"]["veille"]["domain"] == "dialogue"
          and [d["id"] for d in d3["domains"]] == ["dialogue", "comportement", "mouvement", "systeme"])
    extra = copy.deepcopy(doc)
    extra["domains"].append({"id": "vision", "label": "Vision", "color": "#39c5cf", "icon": "eye", "order": 5,
                             "x": 0, "y": -2000, "w": 900, "h": 480})
    extra["columns"]["cloture"] = {"domain": "vision"}
    _r4, l4, e4 = V.from_visual(extra, CFG)
    check("a new domain accepted and stored", not e4 and any(d["id"] == "vision" for d in l4["domains"]) and l4["columns"]["cloture"]["domain"] == "vision", e4)


def main():
    for fn in (test_default_domains, test_roundtrip_and_fold, test_per_domain_server_layout, test_legacy_layout_and_errors):
        try:
            fn()
        except Exception as e:  # report and keep going
            import traceback
            traceback.print_exc()
            check(fn.__name__ + " completed", False, repr(e))
    ok = sum(1 for _n, r in results if r)
    print("graph_domains tests: %d/%d passed" % (ok, len(results)))
    sys.exit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    main()
