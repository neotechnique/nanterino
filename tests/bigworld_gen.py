"""Synthetic "10x" editor document for the bigworld performance tests (lot S3, plan "espace sans limite" A4 + A5).

logging: robotlog is not needed here (pure functions, no I/O); the test files that call this module log through nanterino.log.

Purpose : build a valid editor document (the shape GET /api/graph/visual serves) about ten times the size of the shipped
          graph, by REPLICATING the Dialogue domain of the shipped document under renamed ids: every copy is a new
          domain ("Dialogue 2", ...) holding its own 7 state columns (veille_2, accueil_2, ...), their sub-groups,
          post-its, chains and wires, placed on a grid beside the original (which is kept untouched, with its
          Comportement / Mouvement / Système domains). Several domains, dozens of columns, ~2,300 nodes.
Boundary: pure functions on dicts (no Brain, no server, no network, never imports nanterino.server); never writes
          graph.yaml / graph.layout.json. The web scenario `bigworld` feeds the result to the editor through a fetch stub
          of GET /api/graph/visual (the path a user document takes); tests/test_graph_bigworld.py compiles it offline.
Invariants: deterministic (same input, same output); the input document is never modified; the original document is the
          first part of the output unchanged (same ids, same positions); a state of a copy is `<state>_<k>` (k >= 2) and
          every string of a copied node that names a base state is renamed with it (state refs in params, `etat`
          values, `only_in` of the intents get the new states appended); node / frame / note ids get the same suffix;
          the global rules column is NOT replicated (a global rule is global: one column only).
How to test: .venv/bin/python -m tests.test_graph_bigworld  (offline compile of the 10x document, ~10 s).
"""
import copy

DOMAIN_W, DOMAIN_H, DOM_GAP = 7600, 6289, 260   # footprint of one Dialogue region (shipped document) + gap
ORIGIN_X, ORIGIN_Y = 8000, 190                    # top-left of the first copy, right of the original blocks
PER_ROW = 4


def _rename(v, ren):
    """Deep copy of `v` with every string equal to a base state id replaced by its renamed state."""
    if isinstance(v, str):
        return ren.get(v, v)
    if isinstance(v, list):
        return [_rename(x, ren) for x in v]
    if isinstance(v, dict):
        return {k: _rename(x, ren) for k, x in v.items()}
    return v


def dialogue_states(doc: dict) -> list:
    """State ids that live in the Dialogue domain (every column mapped to it), in document order."""
    cols = doc.get("columns") or {}
    return [s["id"] for s in doc.get("states") or [] if (cols.get(s["id"]) or {}).get("domain") == "dialogue"]


def _frame_state(fid):
    """State id inside an `auto-<state>` / `sub-<state>-<key>` frame id, else None."""
    if fid.startswith(("auto-", "sub-")):
        return fid.split("-", 2)[1]
    return None


def _frame_id(fid, ren):
    parts = fid.split("-", 2)
    parts[1] = ren[parts[1]]
    return "-".join(parts)


def replicate(doc: dict, copies: int = 12) -> dict:
    """The shipped document plus `copies - 1` renamed copies of its Dialogue domain (total ~ copies x the dialogue part)."""
    base_states = dialogue_states(doc)
    out = copy.deepcopy(doc)
    base_dom = next(d for d in doc["domains"] if d["id"] == "dialogue")
    mine = {n["id"] for n in doc["nodes"] if n.get("group") in base_states}
    for k in range(2, copies + 1):
        j = k - 2
        dx = ORIGIN_X + (j % PER_ROW) * (DOMAIN_W + DOM_GAP) - base_dom["x"]
        dy = ORIGIN_Y + (j // PER_ROW) * (DOMAIN_H + DOM_GAP) - base_dom["y"]
        ren = {s: "%s_%d" % (s, k) for s in base_states}
        rid = lambda i, k=k: "%s_%d" % (i, k)
        # --- states, columns, domain
        for s in doc["states"]:
            if s["id"] in ren:
                out["states"].append(dict(copy.deepcopy(s), id=ren[s["id"]]))
                out["columns"][ren[s["id"]]] = {"domain": "dialogue_%d" % k}
        out["domains"].append({**copy.deepcopy(base_dom), "id": "dialogue_%d" % k, "label": "Dialogue %d" % k,
                               "order": 4 + k, "x": base_dom["x"] + dx, "y": base_dom["y"] + dy})
        # --- intents: usable in the copies of the states they were usable in
        for it in out["intents"].values():
            if isinstance(it.get("only_in"), list):
                it["only_in"] = it["only_in"] + [ren[s] for s in it["only_in"] if s in ren]
        # --- nodes, wires, trigger order
        for n in doc["nodes"]:
            if n["id"] not in mine:
                continue
            c = _rename(n, ren)
            c["id"] = rid(n["id"])
            c["x"], c["y"] = n["x"] + dx, n["y"] + dy
            out["nodes"].append(c)
        for lk in doc["links"]:
            if lk["from"] in mine and lk["to"] in mine:
                out["links"].append({**lk, "from": rid(lk["from"]), "to": rid(lk["to"])})
        out["order"] += [rid(i) for i in doc.get("order") or [] if i in mine]
        # --- frames (columns + sub-groups) and post-its of the dialogue columns
        fids = set()
        for f in doc["frames"]:
            if _frame_state(f["id"]) in base_states:
                fids.add(f["id"])
                c = _rename(f, ren)
                c["id"] = _frame_id(f["id"], ren)
                if f.get("parent"):
                    c["parent"] = _frame_id(f["parent"], ren)
                c["x"], c["y"] = f["x"] + dx, f["y"] + dy
                out["frames"].append(c)
        for nt in doc["notes"]:
            par, auto = nt.get("parent"), str(nt.get("auto") or "")
            if par in fids or (auto.startswith("state:") and auto[6:] in base_states):
                c = _rename(nt, ren)
                c["id"] = rid(nt["id"])
                if par:
                    c["parent"] = _frame_id(par, ren) if par in fids else par
                if auto.startswith("state:"):
                    c["auto"] = "state:" + ren[auto[6:]]
                c["x"], c["y"] = nt["x"] + dx, nt["y"] + dy
                out["notes"].append(c)
    return out
