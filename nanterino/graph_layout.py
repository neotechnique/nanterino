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

Sub-groups (lot L13): `var_layout(..., note_h=...)` groups the chain trees of each column into titled sub-groups
    (rule table SUB_RULES / SUB_AFTER keyed by the trigger, see `sub_plan`), each a block with a short post-it;
    `var_frames()` returns the column frames grown around them plus the sub-group frames (parent = the column).

Domains (lot S1): `domain_layout()` runs the variables drawing PER DOMAIN (Dialogue, Comportement, Mouvement,
    Système) and packs one region per domain on a grid; `region_rect()` is the region formula the editor mirrors. The
    cosmetic theme frames (THEMES / `default_frames`, ids `t-*`) are only drawn by the legacy go-to form: the domain
    regions replace them as the level above the columns. Organisation only: nothing here reaches graph.yaml.
Lot S2: `region_boxes()` (drawn regions: folded cards FOLD_COL / FOLD_DOM, the domain post-it), `pack_positions()`
    (grid repack, rows by top within ROW_TOL) and `repack_regions()` (moves each region with its content when two drawn
    regions overlap) mirror web/editor/domains/domains.js; graph_visual.to_visual repairs saved layouts with it.

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

THEMES = [               # (frame id, title, colour, state groups) - cosmetic only, legacy go-to drawing (S1: domains)
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


def var_layout(nodes, links, y0: int = TOP, head: dict | None = None, note_h=None, subs_out: list | None = None) -> dict:
    """Columns layout of the variables drawing (lot L1): no state node, one column per state group in order of first
    appearance (the state order of the graph), `global` last, columns wrapped into rows like hub_layout. Every link of
    this drawing stays inside its column (shared nodes only join chains of one group), so the only crossings are the
    ones the band algorithm leaves inside a column; no room is kept for "→ État" badges and layers use COLW.
    `head` (lot L9): {group: px} of free room kept at the top of a column, above its first chain (default post-it).
    `note_h` (lot L13): callable(text) -> px height of a sub-group post-it; when given, the chains of each column are
    grouped into titled sub-groups (see `sub_plan`) and their rectangles are appended to `subs_out` (see
    `var_frames`). Without it the columns stay flat (pre-L13 drawing, kept for callers and tests)."""
    return hub_layout(nodes, links, y0, badge=0, pitch=COLW, stack=True, head=head, note_h=note_h, subs_out=subs_out)


# ---- lot L13 (2026-11-01): default sub-groups inside the state columns (variables drawing)
# Every chain tree (connected chain component) of a column is classified by its TRIGGER with the rule table below, so
# the grouping follows graph.yaml when it changes: SUB_RULES maps (column or None for any column, event) -> key; an
# `after:` heartbeat is keyed by its delay parameter (SUB_AFTER); "etat devient <column>" is the column's « Entrée ».
# A key with no rule -> « Autres » when the column has two such chains or more; a single unknown chain stays loose
# (no frame, below the sub-groups). Sub-groups are ordered by SUB_ORDER (reading order), not by YAML order.
# Cosmetic only: the sub-group frames / post-its live in graph.layout.json, the compiler never sees them.
SUB_RULES = {
    (None, "visage"): "reveil", (None, "intent.appel"): "reveil", ("veille", "start"): "reveil",
    (None, "ask"): "question_tapee", (None, "greeting_done"): "fin_salutation",
    # G2: the accueil greeting starts on conversation_started; a varied greeting ends with say_done
    ("accueil", "conversation_started"): "salutation", ("accueil", "say_done"): "fin_salutation",
    ("global", "conversation_ended"): "fin_conversation",
    (None, "intent.question"): "questions", (None, "not_understood"): "pas_compris",
    # G3: the help phrase at the repair bound ends with say_done (ecoute, relance; accueil keeps its own rule above);
    # loud noises and the journal summary are global rules
    (None, "say_done"): "fin_aide", ("global", "loud_noise"): "bruit",
    ("global", "hour_changed"): "bilan", ("global", "day_changed"): "bilan",
    (None, "intent.au_revoir"): "depart", (None, "visage_perdu"): "depart",
    (None, "intent.chanson"): "chanson", (None, "sing"): "chanson",
    (None, "answer_done"): "fin_reponse", (None, "barge_in"): "interruption",
    (None, "relance_done"): "fin_relance", (None, "goodbye_done"): "au_revoir_termine",
    (None, "cloture_done"): "retour_veille", ("eteint", "on"): "rallumer", ("eteint", "start"): "rallumer",
    ("global", "stop"): "boutons", ("global", "off"): "boutons", ("global", "hush"): "tais_toi",
}
SUB_AFTER = {"silence_relance_s": "silence_relance", "silence_cloture_s": "silence_cloture"}
# (column, delay) first (G2: the accueil safety delay is not a silence rule), then SUB_AFTER
# G3: the visitor-left rules use the graph constant 11 (seconds of silence, see graph.yaml); an edited delay simply
# leaves that chain loose (no frame), it never breaks the drawing
SUB_AFTER_COL = {("accueil", "silence_cloture_s"): "secours", ("ecoute", "11"): "visiteur_parti",
                 ("relance", "11"): "visiteur_parti"}
SUB_ORDER = ["entree", "boutons", "tais_toi", "reveil", "salutation", "fin_salutation", "secours", "questions", "pas_compris",
             "fin_aide", "silence_relance", "fin_reponse", "interruption", "fin_relance", "silence_cloture",
             "visiteur_parti", "depart", "chanson", "question_tapee", "fin_conversation", "bruit", "bilan",
             "au_revoir_termine", "retour_veille", "rallumer", "autres"]
SUB_TITLES = {
    "entree": "Entrée", "reveil": "Réveil", "question_tapee": "Question tapée", "fin_salutation": "Fin de salutation",
    "questions": "Questions", "pas_compris": "Pas compris", "silence_relance": "Silence → relance",
    "silence_cloture": "Silence → clôture", "depart": "Départ du visiteur", "chanson": "Chanson",
    "fin_reponse": "Fin de réponse", "interruption": "Interruption", "fin_relance": "Fin de relance",
    "au_revoir_termine": "Au revoir terminé", "retour_veille": "Retour en veille", "rallumer": "Rallumer",
    "boutons": "Boutons", "tais_toi": "Tais-toi", "autres": "Autres",
    "salutation": "Salutation", "secours": "Secours", "fin_conversation": "Fin de conversation",
    "visiteur_parti": "Visiteur parti", "fin_aide": "Fin de l'aide", "bruit": "Bruit fort", "bilan": "Bilan du journal",
}
# short French post-it text of a sub-group: (column, key) first, then the key alone
SUB_TEXTS = {
    ("veille", "entree"): "En veille : la conversation est oubliée et le micro se rouvre.",
    ("accueil", "entree"): "Micro coupé ; la salutation part du début de la conversation.",
    ("ecoute", "entree"): "Sous-titre « j'écoute », compteur de silence remis à zéro, micro ouvert.",
    ("relance", "entree"): "Micro coupé, le robot relance le visiteur.",
    ("cloture", "entree"): "Micro coupé, historique effacé, le robot dit au revoir.",
    ("eteint", "entree"): "Conversation oubliée, micro coupé : le robot n'écoute plus.",
    "entree": "Ce que le robot fait en arrivant dans cet état.",
    "reveil": "Un visage, le bouton Démarrer ou « Nanterino » : le robot salue.",
    # G1: the veille column also holds the "face seen while deaf" note chain
    ("veille", "reveil"): "Un visage (sauf robot sourd ou hors des horaires d'ouverture), le bouton Démarrer ou « Nanterino » : le robot salue.",
    "question_tapee": "Question tapée au tableau de bord : traitée comme une phrase entendue.",
    "fin_salutation": "Salutation finie : le robot écoute.",
    # G2: the accueil column (greeting choice + safety delay)
    "salutation": "Début de conversation : salut au groupe (2 visages ou plus), sinon la phrase de la configuration ou une phrase variée.",
    ("accueil", "fin_salutation"): "Salutation finie (phrase de la configuration ou variée) : le robot écoute.",
    "secours": "Rien n'a fini la salutation après 15 s : écouter quand même (jamais bloqué en accueil).",
    "fin_conversation": "Fin d'une conversation : tirer au hasard la prochaine salutation d'un visiteur seul.",
    "questions": "Une question reçoit une réponse ; après trop d'échanges, le robot conclut.",
    "pas_compris": "Parole inexploitable : faire répéter (2 fois au plus), puis une phrase d'aide, puis ne plus insister.",
    "silence_relance": "Silence prolongé : relancer le visiteur, sauf s'il n'y a plus de visage depuis 20 s.",
    "silence_cloture": "Toujours rien après la relance, aucune transcription en cours (ou micro fermé, robot sourd) : conclure.",
    # G3 sub-groups
    "visiteur_parti": "Plus de visage depuis 20 s et 11 s de silence : dire au revoir sans relancer une salle vide.",
    ("relance", "visiteur_parti"): "Après la relance, plus de visage depuis 20 s et 11 s de silence : conclure plus tôt.",
    "fin_aide": "Phrase d'aide dite : rouvrir le micro, le chrono de silence repart de zéro.",
    "bruit": "Bruit fort pendant la conversation : note au journal, délai de silence prolongé (2 fois au plus).",
    "bilan": "Chaque heure et à minuit : une ligne d'état au journal (visiteurs, erreurs), jamais ce que dit le visiteur.",
    "depart": "Le visiteur part (au revoir, ou visage perdu si activé) : dire au revoir.",
    "chanson": "Une chanson demandée : le robot chante.",
    ("global", "chanson"): "Événement sing : couper le reste et chanter (sauf éteint).",
    "fin_reponse": "Réponse finie : écouter la suite.",
    "interruption": "Le visiteur coupe la parole (si activé) : se taire et écouter.",
    "fin_relance": "Relance finie : rouvrir le micro et attendre la réponse.",
    "au_revoir_termine": "Au revoir dit : courte pause avant la veille.",
    "retour_veille": "Pause finie : retour en veille.",
    "rallumer": "Bouton Allumer ou Démarrer : le robot se rallume.",
    "boutons": "Boutons Stop et Éteindre du tableau de bord, valables partout.",
    "tais_toi": "« Tais-toi » : se taire, selon l'état en cours (3 cas).",
    ("global", "question_tapee"): "Question tapée hors veille : traitée comme une phrase entendue.",
    "autres": "Chaînes sans sous-groupe connu.",
}
SUB_HEAD = 40           # sub-group frame top -> its post-it (the 32 px title bar of a user frame + 8)
SUB_NOTE_GAP = 22       # post-it bottom -> first node of the sub-group
SUB_PAD = 28            # free space between a sub-group frame and its nodes (left, right)
SUB_PAD_B = 24          # ... and below its last node
SUB_GAP = 36            # vertical space between two sub-groups of one column
COL_PAD = 20            # column frame <-> its sub-groups (left, right, bottom)
COL_PAD_T = 40          # column frame top -> first sub-group (room under the column post-it)


def sub_key(group, trig: dict) -> str | None:
    """Sub-group key of a chain from its trigger params (None = no rule)."""
    if not trig:
        return None
    if trig.get("type") == "after":
        return SUB_AFTER_COL.get((group, str(trig.get("delay")))) or SUB_AFTER.get(str(trig.get("delay")))
    ev = trig.get("event")
    if ev == "var_changed" and trig.get("name") == "etat" and trig.get("value") == group:
        return "entree"
    return SUB_RULES.get((group, ev)) or SUB_RULES.get((None, ev))


def sub_text(group, key) -> str:
    return SUB_TEXTS.get((group, key)) or SUB_TEXTS.get(key) or ""


def sub_plan(g, comps, by_id) -> list:
    """[(key or None, [component, ...])] of one column, in SUB_ORDER, loose (None) last; see the rule table."""
    keyed = {}
    for c in comps:
        trig = next((by_id[i].get("params") or {} for i in c if by_id[i].get("kind") == "trigger"), {})
        keyed.setdefault(sub_key(g, trig) or "", []).append(c)
    unknown = keyed.pop("", [])
    if len(unknown) >= 2:
        keyed.setdefault("autres", []).extend(unknown)
        unknown = []
    out = [(k, keyed[k]) for k in sorted(keyed, key=lambda k: (SUB_ORDER.index(k) if k in SUB_ORDER else len(SUB_ORDER), k))]
    return out + ([(None, unknown)] if unknown else [])


def _shade(colour: str, k: int) -> str:
    """Colour of the k-th sub-group of a column: the column colour, then alternately lighter / darker variants
    (harmonised with the column, neighbours still told apart)."""
    try:
        r, gg, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    except (TypeError, ValueError):
        r, gg, b = 0x8b, 0x94, 0x9e
    t = (0.0, 0.25, -0.22, 0.45, -0.38)[k % 5]
    tgt = 255 if t > 0 else 0
    return "#%02x%02x%02x" % tuple(int(round(v + (tgt - v) * abs(t))) for v in (r, gg, b))


def var_frames(nodes, pos, subs, colors=None) -> list:
    """Lot L13: automatic column frames (as `hub_frames(..., badge=0)`, grown to contain their sub-groups with
    COL_PAD margins) followed by the sub-group frames of `subs` (from var_layout `subs_out`). A sub-group frame is a
    plain user frame (no `auto`, so the editor lets the user edit it like any group) with `parent` = its column and
    `gen: "sub:<column>:<key>"`; its post-it data rides on the private `_note` key (graph_visual.sub_notes pops it)."""
    cols = hub_frames(nodes, pos, colors, badge=0)
    by_g = {}
    for s in subs:
        by_g.setdefault(s["group"], []).append(s)
    for f in cols:
        mine = by_g.get(f["id"][5:])
        if not mine:
            continue
        loose = [n for n in nodes if n.get("group") == f["id"][5:] and n["id"] in pos and not any(n["id"] in s["ids"] for s in mine)]
        x0 = min([s["x"] - COL_PAD for s in mine] + [pos[n["id"]][0] - 28 for n in loose])
        y0 = min([s["y"] - COL_PAD_T for s in mine] + [pos[n["id"]][1] - 56 for n in loose])
        x1 = max([s["x"] + s["w"] + COL_PAD for s in mine] + [pos[n["id"]][0] + NODE_W + 28 for n in loose])
        y1 = max([s["y"] + s["h"] + COL_PAD for s in mine] + [pos[n["id"]][1] + node_height(n) + 28 for n in loose])
        f.update({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})
    out = []
    for f in cols:
        g = f["id"][5:]
        for k, s in enumerate(by_g.get(g, [])):
            fid = "sub-%s-%s" % (g, s["key"])
            out.append({"id": fid, "title": SUB_TITLES.get(s["key"], s["key"]), "color": _shade(f["color"], k),
                        "x": s["x"], "y": s["y"], "w": s["w"], "h": s["h"], "parent": f["id"], "gen": "sub:%s:%s" % (g, s["key"]),
                        "note": "Sous-groupe automatique (cosmétique) : renommer, déplacer ou supprimer librement.",
                        "_note": {"text": s["text"], "x": s["x"] + 16, "y": s["y"] + SUB_HEAD, "h": s["nh"]}})
    return cols + out


def hub_layout(nodes, links, y0: int = TOP, badge: int = BADGE_ROOM, pitch: int = HUB_PITCH, stack: bool = False,
               head: dict | None = None, note_h=None, subs_out: list | None = None) -> dict:
    """Columns layout of the state-node (hub) drawing (L7, 2026-10-31; fix round: columns wrapped into rows).

    Fix round: the columns (flow order kept) are wrapped into 1..4 rows chosen by `_wrap_rows()` for an
    overall aspect close to TARGET_ASPECT; hubs sit at the top of their column (one hub row per row); a column
    with more than SUBCOL_CHAINS chain groups is split into two sub-columns. The text below describes one row.

    Every state hub sits on the TOP row, left to right in flow order (veille ... eteint); it heads a column that
    holds the chains starting in that state, laid out with the layered band algorithm of `auto_layout()` one
    layer to the right of the hub and below its row (so the hub -> trigger wires fan out down-right). The
    `global` group gets the last column (no hub). Columns are disjoint in x, so nodes never overlap between
    columns; inside a column `auto_layout()` already guarantees no overlap. The wires that return to a state hub
    are not optimised (the editor draws them faded with a "→ État" badge, see web/editor/canvas/wires.js).
    """
    # L7 fix round: the columns are built at the origin, then wrapped into rows (see _wrap_rows)
    hub_h = max([node_height(n) for n in nodes if n.get("kind") == "state"] + [0])
    chain_top = hub_h + HUB_GAP if hub_h else 0
    cols = [_hub_column(g, nodes, links, chain_top + (head or {}).get(g, 0), badge, pitch, stack, note_h)
            for g in hub_groups(nodes)]
    pos = {}
    for row in _wrap_rows(cols):
        x = 0
        for rel, w, _h, subs in row["cols"]:
            for i, (rx, ry) in rel.items():
                pos[i] = (x + rx, y0 + row["y"] + ry)
            if subs_out is not None:      # lot L13: sub-group rectangles, moved with their column
                subs_out.extend(dict(s, x=x + s["x"], y=y0 + row["y"] + s["y"]) for s in subs)
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


def _split_half(items, weight):
    """Index k cutting `items` into two runs of about equal total weight (0 = no split)."""
    half, acc, k = sum(weight) / 2, 0, 0
    while k < len(items) - 1 and acc + weight[k] / 2 < half:
        acc += weight[k]
        k += 1
    return k if 0 < k < len(items) else 0


def _sub_column(g, mine, links, chain_top, by_id, note_h):
    """Lot L13 form of a variables column: (rel, width, height, subs). The chain trees are grouped by `sub_plan`;
    each sub-group is a block (frame top, 32 px title, post-it, its chains stacked like `stack=True`, bottom pad),
    blocks stacked top to bottom with SUB_GAP; loose chains (no sub-group) follow the blocks. More than
    SUBCOL_CHAINS chains: the BLOCKS (never a block) are split into two side-by-side sub-columns. All frames of one
    sub-column get the same width. Coordinates start at COL_PAD so the grown column frame starts at x = 0."""
    plan = sub_plan(g, _components(mine, links), by_id)
    parts = [plan]
    if sum(len(cs) for _k, cs in plan) > SUBCOL_CHAINS:
        weight = [sum(node_height(by_id[i]) + GAP_Y * 2 for c in cs for i in c) + (SUB_HEAD + 60 if k else 0) for k, cs in plan]
        cut = _split_half(plan, weight)
        parts = [plan[:cut], plan[cut:]] if cut else [plan]
    rel, subs, x0 = {}, [], COL_PAD
    for part in parts:
        top, mine_subs, right = chain_top, [], x0 + NODE_W + 2 * SUB_PAD
        for key, cs in part:
            text = sub_text(g, key) if key else ""
            nh = note_h(text) if key else 0
            ntop = top + SUB_HEAD + nh + SUB_NOTE_GAP if key else top
            ids, cur = [], ntop
            for c in cs:
                cb = _band([n for n in mine if n["id"] in set(c)], links, cur, COLW)
                for i, (bx, by) in cb.items():
                    rel[i] = (x0 + SUB_PAD + bx, by)
                    right = max(right, rel[i][0] + NODE_W + SUB_PAD)
                ids += list(cb)
                cur = max(cb[i][1] + node_height(by_id[i]) for i in cb) + GAP_Y * 2
            bottom = max(rel[i][1] + node_height(by_id[i]) for i in ids)
            if key:
                mine_subs.append({"group": g, "key": key, "text": text, "nh": nh, "ids": ids,
                                  "x": x0, "y": top, "h": bottom + SUB_PAD_B - top})
                top = bottom + SUB_PAD_B + SUB_GAP
            else:
                top = bottom + GAP_Y * 2
        for s in mine_subs:
            s["w"] = right - x0
        subs += mine_subs
        x0 = right + SUBCOL_GAP
    width = max([s["x"] + s["w"] for s in subs] + [rel[i][0] + NODE_W + SUB_PAD for i in rel]) + COL_PAD
    height = max([s["y"] + s["h"] for s in subs] + [rel[i][1] + node_height(by_id[i]) for i in rel]) + COL_PAD
    return rel, width, height, subs


def _hub_column(g, nodes, links, chain_top, badge: int = BADGE_ROOM, pitch: int = HUB_PITCH, stack: bool = False,
                note_h=None):
    """({id: (x, y)} relative to the column's top-left, width, height, sub-groups) of one state column.

    Hub at (0, 0); chains one layer to the right, from `chain_top` down. A column with more than SUBCOL_CHAINS
    chains (connected chain groups) is split into two side-by-side sub-columns of about equal height.
    `note_h` (lot L13, variables drawing only): titled sub-groups, see `_sub_column`; otherwise sub-groups = [].
    """
    by_id = {n["id"]: n for n in nodes}
    rel = {n["id"]: (0, 0) for n in nodes if n.get("group") == g and n.get("kind") == "state"}
    mine = [n for n in nodes if n.get("group") == g and n.get("kind") != "state"]
    width, height = NODE_W, max([node_height(by_id[i]) for i in rel] + [0])
    if mine and note_h is not None and stack and not rel:
        return _sub_column(g, mine, links, chain_top, by_id, note_h)
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
    return rel, width, height, []


def _wrap_rows(cols, gap_x: int = COL_GAP, gap_y: int = ROW_GAP, max_rows: int = MAX_ROWS) -> list:
    """Split the column list (flow order kept) into rows so the whole drawing gets close to TARGET_ASPECT.

    Every contiguous split into 1..max_rows rows is scored by the zoom that fits it in a TARGET_ASPECT x 1 canvas
    (min(aspect / W, 1 / H)); the best score wins, fewer rows on a tie. Returns [{"y", "cols"}].
    `cols` items are tuples whose [1] is the width and [2] the height (columns, or S1 domain regions with their own
    gaps and row limit, see domain_layout)."""
    import itertools
    n = len(cols)
    best = None
    for k in range(1, min(max_rows, n) + 1):
        for cuts in itertools.combinations(range(1, n), k - 1):
            bounds = (0,) + cuts + (n,)
            rows = [cols[bounds[j]:bounds[j + 1]] for j in range(k)]
            w = max(sum(c[1] for c in r) + gap_x * (len(r) - 1) for r in rows)
            h = sum(max(c[2] for c in r) for r in rows) + gap_y * (k - 1)
            score = min(TARGET_ASPECT / w, 1.0 / h)
            if best is None or score > best[0] * 1.0001:
                best = (score, rows)
    out, y = [], 0
    for r in best[1]:
        out.append({"y": y, "cols": r})
        y += max(c[2] for c in r) + gap_y
    return out


# ---- lot S1 (2026-11-03): domains, a navigable level ABOVE the state columns (one graph for the whole robot)
# A domain (Dialogue, Comportement, Mouvement, Système) groups state columns; it is ORGANISATION ONLY: the compiler and
# the engine never see it (graph.yaml is unchanged, the mapping lives in graph.layout.json `columns` / `domains`, see
# graph_visual.domain_doc and Notes/graph-visual-format.md « Domaines »). Every state column defaults to « Dialogue »,
# the global rules column to « Système ». Each domain is drawn as a REGION: the bounding box of its column frames
# grown by DOM_PAD (DOM_HEAD on top for its title), or a fixed EMPTY_W x EMPTY_H box (with an explanatory post-it)
# when it holds no column. The server lays the columns out PER DOMAIN (var_layout, so the MAX_ROWS wrap applies inside
# one domain, not to the whole robot) and packs the regions on a grid with _wrap_rows (domain order kept, DOM_GAP).
# The editor computes the same region rectangle from the same frames (web/editor/domains/domains.js REGION_PAD).
DOMAINS = [   # id, label, colour, icon (one of the vendored Tabler icons), order, post-it text of the region
    {"id": "dialogue", "label": "Dialogue", "color": "#4f8ef7", "icon": "message", "order": 1,
     "note": "Dialogue : la conversation avec le visiteur (veille, accueil, écoute, réponse, relance, clôture)."},
    {"id": "comportement", "label": "Comportement", "color": "#2fb59a", "icon": "mood-smile", "order": 2,
     "note": "Comportement (vide pour l'instant) : l'attitude du robot hors dialogue (humeur, réactions, routines). "
             "Glisser une colonne ici dans la hiérarchie pour l'y ranger."},
    {"id": "mouvement", "label": "Mouvement", "color": "#e0a030", "icon": "hand-move", "order": 3,
     "note": "Mouvement (vide pour l'instant) : tête et cou, bras, base mobile. Les futures règles de mouvement "
             "viendront ici."},
    {"id": "systeme", "label": "Système", "color": "#c0504d", "icon": "power", "order": 4,
     "note": "Système / global : règles valables partout (boutons, tais-toi, bilan du journal) et réglages du robot."},
]
DEFAULT_DOMAIN = "dialogue"     # every state column without a saved domain
GLOBAL_DOMAIN = "systeme"       # the global rules column
DOM_PAD = 60                    # region border <-> its column frames (left, right, bottom)
DOM_HEAD = 240                  # region top <-> its highest column frame: domain title + zoom-scaled column titles
DOM_GAP = 260                   # free space between two regions
EMPTY_W, EMPTY_H = 900, 480     # region of a domain without any column (room for its post-it)


def default_domain(group) -> str:
    return GLOBAL_DOMAIN if group == "global" else DEFAULT_DOMAIN


def region_rect(boxes) -> dict | None:
    """Region rectangle {x, y, w, h} around column frame boxes [(x0, y0, x1, y1)], or None without any box."""
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes) - DOM_PAD
    y0 = min(b[1] for b in boxes) - DOM_HEAD
    x1 = max(b[2] for b in boxes) + DOM_PAD
    y1 = max(b[3] for b in boxes) + DOM_PAD
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def domain_layout(nodes, links, col_dom: dict, domains=None, y0: int = TOP, head: dict | None = None, note_h=None,
                  subs_out: list | None = None, regions_out: list | None = None) -> dict:
    """Lot S1: the variables-drawing layout run PER DOMAIN, regions packed on a grid.

    `col_dom` {column group: domain id} (missing -> default_domain); `domains` the ordered domain list (default
    DOMAINS); `head` / `note_h` / `subs_out` as var_layout (sub-group rectangles moved with their region). Each domain
    is laid out alone at the origin with var_layout (so links, which never leave a column, keep the 0-crossing
    guarantee), its region measured with region_rect on its column frames (var_frames, grown upward by `head` like
    graph_visual.column_notes does), then the regions are wrapped into rows (_wrap_rows, DOM_GAP, any row count) and
    every position shifted. `regions_out` receives [{id, x, y, w, h, empty}] in domain order. Returns {id: (x, y)}."""
    doms = [d["id"] for d in (domains or DOMAINS)]
    for n in nodes:   # a column mapped to a domain that is not in the table still gets a region (after the others)
        d = col_dom.get(n.get("group")) or default_domain(n.get("group"))
        if n.get("group") is not None and d not in doms:
            doms.append(d)
    head = head or {}
    blocks = []
    for d in doms:
        mine = [n for n in nodes if n.get("group") is not None and (col_dom.get(n["group"]) or default_domain(n["group"])) == d]
        if not mine:
            blocks.append((d, EMPTY_W, EMPTY_H, {}, [], (0, 0)))
            continue
        subs = []
        rel = var_layout(mine, links, 0, head=head, note_h=note_h, subs_out=subs)
        boxes = []
        for f in var_frames(mine, rel, subs):
            if f.get("auto"):   # column frame; its default post-it grows it upward by head[g] (column_notes)
                boxes.append((f["x"], f["y"] - head.get(f["id"][5:], 0), f["x"] + f["w"], f["y"] + f["h"]))
        r = region_rect(boxes)
        blocks.append((d, r["w"], r["h"], rel, subs, (r["x"], r["y"])))
    pos = {}
    for row in _wrap_rows(blocks, DOM_GAP, DOM_GAP, max(1, len(blocks))):
        x = 0
        for d, w, h, rel, subs, (ox, oy) in row["cols"]:
            dx, dy = x - ox, y0 + row["y"] - oy      # region top-left lands at (x, y0 + row y)
            for i, (rx, ry) in rel.items():
                pos[i] = (rx + dx, ry + dy)
            if subs_out is not None:
                subs_out.extend(dict(s, x=s["x"] + dx, y=s["y"] + dy) for s in subs)
            if regions_out is not None:
                regions_out.append({"id": d, "x": x, "y": y0 + row["y"], "w": w, "h": h, "empty": not rel})
            x += w + DOM_GAP
    if regions_out is not None:
        regions_out.sort(key=lambda r: doms.index(r["id"]))
    return pos


# ---- lot S2 (2026-11-04): folds that reclaim space, overlapping regions repaired on load
# Mirror of web/editor/domains/domains.js (domainRect, packPositions, packRegions). The editor repacks the regions on
# every fold / unfold (a folded column is drawn as a FOLD_COL card, a folded domain as a FOLD_DOM card); the server
# repacks a SAVED layout only when two of its regions overlap (layouts written before S1 / S2, a hand mapping of a
# column to another domain whose frame did not move), so the editor never receives overlapping regions. The repack is
# deterministic: same layout in, same positions out; a packed layout (the default grid) packs to itself.
FOLD_COL_W, FOLD_COL_H = 340, 190   # editor canvas/geometry.js FOLD_COL
FOLD_DOM_W, FOLD_DOM_H = 520, 250   # editor canvas/geometry.js FOLD_DOM
ROW_TOL = DOM_GAP                   # pack_positions: same row when the tops differ by less


def _frame_col(f) -> str | None:
    """State column of an automatic column frame (`auto-<group>`), else None."""
    fid = str(f.get("id", ""))
    return fid[5:] if f.get("auto") and fid.startswith("auto-") else None


def _dom_of(doc, g) -> str:
    ids = {d["id"] for d in doc.get("domains") or []}
    e = (doc.get("columns") or {}).get(g) or {}
    return e["domain"] if e.get("domain") in ids else default_domain(g)


def region_boxes(doc: dict, full: bool = False) -> dict:
    """{domain id: {x, y, w, h}} drawn by the editor: column frames (a folded column = its FOLD_COL card) plus the
    domain's explanatory post-it (`auto: "domain:<id>"`, top level), grown like region_rect; else the stored rectangle;
    a folded domain = its FOLD_DOM card at the same top-left. `full=True`: as if nothing were folded (what it owns)."""
    cols = doc.get("columns") or {}
    out = {}
    for d in doc.get("domains") or []:
        boxes = []
        for f in doc.get("frames") or []:
            g = _frame_col(f)
            if g is None or _dom_of(doc, g) != d["id"]:
                continue
            fold = not full and (cols.get(g) or {}).get("folded")
            boxes.append((f["x"], f["y"], f["x"] + (FOLD_COL_W if fold else f["w"]), f["y"] + (FOLD_COL_H if fold else f["h"])))
        if boxes:
            for n in doc.get("notes") or []:
                if n.get("auto") == "domain:" + d["id"] and not n.get("parent"):
                    boxes.append((n["x"], n["y"], n["x"] + n["w"], n["y"] + n.get("h", 0)))
            r = region_rect(boxes)
        elif all(isinstance(d.get(k), (int, float)) for k in ("x", "y", "w", "h")) and d["w"] > 0 and d["h"] > 0:
            r = {k: d[k] for k in ("x", "y", "w", "h")}
        else:
            r = None
        if r and d.get("folded") and not full:
            r = {"x": r["x"], "y": r["y"], "w": FOLD_DOM_W, "h": FOLD_DOM_H}
        if r:
            out[d["id"]] = r
    return out


def overlapping_regions(rects: dict) -> list:
    """[(id a, id b)] of region rectangles that overlap (strictly: touching edges do not count)."""
    ids = list(rects)
    return [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]
            if rects[a]["x"] < rects[b]["x"] + rects[b]["w"] and rects[b]["x"] < rects[a]["x"] + rects[a]["w"]
            and rects[a]["y"] < rects[b]["y"] + rects[b]["h"] and rects[b]["y"] < rects[a]["y"] + rects[a]["h"]]


def pack_positions(items: list) -> dict:
    """Grid positions {id: (x, y)} of region rectangles [{id, x, y, w, h, i}] (i = domain order). Sorted by top, then
    left, then i; a region starts a new row when its top is ROW_TOL or more below the row's first top; rows stacked from
    the top-left corner of all regions, DOM_GAP between rows (row height = its tallest region) and between regions."""
    if not items:
        return {}
    x0, y0 = min(r["x"] for r in items), min(r["y"] for r in items)
    rows = []
    for r in sorted(items, key=lambda r: (r["y"], r["x"], r["i"])):
        if rows and r["y"] - rows[-1]["top"] < ROW_TOL:
            rows[-1]["items"].append(r)
        else:
            rows.append({"top": r["y"], "items": [r]})
    out, y = {}, y0
    for row in rows:
        x = x0
        for r in sorted(row["items"], key=lambda r: (r["x"], r["i"])):
            out[r["id"]] = (x, y)
            x += r["w"] + DOM_GAP
        y += max(r["h"] for r in row["items"]) + DOM_GAP
    return out


def _centre_in(box, r) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return r["x"] <= cx <= r["x"] + r["w"] and r["y"] <= cy <= r["y"] + r["h"]


def _domain_content(doc, d, claimed: set, rect) -> dict:
    """What a region owns (mirror of the editor's domainContent): its column frames with their sub-groups (parent
    links) and their post-its, the nodes of its column groups, its explanatory post-it, then the loose top-level groups
    / post-its / nodes (no column) whose centre lies in its full rectangle. `claimed` (ids) keeps every item in ONE
    region: the first that claims it, in domain order. Returns {"frames": [...], "notes": [...], "nodes": [...]}."""
    out = {"frames": [], "notes": [], "nodes": []}
    frames, notes = doc.get("frames") or [], doc.get("notes") or []

    def take(kind, it):
        key = (kind, it["id"])
        if key not in claimed:
            claimed.add(key)
            out[kind].append(it)

    def subtree(f):
        ids, todo = {f["id"]}, [f["id"]]
        while todo:
            cur = todo.pop()
            for g in frames:
                if g.get("parent") == cur and g["id"] not in ids:
                    ids.add(g["id"])
                    todo.append(g["id"])
        return ids

    col_groups = {_frame_col(f) for f in frames if _frame_col(f)}
    groups, owned = set(), set()
    for f in frames:
        g = _frame_col(f)
        if g is not None and _dom_of(doc, g) == d["id"]:
            groups.add(g)
            owned |= subtree(f)
    for f in frames:
        if f["id"] in owned:
            take("frames", f)
    for n in notes:
        if n.get("parent") in owned or (n.get("auto") == "domain:" + d["id"] and not n.get("parent")):
            take("notes", n)
    for n in doc.get("nodes") or []:
        if n.get("group") in groups:
            take("nodes", n)
    if rect:
        for f in frames:
            if not f.get("auto") and not f.get("parent") and _centre_in((f["x"], f["y"], f["x"] + f["w"], f["y"] + f["h"]), rect):
                sub = subtree(f)
                for g in frames:
                    if g["id"] in sub:
                        take("frames", g)
                for n in notes:
                    if n.get("parent") in sub:
                        take("notes", n)
        for n in notes:
            if not n.get("parent") and _centre_in((n["x"], n["y"], n["x"] + n["w"], n["y"] + n.get("h", 0)), rect):
                take("notes", n)
        for n in doc.get("nodes") or []:
            if n.get("group") not in col_groups and _centre_in((n["x"], n["y"], n["x"] + NODE_W, n["y"] + node_height(n)), rect):
                take("nodes", n)
    return out


def repack_regions(doc: dict, force: bool = False) -> int:
    """Lot S2: repack the domain regions of an editor document on their grid (pack_positions) with their whole content
    (frames, post-its, nodes; stored rectangles of the domains too). Only when two drawn regions overlap, unless
    `force`. Mutates `doc`; returns the number of regions moved (0 = untouched)."""
    rects = region_boxes(doc)
    if not rects or (not force and not overlapping_regions(rects)):
        return 0
    full = region_boxes(doc, full=True)
    order = [d["id"] for d in doc.get("domains") or [] if d["id"] in rects]
    claimed = set()
    content = {i: _domain_content(doc, next(d for d in doc["domains"] if d["id"] == i), claimed, full.get(i)) for i in order}
    pos = pack_positions([dict(rects[i], id=i, i=k) for k, i in enumerate(order)])
    moved = 0
    for i in order:
        dx, dy = int(round(pos[i][0] - rects[i]["x"])), int(round(pos[i][1] - rects[i]["y"]))
        if not dx and not dy:
            continue
        c = content[i]
        for it in c["frames"] + c["notes"] + c["nodes"]:
            it["x"] += dx
            it["y"] += dy
        d = next(d for d in doc["domains"] if d["id"] == i)
        if isinstance(d.get("x"), (int, float)) and isinstance(d.get("y"), (int, float)):
            d["x"] += dx
            d["y"] += dy
        moved += 1
    return moved


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
