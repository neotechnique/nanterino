"""Nanterino editor web scenarios: the user's manual checks replayed with real pointer / key / touch actions (VIEWPORT env).

Purpose : human area of the editor web suite; scenarios human.
Boundary: drives the live editor through tests/web/driver.py (WebDriver, check()); never imports nanterino.server.
Invariant: verbatim slice (M7) of the former scripts/editor6_wd.py; a scenario is `sc_<name>(wd)` and is listed in
          SCENARIOS at the end of this file, which tests/web/run.py reads.
Test    : .venv/bin/python -m tests.web.run human   (or `area:human`, or `all`)
"""
import glob, json, os, sys, time

from tests.web.driver import *  # noqa: F401,F403  (shared helpers, check(), W, BASE, ROOT)

# ---- lot L7 (2026-11-01): "human" scenario, the user's manual checks reproduced with real WebDriver pointer actions ----
CTRL = ""


def touch(wd, pts, hold_ms=0, gap_ms=0):
    """One touch contact at pts[0] (pointerType touch): down, hold, up. pts = [(x, y)]."""
    acts = [{"type": "pointerMove", "duration": 0, "x": int(pts[0][0]), "y": int(pts[0][1])}, {"type": "pointerDown", "button": 0}]
    if hold_ms:
        acts.append({"type": "pause", "duration": hold_ms})
    acts.append({"type": "pointerUp", "button": 0})
    wd.cmd("POST", "/actions", {"actions": [{"type": "pointer", "id": "t", "parameters": {"pointerType": "touch"}, "actions": acts}]})
    wd.cmd("DELETE", "/actions")
    time.sleep(0.4)


def inside_win(wd, sel_js):
    return js(wd, "const r=%s; return [Math.round(r.left),Math.round(r.top),Math.round(r.right),Math.round(r.bottom),innerWidth,innerHeight, r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight]" % sel_js)


def sc_human(wd):
    pre = set(glob.glob(ROOT + "/graph.*")) | set(glob.glob(ROOT + "/graph*.bak*"))
    iw, ih = js(wd, "return [innerWidth, innerHeight]")
    print("VIEWPORT", iw, ih, flush=True)
    try:
        open_editor(wd)
        js(wd, "window.__editor.closeCtx && window.__editor.closeCtx()")
        # ---- 1 default view at this window size
        t = js(wd, TITLE_JS, ["auto-veille"])
        sw = js(wd, "return [document.documentElement.scrollWidth, document.body.scrollWidth, innerWidth, window.scrollX]")
        check("1 [%dx%d] default view: Veille title fully visible, not under the jump bar" % (iw, ih), t and not t["hit"] and t["inView"]
              and t["title"][1] >= 0 and t["title"][1] + t["title"][3] <= ih and t["title"][0] >= 0 and t["title"][0] + t["title"][2] <= iw, str(t))
        check("1 [%dx%d] no horizontal page scrollbar" % (iw, ih), sw[0] <= sw[2] and sw[1] <= sw[2] and sw[3] == 0, str(sw))
        check("1 [%dx%d] no column title under the jump bar" % (iw, ih), js(wd, ALL_TITLES_JS) == [], str(js(wd, ALL_TITLES_JS)))
        if iw >= 1900:
            wd.shot("human-1920-default.png")
        # ---- 9 ADAPTED (L10): no palette; hierarchy default state (facts) and its filter
        hr = js(wd, "return [...document.querySelectorAll('#tree .hrow')].map(r=>r.dataset.type)")
        print("HIERARCHY default", {t: hr.count(t) for t in set(hr)})
        fr = rect(wd, "#treeFilter")
        lclick(wd, fr[0] + 20, fr[1] + fr[3] / 2)
        for ch in "intention":
            key(wd, ch)
        time.sleep(0.4)
        hits = js(wd, "return [...document.querySelectorAll('#tree .hrow.hit .hlab')].map(e=>e.textContent.toLowerCase())")
        check("9 hierarchy filter 'intention' finds chains (facts above)", len(hits) >= 3 and all("intention" in x for x in hits), "%d hits" % len(hits))
        js(wd, "const s=document.querySelector('#treeFilter'); s.value=''; s.dispatchEvent(new Event('input')); s.blur()")
        time.sleep(0.3)
        # ---- 5 no Start node, triggers without input port
        d = doc(wd)
        kinds = {}
        for n in d["nodes"]:
            kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
        dom = js(wd, """const m=window.__editor.dfMap(), d=window.__editor.serialize(); const o={start:document.querySelectorAll('.drawflow-node.start').length, startText:[...document.querySelectorAll('.drawflow-node')].filter(e=>/^\\s*(Début|Start)\\s*$/.test((e.querySelector('.nhead')||e).textContent.trim())).length, trigIn:0, trig:0};
          d.nodes.filter(n=>n.kind==='trigger').forEach(n=>{o.trig++; o.trigIn+=document.querySelectorAll('#node-'+m[n.id]+' .inputs .input').length}); return o""")
        check("5 no Start / Début node (doc + DOM); triggers have no input port", "start" not in kinds and dom["start"] == 0 and dom["startText"] == 0 and dom["trig"] > 0 and dom["trigIn"] == 0, "%s %s" % (kinds, dom))
        # ---- 2 fast real drag of a connected node, release over the palette
        links = d["links"]
        act = next(n["id"] for n in d["nodes"] if n["kind"] == "action" and n.get("group") == "ecoute"
                   and any(l["to"] == n["id"] for l in links) and any(l["from"] == n["id"] for l in links))
        df = dfid(wd, act)
        center_on(wd, act)
        w0 = wires_of(wd, df)
        r = rect(wd, "#node-%s" % df)
        gx, gy = r[0] + r[2] / 2, r[1] + 14
        pos0 = pos_of(wd, act)
        mv = lambda x, y, dur: {"type": "pointerMove", "duration": dur, "x": int(x), "y": int(y)}
        wd.cmd("POST", "/actions", {"actions": [{"type": "pointer", "id": "m", "parameters": {"pointerType": "mouse"},
               "actions": [mv(gx, gy, 0), {"type": "pointerDown", "button": 0}, mv(gx + 90, gy + 40, 25), mv(gx + 180, gy + 80, 25)]}]})
        time.sleep(0.3)
        wl = wires_of(wd, df)
        check("2 fast drag (2 moves x 25 ms): while held, wires stay on ports (±3 px) and follow", len(wl) == len(w0) and not _ends_ok(wl) and all(a["d"] != b["d"] for a, b in zip(w0, wl)), str(_ends_ok(wl)))
        px = rect(wd, "#drawflow")[0] - 40
        wd.cmd("POST", "/actions", {"actions": [{"type": "pointer", "id": "m", "parameters": {"pointerType": "mouse"},
               "actions": [mv(px, gy + 100, 30), {"type": "pointerUp", "button": 0}]}]})
        wd.cmd("DELETE", "/actions")
        time.sleep(0.6)
        st = js(wd, "return window.__editor.dfState()")
        posr = pos_of(wd, act)
        wr = wires_of(wd, df)
        check("2 release over the left palette: wires on ports (±3 px)", not _ends_ok(wr), str(_ends_ok(wr)))
        # the pointer now wanders over the canvas with no button: a stuck node would follow it
        e = view_empty_point(wd) or (700, 600)
        hover(wd, e[0], e[1]); time.sleep(0.2); hover(wd, e[0] + 60, e[1] + 30); time.sleep(0.5)
        posw = pos_of(wd, act)
        check("2 node released after mouseup (not stuck to the pointer)", not st["drag"] and st["ele"] is None and posw == posr and posr != pos0, "%s -> %s -> %s %s" % (pos0, posr, posw, st))
        # ---- 4 Ctrl+Z / Ctrl+Y on that move
        time.sleep(0.6)
        js(wd, "document.activeElement && document.activeElement.blur()")
        chord(wd, CTRL, "z")
        df = dfid(wd, act)
        wu = wires_of(wd, df)
        posu = pos_of(wd, act)
        check("4 Ctrl+Z: node back, wires snap to ports", posu == pos0 and len(wu) == len(w0) and not _ends_ok(wu), "%s %s" % (posu, _ends_ok(wu)))
        chord(wd, CTRL, "y")
        df = dfid(wd, act)
        wy = wires_of(wd, df)
        posy = pos_of(wd, act)
        check("4 Ctrl+Y: node forward, wires snap to ports", posy == posr and not _ends_ok(wy), "%s %s" % (posy, _ends_ok(wy)))
        check("4 console errors 0 after Ctrl+Z / Ctrl+Y", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))
        chord(wd, CTRL, "z")
        # ---- 3 drag the Écoute column frame title: nodes + wires together
        js(wd, "document.querySelector('#jumpbar .jchip[data-g=ecoute]').click()")
        time.sleep(0.7)
        df = dfid(wd, act)
        grp = [n["id"] for n in doc(wd)["nodes"] if n.get("group") == "ecoute"]
        before = {i: pos_of(wd, i) for i in grp}
        fw0 = wires_of(wd, df)
        tr = rect(wd, ".frame[data-fid=auto-ecoute] .ftitle")
        fx, fy = tr[0] + min(40, tr[2] / 2), tr[1] + tr[3] / 2
        hit = js(wd, "const e=document.elementFromPoint(arguments[0],arguments[1]); return !!(e && e.closest('.ftitle'))", [fx, fy])
        _press_move(wd, fx, fy, fx + 70, fy + 50, release=False, steps=3)
        fwl = wires_of(wd, df)
        _release(wd)
        fw1 = wires_of(wd, df)
        after = {i: pos_of(wd, i) for i in grp}
        dl = [(after[i][0] - before[i][0], after[i][1] - before[i][1]) for i in grp]
        same = all(abs(a[0] - dl[0][0]) <= 1 and abs(a[1] - dl[0][1]) <= 1 for a in dl)
        check("3 Écoute frame title drag: all %d nodes moved by the same delta, wires on ports live + after" % len(grp),
              hit and same and dl[0] != (0, 0) and not _ends_ok(fwl) and not _ends_ok(fw1) and all(a["d"] != b["d"] for a, b in zip(fw0, fw1)), "delta=%s hit=%s %s %s" % (dl[0], hit, _ends_ok(fwl), _ends_ok(fw1)))
        time.sleep(0.6)
        js(wd, "document.querySelector('#btnUndo').click()")
        time.sleep(0.6)
        # ---- 7 right-click near the RIGHT edge of the canvas -> Insérer > Actions > theme > item
        cv = rect(wd, "#drawflow")
        e = js(wd, """const st=document.querySelector('#drawflow').getBoundingClientRect();
          for(let x=st.right-24;x>st.right-260;x-=8) for(let y=st.y+120;y<st.bottom-80;y+=20){
            const el=document.elementFromPoint(x,y); if(el && el.closest('#drawflow') && !el.closest('.drawflow-node,.postit,.ftitle,.fresize,path.main-path,.ctx,#jumpbar,#minimap,.rbadge')) return [x,y]; } return null""")
        n0 = len(doc(wd)["nodes"])
        rclick(wd, *e)
        click_item(wd, "Actions"); click_item(wd, "Micro & écoute")      # ADAPTED (L10): no "Insérer un nœud" level
        rects = js(wd, "return [...document.querySelectorAll('.ctx')].map(m=>{const r=m.getBoundingClientRect(); return [Math.round(r.left),Math.round(r.top),Math.round(r.right),Math.round(r.bottom), r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight]})")
        wd.shot("human-insert-rightedge.png")
        ok_ins = click_item(wd, "Ouvrir le micro")
        d2 = doc(wd)
        check("7 right-edge (x=%d of %d) Insérer>Actions>Micro&écoute: %d submenus all inside the window" % (e[0], iw, len(rects)), len(rects) == 3 and all(x[4] for x in rects), str(rects))
        check("7 insert at the right edge works", ok_ins and len(d2["nodes"]) == n0 + 1 and d2["nodes"][-1]["params"].get("action") == "mic_on", str(d2["nodes"][-1])[:100])
        js(wd, "document.querySelector('#btnUndo').click()")
        time.sleep(0.5)
        # ---- 8 compact post-it, real hover
        nt = js(wd, "return window.__editor.addNote()")
        js(wd, "window.__editor.editNote(window.__editor.notes().slice(-1)[0], {title:'Note longue', text: arguments[0]}, true)", [LONG])
        time.sleep(0.4)
        sel = ".postit[data-nid=%s]" % nt["id"]
        r = rect(wd, sel + " .pmode")
        lclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
        time.sleep(0.4)
        js(wd, "window.__editor.hideTip()")
        t = hover_tip(wd, sel + " .pline", wait=1.0)
        tipr = inside_win(wd, "document.getElementById('tip').getBoundingClientRect()")
        fs = js(wd, "return parseFloat(getComputedStyle(document.getElementById('tip')).fontSize)")
        # the bubble is pointer-events:none (elementFromPoint skips it): "on top" = highest z-index of every positioned element
        top = js(wd, """const t=document.getElementById('tip'); const z=e=>{const v=parseInt(getComputedStyle(e).zIndex); return isNaN(v)?0:v};
          const mine=z(t); let other=0; document.querySelectorAll('body *').forEach(e=>{ if(e!==t && !t.contains(e)){ const c=getComputedStyle(e); if(c.position!=='static') other=Math.max(other,z(e)); }});
          return getComputedStyle(t).position==='fixed' && mine>other""")
        wd.shot("human-postit-compact.png")
        check("8 compact post-it hover: tooltip shows the full text", t and t[0] and "FIN-DU-TEXTE" in t[1] and "Deuxième paragraphe" in t[1], str(t)[:100])
        check("8 tooltip rect inside the window, on top of panels (not clipped), font >= 11 px", tipr[6] and top and fs >= 11, "rect=%s topmost=%s font=%s" % (tipr, top, fs))
        away(wd)
        # ---- 6 touch (pointerType touch)
        js(wd, "window.__t={ts:0,pd:0,pt:[]}; document.addEventListener('touchstart',()=>window.__t.ts++,true); document.addEventListener('pointerdown',e=>{window.__t.pd++; window.__t.pt.push(e.pointerType)},true)")
        js(wd, "window.__editor.hideTip()")
        rb = rect(wd, "#btnSave")
        touch(wd, [(rb[0] + rb[2] / 2, rb[1] + rb[3] / 2)], hold_ms=600)
        # shot while the bubble may still be there: re-do the hold without release for the screenshot
        tp = tip_state(wd)
        tc = js(wd, "return window.__t")
        synthetic = False
        if not (tc["ts"] or "touch" in tc["pt"]):
            print("TOUCH: geckodriver headless delivered NO touch events (%s): falling back to SYNTHETIC events" % tc)
            synthetic = True
        if synthetic:
            js(wd, """const e=document.querySelector('#btnSave'); const r=e.getBoundingClientRect(); const o={bubbles:true,cancelable:true,clientX:r.x+r.width/2,clientY:r.y+r.height/2,pointerType:'touch',isPrimary:true};
              e.dispatchEvent(new PointerEvent('pointerdown',o)); e.dispatchEvent(new Event('touchstart',{bubbles:true,cancelable:true}))""")
            time.sleep(0.8)
            tp = tip_state(wd)
            js(wd, "document.querySelector('#btnSave').dispatchEvent(new Event('touchend',{bubbles:true}))")
        else:
            # the bubble disappears on touchend? re-hold and capture before release
            wd.cmd("POST", "/actions", {"actions": [{"type": "pointer", "id": "t", "parameters": {"pointerType": "touch"}, "actions": [mv(rb[0] + rb[2] / 2, rb[1] + rb[3] / 2, 0), {"type": "pointerDown", "button": 0}, {"type": "pause", "duration": 700}]}]})
            tp_held = tip_state(wd)
            wd.shot("human-touch-tooltip.png")
            wd.cmd("POST", "/actions", {"actions": [{"type": "pointer", "id": "t", "parameters": {"pointerType": "touch"}, "actions": [{"type": "pointerUp", "button": 0}]}]})
            wd.cmd("DELETE", "/actions")
            time.sleep(0.3)
            tp = tp_held if tp_held[0] else tp
        label = "SYNTHETIC" if synthetic else "real touch"
        check("6 [%s] long-press ~600 ms on a toolbar button: bubble with text" % label, tp and tp[0] and len(tp[1]) > 5, "%s events=%s" % (str(tp)[:100], tc))
        if synthetic:
            wd.shot("human-touch-tooltip.png")
        e2 = view_empty_point(wd) or (700, 600)
        if synthetic:
            js(wd, "document.dispatchEvent(new Event('touchstart',{bubbles:true}))")
        else:
            touch(wd, [e2])
        time.sleep(0.4)
        check("6 [%s] next tap elsewhere hides the bubble" % label, not tip_state(wd)[0], str(tip_state(wd)))
        actn = node_of(wd, "n.kind==='action' && n.params.action==='set_var'")
        js(wd, "window.__editor.focusNode(arguments[0]); window.__editor.activateTab('node')", [actn["id"]])
        time.sleep(0.5)
        ri = rect(wd, "#inspector .fld .tipi")
        if synthetic:
            js(wd, "document.querySelector('#inspector .fld .tipi').click()")
        else:
            touch(wd, [(ri[0] + ri[2] / 2, ri[1] + ri[3] / 2)])
        time.sleep(0.3)
        s1 = tip_state(wd)
        if synthetic:
            js(wd, "document.querySelector('#inspector .fld .tipi').click()")
        else:
            touch(wd, [(ri[0] + ri[2] / 2, ri[1] + ri[3] / 2)])
        time.sleep(0.3)
        s2 = tip_state(wd)
        check("6 [%s] tap on the inspector 'i' icon toggles the bubble (on then off)" % label, s1[0] and len(s1[1]) > 5 and not s2[0], "%s / %s" % (str(s1)[:80], s2))
        # ---- 10 break a node, badge + minimap dot, fix, save at once, restore
        js(wd, "window.__editor.hideTip()")
        ids = js(wd, """const E=window.__editor; const t=E.addAt('trigger',{event:'visage'},{x:-900,y:-600},{exact:true});
          const c=E.addAt('condition',{guard:'var_compare',args:{name:'inconnue',op:'=',value:'1'}},{x:-640,y:-600},{exact:true});
          const a=E.addAt('action',{action:'mic_on'},{x:-380,y:-600},{exact:true});
          E.linkNodes(t,'output_1',c); E.linkNodes(c,'output_1',a); const m=E.dfMap(); const inv={}; for(const k in m) inv[m[k]]=k; return [inv[t], inv[c], inv[a]]""")
        if not js(wd, "return document.querySelector('#minimap').classList.contains('open')"):
            rm = rect(wd, "#minimap .mtog")
            lclick(wd, rm[0] + rm[2] / 2, rm[1] + rm[3] / 2)
            time.sleep(0.3)
        rv = rect(wd, "#btnValidate")
        lclick(wd, rv[0] + rv[2] / 2, rv[1] + rv[3] / 2)
        time.sleep(1.8)
        b = badge(wd, ids[1])
        m = js(wd, MINI_JS)
        red = [x for x in (m or {}).get("dots", []) if x[0] == ids[1] and x[1] == "err"]
        js(wd, "window.__editor.focusNode(arguments[0])", [ids[1]])
        time.sleep(0.5)
        wd.shot("human-diag-minimap.png")
        check("10 broken node: red badge", b and "err" in b[0], str(b))
        check("10 broken node: red dot on the minimap (Carte)", red and red[0][2][0] > 200 and red[0][2][1] < 110 and red[0][2][2] < 110, str(red))
        js(wd, "document.querySelectorAll('#toasts .toast').forEach(t=>t.remove())")
        js(wd, "window.__editor.patchNode(arguments[0], {args:{name:'tours', op:'<', value:3}})", [ids[1]])
        rs = rect(wd, "#btnSave")
        lclick(wd, rs[0] + rs[2] / 2, rs[1] + rs[3] / 2)       # real click, right after the fix
        saved, toasts = False, ""
        for _ in range(30):
            toasts = js(wd, "return [...document.querySelectorAll('#toasts .toast')].map(e=>e.className+':'+e.textContent).join(' | ')")
            if "enregistr" in toasts.lower():
                saved = True
                break
            time.sleep(0.25)
        check("10 fix + immediate real click on Enregistrer et appliquer: saved, no blocked toast", saved and "à corriger" not in toasts and "toast err" not in toasts and os.path.exists(ROOT + "/graph.yaml"), toasts[:200])
        check("10 console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))
        # restore through the editor flow
        rr = rect(wd, "#btnReset")
        lclick(wd, rr[0] + rr[2] / 2, rr[1] + rr[3] / 2)
        time.sleep(0.5)
        clicked = js(wd, "const b=[...document.querySelectorAll('#modal button')].find(x=>x.textContent.trim()==='Revenir au graphe par défaut'); if(!b) return false; b.click(); return true")
        time.sleep(2.0)
        print("RESET via UI flow clicked:", clicked)
        left = sorted(set(glob.glob(ROOT + "/graph.*")) | set(glob.glob(ROOT + "/graph*.bak*")))
        print("FILES after UI reset", left)
    finally:
        W.http("POST", BASE + "/api/graph/reset", {})
        for f in (set(glob.glob(ROOT + "/graph.*")) | set(glob.glob(ROOT + "/graph*.bak*"))) - pre:
            try:
                os.remove(f)
            except OSError:
                pass
        left = sorted((set(glob.glob(ROOT + "/graph.*")) | set(glob.glob(ROOT + "/graph*.bak*"))) - pre)
        check("10 no graph.yaml / graph.layout.json override left in the repo", not left and not os.path.exists(ROOT + "/graph.yaml") and not os.path.exists(ROOT + "/graph.layout.json"), str(left))
        st, chk = W.http("POST", BASE + "/api/graph/check", doc(wd) if False else W.http("GET", BASE + "/api/graph/visual")[1])
        check("shipped graph check 0 errors 0 warnings after restore", st == 200 and not chk.get("errors") and not chk.get("warnings"), "%s/%s" % (len(chk.get("errors") or []), len(chk.get("warnings") or [])))


# Scenario registry read by tests/web/run.py (order = order of the former single file).
SCENARIOS = {
    "human": sc_human,
}
