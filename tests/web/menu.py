"""Nanterino editor web scenarios: right-click node menu: insert, cascading sub-menus, categorised menu.

Purpose : menu area of the editor web suite; scenarios menu, ctxsub, menu3.
Boundary: drives the live editor through tests/web/driver.py (WebDriver, check()); never imports nanterino.server.
Invariant: verbatim slice (M7) of the former scripts/editor6_wd.py; a scenario is `sc_<name>(wd)` and is listed in
          SCENARIOS at the end of this file, which tests/web/run.py reads.
Test    : .venv/bin/python -m tests.web.run menu   (or `area:menu`, or `all`)
"""
import glob, json, os, sys, time

from tests.web.driver import *  # noqa: F401,F403  (shared helpers, check(), W, BASE, ROOT)


def sc_menu(wd):
    open_editor(wd)
    E = "window.__editor"
    n0 = len(doc(wd)["nodes"])
    # --- empty canvas
    e = view_empty_point(wd)
    rclick(wd, *e)
    top = menu_labels(wd)[0]
    print("CANVAS MENU", top)
    # ADAPTED (L10): flat root, no "Insérer un nœud" submenu, no "Ajuster la vue" (toolbar only)
    check("canvas menu items", all(any(t.startswith(x) for t in top) for x in ["Déclencheurs", "Actions", "Conditions", "Post-it", "Groupe de nœuds", "Copier la sélection", "Couper", "Coller"])
          and not any(t.startswith(("Insérer", "Ajuster", "Changer d'état")) for t in top), str(top))
    check("Coller disabled with an empty clipboard", any(t.startswith("Coller") and "[off]" in t for t in top))
    # ADAPTED (L10): Fin and the 'Changer d'état →' rows live under Actions › État; no empty blocks, no search field
    click_item(wd, "Actions")
    click_item(wd, "État")
    sub = menu_labels(wd)[-1]
    print("SUBMENU", sub[:12])
    check("Actions › État has Fin and 'Changer d'état →' entries, no 'État :' / Début", all(any(t.startswith(x) for t in sub) for x in ["Fin", "Changer d'état → "]) and not any(t.startswith(("État :", "Aller à :", "Début")) for t in sub), str(sub))
    check("no search field in the menu (L10: typing filters)", not js(wd, "return !!document.querySelector('.ctx .csearch, .ctx input')"))
    # keyboard: Escape closes the innermost submenu first, then the next one, then the menu
    key(wd, "\ue00c")
    check("Esc closes the submenu first", len(menu_labels(wd)) == 2)
    key(wd, "\ue00c"); key(wd, "\ue00c")
    check("Esc closes the menu", len(menu_labels(wd)) == 0)
    # --- insert a node at the cursor
    e = view_empty_point(wd)
    rclick(wd, *e)
    click_item(wd, "Actions"); click_item(wd, "Micro & écoute"); click_item(wd, "Ouvrir le micro")   # ADAPTED (L10): Catégorie › Thème › entrée
    d = doc(wd)
    new = [n for n in d["nodes"] if n["kind"] == "action" and n["id"] not in {m["id"] for m in []}][-1]
    exp = js(wd, "const r=%s.__c; return null" % E)
    cp = js(wd, """const st=document.querySelector('#drawflow > div'); const r=st.getBoundingClientRect(); const z=window.__editor.zoom? window.__editor.zoom:1;
      return [(arguments[0]-r.x)/(r.width/st.offsetWidth), (arguments[1]-r.y)/(r.height/st.offsetHeight)]""", [e[0], e[1]])
    check("node count +1", len(d["nodes"]) == n0 + 1)
    check("node placed at the cursor", abs(new["x"] - cp[0]) <= 3 and abs(new["y"] - cp[1]) <= 3, "node (%s,%s) cursor canvas (%.0f,%.0f)" % (new["x"], new["y"], cp[0], cp[1]))
    js(wd, "document.querySelector('#btnUndo').click()")
    time.sleep(0.5)
    check("undo removes the inserted node", len(doc(wd)["nodes"]) == n0)
    # --- node menu + insert after
    d = doc(wd)
    act = next(n for n in d["nodes"] if n["kind"] == "action" and not any(l["from"] == n["id"] for l in d["links"]) is False)
    center_on(wd, act["id"])
    r = rect(wd, "#node-%s .nhead" % dfid(wd, act["id"]))
    rclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
    top = menu_labels(wd)[0]
    print("NODE MENU", top)
    # ADAPTED (L10): "Grouper" -> "Groupe de nœuds", "Ajouter un post-it ici" -> "Post-it"; Couper / Ranger dans le groupe added
    check("node menu items", all(any(t.startswith(x) for t in top) for x in ["Copier", "Couper", "Dupliquer", "Supprimer", "Ranger dans le groupe", "Insérer après", "Post-it", "Groupe de nœuds", "Coller"]), str(top))
    click_item(wd, "Insérer après")
    sub = menu_labels(wd)[-1]
    # ADAPTED (L10): after an action only the Actions category; Fin and Changer d'état sit in Actions › État
    click_item(wd, "Actions"); click_item(wd, "État")
    sub2 = menu_labels(wd)[-1]
    check("after an action: Actions only (Fin and Changer d'état in État), no Conditions", sub == ["Actions▸"] and any(t.startswith("Fin") for t in sub2) and any(t.startswith("Changer d'état → ") for t in sub2), "%s %s" % (sub, sub2))
    wd.shot("editor6-contextmenu.png")
    click_item(wd, "Fin")
    d2 = doc(wd)
    new = [n for n in d2["nodes"] if n["id"] not in {m["id"] for m in d["nodes"]}]
    check("insert after creates one node", len(new) == 1)
    check("and auto-links it from the output", any(l["from"] == act["id"] and l["to"] == new[0]["id"] for l in d2["links"]))
    js(wd, "document.querySelector('#btnUndo').click()")
    time.sleep(0.5)
    # Vars L2: "Changer d'état → Écoute" inserts an action set_var(etat, ecoute) linked after the node
    center_on(wd, act["id"])
    r = rect(wd, "#node-%s .nhead" % dfid(wd, act["id"]))
    rclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
    click_item(wd, "Insérer après")
    click_item(wd, "Actions"); click_item(wd, "État")    # ADAPTED (L10)
    click_item(wd, "Changer d'état → Écoute")
    d2 = doc(wd)
    new = [n for n in d2["nodes"] if n["id"] not in {m["id"] for m in d["nodes"]}]
    check("'Changer d'état → Écoute' inserts set_var(etat, ecoute), linked", len(new) == 1 and new[0]["kind"] == "action" and new[0]["params"].get("action") == "set_var"
          and new[0]["params"].get("args") == {"name": "etat", "value": "ecoute"} and any(l["from"] == act["id"] and l["to"] == new[0]["id"] for l in d2["links"]), str(new))
    js(wd, "document.querySelector('#btnUndo').click()")
    time.sleep(0.5)
    # trigger -> after: Condition, Action, Fin and states
    # Vars L2: "etat becomes X" (var_changed on etat) is a state entry: never disabled, so pick an ordinary event trigger
    trig = next(n for n in d["nodes"] if n["kind"] == "trigger" and n["params"].get("type") == "event" and n["params"].get("event") != "var_changed")
    center_on(wd, trig["id"])
    r = rect(wd, "#node-%s .nhead" % dfid(wd, trig["id"]))
    rclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
    labs = menu_labels(wd)[0]
    check("trigger menu has Désactiver la chaîne", any(t.startswith(("Désactiver", "Activer")) for t in labs), str(labs))
    js(wd, "window.__editor.closeCtx()")
    # --- wire menu + split
    w = wire_point(wd, "a.kind==='action' && b.kind==='action'")
    if w is None:
        w = wire_point(wd, "a.kind==='action' && b.kind==='state'")
    if w is None:   # L7: 1280 x 700 view, returning wires thin: any chain-internal wire in view
        w = wire_point(wd, "b.kind==='action' && a.kind!=='state'")
    print("WIRE", w)
    rclick(wd, w["x"], w["y"])
    top = menu_labels(wd)[0]
    print("WIRE MENU", top)
    check("wire menu items", len(top) == 2 and top[0].startswith("Insérer un nœud au milieu") and top[1].startswith("Supprimer le fil"))
    d = doc(wd)
    click_item(wd, "Insérer un nœud au milieu")
    sub = menu_labels(wd)[-1]
    check("only valid kinds on a wire (no Début/Fin/Déclencheur)", not any(t.startswith(("Début", "Fin", "Déclencheur")) for t in sub), str(sub[:6]))
    click_item(wd, "Actions"); click_item(wd, "Micro & écoute"); click_item(wd, "Ouvrir le micro")   # ADAPTED (L10)
    d2 = doc(wd)
    new = [n for n in d2["nodes"] if n["id"] not in {m["id"] for m in d["nodes"]}]
    check("split creates one node", len(new) == 1)
    nid = new[0]["id"]
    ok = (any(l["from"] == w["from"] and l["to"] == nid for l in d2["links"]) and any(l["from"] == nid and l["to"] == w["to"] for l in d2["links"])
          and not any(l["from"] == w["from"] and l["to"] == w["to"] and l["port"] == ("true" if w["port"] == "output_1" else "false") for l in d2["links"] if False))
    check("wire split gives A -> new -> B", ok)
    check("old direct wire A -> B is gone", not any(l["from"] == w["from"] and l["to"] == w["to"] for l in d2["links"]))
    js(wd, "document.querySelector('#btnUndo').click()")
    time.sleep(0.5)
    d3 = doc(wd)
    check("undo restores the wire", any(l["from"] == w["from"] and l["to"] == w["to"] for l in d3["links"]) and len(d3["nodes"]) == len(d["nodes"]))
    # --- delete wire / copy-paste
    rclick(wd, w["x"], w["y"])
    click_item(wd, "Supprimer le fil")
    check("delete wire", not any(l["from"] == w["from"] and l["to"] == w["to"] for l in doc(wd)["links"]))
    js(wd, "document.querySelector('#btnUndo').click()")
    time.sleep(0.4)
    d = doc(wd)
    act = next(n for n in d["nodes"] if n["kind"] == "action")
    center_on(wd, act["id"])
    r = rect(wd, "#node-%s .nhead" % dfid(wd, act["id"]))
    rclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
    click_item(wd, "Copier")
    e = view_empty_point(wd)
    rclick(wd, *e)
    top = menu_labels(wd)[0]
    check("Coller enabled after Copier", any(t.startswith("Coller") and "[off]" not in t for t in top))
    click_item(wd, "Coller")
    d2 = doc(wd)
    new = [n for n in d2["nodes"] if n["id"] not in {m["id"] for m in d["nodes"]}]
    check("paste: new id, same params, no link", len(new) == 1 and new[0]["params"] == act["params"] and not any(new[0]["id"] in (l["from"], l["to"]) for l in d2["links"]))
    js(wd, "document.querySelector('#btnUndo').click()")
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


def sc_ctxsub(wd):
    """L7 / Vars L2: on a 700 px tall viewport every "Changer d'état → X" row of the insert submenu is reachable (fits, scrolls).
    ADAPTED (L10): those rows live in Actions › État."""
    open_editor(wd)
    e = view_empty_point(wd, 560) or view_empty_point(wd)   # CHANGED (L4): a really empty point low in the view
    rclick(wd, e[0], max(e[1], 560))
    click_item(wd, "Actions"); click_item(wd, "État")     # ADAPTED (L10): Actions › État lists "Changer d'état → <state>" x 7 + Fin
    sub = js(wd, """const m=[...document.querySelectorAll('.ctx')].pop(); const r=m.getBoundingClientRect();
      return [r.top, r.bottom, innerHeight, m.scrollHeight, m.clientHeight, [...m.querySelectorAll('.cit')].map(e=>e.textContent.trim())]""")
    print("STATE SUBMENU", sub)
    check("state submenu inside the viewport", sub[0] >= 0 and sub[1] <= sub[2], str(sub[:5]))
    labels = sub[5]
    ok = all(any(l == "Changer d'état → " + s for l in labels) for s in ["Veille", "Accueil", "Écoute", "Réponse", "Relance", "Clôture", "Éteint"])
    reach = js(wd, """const m=[...document.querySelectorAll('.ctx')].pop(); const rows=[...m.querySelectorAll('.cit')];
      return rows.every(e=>{e.scrollIntoView({block:'nearest'}); const r=e.getBoundingClientRect(); const x=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2); return x&&e.contains(x)})""")
    check("7 states listed and each one reachable", ok and reach, str(labels))
    js(wd, "const m=[...document.querySelectorAll('.ctx')].pop(); m.scrollTop=0")
    wd.shot("editor6-contextmenu-submenu.png")
    js(wd, "window.__editor.closeCtx()")
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


def sc_menu3(wd):
    open_editor(wd)
    st, voc = W.http("GET", BASE + "/api/graph/vocab")
    tids = [t["id"] for t in voc.get("themes", [])]
    entries = [x for k in ("events", "actions", "guards") for x in voc.get(k, [])]
    check("vocab endpoint exposes themes + one valid theme per entry", st == 200 and len(tids) >= 8 and all(x.get("theme") in tids for x in entries)
          and set(voc.get("theme_slots", {}).values()) <= set(tids), "%d themes, %d entries" % (len(tids), len(entries)))
    # ADAPTED (L10): the palette is gone: categories / themes are read from the menu itself and from menuTree;
    # the palette search became type-to-filter in the open menu.
    e0 = view_empty_point(wd, 330) or view_empty_point(wd)
    rclick(wd, *e0)
    cats = (menu_labels(wd) or [[]])[0][:3]
    check("palette: 3 categories Déclencheurs / Actions / Conditions", cats == ["Déclencheurs▸", "Actions▸", "Conditions▸"], str(cats))
    js(wd, "window.__editor.closeCtx()")
    per = js(wd, """const o={}; window.__editor.menuTree(['trigger','action','condition','end']).forEach(c=>{o[c.cat.id]=c.themes.map(t=>[t.theme.id, t.items.length])}); return o""")
    shared = set(t for t, _n in per.get("trigger", [])) & set(t for t, _n in per.get("action", [])) & set(t for t, _n in per.get("condition", []))
    check("themes shared across the 3 categories (micro, etat, ... in all)", {"micro", "etat"} <= shared and len(shared) >= 5, str(sorted(shared)))
    check("no empty theme shown", all(n > 0 for v in per.values() for _t, n in v), str(per))
    order = [t for t, _n in per.get("action", [])]
    check("themes in vocabulary order", order == [t for t in tids if t in order], str(order))
    rclick(wd, *e0)
    click_item(wd, "Actions"); click_item(wd, "Micro & écoute")
    items = menu_labels(wd)[-1]
    check("theme expands: Micro & écoute lists its actions", "Ouvrir le micro" in items and "Couper le micro" in items, str(items))
    js(wd, "window.__editor.closeCtx()")
    rclick(wd, *e0)
    for ch in "ouvrir le micro":
        key(wd, ch)
    hits = js(wd, "return [...document.querySelectorAll('.ctx .cit')].map(e=>[(e.querySelector('.clab')||e).textContent, (e.querySelector('.cpath')||{}).textContent||''])")
    check("search finds the item with its Catégorie › Thème path", ["Ouvrir le micro", "Actions › Micro & écoute"] in hits, str(hits[:4]))
    js(wd, "window.__editor.closeCtx()")
    rclick(wd, *e0)
    for ch in "micro":
        key(wd, ch)
    hits = js(wd, "return [...document.querySelectorAll('.ctx .cit .cpath')].map(e=>e.textContent)")
    check("search spans the categories (triggers + actions + conditions)", any(h.startswith("Déclencheurs") for h in hits) and any(h.startswith("Actions") for h in hits)
          and any(h.startswith("Conditions") for h in hits), str(sorted(set(hits))))
    js(wd, "window.__editor.closeCtx()")
    # right-click > Insérer un nœud > Actions > Micro & écoute > Ouvrir le micro (mouse)
    n0 = len(doc(wd)["nodes"])
    e = view_empty_point(wd, 330) or view_empty_point(wd)
    rclick(wd, *e)
    lv1 = menu_labels(wd)[-1]      # ADAPTED (L10): the categories are the root rows
    check("Insérer: Déclencheurs / Actions / Conditions cascade first", lv1[:3] == ["Déclencheurs▸", "Actions▸", "Conditions▸"], str(lv1[:5]))
    click_item(wd, "Actions")
    lv2 = menu_labels(wd)[-1]
    check("Actions submenu = themes (with ▸), Micro & écoute and État present", "Micro & écoute▸" in lv2 and "État▸" in lv2 and all(t.endswith("▸") for t in lv2), str(lv2))
    click_item(wd, "Micro & écoute")
    lv3 = menu_labels(wd)[-1]
    check("theme submenu lists its items", "Ouvrir le micro" in lv3 and "Couper le micro" in lv3, str(lv3))
    inside = js(wd, "return [...document.querySelectorAll('.ctx')].every(m=>{const r=m.getBoundingClientRect(); return r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight})")
    check("all cascading menus inside the viewport", inside and len(menu_labels(wd)) == 3)   # ADAPTED (L10): root, Actions, theme
    wd.shot("editor11-menu.png")
    click_item(wd, "Ouvrir le micro")
    d = doc(wd)
    new = [n for n in d["nodes"] if n["params"].get("action") == "mic_on" and n["id"] not in set()]
    newest = d["nodes"][-1] if d["nodes"] else {}
    check("item click inserts the node (action mic_on), menu closed", len(d["nodes"]) == n0 + 1 and newest.get("params", {}).get("action") == "mic_on" and not js(wd, "return window.__editor.ctxOpen()"), str(newest)[:120])
    js(wd, "document.querySelector('#btnUndo').click()")
    time.sleep(0.4)
    # ADAPTED (L10): keyboard: the root opens focused on Déclencheurs: (→) first theme (→) first item (Enter)
    rclick(wd, *e)
    for k in ("\ue014", "\ue014"):
        key(wd, k)
        time.sleep(0.35)
    depth = len(menu_labels(wd))
    foc = js(wd, "return document.activeElement && document.activeElement.textContent.trim()")
    want = js(wd, "const t=window.__editor.menuTree(['trigger']); return t[0].themes[0].items[0].label")
    check("keyboard opens Insérer > Déclencheurs > theme > item", depth == 3 and foc == want, "%s %r vs %r" % (depth, foc, want))
    key(wd, "")
    time.sleep(0.5)
    d2 = doc(wd)
    check("Enter inserts the focused trigger", len(d2["nodes"]) == n0 + 1 and d2["nodes"][-1]["kind"] == "trigger", str(d2["nodes"][-1])[:120])
    js(wd, "document.querySelector('#btnUndo').click()")
    time.sleep(0.4)
    # the State theme keeps the quick "Changer d'état → X" rows and offers 'etat = X' conditions / state entries
    tree = js(wd, "return window.__editor.menuTree(['trigger','action','condition']).map(c=>[c.cat.id, (c.themes.find(t=>t.theme.id==='etat')||{items:[]}).items.map(i=>i.label)])")
    acts = dict(tree)
    check("theme État: Changer d'état → X actions, etat = X conditions, entry triggers", any(l.startswith("Changer d'état → ") for l in acts.get("action", []))
          and any(l.startswith("etat = ") for l in acts.get("condition", [])) and any(l.startswith("Entrée dans") for l in acts.get("trigger", [])), str(tree)[:300])
    check("no Start / Début entry anywhere in the menu tree", not any("Début" in l or "Start" in l for _c, ls in tree for l in ls))
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


# Scenario registry read by tests/web/run.py (order = order of the former single file).
SCENARIOS = {
    "menu": sc_menu,
    "ctxsub": sc_ctxsub,
    "menu3": sc_menu3,
}
