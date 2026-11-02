"""Nanterino editor web scenarios: flat menu + type-to-filter, fragment clipboard, hierarchy panel, inspector of a chain / column.

Purpose : hierarchy area of the editor web suite; scenarios l10.
Boundary: drives the live editor through tests/web/driver.py (WebDriver, check()); never imports nanterino.server.
Invariant: verbatim slice (M7) of the former scripts/editor6_wd.py; a scenario is `sc_<name>(wd)` and is listed in
          SCENARIOS at the end of this file, which tests/web/run.py reads.
Test    : .venv/bin/python -m tests.web.run l10   (or `area:hierarchy`, or `all`)
"""
import glob, json, os, sys, time

from tests.web.driver import *  # noqa: F401,F403  (shared helpers, check(), W, BASE, ROOT)
L10_ESC, L10_ENTER, L10_CTRL, L10_BKSP = "", "", "", ""


def _l10_type(wd, text):
    acts = []
    for ch in text:
        acts += [{"type": "keyDown", "value": ch}, {"type": "keyUp", "value": ch}]
    wd.cmd("POST", "/actions", {"actions": [{"type": "key", "id": "k", "actions": acts}]})
    wd.cmd("DELETE", "/actions")
    time.sleep(0.4)


def _l10_clabs(wd, idx=0):
    return js(wd, "const m=[...document.querySelectorAll('.ctx')][arguments[0]]; return m ? [...m.querySelectorAll(':scope > .cit')].map(e=>(e.querySelector('.clab')||e).textContent.trim()) : null", [idx])


def _l10_canvas_pt(wd, x, y):
    return js(wd, """const st=document.querySelector('#drawflow > div'); const r=st.getBoundingClientRect();
      return [(arguments[0]-r.x)/(r.width/st.offsetWidth), (arguments[1]-r.y)/(r.height/st.offsetHeight)]""", [x, y])


def _l10_click_row(wd, key):
    r = _l10_row(wd, key)
    if not r:
        return False
    x, y = r[0] + min(60, r[2] / 2), r[1] + r[3] / 2
    hit = js(wd, "const e=document.elementFromPoint(arguments[0],arguments[1]); const r=e&&e.closest('.hrow'); return r?r.dataset.key:null", [x, y])
    if hit != key:
        print("WARN row click lands on", hit, "not", key, flush=True)
    lclick(wd, x, y)
    time.sleep(0.5)
    return hit == key


def _l10_drag_row(wd, src, dst, hold_check=None):
    """Human-like pointer drag of tree row `src` onto row `dst` (release with the POINTER on dst)."""
    r0, r1 = _l10_row(wd, src), _l10_row(wd, dst)
    if not r0 or not r1:
        return None, False
    x0, y0 = r0[0] + min(50, r0[2] / 2), r0[1] + r0[3] / 2
    x1, y1 = r1[0] + min(70, r1[2] / 2), r1[1] + r1[3] / 2
    hit = js(wd, "const e=document.elementFromPoint(arguments[0],arguments[1]); const r=e&&e.closest('.hrow'); return r?r.dataset.key:null", [x0, y0])
    steps = 10
    acts = [_mv(x0, y0, 0), _DOWN] + [_mv(x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps, 60) for k in range(1, steps + 1)]
    _pt(wd, acts)
    time.sleep(0.3)
    res = hold_check(wd) if hold_check else None
    _pt(wd, [_UP], end=True)
    time.sleep(0.6)
    return res, hit == src


def sc_l10(wd):
    open_editor(wd)
    js(wd, "try{localStorage.removeItem('nanterino.editor.tree')}catch(e){}; window.__editor.renderTree()")
    time.sleep(0.3)
    n0 = len(doc(wd)["nodes"])
    # ---- 1 canvas menu root: exactly the 3 categories, Post-it, Groupe de nœuds, Copier la sélection, Couper, Coller
    e = view_empty_point(wd, 200) or view_empty_point(wd)
    rclick(wd, *e)
    root = _l10_clabs(wd)
    check("l10 canvas menu root = 3 categories + Post-it + Groupe + Copier/Couper/Coller (nothing else)",
          root == ["Déclencheurs", "Actions", "Conditions", "Post-it", "Groupe de nœuds", "Copier la sélection", "Couper", "Coller"], str(root))
    check("l10 no visible search field in the menu", js(wd, "return document.querySelectorAll('.ctx input, .ctx .csearch, .ctx .cfilter').length") == 0)
    click_item(wd, "Actions"); click_item(wd, "État")
    etat = _l10_clabs(wd, 2) or []
    other = (_l10_clabs(wd, 1) or [])
    check("l10 Actions › État holds Fin and the 7 'Changer d'état → X' rows", "Fin" in etat and len([t for t in etat if t.startswith("Changer d'état → ")]) == 7, str(etat))
    check("l10 Actions submenu = themes only (no Fin / Changer d'état / empty block at its level)", other and not any(t.startswith(("Fin", "Changer d'état", "Action", "Déclencheur", "Condition")) for t in other), str(other))
    wd.shot("editor15-menu.png")
    key(wd, L10_ESC); key(wd, L10_ESC); key(wd, L10_ESC)
    check("l10 Esc closes the cascade level by level", not js(wd, "return window.__editor.ctxOpen()"))
    # ---- 2 typing filters (no field until a key is typed), Enter inserts at the click point
    rclick(wd, *e)
    cp = _l10_canvas_pt(wd, *e)        # measured at the click: an edit may re-wrap the toolbar and shift the canvas
    _l10_type(wd, "ouvrir le micro")
    flt = js(wd, "const m=document.querySelector('.ctx'); const f=m&&m.querySelector('.cfilter'); return [f?f.textContent:null, [...m.querySelectorAll(':scope > .cit')].map(r=>[(r.querySelector('.clab')||r).textContent, (r.querySelector('.cpath')||{}).textContent||''])]")
    check("l10 typing shows a filter line and lists the match with its path", flt and flt[0] and "ouvrir le micro" in flt[0] and ["Ouvrir le micro", "Actions › Micro & écoute"] in flt[1], str(flt)[:200])
    key(wd, L10_BKSP)
    q = js(wd, "const f=document.querySelector('.ctx .cfilter'); return f?f.textContent:''")
    check("l10 Backspace edits the filter", q.endswith("ouvrir le micr"), q)
    _l10_type(wd, "o")
    key(wd, L10_ENTER)
    time.sleep(0.4)
    d = doc(wd)
    new = d["nodes"][-1]
    check("l10 Enter on the filtered row inserts it at the click point", len(d["nodes"]) == n0 + 1 and new["params"].get("action") == "mic_on"
          and abs(new["x"] - cp[0]) <= 3 and abs(new["y"] - cp[1]) <= 3, "%s (%s,%s) vs (%.0f,%.0f)" % (new["params"].get("action"), new["x"], new["y"], cp[0], cp[1]))
    js(wd, "document.querySelector('#btnUndo').click()"); time.sleep(0.4)
    rclick(wd, *e)
    _l10_type(wd, "zzzq")
    none = js(wd, "return [...document.querySelectorAll('.ctx .cit')].map(r=>r.textContent.trim())")
    key(wd, L10_ESC)
    back = _l10_clabs(wd)
    check("l10 filter without match says so; Esc restores the root rows", none == ["Aucun nœud ne correspond"] and back and back[0] == "Déclencheurs" and len(back) == 8, "%s / %s" % (none, back))
    key(wd, L10_ESC)
    # ---- 3 insertion Catégorie › Thème › élément (mouse)
    th = js(wd, "const t=window.__editor.menuTree(['condition'])[0].themes[0]; return [t.theme.label, t.items[0].label, t.items[0].preset]")
    rclick(wd, *e)
    click_item(wd, "Conditions"); click_item(wd, th[0]); click_item(wd, th[1])
    d = doc(wd)
    check("l10 Conditions › %s › %s inserts that condition" % (th[0], th[1]), len(d["nodes"]) == n0 + 1 and d["nodes"][-1]["kind"] == "condition", str(d["nodes"][-1])[:120])
    js(wd, "document.querySelector('#btnUndo').click()"); time.sleep(0.4)
    check("l10 undo removes it", len(doc(wd)["nodes"]) == n0)
    # ---- 4 test material: nested groups + a post-it (page only, never saved), an erroring chain inside the sub-group
    js(wd, """const E=window.__editor, d=E.serialize();
      d.frames.push({id:'f901', title:'L10 parent', color:'#4f8ef7', x:-1600, y:134, w:1100, h:800, parent:null});
      d.frames.push({id:'f902', title:'L10 enfant', color:'#56d364', x:-1560, y:214, w:1000, h:420, parent:'f901'});
      d.notes.push({id:'p901', text:'Note L10\\nseconde ligne', color:'#fff59d', x:-1540, y:680, w:220, h:120, parent:'f901'});
      E.rebuild(d);""")
    time.sleep(0.4)
    ids = js(wd, """const E=window.__editor; const t=E.addAt('trigger',{event:'visage'},{x:-1530,y:300},{exact:true});
      const c=E.addAt('condition',{guard:'var_compare',args:{name:'inconnue',op:'=',value:'1'}},{x:-1270,y:300},{exact:true});
      const a=E.addAt('action',{action:'mic_on'},{x:-1010,y:300},{exact:true});
      E.linkNodes(t,'output_1',c); E.linkNodes(c,'output_1',a); const m=E.dfMap(); const inv={}; for(const k in m) inv[m[k]]=k;
      return [inv[t], inv[c], inv[a]]""")
    tn, cn, an = ids
    js(wd, "document.querySelector('#btnValidate').click()")
    time.sleep(1.8)
    rows = _l10_rows(wd)
    keys = [r[0] for r in rows]
    lvl = {r[0]: r[1] for r in rows}
    cols = [r[2] for r in rows if r[0].startswith("col:")]
    check("l10 tree: the 8 columns, in screen order", cols == ["Veille", "Accueil", "Écoute", "Réponse", "Relance", "Clôture", "Éteint", "Règles globales"], str(cols))
    ntrig = len([n for n in doc(wd)["nodes"] if n["kind"] == "trigger"])
    check("l10 tree: one row per chain (trigger)", len([k for k in keys if k.startswith("c:")]) == ntrig, "%d rows / %d triggers" % (len([k for k in keys if k.startswith("c:")]), ntrig))
    check("l10 tree: nested groups (parent level 1, child level 2, its chain level 3)", lvl.get("g:f901") == 1 and lvl.get("g:f902") == 2 and lvl.get("c:" + tn) == 3, str({k: lvl.get(k) for k in ("g:f901", "g:f902", "c:" + tn)}))
    # ADAPTED (L13): count the 8 column post-its by id (the sub-group post-its sit one level deeper, in their sub-group)
    check("l10 tree: post-its (8 column post-its + the group's one, its first line or title)", len([k for k in keys if k.startswith("p:state-")]) == 8 and lvl.get("p:p901") == 2
          and any(r[0] == "p:p901" and r[2] == "Note L10" for r in rows), str([r for r in rows if r[0].startswith("p:")][-2:]))
    order = keys.index("g:f902") < keys.index("c:" + tn) < keys.index("p:p901")
    check("l10 tree: sibling order groups > chains > post-its", order, str(keys[keys.index("g:f901"):keys.index("g:f901") + 5]))
    # ---- 5 diagnostics badges in the tree (own on the chain, rolled up on a folded parent)
    b = js(wd, "const r=document.querySelector(arguments[0]); return r ? [...r.querySelectorAll('.hb')].map(x=>x.className+'|'+x.textContent) : null", [L10_ROW % ("c:" + tn)])
    check("l10 error badge on the erroring chain row", b and any("err" in x for x in b), str(b))
    js(wd, "document.querySelector(arguments[0]+' .hcar').click()", [L10_ROW % "g:f901"])
    time.sleep(0.4)
    b2 = js(wd, "const r=document.querySelector(arguments[0]); return r ? [r.getAttribute('aria-expanded'), [...r.querySelectorAll('.hb')].map(x=>x.className+'|'+x.textContent)] : null", [L10_ROW % "g:f901"])
    check("l10 folded parent group rolls the error up as a counter", b2 and b2[0] == "false" and any("err" in x for x in b2[1]) and not js(wd, "return !!document.querySelector(arguments[0])", [L10_ROW % "g:f902"]), str(b2))
    js(wd, "document.querySelector(arguments[0]+' .hcar').click()", [L10_ROW % "g:f901"])
    time.sleep(0.4)
    # ---- 6 filter
    fr = rect(wd, "#treeFilter")
    lclick(wd, fr[0] + 20, fr[1] + fr[3] / 2)
    _l10_type(wd, "enfant")
    time.sleep(0.4)
    rows = _l10_rows(wd)
    check("l10 filter keeps the match and its ancestors only", [r[0] for r in rows] == ["g:f901", "g:f902"] and "hit" in rows[1][3], str([r[0] for r in rows]))
    key(wd, L10_ESC)
    time.sleep(0.4)
    check("l10 Esc in the filter brings every row back", len(_l10_rows(wd)) == len(keys), "%d vs %d" % (len(_l10_rows(wd)), len(keys)))
    # ---- 7 no palette any more; first right tab = Inspecteur
    pal = js(wd, "return [!!document.querySelector('#palette'), !!document.querySelector('#search'), document.querySelectorAll('.pitem,.pcat,.pthm').length, !!document.querySelector('#left #tree'), !!document.querySelector('#left #treeFilter')]")
    check("l10 left column: hierarchy + filter, no palette / search / palette items", pal == [False, False, 0, True, True], str(pal))
    tab0 = js(wd, "return document.querySelector('#tabs button').textContent.trim()")
    check("l10 first right tab is 'Inspecteur'", tab0 == "Inspecteur", tab0)
    # ---- 8 click a chain row: its nodes selected, view centred on it; inspector = chain summary
    _l10_click_row(wd, "c:" + tn)
    sc = js(wd, "return window.__editor.selChain()")
    lit = js(wd, "return [...document.querySelectorAll('.drawflow-node.chainsel')].length")
    vis = js(wd, """const out=[]; for (const nid of arguments[0]) { const el=document.getElementById('node-'+window.__editor.dfMap()[nid]); const r=el.getBoundingClientRect();
      const s=document.querySelector('#drawflow').getBoundingClientRect(); out.push(r.left>=s.left && r.right<=s.right && r.top>=s.top && r.bottom<=s.bottom); } return out""", [ids])
    check("l10 chain row click selects all its nodes", sc and sc["tid"] == tn and sorted(sc["ids"]) == sorted(ids) and lit == 3, "%s lit=%s" % (sc, lit))
    check("l10 chain row click centres the chain (all its nodes in view)", all(vis), str(vis))
    ins = js(wd, "return [document.querySelector('#inspector .insttitle').textContent, document.querySelectorAll('#inspector .cstep').length, document.querySelectorAll('#inspector .iss.err').length]")
    check("l10 inspector of a chain: title, 3 steps, its error listed", ins and ins[0].startswith("Chaîne") and ins[1] == 3 and ins[2] >= 1, str(ins))
    check("l10 the clicked row is highlighted", "sel" in js(wd, "return document.querySelector(arguments[0]).className", [L10_ROW % ("c:" + tn)]))
    wd.shot("editor15-hierarchy.png")
    # canvas -> tree: a real click on a node of another chain highlights that chain's row
    other_t = node_of(wd, "n.kind==='trigger' && n.params.type==='event' && n.params.event==='visage' && n.id!=='%s'" % tn)
    center_on(wd, other_t["id"])
    r = rect(wd, "#node-%s .nhead" % dfid(wd, other_t["id"]))
    lclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
    time.sleep(0.5)
    sel = js(wd, "return [...document.querySelectorAll('#tree .hrow.sel')].map(r=>r.dataset.key)")
    check("l10 canvas click on a node highlights its chain row (two-way sync)", sel == ["c:" + other_t["id"]] and not js(wd, "return window.__editor.selChain()"), str(sel))
    # column row: selects the column, inspector says Colonne
    _l10_click_row(wd, "col:auto-accueil")
    ci = js(wd, "return [window.__editor.selFrame(), document.querySelector('#inspector .insttitle').textContent]")
    check("l10 column row click selects the column; inspector 'Colonne'", ci[0] == "auto-accueil" and ci[1].startswith("Colonne"), str(ci))
    # ---- 9 node menu (an action of a non-entry chain)
    center_on(wd, an)
    r = rect(wd, "#node-%s .nhead" % dfid(wd, an))
    rclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
    nm = _l10_clabs(wd)
    check("l10 node menu starts Copier, Couper, Dupliquer, Supprimer, Désactiver la chaîne, Ranger dans le groupe",
          nm and nm[:6] == ["Copier", "Couper", "Dupliquer", "Supprimer", "Désactiver la chaîne", "Ranger dans le groupe"] and "Insérer après" in nm and "Coller" in nm, str(nm))
    click_item(wd, "Ranger dans le groupe")
    rg = _l10_clabs(wd, 1) or []
    check("l10 Ranger dans le groupe ▸ lists the columns and groups, the current one ticked", any(t.strip().startswith("Veille") for t in rg) and any("L10 enfant ✓" in t for t in rg), str(rg)[:200])
    js(wd, "window.__editor.closeCtx()")
    # group menu
    js(wd, "window.__editor.focusFrame('f902')"); time.sleep(0.4)
    r = rect(wd, ".frame[data-fid=f902] > .ftitle")
    rclick(wd, r[0] + 40, r[1] + r[3] / 2)
    gm = _l10_clabs(wd)
    check("l10 group menu starts Copier, Couper, Dupliquer, Supprimer, Ranger dans le groupe", gm and gm[:5] == ["Copier", "Couper", "Dupliquer", "Supprimer", "Ranger dans le groupe"], str(gm))
    js(wd, "window.__editor.closeCtx()")
    # ---- 10 copy the chain, paste at the click point (links kept); undo
    _l10_click_row(wd, "c:" + tn)
    d0 = doc(wd)
    e2 = view_empty_point(wd, 200) or view_empty_point(wd)
    rclick(wd, *e2)
    top = menu_labels(wd)[0]
    check("l10 'Copier la sélection' enabled with a chain selected", any(t.startswith("Copier la sélection") and "[off]" not in t for t in top), str(top))
    click_item(wd, "Copier la sélection")
    cb = js(wd, "const c=window.__editor.clipboard(); return c ? [c.nodes.length, c.links.length] : null")
    check("l10 clipboard = the 3 nodes and their 2 internal links", cb == [3, 2], str(cb))
    e3 = view_empty_point(wd, 420) or e2
    rclick(wd, *e3)
    cp = _l10_canvas_pt(wd, *e3)
    click_item(wd, "Coller")
    d1 = doc(wd)
    newn = [n for n in d1["nodes"] if n["id"] not in {m["id"] for m in d0["nodes"]}]
    newids = {n["id"] for n in newn}
    newl = [l for l in d1["links"] if l["from"] in newids and l["to"] in newids]
    mx, my = (min(n["x"] for n in newn), min(n["y"] for n in newn)) if newn else (None, None)
    check("l10 paste: 3 new nodes, 2 internal links kept, top-left at the click point", len(newn) == 3 and len(newl) == 2 and abs(mx - cp[0]) <= 3 and abs(my - cp[1]) <= 3,
          "%d nodes %d links at (%s,%s) vs (%.0f,%.0f)" % (len(newn), len(newl), mx, my, cp[0], cp[1]))
    chord(wd, L10_CTRL, "z")
    check("l10 Ctrl+Z undoes the whole paste in one step", len(doc(wd)["nodes"]) == len(d0["nodes"]))
    # ---- 11 cut a node (menu) then Ctrl+Z
    center_on(wd, cn)
    r = rect(wd, "#node-%s .nhead" % dfid(wd, cn))
    rclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
    click_item(wd, "Couper")
    d2 = doc(wd)
    check("l10 cut removes the node and its wires", not any(n["id"] == cn for n in d2["nodes"]) and not any(cn in (l["from"], l["to"]) for l in d2["links"])
          and js(wd, "const c=window.__editor.clipboard(); return c && c.nodes.length===1 && c.nodes[0].id===arguments[0]", [cn]))
    chord(wd, L10_CTRL, "z")
    d3 = doc(wd)
    check("l10 Ctrl+Z after a cut brings the node and both wires back", any(n["id"] == cn for n in d3["nodes"]) and len([l for l in d3["links"] if cn in (l["from"], l["to"])]) == 2)
    # ---- 12 drag a group row onto a column row (drop outline while held), undo
    # one caret click per column (each click rebuilds the rows, so the next caret is looked up again)
    js(wd, "for (let i=0;i<8;i++){ const c=document.querySelector('#tree .hrow.h-col[aria-expanded=true] .hcar'); if(!c) break; c.click(); }")
    time.sleep(0.5)
    folded = js(wd, "return window.__editor.treeFold()")
    check("l10 fold arrows fold the columns (state kept per browser)", len([k for k in folded if k.startswith("col:")]) == 8
          and js(wd, "try{return JSON.parse(localStorage.getItem('nanterino.editor.tree')).length}catch(e){return -1}") == 8, str(folded))
    held, hit = _l10_drag_row(wd, "g:f901", "col:auto-cloture", lambda w: js(w, "return [...document.querySelectorAll('#tree .hrow.hdrop')].map(r=>r.dataset.key)"))
    f1, col = _fr(wd, "f901"), _fr(wd, "auto-cloture")
    check("l10 drag press lands on the group row (no overlay)", hit)
    check("l10 drop outline on the column row while held", held == ["col:auto-cloture"], str(held))
    check("l10 group row dropped on a column: filed in it, the column grew to enclose it", f1 and f1.get("parent") == "auto-cloture" and _encl(col, f1), "%s %s" % (f1, col))
    sub = js(wd, "return (()=>{const r=window.__editor.buildTree(); const c=r.kids.find(k=>k.key==='col:auto-cloture'); const g=c&&c.kids.find(k=>k.key==='g:f901'); return g ? g.kids.map(k=>k.key) : null})()")
    check("l10 the moved group keeps its sub-group, chain and post-it", sub and "g:f902" in sub and "p:p901" in sub and _fr(wd, "f902")["parent"] == "f901", str(sub))
    held2, _hit2 = _l10_drag_row(wd, "col:auto-veille", "col:auto-cloture", lambda w: js(w, "return [...document.querySelectorAll('#tree .hrow.hdeny')].map(r=>r.dataset.key)"))
    v = _fr(wd, "auto-veille")
    check("l10 a column row cannot be filed (red outline, stays top level)", held2 == ["col:auto-cloture"] and not v.get("parent"), "%s %s" % (held2, v.get("parent")))
    chord(wd, L10_CTRL, "z")
    check("l10 Ctrl+Z puts the group back at the top level", not (_fr(wd, "f901") or {}).get("parent"), str(_fr(wd, "f901")))
    # ---- 13 fold state survives a reload
    open_editor(wd)
    time.sleep(0.4)
    fl = js(wd, "return [...document.querySelectorAll('#tree .hrow.h-col')].map(r=>r.getAttribute('aria-expanded'))")
    check("l10 fold state kept after a reload", fl == ["false"] * 8, str(fl))
    js(wd, "try{localStorage.removeItem('nanterino.editor.tree')}catch(e){}")
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


# Scenario registry read by tests/web/run.py (order = order of the former single file).
SCENARIOS = {
    "l10": sc_l10,
}
