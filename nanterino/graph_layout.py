"""Automatic layout and default theme frames of the visual dialogue graph (pure functions, no I/O).

logging: robotlog via nanterino.log (imported for the convention; the functions are pure and log nothing).

Purpose
    `graph_visual.to_visual()` builds the node/link document; this module only decides WHERE the nodes go
    when no saved layout exists, and which cosmetic frames ("groupes") frame the themes of the default graph.

Boundary
    - Input: `nodes` (editor node dicts: id, kind, group, params, description) and `links` ({from, port, to}).
    - Output: {node id: (x, y)}; nothing is written. The start node (group None, hub / go-to drawings only; the variables drawing has none since lot L4)
      is placed by the caller.
    - Node height is an ESTIMATE of the editor's rendering (214 px wide node, 13-14 px text that wraps the
      description): kept slightly generous so nodes never overlap even for long French descriptions.

Hub drawing (L7): `hub_layout()` puts the state hubs on the TOP row, left to right in flow order, each heading a
    column with its chains below (layered band layout, one layer right of the hub); `global` is the last column.
    `hub_frames()` gives one automatic translucent frame per column. Wires back to the hubs are not optimised:
    the editor draws them faded with a "→ État" badge. (`auto_layout(hub=True)` = the L6 row-band form, unused.)

Variables drawing (lot L1): `var_layout()` = the hub columns without hubs and badges (one column per state group,
    `global` last, rows wrapped); `hub_frames(..., badge=0)` frames them. `node_height` knows the etat condition and
    the set_var / var_changed nodes.

Invariants
    - One band per state group, stacked top to bottom in the order the groups first appear in `nodes`.
    - Inside a band: columns left to right (trigger, conditions, actions, targets); all targets (goto/end)
      sit in the last column; rows ordered by barycentre sweeps to reduce link crossings; each node is pulled
      towards the mean row of its neighbours without ever overlapping another node of its column.
    - Deterministic: same input, same output (no hashing, no randomness).

How to test
    python -m tests.test_graph_visual   (no overlapping boxes, crossings bound, node count)
"""
import math

from .log import log  # noqa: F401  (project logging convention)

NODE_W = 214            # editor node width (web/editor.css .drawflow-node)
COLW = 270              # column pitch: node width + room for the link curves
GAP_Y = 26              # minimum free space between two stacked nodes
GROUP_GAP = 110         # free space between two state bands (leaves room for theme frames)
TOP = 190               # y of the first band (room for the frame titles; was below the start node)

THEMES = [               # (frame id, title, colour, state groups) - cosmetic only
    ("t-accueil", "Accueil", "#4f8ef7", ("veille", "accueil")),
    ("t-conversation", "Conversation", "#2fb59a", ("ecoute", "reponse", "relance")),
    ("t-fin", "Fin de visite", "#a06cd5", ("cloture", "eteint")),
    ("t-interruptions", "Règles globales", "#e0504d", ("global",)),
]


def _orient(u, v, w):
    return (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0])


def _no_overlap(want, heights):
    """Closest (least squares) ordered positions to `want` with at least GAP_Y between neighbours.

    Pool-adjacent-violators on the positions minus the cumulative stack offsets: when several nodes want the
    same spot they spread symmetrically around it instead of drifting down.
    """
    off, acc = [], 0.0
    for hh in heights:
        off.append(acc)
        acc += hh + GAP_Y
    blocks = []                                 # [sum of (want - offset), count]
    for w, o in zip(want, off):
        blocks.append([w - o, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s2, n2 = blocks.pop()
            blocks[-1][0] += s2
            blocks[-1][1] += n2
    out = []
    for sm, n in blocks:
        out += [sm / n] * n
    return [z + o for z, o in zip(out, off)]


def _lines(text, per_line):
    return max(1, math.ceil(len(text) / per_line)) if text else 0


def node_height(n) -> int:
    """Estimated rendered height (px) of an editor node: header + summary + wrapped description."""
    p = n.get("params") or {}
    k = n.get("kind")
    if k == "state":
        return 84        # hub card: header + state name + one line of description (fixed height in the editor CSS)
    if k == "action":
        # the editor shows the French label + " [après]" + args: two lines is the norm
        summ = "x" * max(27, len(str(p.get("action") or "")) + 14) + "".join(" %s=%s" % kv for kv in (p.get("args") or {}).items())
    elif k == "goto":
        summ = "→ %s %s" % (p.get("state", ""), "(%s)" % p["reason"] if p.get("reason") else "")
    elif k == "condition" and p.get("args"):   # lot L1: guard with arguments, e.g. "etat ∈ reponse, accueil, relance"
        txt = " ".join(", ".join(map(str, v)) if isinstance(v, list) else str(v) for v in p["args"].values())
        summ = "x" * max(27, len(txt) + 10)
    elif k == "condition":
        summ = ("Pas dans : " + ", ".join(str(x) + "xx" for x in p.get("states") or [])
                if p.get("type") == "state" else "x" * max(27, len(str(p.get("guard") or "")) + 8))
    elif k == "trigger":
        summ = "Après 99 secondes depuis la parole" if p.get("type") == "after" else str(p.get("event") or p.get("state") or "") + " xxxxxxxx"
        if p.get("event") == "var_changed":   # "Quand etat devient reponse"
            summ = "Quand %s devient %s" % (p.get("name"), p.get("value", "xxxxxx"))
    else:
        summ = "Fin de chaîne" if k == "end" else "État de départ : veille"
    # calibrated on the rendered editor (Firefox, 2026-10-31): bare node 54 px, +18 per extra summary line,
    # +17 per description line (about 26 characters per line), conditions +22 for their two ports; +6 margin
    h = 36 + 18 * max(1, _lines(summ, 26)) + 17 * _lines(str(n.get("description") or ""), 25) + 6
    if k == "condition":
        h += 22
    if k == "trigger" and p.get("state") and p.get("type") != "enter":
        h += 18   # "dans : <état>" scope line of a compact trigger
    return h


HUB_PITCH = 320         # layer pitch inside a hub column: leaves ~100 px after a node for its "→ État" badge
HUB_GAP = 70            # vertical space between the hub row and the first chain row of its column
COL_GAP = 150           # free space between two hub columns (badge of the last layer + frame padding)
ROW_GAP = 300           # hub row of a wrapped row sits this far below the previous row (room for zoom-scaled frame titles)
SUBCOL_CHAINS = 6       # a column with more chain groups than this is split into two sub-columns
SUBCOL_GAP = 40         # extra space between the two sub-columns of one state column
MAX_ROWS = 4
# wanted width / height of the whole drawing. Measured 2026-10-31: the editor canvas between the two side panels is
# about 660 x 614 at 1280 x 700 (aspect ~1.1); 16/9 gave fit 0.090 there, 1.1 gives 0.105 (best of the splits).
TARGET_ASPECT = 1.1
BADGE_ROOM = 110        # width reserved right of the last layer for the "→ État" proxy badges
STATE_LABELS = {"veille": "Veille", "accueil": "Accueil", "ecoute": "Écoute", "reponse": "Réponse",
                "relance": "Relance", "cloture": "Clôture", "eteint": "Éteint", "global": "Règles globales"}


def hub_groups(nodes) -> list:
    """Column order of the hub drawing: states in flow order (order of their state nodes), then any other group,
    `global` last."""
    out = []
    for n in nodes:
        if n.get("kind") == "state" and n.get("group") not in out:
            out.append(n.get("group"))
    for n in nodes:
        g = n.get("group")
        if g is not None and g != "global" and g not in out:
            out.append(g)
    if any(n.get("group") == "global" for n in nodes):
        out.append("global")
    return out


def var_layout(nodes, links, y0: int = TOP, head: dict | None = None) -> dict:
    """Columns layout of the variables drawing (lot L1): no state node, one column per state group in order of first
    appearance (the state order of the graph), `global` last, columns wrapped into rows like hub_layout. Every link of
    this drawing stays inside its column (shared nodes only join chains of one group), so the only crossings are the
    ones the band algorithm leaves inside a column; no room is kept for "→ État" badges and layers use COLW.
    `head` (lot L9): {group: px} of free room kept at the top of a column, above its first chain (default post-it)."""
    return hub_layout(nodes, links, y0, badge=0, pitch=COLW, stack=True, head=head)


def hub_layout(nodes, links, y0: int = TOP, badge: int = BADGE_ROOM, pitch: int = HUB_PITCH, stack: bool = False,
               head: dict | None = None) -> dict:
    """Columns layout of the state-node (hub) drawing (L7, 2026-10-31; fix round: columns wrapped into rows).

    Fix round: the columns (flow order kept) are wrapped into 1..4 rows chosen by `_wrap_rows()` for an
    overall aspect close to TARGET_ASPECT; hubs sit at the top of their column (one hub row per row); a column
    with more than SUBCOL_CHAINS chain groups is split into two sub-columns. The text below describes one row.

    Every state hub sits on the TOP row, left to right in flow order (veille ... eteint); it heads a column that
    holds the chains starting in that state, laid out with the layered band algorithm of `auto_layout()` one
    layer to the right of the hub and below its row (so the hub -> trigger wires fan out down-right). The
    `global` group gets the last column (no hub). Columns are disjoint in x, so nodes never overlap between
    columns; inside a column `auto_layout()` already guarantees no overlap. The wires that return to a state hub
    are not optimised (the editor draws them faded with a "→ État" badge, see web/editor.js).
    """
    # L7 fix round: the columns are built at the origin, then wrapped into rows (see _wrap_rows)
    hub_h = max([node_height(n) for n in nodes if n.get("kind") == "state"] + [0])
    chain_top = hub_h + HUB_GAP if hub_h else 0
    cols = [_hub_column(g, nodes, links, chain_top + (head or {}).get(g, 0), badge, pitch, stack) for g in hub_groups(nodes)]
    pos = {}
    for row in _wrap_rows(cols):
        x = 0
        for rel, w, _h in row["cols"]:
            for i, (rx, ry) in rel.items():
                pos[i] = (x + rx, y0 + row["y"] + ry)
            x += w + COL_GAP
    return pos


def _components(mine, links) -> list:
    """Connected groups of chain nodes (chain-internal links only), in order of first appearance."""
    ids = [n["id"] for n in mine]
    parent = {i: i for i in ids}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for lk in links:
        a, b = lk["from"], lk["to"]
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    out, seen = [], {}
    for i in ids:
        r = find(i)
        if r not in seen:
            seen[r] = len(out)
            out.append([])
        out[seen[r]].append(i)
    return out


def _band(sub, links, top, pitch: int = HUB_PITCH) -> dict:
    """auto_layout of one sub-band, x converted from COLW layers to `pitch` layers, starting at x = 0."""
    band = auto_layout(sub, links, top)
    return {i: ((bx // COLW) * pitch, by) for i, (bx, by) in band.items()}


def _hub_column(g, nodes, links, chain_top, badge: int = BADGE_ROOM, pitch: int = HUB_PITCH, stack: bool = False):
    """({id: (x, y)} relative to the column's top-left, width, height) of one state column.

    Hub at (0, 0); chains one layer to the right, from `chain_top` down. A column with more than SUBCOL_CHAINS
    chains (connected chain groups) is split into two side-by-side sub-columns of about equal height.
    """
    by_id = {n["id"]: n for n in nodes}
    rel = {n["id"]: (0, 0) for n in nodes if n.get("group") == g and n.get("kind") == "state"}
    mine = [n for n in nodes if n.get("group") == g and n.get("kind") != "state"]
    width, height = NODE_W, max([node_height(by_id[i]) for i in rel] + [0])
    if mine:
        x0 = pitch if rel else 0
        comps = _components(mine, links)
        parts = [comps]
        if len(comps) > SUBCOL_CHAINS:
            weight = [sum(node_height(by_id[i]) + GAP_Y for i in c) for c in comps]
            half, acc, k = sum(weight) / 2, 0, 0
            while k < len(comps) - 1 and acc + weight[k] / 2 < half:
                acc += weight[k]
                k += 1
            parts = [comps[:k], comps[k:]] if 0 < k < len(comps) else [comps]
        for part in parts:
            if stack:   # lot L1: every chain tree gets its own rows, so wires of two trees can never cross
                band, top = {}, chain_top
                for c in part:
                    cb = _band([n for n in mine if n["id"] in set(c)], links, top, pitch)
                    band.update(cb)
                    top = max(cb[i][1] + node_height(by_id[i]) for i in cb) + GAP_Y * 2
            else:
                sub_ids = {i for c in part for i in c}
                band = _band([n for n in mine if n["id"] in sub_ids], links, chain_top, pitch)
            for i, (bx, by) in band.items():
                rel[i] = (x0 + bx, by)
            x0 = max(rel[i][0] for i in band) + NODE_W + badge + SUBCOL_GAP
        width = max(rel[i][0] for i in rel) + NODE_W + badge
        height = max(rel[i][1] + node_height(by_id[i]) for i in rel)
    return rel, width, height


def _wrap_rows(cols) -> list:
    """Split the column list (flow order kept) into rows so the whole drawing gets close to TARGET_ASPECT.

    Every contiguous split into 1..4 rows is scored by the zoom that fits it in a TARGET_ASPECT x 1 canvas
    (min(aspect / W, 1 / H)); the best score wins, fewer rows on a tie. Returns [{"y", "cols"}]."""
    import itertools
    n = len(cols)
    best = None
    for k in range(1, min(MAX_ROWS, n) + 1):
        for cuts in itertools.combinations(range(1, n), k - 1):
            bounds = (0,) + cuts + (n,)
            rows = [cols[bounds[j]:bounds[j + 1]] for j in range(k)]
            w = max(sum(c[1] for c in r) + COL_GAP * (len(r) - 1) for r in rows)
            h = sum(max(c[2] for c in r) for r in rows) + ROW_GAP * (k - 1)
            score = min(TARGET_ASPECT / w, 1.0 / h)
            if best is None or score > best[0] * 1.0001:
                best = (score, rows)
    out, y = [], 0
    for r in best[1]:
        out.append({"y": y, "cols": r})
        y += max(c[2] for c in r) + ROW_GAP
    return out


def auto_layout(nodes, links, y0: int = TOP, hub: bool = False) -> dict:
    """{node id: (x, y)} for every node that has a group; see the module docstring for the rules.

    `hub=True` (state nodes): the `state` nodes form column 0, one per band, vertically centred on the band of
    their own chains; the chains of a state start one column to the right (triggers) and end on a wire that
    runs back to the destination state node. Only chain-internal links shape the rows (the wires into state
    nodes are long by nature and are left out of the crossing minimisation). The group `global` has no hub
    and gets the last band.
    """
    by_id = {n["id"]: n for n in nodes}
    order_idx = {n["id"]: i for i, n in enumerate(nodes)}
    groups = []
    for n in nodes:
        g = n.get("group")
        if g is not None and g not in groups:
            groups.append(g)
    pos, y_cursor = {}, y0
    xoff = COLW if hub else 0
    for g in groups:
        ids = [n["id"] for n in nodes if n.get("group") == g and not (hub and n.get("kind") == "state")]
        hubs = [n["id"] for n in nodes if hub and n.get("group") == g and n.get("kind") == "state"]
        if not ids:                              # a state without any chain: just its hub
            for i in hubs:
                pos[i] = (0, y_cursor)
                y_cursor += node_height(by_id[i]) + GROUP_GAP
            continue
        inb = set(ids)
        pred = {i: [] for i in ids}
        succ = {i: [] for i in ids}
        for lk in links:
            a, b = lk["from"], lk["to"]
            if a in inb and b in inb and b not in succ[a]:
                succ[a].append(b)
                pred[b].append(a)
        # column = longest path from a source; targets are pushed to the last column
        col = {i: 0 for i in ids}
        for _ in range(len(ids)):
            changed = False
            for i in ids:
                for p in pred[i]:
                    if col[i] < col[p] + 1:
                        col[i], changed = col[p] + 1, True
            if not changed:
                break
        terminal = {i for i in ids if by_id[i]["kind"] in ("goto", "end")}
        last = max([col[i] for i in ids if i not in terminal] + [0]) + 1
        for i in terminal:
            col[i] = last
        ncol = max(col.values()) + 1
        cols = [[i for i in ids if col[i] == c] for c in range(ncol)]
        rank = {i: r for c in cols for r, i in enumerate(c)}

        def bary(i, nbrs):
            ns = [rank[x] for x in nbrs[i] if x in rank]
            return sum(ns) / len(ns) if ns else rank[i]

        for _ in range(6):                      # barycentre sweeps (down then up)
            for c in range(1, ncol):
                cols[c].sort(key=lambda i: (bary(i, pred), order_idx[i]))
                rank.update({i: r for r, i in enumerate(cols[c])})
            for c in range(ncol - 2, -1, -1):
                cols[c].sort(key=lambda i: (bary(i, succ), order_idx[i]))
                rank.update({i: r for r, i in enumerate(cols[c])})
        h = {i: node_height(by_id[i]) for i in ids}
        links_g = [(a, b) for a in ids for b in succ[a]]

        def place(cols):
            """Row positions for a column order: stack, pull towards neighbours (order kept), no overlap."""
            y = {}
            for c in cols:
                cur = 0
                for i in c:
                    y[i], cur = cur, cur + h[i] + GAP_Y
            for sweep in range(8):               # alternate left-to-right / right-to-left pulls
                forward = sweep % 2 == 0
                for c in (range(ncol) if forward else range(ncol - 1, -1, -1)):
                    nb = pred if forward else succ
                    want = []
                    for i in cols[c]:
                        ns = [y[x] + h[x] / 2 for x in nb[i]]
                        want.append((sum(ns) / len(ns) - h[i] / 2) if ns else y[i])
                    for i, v in zip(cols[c], _no_overlap(want, [h[i] for i in cols[c]])):
                        y[i] = v
            return y

        def cost(y):
            """(link crossings, total vertical link length) of a placement; lower is better."""
            segs = [((col[a] * COLW + NODE_W, y[a] + h[a] / 2), (col[b] * COLW, y[b] + h[b] / 2), a, b) for a, b in links_g]
            n = 0
            for i in range(len(segs)):
                for j in range(i + 1, len(segs)):
                    p, q, a1, b1 = segs[i]
                    r, t, a2, b2 = segs[j]
                    if a1 == a2 or b1 == b2 or a1 == b2 or b1 == a2:
                        continue
                    if _orient(p, q, r) * _orient(p, q, t) < 0 and _orient(r, t, p) * _orient(r, t, q) < 0:
                        n += 1
            return n, sum(abs(y[a] + h[a] / 2 - y[b] - h[b] / 2) for a, b in links_g)

        y = place(cols)
        best = cost(y)
        for _ in range(3):                      # hill climb: swap adjacent rows of a column while it pays
            improved = False
            for c in range(ncol):
                for r in range(len(cols[c]) - 1):
                    cols[c][r], cols[c][r + 1] = cols[c][r + 1], cols[c][r]
                    y2 = place(cols)
                    c2 = cost(y2)
                    if c2 < best:
                        best, y, improved = c2, y2, True
                    else:
                        cols[c][r], cols[c][r + 1] = cols[c][r + 1], cols[c][r]
            if not improved:
                break
        top = min(y.values())
        for i in ids:
            pos[i] = (col[i] * COLW + xoff, int(round(y[i] - top + y_cursor)))
        bottom = max(pos[i][1] + h[i] for i in ids)
        for i in hubs:                           # hub centred on its band (never above the band top)
            hh = node_height(by_id[i])
            pos[i] = (0, int(round(y_cursor + max(0, (bottom - y_cursor - hh) / 2))))
            bottom = max(bottom, pos[i][1] + hh)
        y_cursor = bottom + GROUP_GAP
    return pos


def hub_frames(nodes, pos, colors=None, badge: int = BADGE_ROOM) -> list:
    """Automatic column frames of the hub drawing: one per column, in a muted copy of the state colour.

    Marked `auto: True` so the editor draws them translucent and distinct from user frames; they reach
    graph.layout.json only if the user saves (like any frame of the document)."""
    out = []
    for g in hub_groups(nodes):
        mine = [n for n in nodes if n.get("group") == g and n["id"] in pos]
        if not mine:
            continue
        x0 = min(pos[n["id"]][0] for n in mine) - 28
        y0 = min(pos[n["id"]][1] for n in mine) - 56
        x1 = max(pos[n["id"]][0] + NODE_W for n in mine) + 28 + (badge if any(n.get("kind") != "state" for n in mine) else 0)
        y1 = max(pos[n["id"]][1] + node_height(n) for n in mine) + 28
        colour = (colors or {}).get(g) or ("#e0504d" if g == "global" else "#8b949e")
        out.append({"id": "auto-" + str(g), "title": STATE_LABELS.get(g, str(g).capitalize()), "color": colour,
                    "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "auto": True,
                    "note": "Colonne automatique (cosmétique) : renommer, déplacer ou supprimer librement."})
    return out


def default_frames(nodes, pos) -> list:
    """Cosmetic theme frames around the bands of `pos` (only themes whose states exist in the graph)."""
    out = []
    for fid, title, colour, states in THEMES:
        mine = [n for n in nodes if n.get("group") in states and n["id"] in pos]
        if not mine:
            continue
        x0 = min(pos[n["id"]][0] for n in mine) - 28
        y0 = min(pos[n["id"]][1] for n in mine) - 56
        x1 = max(pos[n["id"]][0] + NODE_W for n in mine) + 28
        y1 = max(pos[n["id"]][1] + node_height(n) for n in mine) + 28
        out.append({"id": fid, "title": title, "color": colour, "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
                    "note": "Groupe automatique (cosmétique) : renommer, déplacer ou supprimer librement."})
    return out


def crossings(nodes, links, pos, chains_only: bool = False, returning: bool = True) -> int:
    """Number of link pairs whose drawn segments (right edge -> left edge, node middle) intersect.

    `chains_only=True` ignores every link that touches a state node or Start (hub drawing): the wires that
    return to a state hub are long by nature, the layout only optimises the links inside a chain.
    `returning=False` ignores the wires the editor draws faded: those that END in a state node, and those that
    leave a hub for another column (a global rule limited to some states).
    """
    by_id = {n["id"]: n for n in nodes}
    segs = []
    for lk in links:
        a, b = lk["from"], lk["to"]
        if chains_only and (by_id[a].get("kind") in ("state", "start") or by_id[b].get("kind") == "state"):
            continue
        if not returning and (by_id[b].get("kind") == "state" or (
                by_id[a].get("kind") == "state" and by_id[b].get("group") != by_id[a].get("group"))):
            continue     # faded in the editor: returning wires + hub wires to another column (global only_in)
        if a in pos and b in pos:
            pa, pb = pos[a], pos[b]
            segs.append((lk, (pa[0] + NODE_W, pa[1] + node_height(by_id[a]) / 2), (pb[0], pb[1] + node_height(by_id[b]) / 2)))

    def orient(u, v, w):
        return (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0])

    total = 0
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            la, a, b = segs[i]
            lb, p, q = segs[j]
            if {la["from"], la["to"]} & {lb["from"], lb["to"]}:
                continue
            if orient(a, b, p) * orient(a, b, q) < 0 and orient(p, q, a) * orient(p, q, b) < 0:
                total += 1
    return total


def overlaps(nodes, pos) -> list:
    """Pairs of node ids whose estimated boxes intersect."""
    boxes = [(n["id"], pos[n["id"]][0], pos[n["id"]][1], node_height(n)) for n in nodes if n["id"] in pos]
    bad = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if a[1] < b[1] + NODE_W and b[1] < a[1] + NODE_W and a[2] < b[2] + b[3] and b[2] < a[2] + a[3]:
                bad.append((a[0], b[0]))
    return bad
