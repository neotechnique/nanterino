"""Visual (node) form of the dialogue graph: YAML dict <-> editor document, plus persistence helpers.

logging: robotlog via nanterino.log.

Purpose
    The web editor (`web/editor.html`, built against `Notes/graph-visual-format.md`) draws the graph as
    nodes (Trigger -> Conditions -> Actions -> goto/end). This module is the only place that knows that
    format: `to_visual()` turns a raw `graph.yaml` dict into the editor document with an automatic
    layout, `from_visual()` compiles an editor document back into a raw dict and validates it with the
    real validator (`graph.parse_graph`), reporting problems with the id of the offending node.
    What the robot executes stays `graph.yaml`; the visual form is only a drawing of it.

Boundary
    - Pure functions on dicts (no Brain, no FastAPI): `server.py` wires them to the routes and to
      `Brain.request_graph_reload()`. File helpers (`save`, `reset`, `backup_file`, `dump_yaml`) take
      explicit paths so tests can use a temp directory.
    - The vocabulary (events, actions, guards ...) is never duplicated here: it is read from
      `nanterino.graph`, the single registry.
    - Layout positions live in `graph.layout.json` next to the graph file, keyed by a STRUCTURAL key
      (`<state>/t<index>/<position in chain>`, `<state>/enter/<pos>`, `global/t<i>/<pos>`, `start`),
      because node ids are regenerated on every `to_visual()`.

Wave 2 (2026-10-31): trigger `params.enabled`, state icons (layout `icons`), intent errors that name the
    intent, 30 backups with their layout copy (`backup_pair`), `list_versions()` / `restore_version()`.

Wave 3 (2026-10-31, "graphe optimisé"): `to_visual()` draws the graph lighter (shared trigger/condition tree for
    consecutive transitions with the same trigger, one End and one go-to per group, see its docstring) and lays
    it out with `nanterino.graph_layout` (layered, no overlap, default theme frames). Pure drawing: the compiled
    graph is equivalent (only no-op `fan` tags appear on shared exclusive branches). `compact=True` (default) also
    moves the state condition into `params.state` of the trigger (now the default).

Lot L6 (2026-10-31, "nœuds État"): the default drawing has ONE `state` hub node per state (chains start at it and end by
    linking into the destination hub; `reason`/`description` ride on that last link; a trigger linked from several
    states, or flagged `params.global`, is a global `only_in` rule; no link = global). Post-it `notes` are cosmetic like
    `frames` (layout file only). `to_visual(legacy=True)` keeps the go-to drawing. See Notes/graph-visual-format.md.

Invariants
    - Round trip: `from_visual(to_visual(raw))` gives a graph whose `Graph.to_dict()` equals the one of
      `raw` (same transitions in the same order, same actions, guards, on_enter, intents, descriptions).
      Known non-lossless corner: a state transition that also carries `only_in`/`not_in` comes back as a
      global transition. (A global rule limited to ONE state keeps `"global": true` on its state condition.)
    - Compilation of a chain: trigger -> conditions -> actions -> goto|end. A condition may not follow an
      action (the engine evaluates all conditions first, so the drawing would lie).
    - A condition's `false` port compiles to the SAME upstream chain with that condition negated, placed
      right after the `true` branch; this is how "otherwise" branches keep the first-match semantics.
    - Nothing is written when any error is found.
    - Several outgoing links (fan-out) / incoming links (fan-in) are legal: each trigger -> ... -> goto|end path
      is one transition; a trigger with several paths tags them with `fan: <id>` (kept in the trigger's
      `params.fan` by to_visual) so the engine runs shared leading actions once. `from_visual(..., report)` fills
      `report["warnings"]` (two state-changing branches that can match together) and `report["fans"]` (execution
      order per trigger); see Notes/graph-visual-format.md, "Branches multiples".

How to test
    python -m tests.test_graph_visual      (round trip, 68-scenario parity on the compiled graph, errors)
"""
import json
import os
import re
import shutil
import time

import yaml

from . import graph as G
from . import graph_layout as GL
from .log import log

COLW, ROWH, GROUP_GAP = 250, 120, 60            # layout grid (px): column width, band height, gap between state groups
PALETTE = ["#4f8ef7", "#2fb59a", "#e0a030", "#a06cd5", "#e07a5f", "#6c8ea4", "#7a7a7a", "#c26ba6", "#8aa83c"]
STATE_COLORS = {"veille": "#4f8ef7", "accueil": "#2fb59a", "ecoute": "#e0a030", "reponse": "#a06cd5",
                "relance": "#e07a5f", "cloture": "#6c8ea4", "eteint": "#7a7a7a"}
GLOBAL_COLOR = "#c0504d"
ICON_NAME = re.compile(r"^[a-z0-9-]{1,40}$")        # Tabler icon file name; also what the server serves
KEEP_BACKUPS = 30                                    # graph.yaml.bak-* copies kept (was 10)
BACKUP_ID = re.compile(r"^\d{8}-\d{6}(-\d+)?$")        # <stamp> of graph.yaml.bak-<stamp>
KINDS = ("start", "trigger", "condition", "action", "goto", "end", "state")
# `goto` is the legacy "go to state" terminal (still compiled); the current drawing ends chains on `state` nodes.
PORTS = {"start": ("out",), "trigger": ("out",), "condition": ("true", "false"), "action": ("out",), "state": ("out",)}
HEADER = (
    "# Graphe de dialogue de Nanterino, écrit par l'éditeur visuel (/editor).\n"
    "# L'éditeur réécrit ce fichier en entier : une copie datée est gardée à côté (graph.yaml.bak-<date>, 30 dernières).\n"
    "# Le sens des clés est expliqué dans nanterino/graph.yaml (le graphe livré avec le code).\n"
    "# Pour revenir au graphe d'origine : POST /api/graph/reset (ou le bouton de l'éditeur).\n")


# ---------------------------------------------------------------- helpers on raw YAML values
def _aslist(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _calls(v):
    """Raw action list -> [(name, args dict)]."""
    out = []
    for it in _aslist(v):
        if isinstance(it, str):
            out.append((it, {}))
        elif isinstance(it, dict) and len(it) == 1:
            name, args = next(iter(it.items()))
            out.append((name, dict(args or {})))
    return out


def _call_raw(name, args):
    return name if not args else {name: dict(args)}


def _coerce_delay(v):
    """Editors send numbers as text sometimes: '10' -> 10, '2.5' -> 2.5; a config key stays text."""
    if isinstance(v, str) and re.fullmatch(r"\s*\d+(\.\d+)?\s*", v):
        f = float(v)
        return int(f) if f == int(f) else f
    return v


def state_color(sid: str, index: int, layout: dict | None = None) -> str:
    return ((layout or {}).get("states") or {}).get(sid) or STATE_COLORS.get(sid) or PALETTE[index % len(PALETTE)]


def state_icon(sid: str, layout: dict | None = None) -> str:
    """Icon of a state: the one saved with the layout (editor choice), else the registry's."""
    icon = ((layout or {}).get("icons") or {}).get(sid)
    return icon if isinstance(icon, str) and ICON_NAME.match(icon) else G.state_icon(sid)


# ---------------------------------------------------------------- raw dict -> visual document
def _sig(kind, params):
    """Stable text signature of a node (kind + params): equal signatures = interchangeable nodes."""
    return json.dumps([kind, params], sort_keys=True, ensure_ascii=False)


def _tsig(spec):
    """Signature of the trigger node of a spec: its params plus the states it is linked from."""
    return _sig("trigger", spec["trig"]) + "@" + ",".join(spec["scope"])


def _exclusive(a, b):
    """True when two transition specs can never match the same event: opposite guards or disjoint states."""
    if any((g, not neg) in b["guards"] for g, neg in a["guards"]):
        return True
    return a["states"] is not None and b["states"] is not None and not (a["states"] & b["states"])


def _joinable(cluster, head0_sig, spec):
    """May `spec` hang under the trigger node of `cluster` (the transitions already sharing it)?

    Same trigger signature (event/after params, enabled flag, fan id) is required. Sharing a trigger makes the
    compiler tag its branches with one `fan` id, and the engine then runs a leading action common to two
    branches only once per event. So without an explicit fan id the join is allowed only when that dedupe can
    never change anything: the first action of both branches differs (or one has none), or the two can never
    match together (opposite guards / disjoint states).
    """
    if _tsig(spec) != head0_sig:
        return False
    if spec["trig"].get("fan"):
        return True
    # two bare chains (no action) with the same conditions and the same destination would need two parallel
    # wires between the same two nodes, which the editor cannot draw: keep their triggers apart
    if any(not m["acts"] and not spec["acts"] and m["to"] == spec["to"] and m["conds"] == spec["conds"] for m in cluster):
        return False
    return all(m["first"] is None or spec["first"] is None or m["first"] != spec["first"] or _exclusive(m, spec)
               for m in cluster)


def to_visual(graph_dict: dict, layout: dict | None = None, start_state: str = "veille", share: bool = True,
              compact: bool = True, share_ends: bool = True, legacy: bool = False) -> dict:
    """Editor document of a raw graph dict (as read from graph.yaml).

    Default form (2026-10-31, "nœuds État"): ONE `state` node per state (hub); a chain starts at the state node
    (state.out -> trigger.in) and its last node links straight into the destination state node (many wires may
    arrive at one state node); an optional `reason`/`description` of that last hop rides on the link. A global
    rule limited to some states (`only_in`) is a trigger linked from those states with `params.global`; a
    trigger without state link is a global rule. There is no go-to node and no state band any more.
    `legacy=True` draws the previous form (go-to nodes, `compact` / explicit state conditions, band layout):
    kept so the old drawing can still be produced and compiled (tests, migrations).

    `layout` is the content of graph.layout.json ({"nodes": {key: {"x","y"}}, "states": {id: color}, "frames": [...]});
    nodes with a saved position keep it, the others are stacked below the saved ones with the automatic layout
    (all automatic, plus default theme frames, when no layout is given).

    `share=True` (default) draws the graph lighter without changing what it compiles to:
      - consecutive transitions of one list with the same trigger share the trigger node, and the leading
        conditions they have in common (a tree; only the most recent branch is extended, so the compiler's
        depth-first order is the file order). A trigger shared by several branches is compiled with a `fan` id
        (see _joinable for when that is allowed); the description of a branch then lives on its first node
        that no other branch uses;
      - one End per state group and one "go to state" node per (group, target, reason) reached by several
        chains (fan-in), as long as each chain keeps a node of its own to carry its description.
    `share=False` is the old one-chain-per-transition drawing (kept for measurements and tests).
    `compact=True` (default) also drops the per-chain "state" condition: the trigger carries `params.state`
    instead (compiler support in from_visual, mirrored by web/editor.js computeChains); `compact=False` draws
    the explicit state-condition nodes (still compiled the same way).
    """
    layout = layout or {}
    saved = layout.get("nodes") or {}
    new = not legacy
    nodes, links, order, chains, specs = [], [], [], [], []
    link_seen = set()
    state_nid = {}            # state id -> node id of its `state` hub (new form)
    link_meta = {}            # (from, port, to) -> {"reason", "description"} carried by the hop into a state node

    def mk(kind, params, group, desc=""):
        n = {"id": "n%d" % (len(nodes) + 1), "kind": kind, "x": 0, "y": 0, "description": desc, "params": params}
        if group is not None:
            n["group"] = group  # informational (state colour in the editor); ignored by the compiler
        nodes.append(n)
        return n["id"]

    def conds_for(t, state):
        conds = [{"type": "state", "states": [state], "negate": False}] if state and not compact and not new else []
        for k, neg in (("only_in", False), ("not_in", True)):
            if new and k == "only_in" and state is None:
                continue   # a global rule limited to some states is drawn as links from those state nodes
            if t.get(k) is not None:
                c = {"type": "state", "states": list(_aslist(t[k])), "negate": neg}
                if state is None and not neg and len(c["states"]) == 1:
                    c["global"] = True  # keeps "global rule limited to one state" distinct from a state's own transition
                conds.append(c)
        for g in _aslist(t.get("when")):
            if isinstance(g, dict):
                conds.append({"type": "guard", "guard": g.get("not"), "negate": True})
            else:
                conds.append({"type": "guard", "guard": g, "negate": False})
        return conds

    def spec_of(group, key, trig, desc, conds, do, then, to, reason, guards=frozenset(), states=None, scope=()):
        acts = [(n, a, "do") for n, a in do] + [(n, a, "then") for n, a in then]
        return {"group": group, "key": key, "trig": trig, "desc": desc, "conds": conds, "acts": acts, "to": to,
                "reason": reason, "guards": guards, "states": states, "scope": list(scope),
                "first": (acts[0][2], acts[0][0], json.dumps(acts[0][1], sort_keys=True)) if acts else None}

    def transition(group, key, t, state):
        if t.get("after") is not None:
            trig = {"type": "after", "delay": t["after"], "since": t.get("since") or "state"}
        else:
            trig = {"type": "event", "event": t.get("on")}
        trig["enabled"] = t.get("enabled", True) is not False   # False: kept in the file, ignored by the engine
        scope = []
        if new:   # the state links of the trigger carry the scope (state transition, or global rule limited to some states)
            if state:
                scope = [state]
            elif t.get("only_in") is not None:
                scope = [s for s in dict.fromkeys(_aslist(t["only_in"]))]
                trig["global"] = True   # evaluated with the global rules even when a single state is linked
        elif compact and state:
            trig["state"] = state
        if t.get("fan"):
            trig["fan"] = t["fan"]   # keeps the branches of one trigger grouped across save/reload
        allowed = {state} if state else (set(_aslist(t["only_in"])) if t.get("only_in") is not None else None)
        if state and t.get("only_in") is not None:
            allowed &= set(_aslist(t["only_in"]))
        if allowed is not None and t.get("not_in") is not None:
            allowed -= set(_aslist(t["not_in"]))
        guards = frozenset(((g["not"], True) if isinstance(g, dict) else (g, False)) for g in _aslist(t.get("when")))
        specs.append(spec_of(group, key, trig, str(t.get("description") or ""), conds_for(t, state),
                             _calls(t.get("do")), _calls(t.get("then")), t.get("to"), t.get("reason"), guards, allowed, scope))

    start_id = mk("start", {"state": start_state}, None, "Démarrage")
    states_raw = graph_dict.get("states") or {}
    if new:   # one hub node per state, right after Start (Start -> initial state is display only)
        for sname in states_raw:
            state_nid[sname] = mk("state", {"state": sname}, sname)
        if start_state in state_nid:
            links.append({"from": start_id, "port": "out", "to": state_nid[start_state]})
    for sname, spec in states_raw.items():
        spec = spec or {}
        enter = _calls(spec.get("on_enter"))
        if enter:
            specs.append(spec_of(sname, sname + "/enter", {"type": "enter", "state": sname}, "", [], enter, [], None, None,
                                 scope=[sname] if new else ()))
        for i, t in enumerate(spec.get("transitions") or []):
            transition(sname, "%s/t%d" % (sname, i), t, sname)
    for i, t in enumerate(graph_dict.get("global") or []):
        transition("global", "global/t%d" % i, t, None)

    # ---- trigger / condition tree: a spec may reuse the nodes of the PREVIOUS spec of its group (see docstring)
    prev = None
    for s in specs:
        if prev is not None and prev["group"] != s["group"]:
            prev = None
        head = [("trigger", s["trig"])] + [("condition", c) for c in s["conds"]]
        shared = bool(share and prev is not None and _joinable(prev["cluster"], prev["head"][0][1], s))
        s["cluster"] = prev["cluster"] if shared else []
        s["cluster"].append(s)
        path = []
        for d, (kind, params) in enumerate(head):
            sig = _tsig(s) if d == 0 else _sig(kind, params)
            if shared and d < len(prev["head"]) and prev["head"][d][1] == sig:
                path.append(prev["head"][d])
            else:
                shared = False
                path.append((mk(kind, params, s["group"]), sig))
        s["head"] = path
        s["pre"] = [nid for nid, _sig_ in path] + [
            mk("action", {"action": n, "args": a, "phase": ph}, s["group"]) for n, a, ph in s["acts"]]
        prev = s

    # ---- terminals + descriptions: a node used by one spec only can carry that spec's description
    uses = {}
    for s in specs:
        for nid in s["pre"]:
            uses[nid] = uses.get(nid, 0) + 1
    terminals = {}
    for s in specs:
        carrier = next((nid for nid in s["pre"] if uses[nid] == 1), None)
        hub = new and bool(s["to"]) and s["to"] in state_nid
        can_share = share and (carrier is not None or not s["desc"]) and (bool(s["to"]) or share_ends)
        tkey = (s["group"], "goto", s["to"], s["reason"]) if s["to"] else (s["group"], "end")
        if hub:
            tid = state_nid[s["to"]]     # the destination is the state node itself: no go-to node to draw
        elif can_share and tkey in terminals:
            tid = terminals[tkey]
        else:
            if s["to"]:
                tid = mk("goto", dict({"state": s["to"]}, **({"reason": s["reason"]} if s["reason"] else {})), s["group"])
            else:
                tid = mk("end", {}, s["group"])
            if can_share:
                terminals[tkey] = tid
        hop = {}                          # reason / description riding on the last link (hub form)
        if hub and s["reason"]:
            hop["reason"] = s["reason"]
        if s["desc"]:
            if hub and carrier is None:
                hop["description"] = s["desc"]   # every node of the chain is shared: the hop is all that is its own
            else:
                nodes[int((carrier or tid)[1:]) - 1]["description"] = s["desc"]
        ids = s["pre"] + [tid]
        if ids[0] not in order:
            order.append(ids[0])
        for a, b in zip(ids, ids[1:]):
            lk = {"from": a, "port": "true" if nodes[int(a[1:]) - 1]["kind"] == "condition" else "out", "to": b}
            sig = (lk["from"], lk["port"], lk["to"])
            if hub and b == tid:
                lk.update(hop)
            if sig not in link_seen:
                link_seen.add(sig)
                links.append(lk)
                if hub and b == tid and hop:
                    link_meta[sig] = hop
        if new and s["scope"]:            # state -> trigger links: where the chain starts
            for st in s["scope"]:
                if st in state_nid:
                    sig = (state_nid[st], "out", ids[0])
                    if sig not in link_seen:
                        link_seen.add(sig)
                        links.append({"from": sig[0], "port": "out", "to": sig[2]})
        chains.append({"key": s["key"], "group": s["group"], "ids": ids})

    # ---- layout: saved positions per node, the rest automatic (layered, see graph_layout)
    auto = GL.hub_layout(nodes, links) if new else GL.auto_layout(nodes, links)
    pos = {nid: auto[nid] for nid in auto}
    if new and start_state in state_nid:   # Start sits just left of its state hub, on the same row
        sx, sy = auto[state_nid[start_state]]
        auto[start_id] = pos[start_id] = (sx - GL.COLW, sy)
    # An old layout file (written before the state nodes existed) has no `state/<id>` key: its node positions no
    # longer fit the new drawing, so they are ignored (frames, colours and icons of that file are still used).
    usable = not new or any(k.startswith("state/") for k in saved)
    saved_pos = {}
    for c in chains if usable else ():
        for j, nid in enumerate(c["ids"]):
            p = saved.get("%s/%d" % (c["key"], j))
            if isinstance(p, dict) and nid not in saved_pos and nid not in state_nid.values():
                saved_pos[nid] = (p.get("x", 0), p.get("y", 0))
    for sid, nid in state_nid.items():
        p = saved.get("state/" + sid) if usable else None
        if isinstance(p, dict):
            saved_pos[nid] = (p.get("x", 0), p.get("y", 0))
    if usable and (saved_pos or "start" in saved):
        max_y = max([v.get("y", 0) for v in saved.values() if isinstance(v, dict)] + [0])
        for nid in auto:
            if nid == start_id:
                continue
            pos[nid] = saved_pos.get(nid) or (auto[nid][0], auto[nid][1] + max_y + 260)
        pos[start_id] = (saved["start"]["x"], saved["start"]["y"]) if "start" in saved else auto.get(start_id, (0, 0))
    else:
        pos[start_id] = auto.get(start_id, (0, 0))
    for n in nodes:
        n["x"], n["y"] = pos[n["id"]]

    doc = {
        "version": 1, "nodes": nodes, "links": links,
        "states": [{"id": s, "description": str((spec or {}).get("description") or ""),
                    "color": state_color(s, i, layout), "icon": state_icon(s, layout)}
                   for i, (s, spec) in enumerate(states_raw.items())],
        "intents": json.loads(json.dumps(graph_dict.get("intents") or {})),
        "order": order,
    }
    if graph_dict.get("description"):
        doc["description"] = str(graph_dict["description"])
    # cosmetic frames ("groupes"): only what passes validation is shown, a hand-edited layout never breaks the GET;
    # with no layout at all the default theme frames frame the automatic layout
    if layout:
        doc["frames"] = [f for f in (layout.get("frames") or []) if isinstance(f, dict) and _frame_problem(f) is None][:MAX_FRAMES]
    else:
        doc["frames"] = GL.default_frames(nodes, pos)
    # post-it notes: cosmetic like frames (layout file only, never compiled); invalid entries are not shown
    doc["notes"] = [n for n in (layout.get("notes") or []) if isinstance(n, dict) and _note_problem(n) is None][:MAX_NOTES]
    return doc


# ---------------------------------------------------------------- cosmetic frames
MAX_FRAMES, MAX_FRAME_TITLE, MAX_FRAME_NOTE = 100, 60, 2000
# post-it notes (2026-10-31): sticky notes drawn on the canvas, stored like frames in graph.layout.json
MAX_NOTES, MAX_NOTE_TEXT, MAX_NOTE_TITLE = 200, 2000, 60
FRAME_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) < 1e7


def _frame_problem(f: dict):
    """French message for the first problem of a frame dict, or None when it is valid."""
    if not isinstance(f.get("id"), str) or not f["id"] or len(f["id"]) > 64:
        return "Identifiant de groupe invalide."
    if not isinstance(f.get("title"), str) or len(f["title"]) > MAX_FRAME_TITLE:
        return "Le titre du groupe doit être un texte de %d caractères au plus." % MAX_FRAME_TITLE
    if not isinstance(f.get("color"), str) or not FRAME_COLOR.match(f["color"]):
        return "La couleur du groupe doit être au format #rrggbb."
    if not all(_num(f.get(k)) for k in ("x", "y", "w", "h")) or f["w"] <= 0 or f["h"] <= 0:
        return "La position et la taille du groupe doivent être numériques (largeur et hauteur > 0)."
    if "note" in f and f["note"] is not None and (not isinstance(f["note"], str) or len(f["note"]) > MAX_FRAME_NOTE):
        return "La note du groupe doit être un texte de %d caractères au plus." % MAX_FRAME_NOTE
    return None


def clean_frames(frames):
    """Validate the `frames` list of a document. Returns (clean_list, errors); each error carries `frame` (id)."""
    if frames is None:
        return [], []
    if not isinstance(frames, list):
        return [], [{"node": None, "frame": None, "message": "`frames` doit être une liste."}]
    if len(frames) > MAX_FRAMES:
        return [], [{"node": None, "frame": None, "message": "Trop de groupes (%d au plus)." % MAX_FRAMES}]
    out, errors, ids = [], [], set()
    for f in frames:
        fid = f.get("id") if isinstance(f, dict) and isinstance(f.get("id"), str) else None
        msg = "Un groupe n'est pas un objet." if not isinstance(f, dict) else _frame_problem(f)
        if msg is None and f["id"] in ids:
            msg = "Identifiant de groupe en double : %s." % f["id"]
        if msg:
            errors.append({"node": None, "frame": fid, "message": msg}); continue
        ids.add(f["id"])
        c = {"id": f["id"], "title": f["title"], "color": f["color"].lower(),
             "x": f["x"], "y": f["y"], "w": f["w"], "h": f["h"]}
        if f.get("note"):
            c["note"] = f["note"]
        out.append(c)
    return out, errors


def _note_problem(n: dict):
    """French message for the first problem of a post-it dict, or None when it is valid."""
    if not isinstance(n.get("id"), str) or not n["id"] or len(n["id"]) > 64:
        return "Identifiant de post-it invalide."
    if not isinstance(n.get("text"), str) or len(n["text"]) > MAX_NOTE_TEXT:
        return "Le texte du post-it doit faire %d caractères au plus." % MAX_NOTE_TEXT
    if "title" in n and n["title"] is not None and (not isinstance(n["title"], str) or len(n["title"]) > MAX_NOTE_TITLE):
        return "Le titre du post-it doit faire %d caractères au plus." % MAX_NOTE_TITLE
    if not isinstance(n.get("color"), str) or not FRAME_COLOR.match(n["color"]):
        return "La couleur du post-it doit être au format #rrggbb."
    if not all(_num(n.get(k)) for k in ("x", "y", "w", "h")) or n["w"] <= 0 or n["h"] <= 0:
        return "La position et la taille du post-it doivent être numériques (largeur et hauteur > 0)."
    return None


def clean_notes(notes):
    """Validate the `notes` list of a document. Returns (clean_list, errors); each error carries `note` (id)."""
    if notes is None:
        return [], []
    if not isinstance(notes, list):
        return [], [{"node": None, "note": None, "message": "`notes` doit être une liste."}]
    if len(notes) > MAX_NOTES:
        return [], [{"node": None, "note": None, "message": "Trop de post-it (%d au plus)." % MAX_NOTES}]
    out, errors, ids = [], [], set()
    for n in notes:
        nid = n.get("id") if isinstance(n, dict) and isinstance(n.get("id"), str) else None
        msg = "Un post-it n'est pas un objet." if not isinstance(n, dict) else _note_problem(n)
        if msg is None and n["id"] in ids:
            msg = "Identifiant de post-it en double : %s." % n["id"]
        if msg:
            errors.append({"node": None, "note": nid, "message": msg}); continue
        ids.add(n["id"])
        c = {"id": n["id"], "text": n["text"], "color": n["color"].lower(),
             "x": n["x"], "y": n["y"], "w": n["w"], "h": n["h"]}
        if n.get("title"):
            c["title"] = n["title"]
        out.append(c)
    return out, errors


# ---------------------------------------------------------------- visual document -> raw dict
def from_visual(doc: dict, cfg: dict, report: dict | None = None):
    """Compile an editor document. Returns (raw_dict | None, layout dict, errors).

    errors = [{"node": id | None, "message": str}] (French); when non-empty nothing may be written.
    `report` (optional dict, filled in place): "warnings" = non-blocking remarks [{"node", "nodes", "kind",
    "message"}] and "fans" = {trigger id: [{"target", "nodes", "moves", "rank", "ignored"}]} for triggers with
    several outgoing paths (rank = execution order, see _fan_report).
    """
    if report is not None:
        report["warnings"], report["fans"] = [], {}
    errors, seen = [], set()

    def err(node, msg, **extra):
        if (node, msg) not in seen:
            seen.add((node, msg))
            errors.append({"node": node, "message": msg, **extra})

    if not isinstance(doc, dict) or not isinstance(doc.get("nodes"), list):
        return None, {}, [{"node": None, "message": "Document invalide : la liste `nodes` est absente."}]
    nodes = {}
    for n in doc["nodes"]:
        if not isinstance(n, dict) or not isinstance(n.get("id"), str):
            err(None, "Un nœud n'a pas d'identifiant."); continue
        if n["id"] in nodes:
            err(n["id"], "Identifiant de nœud en double : %s." % n["id"]); continue
        if n.get("kind") not in KINDS:
            err(n["id"], "Type de nœud inconnu : %r." % (n.get("kind"),)); continue
        if not isinstance(n.get("params"), dict):
            n = dict(n, params={})
        nodes[n["id"]] = n
    adj = {}
    state_out = {}             # trigger id -> [state node ids linked into it], in link order
    link_meta = {}             # (from, port, to) -> {"reason", "description"} of a hop into a state node
    for lk in doc.get("links") or []:
        a, b, port = (lk.get("from"), lk.get("to"), lk.get("port")) if isinstance(lk, dict) else (None, None, None)
        if a not in nodes or b not in nodes:
            err(a if a in nodes else (b if b in nodes else None), "Lien vers un nœud inexistant (%s -> %s)." % (a, b)); continue
        if port not in PORTS.get(nodes[a]["kind"], ()):
            err(a, "Ce nœud (%s) n'a pas de sortie « %s »." % (nodes[a]["kind"], port)); continue
        ka, kb = nodes[a]["kind"], nodes[b]["kind"]
        if kb == "start":
            err(b, "Le nœud Début ne peut pas recevoir de lien."); continue
        if ka == "start":
            if kb != "state":
                err(a, "Le nœud Début se relie seulement à un nœud État (état de démarrage, affichage)."); continue
            continue            # Start -> state is display only: the start state is fixed by the code
        if ka == "state":
            if kb != "trigger":
                err(a, "La sortie d'un nœud État se relie seulement à un déclencheur."); continue
            state_out.setdefault(b, [])
            if a not in state_out[b]:
                state_out[b].append(a)
            continue
        if kb == "trigger":
            err(b, "Un déclencheur n'accepte de lien que depuis un nœud État."); continue
        adj.setdefault((a, port), []).append(b)
        if kb == "state":      # the hop into a state node may carry the transition's reason / description
            hop = {}
            for k in ("reason", "description"):
                v = lk.get(k)
                if v is None or v == "":
                    continue
                if not isinstance(v, str) or len(v) > 500:
                    err(a, "Le champ « %s » du lien doit être un texte." % k)
                else:
                    hop[k] = v
            if hop:
                link_meta[(a, port, b)] = hop

    states_doc = doc.get("states")
    if not isinstance(states_doc, list) or not states_doc:
        return None, {}, errors + [{"node": None, "message": "Document invalide : la liste `states` est absente ou vide."}]
    state_ids = [s.get("id") for s in states_doc if isinstance(s, dict)]
    state_node_of = {}         # state id -> id of its state node
    for nid_, n_ in nodes.items():
        if n_["kind"] != "state":
            continue
        sid_ = n_["params"].get("state")
        if sid_ not in state_ids:
            err(nid_, "État inconnu : %r." % (sid_,))
        elif sid_ in state_node_of:
            err(nid_, "Il y a déjà un nœud pour l'état %s : un seul nœud État par état." % sid_)
        else:
            state_node_of[sid_] = nid_
    intent_names = set(doc.get("intents") or {}) | {"question"}

    # evaluation order of triggers: `order`, then the rest by (y, x)
    trig_ids = [i for i, n in nodes.items() if n["kind"] == "trigger"]
    ordered = [i for i in (doc.get("order") or []) if i in nodes and nodes[i]["kind"] == "trigger"]
    ordered = list(dict.fromkeys(ordered))
    ordered += sorted((i for i in trig_ids if i not in ordered), key=lambda i: (nodes[i].get("y", 0), nodes[i].get("x", 0)))

    reached = set(i for i in nodes if nodes[i]["kind"] in ("start", "trigger", "state"))
    states_raw = {s["id"]: {"description": str(s.get("description") or "")} for s in states_doc if isinstance(s, dict)}
    on_enter, transitions, globals_, where_map, node_pos = {}, {}, [], {}, {}
    fan_groups = {}

    def paths(tid):
        """All trigger -> terminal paths as [(node id, negated by false port)], true branch first."""
        out = []

        def rec(nid, chain):
            if nid in {c[0] for c in chain}:
                err(nid, "Boucle dans la chaîne : ce nœud revient sur lui-même."); return
            reached.add(nid)
            k = nodes[nid]["kind"]
            if k in ("goto", "end", "state"):   # terminals; a state node ends the path (its own outputs start OTHER chains)
                out.append(chain + [(nid, False)]); return
            if k == "condition":
                linked = False
                for port, inv in (("true", False), ("false", True)):
                    for t in adj.get((nid, port), []):
                        linked = True
                        rec(t, chain + [(nid, inv)])
                if not linked:
                    err(nid, "La condition n'a aucune suite : relier au moins une de ses sorties.")
                return
            targets = adj.get((nid, "out"), [])
            if not targets:
                err(nid, "Chaîne sans cible : ce nœud n'est relié ni à un changement d'état (goto) ni à une fin.")
            for t in targets:
                rec(t, chain + [(nid, False)])
        rec(tid, [])
        return out

    for tid in ordered:
        trig = nodes[tid]
        p = trig["params"]
        kind = p.get("type")
        n_err = len(errors)
        if kind == "event":
            ev = p.get("event")
            if not ((ev in G.EVENTS and ev != "tick") or (isinstance(ev, str) and ev.startswith("intent.") and ev[7:] in intent_names)):
                err(tid, "Événement inconnu : %r." % (ev,))
        elif kind == "after":
            if p.get("since", "state") not in G.SINCE:
                err(tid, "« depuis » doit être l'un de : %s." % ", ".join(G.SINCE))
        elif kind == "enter":
            if p.get("state") not in state_ids:
                err(tid, "État inconnu : %r." % (p.get("state"),))
            if p.get("enabled") is False:
                err(tid, "Un déclencheur « entrée dans l'état » ne peut pas être désactivé.")
        else:
            err(tid, "Type de déclencheur inconnu : %r (event, after ou enter)." % (kind,))
        if p.get("enabled") not in (None, True, False):
            err(tid, "« enabled » doit être vrai ou faux.")
        if len(errors) > n_err:
            paths(tid)  # still walk it so its nodes count as reached
            continue
        plist = paths(tid)
        # states this trigger is linked from (hub form); the legacy `params.state` scope adds to them
        links_from = [nodes[s]["params"].get("state") for s in state_out.get(tid, []) if nodes[s]["params"].get("state") in state_ids]
        if kind == "enter" and links_from and links_from != [p.get("state")]:
            err(tid, "Un déclencheur « entrée dans l'état » ne se relie qu'au nœud de son propre état (%s)." % (p.get("state"),))
            continue
        scope = list(dict.fromkeys(links_from + ([p["state"]] if p.get("state") is not None else [])))
        fan_id = (p.get("fan") if isinstance(p.get("fan"), str) and p.get("fan").strip() else None) or ("fan-" + tid if len(plist) > 1 else None)
        # branches of triggers sharing a fan id (one editor trigger, or its copies after a reload) are analysed together
        grp = fan_groups.setdefault(fan_id or tid, {"tids": [], "emitted": []})
        if tid not in grp["tids"]:
            grp["tids"].append(tid)
        emitted = grp["emitted"] if p.get("enabled") is not False else []
        for path in plist:
            ids = [x[0] for x in path]
            mid, term = path[1:-1], nodes[path[-1][0]]
            pos_sets, neg_sets, when, do, then = [], [], [], [], []
            force_global = False
            n_err = len(errors)
            seen_action = False
            hop = {}
            if kind in ("event", "after") and scope:
                # the states the trigger is linked from (and the legacy `params.state`) act as a non-negated state
                # condition; several states, or `params.global`, make it a global rule limited to them (only_in)
                if p.get("state") is not None and p["state"] not in state_ids:
                    err(tid, "État inconnu : %r." % (p["state"],))
                else:
                    pos_sets.append(list(scope))
                    force_global = bool(p.get("global")) or len(scope) > 1
            for nid, inv in mid:
                n = nodes[nid]
                q = n["params"]
                if n["kind"] == "condition":
                    if seen_action:
                        err(nid, "Une condition ne peut pas venir après une action (les conditions sont évaluées d'abord).")
                    neg = bool(q.get("negate")) != inv
                    if q.get("type") == "state":
                        sts = [s for s in _aslist(q.get("states"))]
                        if not sts:
                            err(nid, "Choisir au moins un état.")
                        for s in sts:
                            if s not in state_ids:
                                err(nid, "État inconnu : %r." % (s,))
                        (neg_sets if neg else pos_sets).append(sts)
                        force_global = force_global or (not neg and bool(q.get("global")))
                    elif q.get("type") == "guard":
                        if q.get("guard") not in G.GUARDS:
                            err(nid, "Condition inconnue : %r." % (q.get("guard"),))
                        when.append({"not": q.get("guard")} if neg else q.get("guard"))
                    else:
                        err(nid, "Type de condition inconnu : %r (state ou guard)." % (q.get("type"),))
                elif n["kind"] == "action":
                    seen_action = True
                    name, args = q.get("action"), q.get("args") or {}
                    if name not in G.ACTION_SPECS:
                        err(nid, "Action inconnue : %r." % (name,)); continue
                    if not isinstance(args, dict):
                        err(nid, "Les arguments de l'action doivent être un objet."); continue
                    if q.get("phase", "do") not in ("do", "then"):
                        err(nid, "La phase d'une action est « do » ou « then »."); continue
                    args = {k: (_coerce_delay(v) if G.ACTION_SPECS[name].get(k) == "delay" else v) for k, v in args.items()}
                    (then if q.get("phase") == "then" else do).append(_call_raw(name, args))
                else:
                    err(nid, "Nœud inattendu au milieu d'une chaîne.")
            to = reason = None
            if term["kind"] == "goto":
                to = term["params"].get("state")
                if to not in state_ids:
                    err(term["id"], "État de destination inconnu : %r." % (to,))
                reason = term["params"].get("reason") or None
            elif term["kind"] == "state":     # hub form: the destination state node ends the chain
                to = term["params"].get("state")
                pid, pinv = path[-2]
                port = ("false" if pinv else "true") if nodes[pid]["kind"] == "condition" else "out"
                hop = link_meta.get((pid, port, term["id"]), {})
                reason = hop.get("reason") or None
            if kind == "enter":
                for nid, _inv in mid:
                    if nodes[nid]["kind"] == "condition":
                        err(nid, "Un déclencheur « entrée dans l'état » n'accepte pas de condition.")
                if term["kind"] in ("goto", "state"):
                    err(term["id"], "Une entrée dans l'état ne peut pas changer d'état : terminer par une fin.")
                if then:
                    err(tid, "Une entrée dans l'état n'a pas de phase « then ».")
            if len(errors) > n_err:
                continue
            # a state node's own text is not the chain's description; the hop into it may carry one
            desc_ids = ids[:-1] if term["kind"] == "state" else ids
            desc = (trig.get("description") or next((nodes[i].get("description") for i in desc_ids if nodes[i].get("description")), "")
                    or hop.get("description") or "")
            if kind == "enter":
                st = p["state"]
                if st in on_enter:
                    err(tid, "L'état %s a déjà un déclencheur d'entrée." % st); continue
                on_enter[st] = do
                where_map["state %s on_enter" % st] = tid
                key = st + "/enter"
            else:
                t = {}
                if kind == "after":
                    t["after"] = _coerce_delay(p.get("delay"))
                    t["since"] = p.get("since") or "state"
                else:
                    t["on"] = p["event"]
                if p.get("enabled") is False:
                    t["enabled"] = False
                if fan_id and kind != "enter":
                    t["fan"] = fan_id   # branches of one trigger: the engine runs their shared leading actions once
                single = len(pos_sets) == 1 and len(pos_sets[0]) == 1 and not neg_sets and not force_global
                if single:
                    container, label = transitions.setdefault(pos_sets[0][0], []), "state %s transition" % pos_sets[0][0]
                    key = "%s/t%d" % (pos_sets[0][0], len(container))
                else:
                    if kind == "after":
                        err(tid, "Un délai doit être rattaché à un seul état (une condition « état » non niée, avec un seul état).")
                        continue
                    container, label = globals_, "global transition"
                    key = "global/t%d" % len(container)
                    if pos_sets:
                        inter = [s for s in pos_sets[0] if all(s in o for o in pos_sets[1:])]
                        if not inter:
                            err(tid, "Les conditions d'état se contredisent (aucun état possible)."); continue
                        t["only_in"] = inter
                    if neg_sets:
                        t["not_in"] = list(dict.fromkeys(s for ss in neg_sets for s in ss))
                if when:
                    t["when"] = when
                if do:
                    t["do"] = do
                if to:
                    t["to"] = to
                    if reason:
                        t["reason"] = reason
                if then:
                    t["then"] = then
                t["description"] = desc
                container.append(t)
                where_map["%s #%d" % (label, len(container))] = tid
                if report is not None:
                    allowed = set(state_ids)
                    if pos_sets:
                        allowed = set.intersection(*[set(x) for x in pos_sets])
                    for x in neg_sets:
                        allowed -= set(x)
                    emitted.append({"target": term["id"], "nodes": ids, "moves": bool(to), "global": container is globals_,
                                    "states": allowed, "guards": {(g["not"], True) if isinstance(g, dict) else (g, False) for g in when}})
            # layout: every path records the position of each of its nodes (shared nodes repeat the same value)
            for j, nid in enumerate(ids):
                if nodes[nid]["kind"] != "state":   # state nodes are saved once, under `state/<id>`
                    node_pos["%s/%d" % (key, j)] = {"x": nodes[nid].get("x", 0), "y": nodes[nid].get("y", 0)}

    if report is not None:
        for grp in fan_groups.values():
            if len(grp["emitted"]) > 1:
                _fan_report(grp["tids"], grp["emitted"], report)

    for nid, n in nodes.items():
        if nid not in reached:
            err(nid, "Nœud non relié à un déclencheur : il serait perdu à l'enregistrement.")

    raw = {"version": 1}
    if doc.get("description"):
        raw["description"] = str(doc["description"])
    raw["states"] = {}
    for s in states_doc:
        sid = s.get("id") if isinstance(s, dict) else None
        if sid is None:
            continue
        spec = states_raw[sid]
        if on_enter.get(sid):
            spec["on_enter"] = on_enter[sid]
        if transitions.get(sid):
            spec["transitions"] = transitions[sid]
        raw["states"][sid] = spec
    if globals_:
        raw["global"] = globals_
    if doc.get("intents"):
        raw["intents"] = json.loads(json.dumps(doc["intents"]))

    if not errors:
        try:
            G.parse_graph(raw, cfg, "<visual>")
        except G.GraphError as e:
            items = e.items or [("", str(e))]
            for where, msg in items:
                nid = next((v for k, v in where_map.items() if where == k or where.startswith(k + " ")), None)
                if where.startswith("intent "):   # the editor shows intent problems next to the intent, not a node
                    err(None, "%s : %s" % (where, msg), intent=where[7:])
                else:
                    err(nid, "%s : %s" % (where, msg) if where else msg)

    layout = {"nodes": node_pos, "states": {s["id"]: s["color"] for s in states_doc if isinstance(s, dict) and s.get("color")}}
    icons = {s["id"]: s["icon"] for s in states_doc
             if isinstance(s, dict) and isinstance(s.get("icon"), str) and ICON_NAME.match(s["icon"])
             and s["icon"] != G.state_icon(s["id"])}
    if icons:   # only the icons the user changed; the registry supplies the rest
        layout["icons"] = icons
    for nid, n in nodes.items():
        if n["kind"] == "start":
            layout["nodes"]["start"] = {"x": n.get("x", 0), "y": n.get("y", 0)}
    for sid_, nid_ in state_node_of.items():
        layout["nodes"]["state/" + sid_] = {"x": nodes[nid_].get("x", 0), "y": nodes[nid_].get("y", 0)}
    frames, ferrors = clean_frames(doc.get("frames"))
    errors.extend(ferrors)
    if frames:   # purely cosmetic: lives in the layout file only, never compiled into graph.yaml
        layout["frames"] = frames
    notes, nerrors = clean_notes(doc.get("notes"))
    errors.extend(nerrors)
    if notes:    # post-it notes: same story as frames (layout only, never compiled)
        layout["notes"] = notes
    return (None if errors else raw), layout, errors


def _fan_report(tids: list, emitted: list, report: dict):
    """Execution order + conflict warning of a trigger with several outgoing branches.

    Engine rule (graph.GraphEngine._run_matches): every matching branch that does not change the state runs,
    in evaluation order (global transitions first, then the current state's, in file order); then the FIRST
    matching branch that changes the state (goto). rank = that order, movers after the non-movers. Two moving
    branches are only a conflict when they can match together: their state sets overlap and no guard is
    required true by one and false by the other.
    """
    ordered = sorted(enumerate(emitted), key=lambda ie: (0 if ie[1]["global"] else 1, ie[0]))
    seq = [e for _i, e in ordered if not e["moves"]] + [e for _i, e in ordered if e["moves"]]
    movers = [e for e in seq if e["moves"]]
    overlap = [m for k, m in enumerate(movers) if k > 0 and any(
        (m["states"] & w["states"]) and not any((g, not n) in w["guards"] for g, n in m["guards"]) for w in movers[:k])]
    for rank, e in enumerate(seq, 1):
        e["rank"], e["ignored"] = rank, any(e is m for m in overlap)
    branches = [{"target": e["target"], "nodes": e["nodes"], "moves": e["moves"], "rank": e["rank"],
                 "ignored": e["ignored"]} for e in emitted]
    for tid in tids:
        report["fans"][tid] = branches
    if overlap:
        ids = [m["target"] for m in movers]
        report["warnings"].append({
            "node": tids[0], "nodes": ids, "triggers": list(tids), "kind": "fan_conflict",
            "message": "Plusieurs branches de ce déclencheur changent d'état : seule la première (ordre : %s) s'appliquera."
                       % " puis ".join(ids)})


# ---------------------------------------------------------------- YAML text
class _Flow(list):
    pass


class _FlowMap(dict):
    pass


class _Dumper(yaml.SafeDumper):
    """Block mappings, indented sequences, short lists/actions in flow style, no aliases."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)

    def ignore_aliases(self, data):
        return True


_Dumper.add_representer(_Flow, lambda d, v: d.represent_sequence("tag:yaml.org,2002:seq", list(v), flow_style=True))
_Dumper.add_representer(_FlowMap, lambda d, v: d.represent_mapping("tag:yaml.org,2002:map", dict(v), flow_style=True))


def _flow(v):
    if isinstance(v, list):
        return _Flow(_flow(x) for x in v)
    if isinstance(v, dict):
        return _FlowMap((k, _flow(x)) for k, x in v.items())
    return v


def dump_yaml(raw: dict) -> str:
    """graph.yaml text: French header, descriptions kept as fields, `do`/`then`/`when` lists inline."""
    out = {}
    for k, v in raw.items():
        if k == "states":
            out[k] = {}
            for sn, spec in v.items():
                s = {"description": spec["description"]}
                if spec.get("on_enter"):
                    s["on_enter"] = _flow(spec["on_enter"])
                if spec.get("transitions"):
                    s["transitions"] = [_tr(t) for t in spec["transitions"]]
                out[k][sn] = s
        elif k == "global":
            out[k] = [_tr(t) for t in v]
        elif k == "intents":
            out[k] = {n: {kk: (_flow(vv) if isinstance(vv, list) else vv) for kk, vv in spec.items()} for n, spec in v.items()}
        else:
            out[k] = v
    body = yaml.dump(out, Dumper=_Dumper, sort_keys=False, allow_unicode=True, default_flow_style=False, width=10 ** 6)
    return HEADER + body


def _tr(t: dict) -> dict:
    order = ("on", "after", "since", "enabled", "fan", "when", "only_in", "not_in", "do", "to", "reason", "then", "description")
    return {k: (_flow(t[k]) if isinstance(t[k], list) else t[k]) for k in order if k in t}


# ---------------------------------------------------------------- files
def layout_path_for(graph_path: str) -> str:
    return os.path.join(os.path.dirname(graph_path), "graph.layout.json")


def load_raw(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.load(f, Loader=G._Loader) or {}


def load_layout(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def backup_file(path: str, keep: int = KEEP_BACKUPS):
    """Copy `path` to `path.bak-<timestamp>` (if it exists) and keep only the `keep` newest copies."""
    d, base = os.path.dirname(path), os.path.basename(path)
    made = None
    if os.path.exists(path):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        made, n = "%s.bak-%s" % (path, stamp), 0
        while os.path.exists(made):
            n += 1
            made = "%s.bak-%s-%d" % (path, stamp, n)
        shutil.copy2(path, made)
    baks = sorted((f for f in os.listdir(d) if f.startswith(base + ".bak-")),
                  key=lambda f: os.path.getmtime(os.path.join(d, f)))
    for old in baks[:-keep]:
        try:
            os.remove(os.path.join(d, old))
        except OSError:
            pass
    return made


def backup_pair(graph_path: str, layout_path: str):
    """Back up graph.yaml AND graph.layout.json under the same stamp; returns the graph backup path or None.

    The layout copy lets a restore bring the nodes back where they were; layout copies whose graph copy was
    pruned are removed too.
    """
    made = backup_file(graph_path)
    if made:
        suffix = made.rsplit(".bak-", 1)[1]
        if os.path.exists(layout_path):
            shutil.copy2(layout_path, "%s.bak-%s" % (layout_path, suffix))
        gbase = os.path.basename(graph_path)
        live = {f[len(gbase) + 5:] for f in os.listdir(os.path.dirname(graph_path)) if f.startswith(gbase + ".bak-")}
        d, base = os.path.dirname(layout_path), os.path.basename(layout_path)
        for f in os.listdir(d):
            if f.startswith(base + ".bak-") and f[len(base) + 5:] not in live:
                try:
                    os.remove(os.path.join(d, f))
                except OSError:
                    pass
    return made


def _summary(raw: dict) -> dict:
    states = raw.get("states") or {}
    trs = list(raw.get("global") or []) + [t for s in states.values() for t in ((s or {}).get("transitions") or [])]
    return {"states": len(states), "chains": len(trs),
            "disabled": sum(1 for t in trs if isinstance(t, dict) and t.get("enabled") is False)}


def list_versions(graph_path: str) -> list:
    """Backups of the graph file, newest first: [{id, date, size, summary}]."""
    d, base = os.path.dirname(graph_path), os.path.basename(graph_path)
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for f in names:
        vid = f[len(base) + 5:] if f.startswith(base + ".bak-") else None
        if not vid or not BACKUP_ID.match(vid):
            continue
        p = os.path.join(d, f)
        try:
            summary = _summary(load_raw(p))
        except Exception as e:  # unreadable backup: still listed so the user can see it
            summary = {"error": str(e)[:120]}
        stamp = vid[:15]
        date = "%s-%s-%sT%s:%s:%s" % (stamp[:4], stamp[4:6], stamp[6:8], stamp[9:11], stamp[11:13], stamp[13:15])
        out.append({"id": vid, "date": date, "size": os.path.getsize(p), "summary": summary})
    out.sort(key=lambda v: (v["id"][:15], int(v["id"][16:] or 0) if len(v["id"]) > 16 else 0), reverse=True)
    return out


def restore_version(vid: str, cfg: dict, graph_path: str, layout_path: str):
    """Make backup `vid` the active graph. Returns (ok, http_status, message).

    The id is matched against a strict pattern first (it becomes a file name). The backup must still
    validate against the current vocabulary/config; the CURRENT graph is backed up before it is replaced.
    """
    if not isinstance(vid, str) or not BACKUP_ID.match(vid):
        return False, 404, "Version inconnue."
    src = "%s.bak-%s" % (graph_path, vid)
    if not os.path.exists(src):
        return False, 404, "Version inconnue."
    try:
        with open(src, encoding="utf-8") as f:
            text = f.read()
        G.parse_graph(yaml.load(text, Loader=G._Loader), cfg, src)
    except (OSError, yaml.YAMLError, G.GraphError) as e:
        return False, 400, "Cette sauvegarde n'est plus valide : %s" % str(e)[:300]
    lsrc = "%s.bak-%s" % (layout_path, vid)
    ltext = None
    if os.path.exists(lsrc):
        with open(lsrc, encoding="utf-8") as f:
            ltext = f.read()
    backup_pair(graph_path, layout_path)
    _atomic_write(graph_path, text)
    if ltext is not None:
        _atomic_write(layout_path, ltext)
    log.info("graph restored from backup %s", vid)
    return True, 200, "Version restaurée."


def _atomic_write(path: str, text: str):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def save(doc: dict, cfg: dict, graph_path: str, layout_path: str, report: dict | None = None):
    """Compile + validate + back up + write graph and layout. Returns (True, None) or (False, errors)."""
    raw, layout, errors = from_visual(doc, cfg, report)
    if errors:
        log.info("graph save refused: %d error(s)", len(errors))
        return False, errors
    text = dump_yaml(raw)
    try:  # what lands on disk must itself load and validate
        G.parse_graph(yaml.load(text, Loader=G._Loader), cfg, graph_path)
    except (G.GraphError, yaml.YAMLError) as e:
        log.error("graph save: produced file invalid: %s", e)
        return False, [{"node": None, "message": "Le fichier produit est invalide : %s" % e}]
    made = backup_pair(graph_path, layout_path)
    _atomic_write(graph_path, text)
    _atomic_write(layout_path, json.dumps(layout, ensure_ascii=False, indent=1))
    log.info("graph saved from the visual editor (backup=%s)", os.path.basename(made) if made else None)
    return True, None


def reset(graph_path: str, layout_path: str):
    """Back up the override and remove it (and its layout): the packaged default graph runs again."""
    made = backup_pair(graph_path, layout_path)
    for p in (graph_path, layout_path):
        try:
            os.remove(p)
        except OSError:
            pass
    log.info("graph reset to the packaged default (backup=%s)", os.path.basename(made) if made else None)
    return made
