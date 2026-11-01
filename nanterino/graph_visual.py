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
      (`<state>/t<index>/<position in chain>`, `<state>/enter/<pos>`, `global/t<i>/<pos>`, `start` for the hub / go-to forms only),
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

Lot L1 (2026-10-31, "variables et triggers sans entrée"): the default drawing (`form="vars"`) has NO `state` / `goto`
    node. The state is the system variable `etat`: a state transition is Trigger -> Condition var_compare(etat = X) ->
    ... ; a global `only_in` rule gets var_compare(etat in [..], `global: true`); a move is the action
    set_var(etat, Y) (+ `params.reason`); on_enter X is the trigger var_changed(etat, X). A trigger has no input (a link
    into a trigger is an error, except from a legacy state node); an action whose output is unlinked ends its chain
    (implicit End, so chains carry no End node unless they have no action). A condition etat in [A, B] without
    `global` compiles to one transition per state sharing a `fan` id. `form="hub"` / `legacy=True` still draw the L6
    hub / go-to forms and every old document still compiles (migration). The layout is one column per state + one
    for the global rules (`graph_layout.var_layout`); graph.layout.json written by this form carries "form": "vars",
    older files only lend their user frames, colours, icons and post-its. `variables` rides on the document like
    `intents`. See Notes/graph-visual-format.md, "Variables et triggers sans entrée".

Lot L3 (2026-10-31, "si / sinon"): in the shared trigger/condition tree, a transition whose next condition is the
    NEGATION of the condition the previous transition of the same tree left by its `true` port (same trigger, same
    leading conditions, adjacent in the file) reuses that condition node through its `false` port instead of drawing
    a negated twin. from_visual walks `true` before `false`, so it recompiles the same transitions in the same order
    (`{not: g}` comes from the false port). Only a true -> false step merges (never back to `true`). Leading actions
    common to both branches stay duplicated: a condition may not follow an action (the engine evaluates guards first).

Lot L4 (2026-11-01, "sans nœud Début"): the variables drawing emits NO `start` node and no `start` layout key (triggers
    start their chains; the start state is fixed by the code). from_visual still accepts a legacy `start` node silently
    (display only, ignored); the hub / go-to drawings keep theirs for migration tests.

Lot L11 (2026-11-01, "variables v2"): the `variables` block rides on the document unchanged, so the new keys (min / max /
    step / scope / persist, list kind / mode / max, dictionary items) round-trip as data. A `timer_reached` trigger carries
    `name` (timer) + `value` (seconds) like var_changed; dictionary values are coerced with the dictionary's type; the
    validator's non-blocking diagnostics (`out_of_bounds`) are added to report["warnings"] with the node they are about.

Lot L13 (2026-11-01, "sous-groupes par défaut"): a layout the server draws (same cases as the L9 column post-its) also
    groups the chains of each column into titled sub-groups (graph_layout rule table, keyed by the trigger): one frame
    per sub-group (`parent` = its column, marker `gen: "sub:<col>:<key>"`, NOT `auto`, which the editor reserves for
    columns) and one post-it inside it (`auto: "sub:<col>:<key>"`, see sub_notes). Never re-seeded once a vars layout is
    saved, so user edits / deletions stay. Layout only: the compiled YAML is unchanged.

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
# `goto` (go-to terminal) and `state` (L6 hub) are import-only since lot L1: the drawing ends chains on an action.
END0 = "\x00end"   # pseudo node id of the implicit End after an action with no outgoing link (never in a document)
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


def _gkey(g):
    """Hashable (guard, negated) key of a raw `when:` item; a guard with arguments is keyed by its JSON text."""
    neg = isinstance(g, dict) and set(g) == {"not"}
    core = g["not"] if neg else g
    return (core if isinstance(core, str) else json.dumps(core, sort_keys=True, ensure_ascii=False), neg)


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
              compact: bool = True, share_ends: bool = True, legacy: bool = False, form: str = "vars") -> dict:
    """Editor document of a raw graph dict (as read from graph.yaml).

    `form` (lot L1): "vars" (default, no state/goto node, see the module docstring), "hub" (L6 state nodes, described
    just below) or "goto" (same as `legacy=True`).

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
    form = "goto" if legacy else form
    if form not in ("vars", "hub", "goto"):
        raise ValueError("to_visual: unknown form %r" % (form,))
    legacy = form == "goto"
    new = form == "hub"           # L6 state-node (hub) drawing
    vform = form == "vars"        # lot L1 drawing: etat conditions / set_var(etat) / var_changed(etat)
    seed_frames = []              # lot L9: column frames drawn by this call (default post-its go into them)
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

    def etat_cond(op, value, glob=False):
        c = {"type": "guard", "guard": "var_compare", "args": {"name": "etat", "op": op, "value": value}, "negate": False}
        if glob:
            c["global"] = True   # a global rule limited to these states (keeps the global evaluation order)
        return c

    def guard_cond(g):
        neg = isinstance(g, dict) and set(g) == {"not"}
        core = g["not"] if neg else g
        c = {"type": "guard", "guard": core, "negate": neg}
        if isinstance(core, dict):     # guard with arguments: {var_compare: {...}}
            (c["guard"], args), = core.items()
            c["args"] = dict(args or {})
        return c

    def conds_for(t, state):
        if vform:
            conds = [etat_cond("=", state)] if state else []
            if t.get("only_in") is not None:
                conds.append(etat_cond("in", list(_aslist(t["only_in"])), glob=state is None))
            if t.get("not_in") is not None:
                conds.append(etat_cond("not_in", list(_aslist(t["not_in"]))))
            return conds + [guard_cond(g) for g in _aslist(t.get("when"))]
        conds = [{"type": "state", "states": [state], "negate": False}] if state and not compact and not new else []
        for k, neg in (("only_in", False), ("not_in", True)):
            if new and k == "only_in" and state is None:
                continue   # a global rule limited to some states is drawn as links from those state nodes
            if t.get(k) is not None:
                c = {"type": "state", "states": list(_aslist(t[k])), "negate": neg}
                if state is None and not neg and len(c["states"]) == 1:
                    c["global"] = True  # keeps "global rule limited to one state" distinct from a state's own transition
                conds.append(c)
        return conds + [guard_cond(g) for g in _aslist(t.get("when"))]

    def spec_of(group, key, trig, desc, conds, do, then, to, reason, guards=frozenset(), states=None, scope=()):
        acts = [(n, a, "do") for n, a in do] + [(n, a, "then") for n, a in then]
        if vform and to:   # the move is an action node between the `do` and the `then` actions
            acts.insert(len(do), ("set_var", {"name": "etat", "value": to}, "do", reason))
        return {"group": group, "key": key, "trig": trig, "desc": desc, "conds": conds, "acts": acts, "to": to,
                "reason": reason, "guards": guards, "states": states, "scope": list(scope),
                "first": (acts[0][2], acts[0][0], json.dumps(acts[0][1], sort_keys=True)) if acts else None}

    def transition(group, key, t, state):
        if t.get("after") is not None:
            trig = {"type": "after", "delay": t["after"], "since": t.get("since") or "state"}
        else:
            trig = {"type": "event", "event": t.get("on")}
            if t.get("on") in G.WATCH_EVENTS:   # lot L1 / L11: the watched variable (and value / seconds) ride on the trigger
                trig["name"] = t.get("var")
                if "value" in t:
                    trig["value"] = t["value"]
        trig["enabled"] = t.get("enabled", True) is not False   # False: kept in the file, ignored by the engine
        scope = []
        if new:   # the state links of the trigger carry the scope (state transition, or global rule limited to some states)
            if state:
                scope = [state]
            elif t.get("only_in") is not None:
                scope = [s for s in dict.fromkeys(_aslist(t["only_in"]))]
                trig["global"] = True   # evaluated with the global rules even when a single state is linked
        elif compact and state and not vform:
            trig["state"] = state
        if t.get("fan"):
            trig["fan"] = t["fan"]   # keeps the branches of one trigger grouped across save/reload
        allowed = {state} if state else (set(_aslist(t["only_in"])) if t.get("only_in") is not None else None)
        if state and t.get("only_in") is not None:
            allowed &= set(_aslist(t["only_in"]))
        if allowed is not None and t.get("not_in") is not None:
            allowed -= set(_aslist(t["not_in"]))
        guards = frozenset(_gkey(g) for g in _aslist(t.get("when")))
        specs.append(spec_of(group, key, trig, str(t.get("description") or ""), conds_for(t, state),
                             _calls(t.get("do")), _calls(t.get("then")), t.get("to"), t.get("reason"), guards, allowed, scope))

    # Lot L4 (2026-11-01): the variables drawing has NO Start node (a trigger starts its own chain; the start state is
    # fixed by the code). The hub / go-to drawings keep it so old documents are still produced as they were.
    start_id = None if vform else mk("start", {"state": start_state}, None, "Démarrage")
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
            trig = ({"type": "event", "event": "var_changed", "name": "etat", "value": sname, "enabled": True} if vform   # "etat becomes X"
                    else {"type": "enter", "state": sname})
            specs.append(spec_of(sname, sname + "/enter", trig, "", [], enter, [], None, None,
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
        # head entries are (node id, signature AS SEEN BY THIS SPEC, port this spec leaves the node by)
        path = []
        for d, (kind, params) in enumerate(head):
            sig = _tsig(s) if d == 0 else _sig(kind, params)
            port = "true" if kind == "condition" else "out"
            p_ent = prev["head"][d] if shared and d < len(prev["head"]) else None
            if p_ent is not None and p_ent[1] == sig:
                path.append(p_ent)
            elif (p_ent is not None and kind == "condition" and p_ent[2] == "true"
                  and p_ent[1] == _sig("condition", dict(params, negate=not params.get("negate")))):
                # lot L3 (if/else): this spec's condition is the negation of the one the previous spec left by its
                # `true` port, after the same trigger and leading conditions. Draw it as the `false` output of that
                # node. from_visual walks the true port before the false one, so the compiled order (previous spec,
                # then this one) and the guards (`{not: g}` from the false port) are exactly the file's. Only a
                # true -> false step is allowed: going back to `true` after `false` would reorder the transitions.
                path.append((p_ent[0], sig, "false"))
                shared = False
            else:
                shared = False
                path.append((mk(kind, params, s["group"]), sig, port))
        s["head"] = path
        s["ports"] = {nid: prt for nid, _sig_, prt in path}
        s["pre"] = [nid for nid, _sig_, _prt in path] + [
            mk("action", dict({"action": n, "args": a, "phase": ph[0]}, **({"reason": ph[1]} if len(ph) > 1 and ph[1] else {})),
               s["group"]) for n, a, *ph in s["acts"]]
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
        if vform:
            tkey = (s["group"], "end")
        if hub:
            tid = state_nid[s["to"]]     # the destination is the state node itself: no go-to node to draw
        elif vform and s["acts"]:
            tid = None                   # lot L1: the last action ends the chain (implicit End), no terminal node
        elif can_share and tkey in terminals:
            tid = terminals[tkey]
        else:
            if s["to"] and not vform:
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
        ids = s["pre"] + ([tid] if tid else [])
        if ids[0] not in order:
            order.append(ids[0])
        for a, b in zip(ids, ids[1:]):
            # a condition is left by `true`, or by `false` for the else-branch of an if/else pair (lot L3)
            lk = {"from": a, "port": s["ports"].get(a) or ("true" if nodes[int(a[1:]) - 1]["kind"] == "condition" else "out"), "to": b}
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
    # lot L9: the variables drawing reserves room at the top of each column for its default post-it (see column_notes)
    seed_text = column_note_texts(states_raw) if vform else {}
    subs = []                     # lot L13: sub-group rectangles of the default variables drawing (see var_frames)
    auto = GL.hub_layout(nodes, links) if new else (
        GL.var_layout(nodes, links, head={g: column_note_height(t) for g, t in seed_text.items()},
                      note_h=column_note_height, subs_out=subs) if vform else GL.auto_layout(nodes, links))
    pos = {nid: auto[nid] for nid in auto}
    if new and start_state in state_nid:   # Start sits just left of its state hub, on the same row
        sx, sy = auto[state_nid[start_state]]
        auto[start_id] = pos[start_id] = (sx - GL.COLW, sy)
    # An old layout file (written before the state nodes existed) has no `state/<id>` key: its node positions no
    # longer fit the new drawing, so they are ignored (frames, colours and icons of that file are still used).
    # Lot L1: only a layout written by the variables form ("form": "vars") lends positions to it.
    usable = (layout.get("form") == "vars") if vform else (not new or any(k.startswith("state/") for k in saved))
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
    if usable and (saved_pos or (start_id and "start" in saved)):
        # a legacy `start` key of a vars layout is ignored (lot L4: no Start node to place)
        max_y = max([v.get("y", 0) for k, v in saved.items() if isinstance(v, dict) and (start_id or k != "start")] + [0])
        for nid in auto:
            if nid == start_id:
                continue
            pos[nid] = saved_pos.get(nid) or (auto[nid][0], auto[nid][1] + max_y + 260)
        if start_id:
            pos[start_id] = (saved["start"]["x"], saved["start"]["y"]) if "start" in saved else auto.get(start_id, (0, 0))
    elif start_id:
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
    if graph_dict.get("variables") is not None:
        doc["variables"] = json.loads(json.dumps(graph_dict["variables"]))   # carried like `intents`
    if vform and layout and not usable:
        # an older layout (hub / go-to drawing): its automatic column frames no longer fit, the user's frames stay
        old = [f for f in (layout.get("frames") or []) if isinstance(f, dict) and _frame_problem(f) is None]
        theme_ids = {t[0] for t in GL.THEMES}
        auto_old = [f for f in old if f.get("auto") or f["id"] in theme_ids]   # automatic / theme frames of that drawing
        user = [f for f in old if f not in auto_old]
        fresh = GL.var_frames(nodes, pos, subs, {s["id"]: s["color"] for s in doc["states"]}) if auto_old else []
        doc["frames"] = (user + fresh)[:MAX_FRAMES]
        seed_frames = fresh       # lot L9: freshly drawn columns get their default post-it
    elif layout:
        doc["frames"] = [f for f in (layout.get("frames") or []) if isinstance(f, dict) and _frame_problem(f) is None][:MAX_FRAMES]
    elif vform:   # one automatic column frame per state, the global rules last
        doc["frames"] = GL.var_frames(nodes, pos, subs, {s["id"]: s["color"] for s in doc["states"]})
        seed_frames = doc["frames"]   # lot L9: default layout -> one post-it per column; L13: + its sub-groups
    else:
        # hub drawing: one automatic column frame per state (muted state colour, `auto: True`), globals last
        doc["frames"] = (GL.hub_frames(nodes, pos, {s["id"]: s["color"] for s in doc["states"]}) if new
                         else GL.default_frames(nodes, pos))
    # post-it notes: cosmetic like frames (layout file only, never compiled); invalid entries are not shown
    doc["notes"] = [n for n in (layout.get("notes") or []) if isinstance(n, dict) and _note_problem(n) is None][:MAX_NOTES]
    if vform and seed_frames:
        doc["notes"] = (column_notes(seed_frames, seed_text, doc["notes"]) + sub_notes(seed_frames, doc["notes"])
                        + doc["notes"])[:MAX_NOTES]
    # lot L8: nested groups / post-its in groups; a link to a frame that is not shown (or a cycle) is dropped
    doc["frames"], doc["notes"] = clean_parents(doc["frames"], doc["notes"])
    return doc


# ---------------------------------------------------------------- cosmetic frames
MAX_FRAMES, MAX_FRAME_TITLE, MAX_FRAME_NOTE = 100, 60, 2000
# post-it notes (2026-10-31): sticky notes drawn on the canvas, stored like frames in graph.layout.json
MAX_NOTES, MAX_NOTE_TEXT, MAX_NOTE_TITLE = 200, 2000, 60
FRAME_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) < 1e7


# ---- lot L9 (2026-11-01): default post-it of each state column (variables drawing)
# A layout the SERVER draws (no graph.layout.json, or an older-form file whose columns are redrawn) gets one post-it per
# column frame, at its top, child of the column (`parent`), titled with the column title, text = the state's
# `description` from graph.yaml (the global column: GLOBAL_NOTE), full display. Marked `auto: "state:<id>"`. A saved
# vars layout is never seeded again: its notes list is the record, so a deleted default post-it stays deleted and an
# edited one keeps the user's text. Layout only: graph.yaml never changes (YAML parity unaffected).
GLOBAL_NOTE = ("Règles globales : chacune peut se déclencher quel que soit l'état du robot "
               "(ou seulement dans les états choisis sur son déclencheur).")
COLUMN_NOTE_W = GL.NODE_W + 24     # fits inside every column frame (frame = nodes + 28 px each side)
COLUMN_NOTE_COLOR = "#fff59d"      # web/editor.js NOTE_COLORS[0]
AUTO_NOTE = re.compile(r"^(state:[A-Za-z0-9_.-]{1,60}|sub:[A-Za-z0-9_.-]{1,60}:[A-Za-z0-9_.-]{1,40})$")
# lot L13: marker of a default sub-group frame (`gen`, not `auto`: the editor treats a truthy `auto` as a column)
GEN_FRAME = re.compile(r"^sub:[A-Za-z0-9_.-]{1,60}:[A-Za-z0-9_.-]{1,40}$")
SUB_NOTE_TITLE = "En bref"


def column_note_texts(states_raw) -> dict:
    """{column group: post-it text} for the state columns (non-empty description) and the global column."""
    out = {}
    for sid, spec in (states_raw or {}).items():
        d = str((spec or {}).get("description") or "").strip() if isinstance(spec, dict) else ""
        if d:
            out[str(sid)] = d[:MAX_NOTE_TEXT]
    out["global"] = GLOBAL_NOTE
    return out


def column_note_height(text: str) -> int:
    """Estimated drawn height (px) of a full-mode column post-it: 28 px title bar, 15 px / 1.4 text wrapped at about
    26 characters per line (COLUMN_NOTE_W, conservative), 7 px padding top and bottom."""
    lines, cur = 0, 0
    for para in str(text).split("\n"):
        lines, cur = lines + 1, 0
        for w in para.split():
            if cur and cur + 1 + len(w) > 26:
                lines, cur = lines + 1, len(w)
            else:
                cur += (1 if cur else 0) + len(w)
    return 28 + 14 + 21 * max(1, lines) + 8


def column_notes(frames: list, texts: dict, existing: list) -> list:
    """Default post-its for the automatic column frames `frames` (ids `auto-<group>`): each column is grown upward by
    the post-it height (the layout reserved that room above its nodes, see graph_layout.var_layout `head`) and its
    post-it sits 16 px inside its top-left corner. Columns that already have a note marked `auto: "state:<group>"` in
    `existing` are skipped. Mutates the frames in place, returns the new notes."""
    have = {n.get("auto") for n in existing if isinstance(n, dict)}
    used = {n.get("id") for n in existing if isinstance(n, dict)}
    out = []
    for f in frames:
        g = f["id"][5:] if f.get("auto") and f["id"].startswith("auto-") else None
        if not g or g not in texts or "state:" + g in have or "state-" + g in used:
            continue
        hh = column_note_height(texts[g])
        f["y"] -= hh
        f["h"] += hh
        out.append({"id": "state-" + g, "title": str(f.get("title") or g)[:MAX_NOTE_TITLE], "text": texts[g],
                    "color": COLUMN_NOTE_COLOR, "x": f["x"] + 16, "y": f["y"] + 16, "w": COLUMN_NOTE_W, "h": hh,
                    "parent": f["id"], "auto": "state:" + g})
    return out


def sub_notes(frames: list, existing: list) -> list:
    """Lot L13: the post-it of each default sub-group frame of `frames` (built by graph_layout.var_frames, which put
    the post-it geometry on the private `_note` key; popped here so it never reaches the document). The note sits
    under the frame's title bar, child of the sub-group (`parent`), full display, marked `auto: "sub:<col>:<key>"`.
    Like column_notes, a marker or id already in `existing` is skipped. Mutates the frames, returns the new notes."""
    have = {n.get("auto") for n in existing if isinstance(n, dict)}
    used = {n.get("id") for n in existing if isinstance(n, dict)}
    out = []
    for f in frames:
        spec = f.pop("_note", None)
        if not spec or not spec["text"] or f.get("gen") in have:
            continue
        nid = "note-" + f["id"]
        if nid in used:
            continue
        out.append({"id": nid, "title": SUB_NOTE_TITLE, "text": spec["text"][:MAX_NOTE_TEXT], "color": COLUMN_NOTE_COLOR,
                    "x": spec["x"], "y": spec["y"], "w": COLUMN_NOTE_W, "h": spec["h"], "parent": f["id"], "auto": f["gen"]})
    return out


def _parent_ok(item: dict) -> bool:
    """Lot L8: `parent` is absent / null / "" (top level) or a frame id string (<= 64 chars)."""
    p = item.get("parent")
    return p is None or (isinstance(p, str) and len(p) <= 64)


def clean_parents(frames: list, notes: list) -> tuple:
    """Lot L8 (nested groups): drop every `parent` link that cannot be drawn, never an error (layout is cosmetic).

    A link survives only when it names another existing frame; automatic column frames (`auto`) stay top level;
    a cycle (hand-edited file) is broken by dropping the link that closes it, in list order. Items are copied
    only when a link is removed, so a clean list comes back equal (old files without `parent` are unchanged).
    Lot L9: `parent: null` (explicit top level, written by the editor after the user's first nesting choice so its
    geometry adoption never runs again) is kept on user frames and notes.
    Returns (frames, notes)."""
    ids = {f["id"] for f in frames}
    out_f = []
    for f in frames:
        p = f.get("parent")
        if "parent" in f and (f.get("auto") or (p is not None and (not p or p not in ids or p == f["id"]))):
            f = {k: v for k, v in f.items() if k != "parent"}
        out_f.append(f)
    parent = {f["id"]: f.get("parent") for f in out_f}
    for i, f in enumerate(out_f):     # walk up; a revisit means f's own link closes a cycle
        seen, cur = {f["id"]}, parent.get(f["id"])
        while cur:
            if cur in seen:
                out_f[i] = {k: v for k, v in f.items() if k != "parent"}
                parent[f["id"]] = None
                break
            seen.add(cur)
            cur = parent.get(cur)
    out_n = [n if not ("parent" in n and n["parent"] is not None and (not n["parent"] or n["parent"] not in ids))
             else {k: v for k, v in n.items() if k != "parent"} for n in notes]
    return out_f, out_n


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
    if not _parent_ok(f):
        return "Le parent du groupe doit être l'identifiant d'un groupe."
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
        if f.get("auto") is True:     # automatic column frame the user saved: keeps its muted drawing
            c["auto"] = True
        if isinstance(f.get("gen"), str) and GEN_FRAME.match(f["gen"]):   # lot L13: default sub-group marker
            c["gen"] = f["gen"]
        if "parent" in f:             # lot L8: enclosing group id (checked against the other frames by clean_parents);
            c["parent"] = f["parent"] or None   # L9: null = explicit top level (the editor's choice, kept)
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
    if n.get("display") not in (None, "full", "compact"):   # lot L5: full text (default) or title / first line only
        return "L'affichage du post-it est « full » ou « compact »."
    if not _parent_ok(n):
        return "Le parent du post-it doit être l'identifiant d'un groupe."
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
        if n.get("display") == "compact":   # lot L5: only the non-default mode is stored (old files stay byte-identical)
            c["display"] = "compact"
        if "parent" in n:                   # lot L8: the group the post-it belongs to (moves with it); L9: null kept
            c["parent"] = n["parent"] or None
        if isinstance(n.get("auto"), str) and AUTO_NOTE.match(n["auto"]):   # lot L9: default column post-it marker
            c["auto"] = n["auto"]
        out.append(c)
    return out, errors


# ---------------------------------------------------------------- visual document -> raw dict
def from_visual(doc: dict, cfg: dict, report: dict | None = None):
    """Compile an editor document. Returns (raw_dict | None, layout dict, errors).

    errors = [{"node": id | None, "message": str}] (French); when non-empty nothing may be written. A validator
    (parse_graph) error also carries `at` (the condition / action node it is about) and `nodes` [trigger, at] (lot L5).
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
        if kb == "trigger" and ka != "state":   # lot L1: a trigger only STARTS a chain (legacy hub links excepted)
            err(b, "Un déclencheur n'a pas d'entrée : il démarre la chaîne, aucun fil ne peut y entrer "
                   "(fil venant de %s)." % a); continue
        if ka == "start":
            if kb != "state":
                err(a, "Le nœud Début ne se relie à rien : l'état de départ est fixé par le code."); continue
            continue            # Start -> state is display only: the start state is fixed by the code
        if ka == "state":
            if kb != "trigger":
                err(a, "La sortie d'un nœud État se relie seulement à un déclencheur."); continue
            state_out.setdefault(b, [])
            if a not in state_out[b]:
                state_out[b].append(a)
            continue
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
    nodes[END0] = {"id": END0, "kind": "end", "params": {}, "description": ""}   # implicit End (see paths)
    vdoc = doc.get("variables") if isinstance(doc.get("variables"), dict) else {}
    var_types = {n: (v or {}).get("type") for n, v in ((vdoc.get("names") or {}).items() if isinstance(vdoc.get("names"), dict) else ())}
    var_types.update({n: G.SYSTEM_VARS[n][0] for n in G.SYSTEM_VARS})
    list_types = {n: (v or {}).get("type", "string") for n, v in ((vdoc.get("lists") or {}).items() if isinstance(vdoc.get("lists"), dict) else ())}

    def coerce_args(name, args, spec):
        """Editor text -> typed literals for the `value` / `number` arguments (type of the named variable / list)."""
        out = dict(args)
        vt = (var_types.get(args.get("name")) if "name" in args else list_types.get(args.get("list")) if "list" in args
              else list_types.get(args.get("dict")))   # lot L11: dictionary values follow the dictionary's type
        for k, kind in spec.items():
            if k in out and kind in ("value", "listvalue") and vt:
                out[k] = G.coerce_value(vt, out[k])
            elif k in out and kind in ("number", "seconds0"):
                out[k] = G.coerce_value("number", out[k])
        return out

    # evaluation order of triggers: `order`, then the rest by (y, x)
    trig_ids = [i for i, n in nodes.items() if n["kind"] == "trigger"]
    ordered = [i for i in (doc.get("order") or []) if i in nodes and nodes[i]["kind"] == "trigger"]
    ordered = list(dict.fromkeys(ordered))
    ordered += sorted((i for i in trig_ids if i not in ordered), key=lambda i: (nodes[i].get("y", 0), nodes[i].get("x", 0)))

    reached = set(i for i in nodes if nodes[i]["kind"] in ("start", "trigger", "state")) | {END0}
    states_raw = {s["id"]: {"description": str(s.get("description") or "")} for s in states_doc if isinstance(s, dict)}
    on_enter, transitions, globals_, where_map, node_pos = {}, {}, [], {}, {}
    where_nodes = {}           # lot L5: validator location -> condition / action node ids of that chain (error -> node)
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
            if not targets and k == "action":   # lot L1: an action with an unlinked output ends the chain
                out.append(chain + [(nid, False), (END0, False)]); return
            if not targets:
                err(nid, "Chaîne sans suite : relier ce déclencheur à une condition ou à une action.")
            for t in targets:
                rec(t, chain + [(nid, False)])
        rec(tid, [])
        return out

    for tid in ordered:
        trig = nodes[tid]
        p = trig["params"]
        kind = p.get("type")
        n_err = len(errors)
        if kind == "event" and p.get("event") == "var_changed" and p.get("name") == "etat":
            # lot L1: "etat becomes X" is the on_enter of X (same rules as the legacy `enter` trigger)
            if "value" not in p or p.get("value") in (None, ""):
                err(tid, "« Quand etat change » : choisir l'état (la valeur) qui déclenche la chaîne.")
            p = dict(p, type="enter", state=p.get("value"))
            kind = "enter"
        if kind == "event":
            ev = p.get("event")
            if ev == "var_changed" and not (isinstance(p.get("name"), str) and p.get("name")):
                err(tid, "« Une variable change » : choisir la variable.")
            if ev == "timer_reached" and not (isinstance(p.get("name"), str) and p.get("name")):
                err(tid, "« Un chrono atteint une durée » : choisir le chrono.")
            elif ev == "timer_reached" and p.get("value") in (None, ""):
                err(tid, "« Un chrono atteint une durée » : indiquer le nombre de secondes.")
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
            dup_ok = True      # lot L1: etat conditions without `global` duplicate the chain under each state
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
                    dup_ok = False
            to = reason = None
            # a move (set_var etat) splits the actions by position: before = do, after = then (else the `phase` field)
            moves_at = [k for k, (nid, _inv) in enumerate(mid) if nodes[nid]["kind"] == "action"
                        and (nodes[nid]["params"].get("action") == "set_var")
                        and ((nodes[nid]["params"].get("args") or {}).get("name") == "etat")]
            for pos_k, (nid, inv) in enumerate(mid):
                n = nodes[nid]
                q = n["params"]
                if n["kind"] == "condition":
                    if seen_action:
                        err(nid, "Une condition ne peut pas venir après une action (les conditions sont évaluées d'abord).")
                    neg = bool(q.get("negate")) != inv
                    qargs = q.get("args") if isinstance(q.get("args"), dict) else {}
                    if q.get("type") == "state":
                        dup_ok = False   # legacy state condition: several states = a global only_in rule, as before
                        sts = [s for s in _aslist(q.get("states"))]
                        if not sts:
                            err(nid, "Choisir au moins un état.")
                        for s in sts:
                            if s not in state_ids:
                                err(nid, "État inconnu : %r." % (s,))
                        (neg_sets if neg else pos_sets).append(sts)
                        force_global = force_global or (not neg and bool(q.get("global")))
                    elif q.get("type") == "guard" and q.get("guard") == "var_compare" and qargs.get("name") == "etat":
                        # lot L1: the state is the variable etat; its condition places the transition
                        op, val = qargs.get("op"), qargs.get("value")
                        if op not in ("=", "!=", "in", "not_in"):
                            err(nid, "Sur « etat », l'opérateur est =, ≠, « parmi » (in) ou « hors de » (not_in).")
                            continue
                        sts = list(dict.fromkeys(_aslist(val))) if op in ("in", "not_in") else [val]
                        if not sts or any(x in (None, "") for x in sts):
                            err(nid, "Choisir au moins un état.")
                        for s in sts:
                            if s not in state_ids and s not in (None, ""):
                                err(nid, "État inconnu : %r." % (s,))
                        neg = neg != (op in ("!=", "not_in"))
                        (neg_sets if neg else pos_sets).append(sts)
                        force_global = force_global or (not neg and bool(q.get("global")))
                    elif q.get("type") == "guard":
                        g = q.get("guard")
                        if g not in G.GUARDS:
                            err(nid, "Condition inconnue : %r." % (g,)); continue
                        spec = G.GUARD_SPECS[g]
                        if spec and not qargs:
                            err(nid, "Cette condition attend des réglages : %s." % ", ".join(spec)); continue
                        core = {g: coerce_args(g, qargs, spec)} if spec else g
                        when.append({"not": core} if neg else core)
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
                    if name == "set_var" and args.get("name") == "etat":   # lot L1: the move (`to:`)
                        if kind == "enter":
                            err(nid, "Une entrée dans l'état ne peut pas changer d'état.")
                        elif len(moves_at) > 1:
                            err(nid, "Un seul changement d'état par chaîne.")
                        elif args.get("value") not in state_ids:
                            err(nid, "État de destination inconnu : %r." % (args.get("value"),))
                        else:
                            to, reason = args["value"], (q.get("reason") or None)
                        continue
                    if name in ("set_var", "add_var", "toggle_var") and args.get("name") in G.SYSTEM_VARS:
                        err(nid, "La variable système « %s » est en lecture seule." % args.get("name")); continue
                    args = {k: (_coerce_delay(v) if G.ACTION_SPECS[name].get(k) == "delay" else v) for k, v in args.items()}
                    args = coerce_args(name, args, G.ACTION_SPECS[name])
                    is_then = (pos_k > moves_at[0]) if moves_at else q.get("phase") == "then"
                    (then if is_then else do).append(_call_raw(name, args))
                else:
                    err(nid, "Nœud inattendu au milieu d'une chaîne.")
            if term["kind"] == "goto":
                if to is not None:
                    err(term["id"], "Un seul changement d'état par chaîne.")
                to = term["params"].get("state")
                if to not in state_ids:
                    err(term["id"], "État de destination inconnu : %r." % (to,))
                reason = term["params"].get("reason") or None
            elif term["kind"] == "state":     # hub form: the destination state node ends the chain
                if to is not None:
                    err(term["id"], "Un seul changement d'état par chaîne.")
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
                where_nodes["state %s on_enter" % st] = [x for x in ids if x in nodes and nodes[x]["kind"] in ("condition", "action")]
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
                places = None          # lot L1: states the chain is duplicated under (etat in [A, B] without `global`)
                if not single and dup_ok and pos_sets and not neg_sets and not force_global:
                    places = [s for s in pos_sets[0] if all(s in o for o in pos_sets[1:])]
                    if not places:
                        err(tid, "Les conditions d'état se contredisent (aucun état possible)."); continue
                    if len(places) == 1:
                        single, pos_sets, places = True, [places], None   # e.g. etat in [A, B] and etat = A
                if single:
                    targets = [(transitions.setdefault(pos_sets[0][0], []), "state %s transition" % pos_sets[0][0], pos_sets[0][0])]
                elif places:
                    # one transition per state, sharing a fan id: only one of them can match (one current state)
                    t["fan"] = fan_id or ("fan-" + tid)
                    targets = [(transitions.setdefault(st, []), "state %s transition" % st, st) for st in places]
                else:
                    if kind == "after":
                        err(tid, "Un délai doit être rattaché à un état (condition « etat = … » ou « etat parmi … », sans « global »).")
                        continue
                    targets = [(globals_, "global transition", "global")]
                    if pos_sets:
                        inter = [s for s in pos_sets[0] if all(s in o for o in pos_sets[1:])]
                        if not inter:
                            err(tid, "Les conditions d'état se contredisent (aucun état possible)."); continue
                        t["only_in"] = inter
                    if neg_sets:
                        t["not_in"] = list(dict.fromkeys(s for ss in neg_sets for s in ss))
                if kind == "event" and p.get("event") == "var_changed":
                    t["var"] = p.get("name")
                    if "value" in p and p.get("value") not in (None, ""):
                        t["value"] = p["value"]
                elif kind == "event" and p.get("event") == "timer_reached":   # lot L11: seconds may arrive as text
                    t["var"] = p.get("name")
                    t["value"] = G.coerce_value("number", p.get("value"))
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
                key = None
                for container, label, cname in targets:
                    if key is None:   # positions are saved under the first copy's structural key
                        key = "%s/t%d" % (cname, len(container))
                    container.append(json.loads(json.dumps(t)))
                    where_map["%s #%d" % (label, len(container))] = tid
                    where_nodes["%s #%d" % (label, len(container))] = [x for x in ids if x in nodes and nodes[x]["kind"] in ("condition", "action")]
                if report is not None:
                    allowed = set(state_ids)
                    if pos_sets:
                        allowed = set.intersection(*[set(x) for x in pos_sets])
                    for x in neg_sets:
                        allowed -= set(x)
                    emitted.append({"target": ids[-2] if term["id"] == END0 else term["id"], "nodes": [x for x in ids if x != END0],
                                    "moves": bool(to), "global": targets[0][0] is globals_,
                                    "states": allowed, "guards": {_gkey(g) for g in when}})
            # layout: every path records the position of each of its nodes (shared nodes repeat the same value)
            for j, nid in enumerate(ids):
                if nodes[nid]["kind"] != "state" and nid != END0:   # state nodes are saved once, under `state/<id>`
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
    if doc.get("variables") is not None:   # lot L1: the variable manager's data, validated by parse_graph below
        if not isinstance(doc["variables"], dict):
            err(None, "`variables` doit être un objet {names, lists}.")
        else:
            raw["variables"] = json.loads(json.dumps(doc["variables"]))

    if not errors:
        try:
            parsed = G.parse_graph(raw, cfg, "<visual>")
        except G.GraphError as e:
            items = e.items or [("", str(e))]
            for where, msg in items:
                wkey = next((k for k in where_map if where == k or where.startswith(k + " ")), None)
                nid = where_map.get(wkey)
                at = _error_node(msg, where_nodes.get(wkey) or [], nodes) if wkey else None
                if where.startswith("intent "):   # the editor shows intent problems next to the intent, not a node
                    err(None, "%s : %s" % (where, msg), intent=where[7:])
                elif where.startswith(("variable ", "list ", "variables")):   # shown in the variable manager
                    err(None, "%s : %s" % (where, msg), variable=where.split(" ", 1)[1] if " " in where else None)
                elif at and at != nid:   # lot L5: `node` stays the trigger (contract), `at` names the faulty node
                    err(nid, "%s : %s" % (where, msg) if where else msg, at=at, nodes=[nid, at])
                else:
                    err(nid, "%s : %s" % (where, msg) if where else msg)
        else:   # lot L11: non-blocking validator remarks (a constant outside a variable's bounds) become warnings
            for where, msg, wkind in (parsed.diagnostics if report is not None else ()):
                wkey = next((k for k in where_map if where == k or where.startswith(k + " ")), None)
                nid = where_map.get(wkey)
                at = _error_node(msg, where_nodes.get(wkey) or [], nodes) if wkey else None
                report["warnings"].append({"node": nid, "nodes": [x for x in (nid, at) if x], "kind": wkind,
                                           "message": "%s : %s" % (where, msg), **({"at": at} if at and at != nid else {})})

    layout = {"nodes": node_pos, "states": {s["id"]: s["color"] for s in states_doc if isinstance(s, dict) and s.get("color")}}
    if not any(n["kind"] in ("state", "goto") for n in nodes.values()):
        layout["form"] = "vars"   # lot L1: these positions fit the variables drawing (older files are not reused)
    icons = {s["id"]: s["icon"] for s in states_doc
             if isinstance(s, dict) and isinstance(s.get("icon"), str) and ICON_NAME.match(s["icon"])
             and s["icon"] != G.state_icon(s["id"])}
    if icons:   # only the icons the user changed; the registry supplies the rest
        layout["icons"] = icons
    for nid, n in nodes.items():
        # lot L4: a legacy Start node in a variables document is accepted and ignored (not even its position is kept)
        if n["kind"] == "start" and layout.get("form") != "vars":
            layout["nodes"]["start"] = {"x": n.get("x", 0), "y": n.get("y", 0)}
    for sid_, nid_ in state_node_of.items():
        layout["nodes"]["state/" + sid_] = {"x": nodes[nid_].get("x", 0), "y": nodes[nid_].get("y", 0)}
    frames, ferrors = clean_frames(doc.get("frames"))
    errors.extend(ferrors)
    notes, nerrors = clean_notes(doc.get("notes"))
    errors.extend(nerrors)
    frames, notes = clean_parents(frames, notes)   # lot L8: dangling / cyclic / auto parent links dropped
    if frames:   # purely cosmetic: lives in the layout file only, never compiled into graph.yaml
        layout["frames"] = frames
    if notes:    # post-it notes: same story as frames (layout only, never compiled)
        layout["notes"] = notes
    return (None if errors else raw), layout, errors


def _error_node(msg: str, cands: list, nodes: dict):
    """Node of a chain that a validator message is about (lot L5), or None.

    parse_graph reports a problem per transition (`state x transition #n do: set_var.name: unknown variable 'v'`);
    the editor wants the faulty node itself. The message names the call (`set_var.name`, `guard var_compare`,
    `action set_var`); among the chain's condition / action nodes using that call, the one whose argument values
    appear in the message wins (two set_var nodes in one chain), else the first one.
    """
    names = set(re.findall(r"\b([a-z][a-z0-9_]*)\.[a-z_]+:", msg)) | set(re.findall(r"(?:guard|action) ([a-z][a-z0-9_]*)", msg))
    hits = []
    for nid in cands:
        q = nodes[nid].get("params") or {}
        call = q.get("action") if nodes[nid]["kind"] == "action" else q.get("guard")
        if call in names:
            hits.append((nid, q.get("args") or {}))
    for nid, args in hits:
        if any(isinstance(v, (str, int, float)) and not isinstance(v, bool) and repr(v) in msg for v in args.values()):
            return nid
    return hits[0][0] if hits else None


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
        elif k == "variables" and isinstance(v, dict):   # lot L1: one block per variable, short lists inline
            out[k] = {part: {n: {kk: (_flow(vv) if isinstance(vv, list) else vv) for kk, vv in (spec or {}).items()}
                             for n, spec in (v.get(part) or {}).items()} for part in ("names", "lists") if part in v}
        else:
            out[k] = v
    body = yaml.dump(out, Dumper=_Dumper, sort_keys=False, allow_unicode=True, default_flow_style=False, width=10 ** 6)
    return HEADER + body


def _tr(t: dict) -> dict:
    order = ("on", "var", "value", "after", "since", "enabled", "fan", "when", "only_in", "not_in", "do", "to", "reason", "then",
             "description")
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
