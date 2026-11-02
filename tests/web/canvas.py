"""Nanterino editor web scenarios: nodes, wires, ports, mouse buttons, navigation (pan / zoom / keys), no-input triggers, no Start node, wire drags.

Purpose : canvas area of the editor web suite; scenarios nodes, wires, buttons, nav, noinput, nostart, wiredrag.
Boundary: drives the live editor through tests/web/driver.py (WebDriver, check()); never imports nanterino.server.
Invariant: verbatim slice (M7) of the former scripts/editor6_wd.py; a scenario is `sc_<name>(wd)` and is listed in
          SCENARIOS at the end of this file, which tests/web/run.py reads.
Test    : .venv/bin/python -m tests.web.run nodes   (or `area:canvas`, or `all`)
"""
import glob, json, os, sys, time

from tests.web.driver import *  # noqa: F401,F403  (shared helpers, check(), W, BASE, ROOT)


def sc_nodes(wd):
    open_editor(wd)
    d = doc(wd)
    kinds = {}
    for n in d["nodes"]:
        kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
    print("COUNTS nodes=%d links=%d %s" % (len(d["nodes"]), len(d["links"]), kinds))
    check("no state / goto node (etat is a variable)", "state" not in kinds and "goto" not in kinds, str(kinds))
    ec = sum(1 for n in d["nodes"] if n["kind"] == "condition" and n["params"].get("guard") == "var_compare" and (n["params"].get("args") or {}).get("name") == "etat")
    mv = sum(1 for n in d["nodes"] if n["kind"] == "action" and n["params"].get("action") == "set_var" and (n["params"].get("args") or {}).get("name") == "etat")
    en = sum(1 for n in d["nodes"] if n["kind"] == "trigger" and n["params"].get("event") == "var_changed" and n["params"].get("name") == "etat")
    check("etat conditions, state changes and 'etat becomes X' triggers drawn", ec > 0 and mv > 0 and en >= 5, "cond=%d moves=%d enter=%d" % (ec, mv, en))
    check("no automatic band in DOM", js(wd, "return document.querySelectorAll('.band,#bands').length") == 0)
    check("no trigger has an input port", js(wd, "const t=[...document.querySelectorAll('.node-trigger')]; return t.length>30 && t.every(e=>!e.querySelector('.input'))"))
    # L7: default view = top-left of the start column; hubs on one top row, left to right in flow order
    time.sleep(0.6)
    wd.shot("editor7-default.png")
    cols = js(wd, """return window.__editor.serialize().frames.filter(f=>f.auto && f.id!=='auto-global').map(f=>[f.id.slice(5), f.x, f.y])""")
    order = [c[0] for c in sorted(cols, key=lambda c: (c[2], c[1]))]
    check("state columns (auto frames) in reading order = flow order (wrapped rows)", order == ["veille", "accueil", "ecoute", "reponse", "relance", "cloture", "eteint"], str(order))
    ret = js(wd, "return [document.querySelectorAll('svg.connection.ret').length, document.querySelectorAll('.rbadge').length, !!document.querySelector('#btnRet'), !!document.querySelector('#btnVars')]")
    check("no returning wires / state badges / their toggle; Variables button present", ret == [0, 0, False, True], str(ret))
    frames = js(wd, "return window.__editor.serialize().frames.map(f=>[f.title,!!f.auto])")
    # ADAPTED (L13): the default layout adds sub-group frames (no `auto`) after the 8 column frames
    cols8 = [f for f in frames if f[1]]
    check("auto column frames, globals last", len(cols8) == 8 and frames[:8] == cols8 and cols8[-1][0] == "Règles globales", str(cols8))
    # the live robot state glows on its column frame (robot idles in veille or eteint)
    live = js(wd, "return [...document.querySelectorAll('.frame.auto.live')].map(e=>e.dataset.fid)")
    st_live = W.http("GET", BASE + "/api/status")[1]["state"]
    check("live state = its column frame glows", live == ["auto-" + st_live], "%s vs %s" % (live, st_live))
    js(wd, "window.__editor.fit()")
    time.sleep(0.6)
    fz = js(wd, "const t=document.querySelector('.frame.auto .ftitle'); const r=t.getBoundingClientRect(); return [document.querySelector('#drawflow > .drawflow').style.transform, r.height, document.querySelector('#drawflow').classList.contains('semzoom'), document.querySelector('.frame.auto .fcard .fcname') ? document.querySelector('.frame.auto .fcard .fcname').getBoundingClientRect().height : 0]")
    print("FIT", fz)
    check("fit: frame titles >= ~14 px on screen, column cards readable", fz[1] >= 16 and (not fz[2] or fz[3] >= 20), str(fz))
    wd.shot("editor7-fit.png")
    # jump bar: one chip per state + Globales; a click fits the column at 0.6-0.8
    chips = js(wd, "return [...document.querySelectorAll('#jumpbar .jchip')].map(e=>e.textContent.trim())")
    check("jump bar: 7 states + Globales", len(chips) == 8 and chips[-1] == "Globales", str(chips))
    js(wd, "document.querySelector('#jumpbar .jchip[data-g=ecoute]').click()")
    time.sleep(0.5)
    jz = js(wd, """const r=document.querySelector('.frame[data-fid=auto-ecoute] .ftitle').getBoundingClientRect(), s=document.querySelector('#drawflow').getBoundingClientRect();
      const tr=document.querySelector('#drawflow > .drawflow').style.transform; return [tr, r.x>=s.x&&r.right<=s.right&&r.y>=s.y&&r.bottom<=s.bottom]""")
    zval = float(jz[0].split("scale(")[1].rstrip(")"))
    check("chip click: Écoute column at zoom 0.6-0.8, its title in view", 0.59 <= zval <= 0.81 and jz[1], str(jz))
    wd.shot("editor7-jumpbar.png")
    mm = js(wd, "const m=document.querySelector('#minimap'); return [!!m, m&&m.classList.contains('open'), !!(m&&m.querySelector('canvas'))]")
    check("minimap present and open by default", all(mm), str(mm))
    js(wd, "document.querySelector('#minimap .mtog').click()")
    mm2 = js(wd, "return document.querySelector('#minimap').classList.contains('open')")
    js(wd, "document.querySelector('#minimap .mtog').click()")
    check("minimap collapses", mm2 is False)
    # minimap click moves the view
    t0 = js(wd, "return document.querySelector('#drawflow > .drawflow').style.transform")
    r = rect(wd, "#minimap canvas")
    lclick(wd, r[0] + 10, r[1] + r[3] - 10)
    t1 = js(wd, "return document.querySelector('#drawflow > .drawflow').style.transform")
    check("minimap click pans the view", t0 != t1, "%s -> %s" % (t0, t1))
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


def sc_wires(wd):
    open_editor(wd)
    info = js(wd, """const ps=[...document.querySelectorAll('svg.connection')]; const E=window.__editor;
      const grad=ps.filter(s=>{const p=s.querySelector('.main-path'); return p && /url\\(.*#wg\\d+/.test(p.style.stroke) && s.querySelector('linearGradient')}).length;
      return {wires:ps.length, grad:grad}""")
    print("WIRES", info)
    check("every wire has a gradient", info["wires"] > 100 and info["wires"] == info["grad"])
    pt = wire_point(wd, "a.kind==='action'")
    d = doc(wd)
    # an action -> state wire: blue to purple
    st = js(wd, """const out=[]; for(const svg of document.querySelectorAll('svg.connection')){ const g=svg.querySelector('linearGradient'); if(!g) continue;
      const s=[...g.querySelectorAll('stop')].map(x=>x.getAttribute('stop-color')); out.push(s.join('>')); } return [...new Set(out)]""")
    print("GRADIENT PAIRS", st)
    check("trigger>action and condition>action pairs present, no state colour", "#e3b341>#4f8ef7" in st and "#56d364>#4f8ef7" in st and not any("#a371f7" in x for x in st), str(st))
    # L3 (if/else): the shipped if/else pairs are ONE condition whose Faux output carries the else chain; every wire
    # leaving a Faux port starts with the condition colour (green), not the red port pastille
    fw = js(wd, """const out=[]; for(const svg of document.querySelectorAll('svg.connection.output_2')){ const g=svg.querySelector('linearGradient');
      out.push(g ? [...g.querySelectorAll('stop')].map(x=>x.getAttribute('stop-color')).join('>') : 'none'); } return out""")
    nfalse = sum(1 for l in d["links"] if l["port"] == "false")
    negs = [n for n in d["nodes"] if n["kind"] == "condition" and n["params"].get("negate")]
    print("FALSE WIRES", fw, "doc false links", nfalse, "negated condition nodes", len(negs))
    # CHANGED (lot G1): 5 if/else pairs (+ veille is_deaf) and ONE lone negated condition (relance `not mic_active`,
    # no positive twin on the same trigger)
    check("if/else: 5 Faux links in the shipped graph, only the lone relance negated condition", nfalse == 5 and
          [(n["group"], n["params"].get("guard")) for n in negs] == [("relance", "mic_active")], "%d %d" % (nfalse, len(negs)))
    check("Faux wires: gradient starts with the condition colour #56d364", len(fw) == 5 and all(x.startswith("#56d364>") for x in fw), str(fw))
    # the wire being dragged out of a Faux port starts green too (pointer held between two WebDriver action calls)
    cnd = next(n["id"] for n in d["nodes"] if n["kind"] == "condition" and n["params"].get("guard") == "turns_left" and n.get("group") == "ecoute")
    center_on(wd, cnd)
    pr = js(wd, "const e=document.querySelector('#node-'+arguments[0]+' .output_2'); const r=e.getBoundingClientRect(); return [r.x+r.width/2, r.y+r.height/2]", [dfid(wd, cnd)])
    ep = view_empty_point(wd)
    drag = None
    if pr and ep:
        wd.cmd("POST", "/actions", {"actions": [{"type": "pointer", "id": "m", "parameters": {"pointerType": "mouse"}, "actions": [
            {"type": "pointerMove", "duration": 0, "x": int(pr[0]), "y": int(pr[1])}, {"type": "pointerDown", "button": 0},
            {"type": "pointerMove", "duration": 200, "x": int(ep[0]), "y": int(ep[1])}]}]})
        time.sleep(0.3)
        drag = js(wd, """const s=window.__editor && document.querySelector('#drawflow svg.connection:not([class*=node_in_])'); if(!s) return null;
          const g=s.querySelector('linearGradient'); const p=s.querySelector('.main-path');
          return {stops: g ? [...g.querySelectorAll('stop')].map(x=>x.getAttribute('stop-color')) : null, stroke: p ? p.style.stroke : null}""")
        wd.cmd("POST", "/actions", {"actions": [{"type": "pointer", "id": "m", "parameters": {"pointerType": "mouse"}, "actions": [{"type": "pointerUp", "button": 0}]}]})
        wd.cmd("DELETE", "/actions")
        time.sleep(0.5)
    print("DRAG WIRE", pr, ep, drag)
    check("dragged wire from a Faux port: gradient starts with #56d364", bool(drag) and drag["stops"] and drag["stops"][0] == "#56d364" and "url(" in (drag["stroke"] or ""), str(drag))
    check("drop in the void adds no link", len(doc(wd)["links"]) == len(d["links"]))
    # a NEW link from a Faux port is painted at once (condition green -> action blue), then undone
    act = next(n["id"] for n in d["nodes"] if n["kind"] == "action" and n.get("group") == "ecoute"
               and not any(l["from"] == cnd and l["to"] == n["id"] for l in d["links"]))
    a_df, c_df = dfid(wd, act), dfid(wd, cnd)
    ok = js(wd, "return window.__editor.linkNodes(arguments[0], 'output_2', arguments[1])", [c_df, a_df])
    time.sleep(0.4)
    new = js(wd, """const s=document.querySelector('svg.connection.node_out_node-'+arguments[0]+'.node_in_node-'+arguments[1]+'.output_2'); if(!s) return null;
      const g=s.querySelector('linearGradient'); return g ? [...g.querySelectorAll('stop')].map(x=>x.getAttribute('stop-color')) : 'nograd'""", [c_df, a_df])
    print("NEW FAUX LINK", ok, new)
    check("new Faux link: gradient #56d364 -> #4f8ef7 right after linking", new == ["#56d364", "#4f8ef7"], str(new))
    js(wd, "document.querySelector('#btnUndo').click()")
    time.sleep(0.5)
    check("undo removes the new Faux link", len(doc(wd)["links"]) == len(d["links"]), str(len(doc(wd)["links"])))
    # screenshot of the relance question if/else: turns_left, Vrai -> réponse chain, Faux -> clôture chain
    rc = next(n["id"] for n in d["nodes"] if n["kind"] == "condition" and n["params"].get("guard") == "turns_left" and n.get("group") == "relance")
    center_on(wd, rc)
    js(wd, "window.__editor.closeCtx && window.__editor.closeCtx()")
    # zoom out around the condition (Ctrl+wheel = zoom at the cursor, L8) so both branches fit, condition on the left
    js(wd, """const e=document.getElementById('node-'+arguments[0]); const r=e.getBoundingClientRect(), s=document.querySelector('#drawflow').getBoundingClientRect();
      document.querySelector('#drawflow').dispatchEvent(new WheelEvent('wheel',{deltaY:260,ctrlKey:true,clientX:s.x+40,clientY:r.y+r.height/2,bubbles:true,cancelable:true}))""", [dfid(wd, rc)])
    time.sleep(0.6)
    wd.shot("editor9-ifelse.png")
    nid = next(n["id"] for n in d["nodes"] if n["kind"] == "action" and n.get("group") == "ecoute")
    center_on(wd, nid)
    js(wd, "window.__editor.selectTrace && 0")
    # port look
    port = js(wd, "const p=document.querySelector('.node-action .input'); const s=getComputedStyle(p); return [s.width,s.borderTopWidth,s.borderTopColor,s.backgroundColor]")
    print("PORT", port)
    check("port: 16px, 2px white ring", port[0] == "16px" and port[1] == "2px" and port[2] == "rgb(255, 255, 255)", str(port))
    wd.shot("editor6-wires.png")
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


def sc_buttons(wd):
    open_editor(wd)
    d = doc(wd)
    act = next(n for n in d["nodes"] if n["kind"] == "action")
    center_on(wd, act["id"])
    r = rect(wd, "#node-%s .nhead" % dfid(wd, act["id"]))
    x, y = r[0] + r[2] / 2, r[1] + r[3] / 2
    def pos():
        n = next(m for m in doc(wd)["nodes"] if m["id"] == act["id"]); return n["x"], n["y"]
    p0 = pos()
    actions(wd, 1, [(x, y), (x + 80, y + 40), (x + 160, y + 80)])
    check("middle-drag leaves the node in place", pos() == p0, "%s -> %s" % (p0, pos()))
    actions(wd, 2, [(x, y), (x + 80, y + 40), (x + 160, y + 80)])
    check("right-drag leaves the node in place", pos() == p0, "%s -> %s" % (p0, pos()))
    js(wd, "window.__editor.closeCtx()")
    actions(wd, 0, [(x, y), (x + 80, y + 40), (x + 160, y + 80)])
    p1 = pos()
    check("left-drag moves the node", p1 != p0 and p1[0] > p0[0] and p1[1] > p0[1], "%s -> %s" % (p0, p1))
    # canvas pan: left-drag on empty canvas pans; middle-drag does not
    e = view_empty_point(wd)
    cx0 = js(wd, "return document.querySelector('#drawflow > div').style.transform")
    actions(wd, 1, [e, (e[0] + 100, e[1] + 60)])
    cx1 = js(wd, "return document.querySelector('#drawflow > div').style.transform")
    e = view_empty_point(wd)
    actions(wd, 0, [e, (e[0] + 100, e[1] + 60)])
    cx2 = js(wd, "return document.querySelector('#drawflow > div').style.transform")
    check("canvas: middle-drag does not pan, left-drag pans", cx1 == cx0 and cx2 != cx1, "%s | %s" % (cx1, cx2))
    # native context menu is suppressed (our own menu opens instead)
    e = view_empty_point(wd)
    rclick(wd, *e)
    check("right-click opens our menu", js(wd, "return !!document.querySelector('.ctx')"))
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


def sc_nav(wd):
    """L8 safe navigation: Space+drag, wheel pan / Ctrl+wheel zoom, hand tool, lock mode, view keys."""
    pre = {f: os.path.getmtime(f) for f in glob.glob(ROOT + "/graph.*")}
    open_editor(wd)
    js(wd, "window.__editor.setLock(false); window.__editor.setHand(false)")
    d0 = doc(wd)
    act = next(n for n in d0["nodes"] if n["kind"] == "action")
    center_on(wd, act["id"])
    nav = lambda: js(wd, "return window.__editor.nav()")
    sel = lambda: js(wd, "return [...document.querySelectorAll('.drawflow-node.selected')].map(e=>e.id)")
    def pos():
        n = next(m for m in doc(wd)["nodes"] if m["id"] == act["id"]); return n["x"], n["y"]
    def head():
        r = rect(wd, "#node-%s .nhead" % dfid(wd, act["id"])); return r[0] + r[2] / 2, r[1] + r[3] / 2
    def links():
        return sorted(l["from"] + l["port"] + l["to"] for l in doc(wd)["links"])
    e = view_empty_point(wd)
    lclick(wd, *e)                                   # canvas focus, nothing selected
    p0, s0, l0, v0 = pos(), sel(), links(), nav()
    # 1. Space + left-drag on a node: view pans, node / selection / links unchanged
    x, y = head()
    key(wd, " ", release=False)
    check("Space held -> grab mode", js(wd, "return document.body.classList.contains('nav-grab') && window.__editor.nav().space"))
    actions(wd, 0, [(x, y), (x + 60, y + 30), (x + 120, y + 60)])     # its DELETE /actions releases Space
    v1 = nav()
    check("Space+drag pans the view", (v1["x"], v1["y"]) != (v0["x"], v0["y"]) and v1["zoom"] == v0["zoom"], "%s -> %s" % (v0, v1))
    check("Space+drag: node, selection, links unchanged", pos() == p0 and sel() == s0 and links() == l0, "%s %s" % (pos(), sel()))
    check("Space released -> normal mode", not js(wd, "return document.body.classList.contains('nav-grab')"))
    # 2. wheel = pan, Shift+wheel = horizontal, Ctrl+wheel = zoom around the cursor
    e = view_empty_point(wd)
    v1 = nav()
    how = wheel(wd, e[0], e[1], 0, 120)
    v2 = nav()
    check("wheel pans vertically, zoom unchanged", v2["y"] < v1["y"] and v2["x"] == v1["x"] and v2["zoom"] == v1["zoom"], "%s %s -> %s" % (how, v1, v2))
    how = wheel(wd, e[0], e[1], 0, 120, "")
    v3 = nav()
    check("Shift+wheel pans horizontally", v3["x"] < v2["x"] and v3["y"] == v2["y"] and v3["zoom"] == v2["zoom"], "%s %s -> %s" % (how, v2, v3))
    pt_before = js(wd, "const r=document.querySelector('#drawflow > div').getBoundingClientRect(); const z=window.__editor.nav().zoom; return [(arguments[0]-r.x)/z,(arguments[1]-r.y)/z]", [e[0], e[1]])
    how = wheel(wd, e[0], e[1], 0, -120, "")
    v4 = nav()
    pt_after = js(wd, "const r=document.querySelector('#drawflow > div').getBoundingClientRect(); const z=window.__editor.nav().zoom; return [(arguments[0]-r.x)/z,(arguments[1]-r.y)/z]", [e[0], e[1]])
    check("Ctrl+wheel zooms in around the cursor", v4["zoom"] > v3["zoom"] and abs(pt_after[0] - pt_before[0]) < 2 and abs(pt_after[1] - pt_before[1]) < 2,
          "%s zoom %s -> %s, point %s -> %s" % (how, v3["zoom"], v4["zoom"], pt_before, pt_after))
    check("page did not scroll", js(wd, "return scrollX===0 && scrollY===0 && document.querySelector('#stage').scrollTop===0"))
    # view keys (canvas focused)
    e = view_empty_point(wd)
    lclick(wd, *e)
    v5 = nav(); key(wd, ""); v6 = nav()                          # ArrowLeft
    check("ArrowLeft pans (canvas focused)", v6["x"] - v5["x"] == 60, "%s -> %s" % (v5["x"], v6["x"]))
    key(wd, "+"); v7 = nav()
    check("'+' zooms in", v7["zoom"] > v6["zoom"], "%s -> %s" % (v6["zoom"], v7["zoom"]))
    # 3. hand tool (H): drag on a node pans and does not move it; clicks select nothing
    center_on(wd, act["id"])
    lclick(wd, *view_empty_point(wd))
    key(wd, "h")
    check("H -> hand tool on (button pressed, banner)", js(wd, "return window.__editor.nav().hand && document.querySelector('#btnHand').classList.contains('on') && !document.querySelector('#navBanner').hidden && document.querySelector('#navBanner').textContent.includes('Outil main — H pour éditer')"))
    p0, v0 = pos(), nav()
    x, y = head()
    actions(wd, 0, [(x, y), (x + 60, y + 30), (x + 120, y + 60)])
    v1 = nav()
    check("hand tool: drag on a node pans, node stays", pos() == p0 and (v1["x"], v1["y"]) != (v0["x"], v0["y"]), "%s %s -> %s" % (pos(), v0, v1))
    x, y = head()
    lclick(wd, x, y)
    check("hand tool: click selects nothing", sel() == [], str(sel()))
    js(wd, "document.querySelector('#btnHelp').click()")
    time.sleep(0.4)
    check("help popover lists the controls", js(wd, "const h=document.querySelector('#navHelp'); return !!h && !h.hidden && h.textContent.includes('Espace') && h.textContent.includes('Ctrl + molette')"))
    wd.shot("editor8-nav.png")
    js(wd, "document.querySelector('#navHelp .nhclose').click()")
    key(wd, "h")
    check("H again -> hand tool off", not js(wd, "return window.__editor.nav().hand || !document.querySelector('#navBanner').hidden"))
    # 4. lock mode (L)
    n0 = len(doc(wd)["nodes"])
    nn0 = len(js(wd, "return window.__editor.notes()"))
    key(wd, "l")
    check("L -> locked, banner, persisted", js(wd, "return window.__editor.nav().locked && document.querySelector('#navBanner').textContent.includes('Verrouillé — lecture seule') && localStorage.getItem('nanterino.editor.locked')==='1'"))
    p0 = pos()
    x, y = head()
    actions(wd, 0, [(x, y), (x + 80, y + 40), (x + 160, y + 80)])
    check("lock: left-drag on a node does not move it", pos() == p0, "%s -> %s" % (p0, pos()))
    x, y = head()
    lclick(wd, x, y)
    check("lock: click still selects the node (read-only inspector)", sel() == ["node-%s" % dfid(wd, act["id"])], str(sel()))
    ro = js(wd, "const a=[...document.querySelectorAll('#inspector input, #inspector select, #inspector textarea, #inspector button')]; return [a.length, a.filter(e=>!e.disabled).length]")
    check("lock: inspector inputs disabled", ro[0] > 0 and ro[1] == 0, str(ro))
    key(wd, "")                                                  # Delete
    check("lock: Delete removes nothing", len(doc(wd)["nodes"]) == n0)
    e = view_empty_point(wd)
    rclick(wd, *e)
    top = menu_labels(wd)[0]
    click_item(wd, "Actions")              # ADAPTED (L10): the categories are the insert entries now
    check("lock: context-menu insert disabled", all(any(t.startswith(c) and "[off]" in t for t in top) for c in ("Déclencheurs", "Actions", "Conditions")) and len(menu_labels(wd)) <= 1 and len(doc(wd)["nodes"]) == n0, str(top))
    js(wd, "window.__editor.closeCtx()")
    js(wd, """const dt=new DataTransfer(); dt.setData('text/plain', JSON.stringify({kind:'action',preset:null}));
      const r=document.querySelector('#drawflow').getBoundingClientRect();
      document.querySelector('#drawflow').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt,clientX:r.x+200,clientY:r.y+200}))""")
    time.sleep(0.3)
    check("lock: palette drop refused", len(doc(wd)["nodes"]) == n0)
    key(wd, "n")
    js(wd, "document.querySelector('#btnSave').click()")
    time.sleep(1.0)
    post = {f: os.path.getmtime(f) for f in glob.glob(ROOT + "/graph.*")}
    check("lock: N adds no post-it, save is refused (no file written)", len(js(wd, "return window.__editor.notes()")) == nn0 and post == pre
          and js(wd, "return [...document.querySelectorAll('.toast')].some(t=>t.textContent.includes('enregistrement désactivé'))"))
    wd.cmd("POST", "/refresh", {})                  # a real reload (same-URL hash navigation would not reload)
    time.sleep(3.0)
    check("lock survives a reload (localStorage)", js(wd, "return window.__editor.nav().locked && document.body.classList.contains('nav-locked')"))
    # unlock: everything back
    lclick(wd, *view_empty_point(wd))
    key(wd, "l")
    check("L again -> unlocked, storage cleared", js(wd, "return !window.__editor.nav().locked && document.querySelector('#navBanner').hidden && localStorage.getItem('nanterino.editor.locked')===null"))
    center_on(wd, act["id"])
    x, y = head()
    lclick(wd, x, y)
    ro = js(wd, "const a=[...document.querySelectorAll('#inspector input, #inspector select, #inspector textarea')]; return [a.length, a.filter(e=>!e.disabled).length]")
    check("unlocked: inspector inputs enabled", ro[0] > 0 and ro[1] == ro[0], str(ro))
    p0 = pos()
    x, y = head()
    actions(wd, 0, [(x, y), (x + 80, y + 40), (x + 160, y + 80)])
    check("unlocked: left-drag moves the node again", pos() != p0, "%s -> %s" % (p0, pos()))
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))
    print("LEFT OVER", sorted(set(glob.glob(ROOT + "/graph.*")) - set(pre)))


def sc_noinput(wd):
    """Vars L2: no trigger has an input port (canvas, palette insert, vocabulary); a wire dragged onto a trigger is refused."""
    open_editor(wd)
    E = "window.__editor"
    voc = W.http("GET", BASE + "/api/graph/vocab")[1]
    tk = next(k for k in voc["kinds"] if k["id"] == "trigger")
    check("vocabulary: trigger inputs = 0", tk["inputs"] == 0, str(tk))
    info = js(wd, "const t=[...document.querySelectorAll('.drawflow-node.node-trigger')]; return [t.length, t.filter(e=>e.querySelector('.input')).length, window.__editor.kinds().trigger.ins]")
    check("canvas: no trigger has an input port", info[0] > 30 and info[1] == 0 and info[2] == 0, str(info))
    # palette / menu insert: a new trigger has no input either
    n0 = len(doc(wd)["nodes"])
    nd = js(wd, "return window.__editor.addAt('trigger', {event:'visage'}, null, {select:false})")
    has_in = js(wd, "const e=document.getElementById('node-'+arguments[0]); return !!(e && e.querySelector('.input'))", [nd])
    check("inserted trigger has no input port", nd is not None and not has_in, str(nd))
    js(wd, "document.querySelector('#btnUndo').click()"); time.sleep(0.4)
    check("undo removes it", len(doc(wd)["nodes"]) == n0)
    # programmatic link into a trigger is refused (same rule as the server)
    d = doc(wd)
    trig = next(n for n in d["nodes"] if n["kind"] == "trigger" and n.get("group") == "ecoute")
    act = next(n for n in d["nodes"] if n["kind"] == "action" and n.get("group") == "ecoute")
    ok = js(wd, "return window.__editor.linkNodes(arguments[0], 'output_1', arguments[1])", [dfid(wd, act["id"]), dfid(wd, trig["id"])])
    check("linkNodes(action -> trigger) refused", ok is False and len(doc(wd)["links"]) == len(d["links"]), str(ok))
    # real drag: from a visible action output port onto a trigger card
    center_on(wd, trig["id"])
    js(wd, "window.__editor.closeCtx()")
    pts = js(wd, """const s=document.querySelector('#drawflow').getBoundingClientRect(); const inV=(r)=>r.x>s.x+10&&r.right<s.right-10&&r.y>s.y+40&&r.bottom<s.bottom-10;
      const te=document.getElementById('node-'+window.__editor.dfMap()[arguments[0]]); const t=te.getBoundingClientRect();
      const outs=[...document.querySelectorAll('.drawflow-node.node-action .output, .drawflow-node.node-condition .output')].map(e=>e.getBoundingClientRect());
      const o=outs.find(r=>inV(r) && !(r.right>t.x-10 && r.x<t.right+10 && r.bottom>t.y-10 && r.y<t.bottom+10));
      return o ? [[o.x+o.width/2,o.y+o.height/2],[t.x+t.width/2,t.y+t.height/2]] : ['none', [t.x,t.y,t.width,t.height], [s.x,s.y,s.width,s.height], outs.length, outs.filter(inV).length]""", [trig["id"]])
    if pts and pts[0] == 'none':
        print("DRAG DEBUG", pts)
        pts = None
    print("DRAG", pts)
    l0 = len(doc(wd)["links"])
    r0 = js(wd, "return window.__editor.noInputRefusals()")
    if pts:
        (ox, oy), (tx, ty) = pts
        actions(wd, 0, [(ox, oy), ((ox + tx) / 2, (oy + ty) / 2), (tx, ty)], hold_ms=200)
    l1 = len(doc(wd)["links"])
    r1 = js(wd, "return window.__editor.noInputRefusals()")
    msg = js(wd, "return [...document.querySelectorAll('#toasts .toast')].map(e=>e.textContent).join(' | ')")
    check("dragging a wire onto a trigger links nothing and tells why", pts is not None and l1 == l0 and r1 == r0 + 1 and "pas d'entrée" in msg, "links %d -> %d refusals %s -> %s toast=%s" % (l0, l1, r0, r1, msg[:120]))
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


# ---------------------------------------------------------------- lot L4 (2026-11-01): no Start node, wires follow drags
def sc_nostart(wd):
    open_editor(wd)
    d = doc(wd)
    check("no start node in the document", not [n for n in d["nodes"] if n["kind"] == "start"])
    check("no start node in the DOM", js(wd, "return document.querySelectorAll('.drawflow-node.node-start, .drawflow-node.start').length") == 0)
    wd.shot("editor10-nostart.png")   # default view, before any toast: the Veille column starts the canvas, no Start node
    # ADAPTED (L10): no palette any more: the hierarchy and the whole node menu tree have no Début / Start
    pal = js(wd, "return [...document.querySelectorAll('#tree .hrow .hlab')].map(e=>e.textContent.trim())")
    check("hierarchy (no palette) has no Début / Start", pal and not js(wd, "return !!document.querySelector('#palette')") and not any(t.startswith(("Début", "Start")) for t in pal), str([t for t in pal if t.startswith(("Début", "Start"))]))
    e = view_empty_point(wd)
    rclick(wd, *e)
    click_item(wd, "Déclencheurs")
    sub = [t for m in menu_labels(wd) for t in m]
    allm = js(wd, "return window.__editor.menuTree(['trigger','condition','action','end']).flatMap(c=>c.themes.flatMap(t=>t.items.map(i=>i.label)))")
    check("Insérer submenu has no Début", sub and not any(t.startswith("Début") for t in sub) and not any(t.startswith("Début") for t in allm), str(sub[:8]))
    js(wd, "window.__editor.closeCtx && window.__editor.closeCtx()")
    refused = js(wd, "return window.__editor.addAt('start', null, {x: 0, y: 0})")
    check("addAt('start') is refused", refused is None and js(wd, "return document.querySelectorAll('.drawflow-node.node-start').length") == 0, str(refused))
    # a legacy document still carrying a Start node (and a wire from it) loads without it and without errors
    legacy = json.loads(json.dumps(d))
    legacy["nodes"].insert(0, {"id": "nstart", "kind": "start", "x": -400, "y": 0, "description": "Démarrage", "params": {"state": "veille"}})
    legacy["links"].append({"from": "nstart", "port": "out", "to": legacy["nodes"][1]["id"]})
    js(wd, "window.__editor.rebuild(arguments[0])", [legacy])
    time.sleep(0.6)
    d2 = doc(wd)
    check("legacy Start dropped on load (same nodes / links as before)", not [n for n in d2["nodes"] if n["kind"] == "start"]
          and len(d2["nodes"]) == len(d["nodes"]) and len(d2["links"]) == len(d["links"]), "%d/%d" % (len(d2["nodes"]), len(d2["links"])))
    # the server side: a link-free Start (what the vars drawing produced before L4) is ignored; a wire from it into a
    # trigger never existed in any form and stays an error (a trigger has no input)
    legacy_srv = json.loads(json.dumps(legacy))
    legacy_srv["links"] = [l for l in legacy_srv["links"] if l["from"] != "nstart"]
    st, chk = W.http("POST", BASE + "/api/graph/check", legacy_srv)
    check("server accepts a legacy Start node silently (check 0 errors)", st == 200 and chk.get("ok") and not chk.get("errors"), str(chk.get("errors"))[:200])
    js(wd, "window.__editor.loadAll()")
    time.sleep(1.0)
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


def sc_wiredrag(wd):
    def ck(name, cond, extra=''):
        check(name, cond, extra + ' ERRS=%s' % js(wd, 'return window.__editor.errors.length'))
    open_editor(wd)
    d = doc(wd)
    links = d["links"]
    # an action of the ecoute column with a wire in AND a wire out
    act = next(n["id"] for n in d["nodes"] if n["kind"] == "action" and n.get("group") == "ecoute"
               and any(l["to"] == n["id"] for l in links) and any(l["from"] == n["id"] for l in links))
    df = dfid(wd, act)
    center_on(wd, act)
    w0 = wires_of(wd, df)
    print("WIRES BEFORE", [(w["key"], w["d"][:40], w["first"]) for w in w0])
    ck("the node has >= 2 wires, path first in each svg, ends on the ports", len(w0) >= 2 and all(w["first"] == "path" for w in w0) and not _ends_ok(w0), str(_ends_ok(w0)))
    r = rect(wd, "#node-%s" % df)
    gx, gy = r[0] + r[2] / 2, r[1] + 14          # grab the node header (not a port)
    pos0 = js(wd, "const n=window.__editor.serialize().nodes.find(x=>x.id===arguments[0]); return [n.x,n.y]", [act])
    # live: pointer still held after the moves
    _press_move(wd, gx, gy, gx + 110, gy + 70, release=False)
    wl = wires_of(wd, df)
    live_changed = all(a["d"] != b["d"] for a, b in zip(w0, wl))
    print("WIRES LIVE", [(w["key"], w["d"][:40]) for w in wl], _ends_ok(wl))
    ck("during the drag every wire of the node is redrawn and stays on its ports (±3 px)", len(wl) == len(w0) and live_changed and not _ends_ok(wl), str(_ends_ok(wl)))
    _release(wd)
    w1 = wires_of(wd, df)
    pos1 = js(wd, "const n=window.__editor.serialize().nodes.find(x=>x.id===arguments[0]); return [n.x,n.y]", [act])
    print("MOVED", pos0, "->", pos1)
    ck("node moved by a real pointer drag", pos1 != pos0 and abs((pos1[0] - pos0[0]) - 110 / 0.9) < 25, "%s -> %s" % (pos0, pos1))
    ck("after the drag: wire d changed, ends on the new port positions (±3 px), gradient follows",
          all(a["d"] != b["d"] for a, b in zip(w0, w1)) and not _ends_ok(w1), str(_ends_ok(w1)))
    # undo of the move: node and wires come back
    time.sleep(0.6)    # commitSoon
    js(wd, "document.querySelector('#btnUndo').click()")
    time.sleep(0.6)
    df = dfid(wd, act)  # undo rebuilds the canvas (new Drawflow ids)
    wu = wires_of(wd, df)
    posu = js(wd, "const n=window.__editor.serialize().nodes.find(x=>x.id===arguments[0]); return [n.x,n.y]", [act])
    ck("undo of the move: node back, wires on its ports", posu == pos0 and len(wu) == len(w0) and not _ends_ok(wu), "%s %s" % (posu, _ends_ok(wu)))
    js(wd, "document.querySelector('#btnRedo') && document.querySelector('#btnRedo').click()")
    time.sleep(0.6)
    df = dfid(wd, act)
    wr = wires_of(wd, df)
    posr = js(wd, "const n=window.__editor.serialize().nodes.find(x=>x.id===arguments[0]); return [n.x,n.y]", [act])
    ck("redo of the move: node moved again, wires on its ports", posr == pos1 and not _ends_ok(wr), "%s %s" % (posr, _ends_ok(wr)))
    js(wd, "document.querySelector('#btnUndo').click()")
    time.sleep(0.6)
    # a second drag after the first one (the bug froze wires from the 2nd redraw on)
    df = dfid(wd, act)
    center_on(wd, act)
    w2a = wires_of(wd, df)
    r = rect(wd, "#node-%s" % df)
    # moved LEFT out of the canvas: released over the palette (Drawflow alone never ended such a drag)
    x0 = r[0] + r[2] / 2
    x1 = rect(wd, "#drawflow")[0] - 40
    _press_move(wd, x0, r[1] + 14, x1, r[1] + 14 + 50)
    st = js(wd, "return window.__editor.dfState()")
    ck("a drag released outside the canvas (over the palette) ends: node no longer glued to the pointer", not st["drag"] and st["ele"] is None, str(st))
    w2b = wires_of(wd, df)
    ck("second drag: wires follow again", all(a["d"] != b["d"] for a, b in zip(w2a, w2b)) and not _ends_ok(w2b), str(_ends_ok(w2b)))
    time.sleep(0.6)
    js(wd, "document.querySelector('#btnUndo').click()")
    time.sleep(0.6)
    # zoom (Ctrl+wheel at the cursor): wires still end on the ports
    df = dfid(wd, act)
    center_on(wd, act)
    rr = rect(wd, "#node-%s" % df)
    js(wd, """document.querySelector('#drawflow').dispatchEvent(new WheelEvent('wheel',{deltaY:-200,ctrlKey:true,clientX:arguments[0],clientY:arguments[1],bubbles:true,cancelable:true}))""", [rr[0], rr[1]])
    time.sleep(0.6)
    wz = wires_of(wd, df)
    zoom = js(wd, "return window.__editor.nav().zoom")
    ck("after a zoom: wires end on the ports", not _ends_ok(wz) and len(wz) == len(w0), "zoom=%s %s" % (zoom, _ends_ok(wz)))
    # frame drag: the ecoute column frame moves its nodes, their wires follow (jump-bar zoom: titles are live there;
    # at fit zoom the semantic view makes them inert)
    js(wd, "document.querySelector('#jumpbar .jchip[data-g=ecoute]').click()")
    time.sleep(0.6)
    df = dfid(wd, act)
    fw0 = wires_of(wd, df)
    tr = rect(wd, ".frame[data-fid=auto-ecoute] .ftitle")
    print("FRAME TITLE", tr)
    if tr:
        fx, fy = tr[0] + min(40, tr[2] / 2), tr[1] + tr[3] / 2
        hit = js(wd, "const e=document.elementFromPoint(arguments[0],arguments[1]); return [e.className, !!e.closest('.ftitle')]", [fx, fy])
        ck("frame drag starts on the frame title", hit and hit[1], str(hit))
        _press_move(wd, fx, fy, fx + 60, fy + 40, release=False)
        fwl = wires_of(wd, df)
        _release(wd)
        fw1 = wires_of(wd, df)
        moved = js(wd, "const n=window.__editor.serialize().nodes.find(x=>x.id===arguments[0]); return [n.x,n.y]", [act])
        print("FRAME DRAG node", pos0, "->", moved, _ends_ok(fwl), _ends_ok(fw1))
        ck("frame drag moves its nodes", moved != pos0, "%s -> %s" % (pos0, moved))
        ck("frame drag: wires follow live and after (±3 px)", all(a["d"] != b["d"] for a, b in zip(fw0, fw1)) and not _ends_ok(fwl) and not _ends_ok(fw1), "%s %s" % (_ends_ok(fwl), _ends_ok(fw1)))
        time.sleep(0.6)
        js(wd, "document.querySelector('#btnUndo').click()")
        time.sleep(0.6)
    else:
        ck("ecoute frame title found for the frame drag", False)
    # multi-select drag: the editor has no multi-selection (Drawflow selects one node), nothing to test
    print("MULTI-SELECT: feature absent in the editor (single selection only), not tested")
    wd.shot("editor10-wiredrag.png")
    ck("doc back to the loaded one after the undos (positions)", [(n["id"], n["x"], n["y"]) for n in doc(wd)["nodes"]] == [(n["id"], n["x"], n["y"]) for n in d["nodes"]])
    ck("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


# Scenario registry read by tests/web/run.py (order = order of the former single file).
SCENARIOS = {
    "nodes": sc_nodes,
    "wires": sc_wires,
    "buttons": sc_buttons,
    "nav": sc_nav,
    "noinput": sc_noinput,
    "nostart": sc_nostart,
    "wiredrag": sc_wiredrag,
}
