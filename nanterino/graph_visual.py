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
from .log import log

COLW, ROWH, GROUP_GAP = 250, 120, 60            # layout grid (px): column width, band height, gap between state groups
PALETTE = ["#4f8ef7", "#2fb59a", "#e0a030", "#a06cd5", "#e07a5f", "#6c8ea4", "#7a7a7a", "#c26ba6", "#8aa83c"]
STATE_COLORS = {"veille": "#4f8ef7", "accueil": "#2fb59a", "ecoute": "#e0a030", "reponse": "#a06cd5",
                "relance": "#e07a5f", "cloture": "#6c8ea4", "eteint": "#7a7a7a"}
GLOBAL_COLOR = "#c0504d"
KINDS = ("start", "trigger", "condition", "action", "goto", "end")
PORTS = {"start": ("out",), "trigger": ("out",), "condition": ("true", "false"), "action": ("out",)}
HEADER = (
    "# Graphe de dialogue de Nanterino, écrit par l'éditeur visuel (/editor).\n"
    "# L'éditeur réécrit ce fichier en entier : une copie datée est gardée à côté (graph.yaml.bak-<date>, 10 dernières).\n"
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


# ---------------------------------------------------------------- raw dict -> visual document
def to_visual(graph_dict: dict, layout: dict | None = None, start_state: str = "veille") -> dict:
    """Editor document of a raw graph dict (as read from graph.yaml).

    `layout` is the content of graph.layout.json ({"nodes": {key: {"x","y"}}, "states": {id: color}});
    chains whose every node has a saved position keep it, the others are stacked below the saved ones
    with the automatic column layout (all chains automatic when nothing is saved).
    """
    layout = layout or {}
    saved = layout.get("nodes") or {}
    nodes, links, order, chains = [], [], [], []

    def mk(kind, params, group, desc=""):
        n = {"id": "n%d" % (len(nodes) + 1), "kind": kind, "x": 0, "y": 0, "description": desc, "params": params}
        if group is not None:
            n["group"] = group  # informational (state colour in the editor); ignored by the compiler
        nodes.append(n)
        return n["id"]

    def kind_of(nid):
        return nodes[int(nid[1:]) - 1]["kind"]

    def chain(group, key, trig, desc, conds, do, then, to, reason):
        ids = [mk("trigger", trig, group, desc)]
        ids += [mk("condition", c, group) for c in conds]
        ids += [mk("action", {"action": n, "args": a, "phase": "do"}, group) for n, a in do]
        ids += [mk("action", {"action": n, "args": a, "phase": "then"}, group) for n, a in then]
        if to:
            ids.append(mk("goto", dict({"state": to}, **({"reason": reason} if reason else {})), group))
        else:
            ids.append(mk("end", {}, group))
        for a, b in zip(ids, ids[1:]):
            links.append({"from": a, "port": "true" if kind_of(a) == "condition" else "out", "to": b})
        chains.append({"key": key, "group": group, "ids": ids})
        return ids[0]

    def conds_for(t, state):
        conds = [{"type": "state", "states": [state], "negate": False}] if state else []
        for k, neg in (("only_in", False), ("not_in", True)):
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

    def transition(group, key, t, state):
        if t.get("after") is not None:
            trig = {"type": "after", "delay": t["after"], "since": t.get("since") or "state"}
        else:
            trig = {"type": "event", "event": t.get("on")}
        order.append(chain(group, key, trig, str(t.get("description") or ""), conds_for(t, state),
                           _calls(t.get("do")), _calls(t.get("then")), t.get("to"), t.get("reason")))

    start_id = mk("start", {"state": start_state}, None, "Démarrage")
    states_raw = graph_dict.get("states") or {}
    for sname, spec in states_raw.items():
        spec = spec or {}
        enter = _calls(spec.get("on_enter"))
        if enter:
            chain(sname, sname + "/enter", {"type": "enter", "state": sname}, "", [], enter, [], None, None)
        for i, t in enumerate(spec.get("transitions") or []):
            transition(sname, "%s/t%d" % (sname, i), t, sname)
    for i, t in enumerate(graph_dict.get("global") or []):
        transition("global", "global/t%d" % i, t, None)

    # ---- layout: one band (row) per chain, bands grouped by state, columns follow the chain
    pos, row, gi, last_group = {}, 1, -1, object()
    for c in chains:
        if c["group"] != last_group:
            gi, last_group = gi + 1, c["group"]
        for j, nid in enumerate(c["ids"]):
            pos[nid] = (j * COLW, row * ROWH + gi * GROUP_GAP)
        row += 1
    is_saved = lambda c: all("%s/%d" % (c["key"], j) in saved for j in range(len(c["ids"])))  # noqa: E731
    if any(is_saved(c) for c in chains) or "start" in saved:
        max_y = max([saved[k].get("y", 0) for k in saved] + [0])
        extra = 0
        for c in chains:
            if is_saved(c):
                for j, nid in enumerate(c["ids"]):
                    p = saved["%s/%d" % (c["key"], j)]
                    pos[nid] = (p.get("x", 0), p.get("y", 0))
            else:
                extra += 1
                for j, nid in enumerate(c["ids"]):
                    pos[nid] = (j * COLW, max_y + extra * ROWH)
        pos[start_id] = (saved["start"]["x"], saved["start"]["y"]) if "start" in saved else (0, 0)
    else:
        pos[start_id] = (0, 0)
    for n in nodes:
        n["x"], n["y"] = pos[n["id"]]

    doc = {
        "version": 1, "nodes": nodes, "links": links,
        "states": [{"id": s, "description": str((spec or {}).get("description") or ""),
                    "color": state_color(s, i, layout)} for i, (s, spec) in enumerate(states_raw.items())],
        "intents": json.loads(json.dumps(graph_dict.get("intents") or {})),
        "order": order,
    }
    if graph_dict.get("description"):
        doc["description"] = str(graph_dict["description"])
    return doc


# ---------------------------------------------------------------- visual document -> raw dict
def from_visual(doc: dict, cfg: dict):
    """Compile an editor document. Returns (raw_dict | None, layout dict, errors).

    errors = [{"node": id | None, "message": str}] (French); when non-empty nothing may be written.
    """
    errors, seen = [], set()

    def err(node, msg):
        if (node, msg) not in seen:
            seen.add((node, msg))
            errors.append({"node": node, "message": msg})

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
    for lk in doc.get("links") or []:
        a, b, port = (lk.get("from"), lk.get("to"), lk.get("port")) if isinstance(lk, dict) else (None, None, None)
        if a not in nodes or b not in nodes:
            err(a if a in nodes else (b if b in nodes else None), "Lien vers un nœud inexistant (%s -> %s)." % (a, b)); continue
        if port not in PORTS.get(nodes[a]["kind"], ()):
            err(a, "Ce nœud (%s) n'a pas de sortie « %s »." % (nodes[a]["kind"], port)); continue
        if nodes[b]["kind"] in ("start", "trigger"):
            err(b, "Un déclencheur ne peut pas recevoir de lien."); continue
        adj.setdefault((a, port), []).append(b)

    states_doc = doc.get("states")
    if not isinstance(states_doc, list) or not states_doc:
        return None, {}, errors + [{"node": None, "message": "Document invalide : la liste `states` est absente ou vide."}]
    state_ids = [s.get("id") for s in states_doc if isinstance(s, dict)]
    intent_names = set(doc.get("intents") or {}) | {"question"}

    # evaluation order of triggers: `order`, then the rest by (y, x)
    trig_ids = [i for i, n in nodes.items() if n["kind"] == "trigger"]
    ordered = [i for i in (doc.get("order") or []) if i in nodes and nodes[i]["kind"] == "trigger"]
    ordered = list(dict.fromkeys(ordered))
    ordered += sorted((i for i in trig_ids if i not in ordered), key=lambda i: (nodes[i].get("y", 0), nodes[i].get("x", 0)))

    reached = set(i for i in nodes if nodes[i]["kind"] in ("start", "trigger"))
    states_raw = {s["id"]: {"description": str(s.get("description") or "")} for s in states_doc if isinstance(s, dict)}
    on_enter, transitions, globals_, where_map, node_pos = {}, {}, [], {}, {}
    recorded = set()

    def paths(tid):
        """All trigger -> terminal paths as [(node id, negated by false port)], true branch first."""
        out = []

        def rec(nid, chain):
            if nid in {c[0] for c in chain}:
                err(nid, "Boucle dans la chaîne : ce nœud revient sur lui-même."); return
            reached.add(nid)
            k = nodes[nid]["kind"]
            if k in ("goto", "end"):
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
        else:
            err(tid, "Type de déclencheur inconnu : %r (event, after ou enter)." % (kind,))
        if len(errors) > n_err:
            paths(tid)  # still walk it so its nodes count as reached
            continue
        for path in paths(tid):
            ids = [x[0] for x in path]
            mid, term = path[1:-1], nodes[path[-1][0]]
            pos_sets, neg_sets, when, do, then = [], [], [], [], []
            force_global = False
            n_err = len(errors)
            seen_action = False
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
            if kind == "enter":
                for nid, _inv in mid:
                    if nodes[nid]["kind"] == "condition":
                        err(nid, "Un déclencheur « entrée dans l'état » n'accepte pas de condition.")
                if term["kind"] == "goto":
                    err(term["id"], "Une entrée dans l'état ne peut pas changer d'état : terminer par une fin.")
                if then:
                    err(tid, "Une entrée dans l'état n'a pas de phase « then ».")
            if len(errors) > n_err:
                continue
            desc = trig.get("description") or next((nodes[i].get("description") for i in ids if nodes[i].get("description")), "")
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
            # layout: record a path only when none of its nodes was recorded by an earlier branch
            if not recorded & set(ids):
                recorded |= set(ids)
                for j, nid in enumerate(ids):
                    node_pos["%s/%d" % (key, j)] = {"x": nodes[nid].get("x", 0), "y": nodes[nid].get("y", 0)}

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
                err(nid, "%s : %s" % (where, msg) if where else msg)

    layout = {"nodes": node_pos, "states": {s["id"]: s["color"] for s in states_doc if isinstance(s, dict) and s.get("color")}}
    for nid, n in nodes.items():
        if n["kind"] == "start":
            layout["nodes"]["start"] = {"x": n.get("x", 0), "y": n.get("y", 0)}
    return (None if errors else raw), layout, errors


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
    order = ("on", "after", "since", "when", "only_in", "not_in", "do", "to", "reason", "then", "description")
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


def backup_file(path: str, keep: int = 10):
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


def _atomic_write(path: str, text: str):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def save(doc: dict, cfg: dict, graph_path: str, layout_path: str):
    """Compile + validate + back up + write graph and layout. Returns (True, None) or (False, errors)."""
    raw, layout, errors = from_visual(doc, cfg)
    if errors:
        log.info("graph save refused: %d error(s)", len(errors))
        return False, errors
    text = dump_yaml(raw)
    try:  # what lands on disk must itself load and validate
        G.parse_graph(yaml.load(text, Loader=G._Loader), cfg, graph_path)
    except (G.GraphError, yaml.YAMLError) as e:
        log.error("graph save: produced file invalid: %s", e)
        return False, [{"node": None, "message": "Le fichier produit est invalide : %s" % e}]
    made = backup_file(graph_path)
    _atomic_write(graph_path, text)
    _atomic_write(layout_path, json.dumps(layout, ensure_ascii=False, indent=1))
    log.info("graph saved from the visual editor (backup=%s)", os.path.basename(made) if made else None)
    return True, None


def reset(graph_path: str, layout_path: str):
    """Back up the override and remove it (and its layout): the packaged default graph runs again."""
    made = backup_file(graph_path)
    for p in (graph_path, layout_path):
        try:
            os.remove(p)
        except OSError:
            pass
    log.info("graph reset to the packaged default (backup=%s)", os.path.basename(made) if made else None)
    return made
