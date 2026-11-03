"""Nanterino editor web scenarios: node diagnostics badges, fresh check on save, minimap diagnostics, column titles vs jump bar.

Purpose : diagnostics area of the editor web suite; scenarios diag, l6, emptylist (L29: server empty_list badge).
Boundary: drives the live editor through tests/web/driver.py (WebDriver, check()); never imports nanterino.server.
Invariant: verbatim slice (M7) of the former scripts/editor6_wd.py; a scenario is `sc_<name>(wd)` and is listed in
          SCENARIOS at the end of this file, which tests/web/run.py reads.
Test    : .venv/bin/python -m tests.web.run diag   (or `area:diagnostics`, or `all`)
"""
import glob, json, os, sys, time

from tests.web.driver import *  # noqa: F401,F403  (shared helpers, check(), W, BASE, ROOT)


def sc_diag(wd):
    open_editor(wd)
    E = "window.__editor"
    d0 = doc(wd)
    st, chk = W.http("POST", BASE + "/api/graph/check", d0)
    check("shipped graph: /api/graph/check 0 errors 0 warnings", st == 200 and chk.get("ok") and not chk.get("errors") and not chk.get("warnings"), str(chk.get("errors"))[:200])
    cnt = js(wd, "const b=document.querySelector('#btnDiag'); return [b.className, b.textContent]")
    check("toolbar counter: no error / warning on the shipped graph", "ok" in cnt[0], str(cnt))
    check("no error / warning badge on the shipped graph", js(wd, "return document.querySelectorAll('.dbadge.err,.dbadge.warn').length") == 0)
    # (b) live client check: reference to an unknown variable
    ids = js(wd, """const E=window.__editor; const t=E.addAt('trigger',{event:'visage'},{x:-900,y:-600},{exact:true});
      const c=E.addAt('condition',{guard:'var_compare',args:{name:'inconnue',op:'=',value:'1'}},{x:-640,y:-600},{exact:true});
      const a=E.addAt('action',{action:'mic_on'},{x:-380,y:-600},{exact:true});
      E.linkNodes(t,'output_1',c); E.linkNodes(c,'output_1',a); const m=E.dfMap(); const inv={}; for(const k in m) inv[m[k]]=k;
      return [inv[t], inv[c], inv[a]]""")
    tn, cn, an = ids
    js(wd, "document.querySelector('#btnValidate').click()")
    time.sleep(1.6)
    b = badge(wd, cn)
    check("unknown variable: red badge on the condition, message in its tooltip", b and "err" in b[0] and "inconnue" in b[1], str(b))
    cnt = js(wd, "const b=document.querySelector('#btnDiag'); return [b.className, b.querySelector('.dne') ? b.querySelector('.dne').textContent : '']")
    check("toolbar counter shows the error(s)", "err" in cnt[0] and cnt[1] != "✖ 0", str(cnt))
    check("wires of the erroring nodes are tinted", js(wd, "return document.querySelectorAll('#drawflow svg.connection.derr').length") >= 1)
    js(wd, "window.__editor.focusNode(arguments[0])", [cn])
    time.sleep(0.5)
    js(wd, "window.__editor.hideTip()")
    t = hover_tip(wd, "#node-%s > .dbadge" % dfid(wd, cn))
    check("badge hover: tooltip with the message", t and t[0] and "inconnue" in t[1], str(t))
    wd.shot("editor11-diag.png")
    away(wd)
    js(wd, "window.__editor.focusNode(arguments[0])", [tn])   # the trigger is selected, the condition stays in view
    time.sleep(0.4)
    js(wd, "window.__editor.activateTab('vars')")             # another tab: the badge click must come back to the node tab
    time.sleep(0.3)
    r = rect(wd, "#node-%s > .dbadge" % dfid(wd, cn))
    lclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
    time.sleep(0.4)
    sel = js(wd, "return window.__editor.selDf()")
    iss = js(wd, "return [...document.querySelectorAll('#inspector .isslist .iss.err')].map(e=>e.textContent)")
    check("badge click selects the node, inspector tab shows the messages", str(sel) == str(dfid(wd, cn)) and any("inconnue" in x for x in iss)
          and js(wd, "return !document.querySelector('#inspector').hidden"), "%s %s" % (sel, iss))
    # counter click cycles through the affected nodes (errors first)
    lst = js(wd, "return window.__editor.diagNodes()")
    seen = []
    for _ in range(len(lst)):
        rb = rect(wd, "#btnDiag")
        lclick(wd, rb[0] + rb[2] / 2, rb[1] + rb[3] / 2)
        time.sleep(0.4)
        seen.append(js(wd, "const m=window.__editor.dfMap(); const s=String(window.__editor.selDf()); return Object.keys(m).find(k=>String(m[k])===s)||null"))
    check("toolbar counter click selects each affected node in turn", lst and seen == lst and cn in seen, "%s vs %s" % (seen, lst))
    # fix: compare a number variable -> badge gone
    js(wd, "window.__editor.patchNode(arguments[0], {args:{name:'tours', op:'<', value:3}})", [cn])
    time.sleep(1.6)
    check("fixed: no badge on the condition (client + server check)", badge(wd, cn) is None, str(badge(wd, cn)))
    # type mismatch: order operator on a text-like variable is flagged live
    js(wd, "window.__editor.patchNode(arguments[0], {args:{name:'tours', op:'=', value:'beaucoup'}})", [cn])
    time.sleep(0.4)
    b = badge(wd, cn)
    check("type mismatch in var_compare: red badge", b and "err" in b[0] and "pas un nombre" in b[1], str(b))
    js(wd, "window.__editor.patchNode(arguments[0], {args:{name:'tours', op:'<', value:3}})", [cn])
    time.sleep(1.6)
    # (a) server-sourced: a required argument removed from a shipped action -> its node gets the badge (check `at`)
    sp = node_of(wd, "n.kind==='action' && n.params.action==='speak_phrase'")
    js(wd, "window.__editor.patchNode(arguments[0], {args:{done: arguments[1]}})", [sp["id"], sp["params"]["args"].get("done", "greeting_done")])
    time.sleep(2.0)
    ce = js(wd, "return window.__editor.checkErrors()")
    b = badge(wd, sp["id"])
    check("server check error carries the node id (at) and paints that node", any(e.get("at") == sp["id"] for e in ce) and b and "err" in b[0] and "speak_phrase" in b[1], "%s %s" % (str(ce)[:200], b))
    js(wd, "window.__editor.patchNode(arguments[0], {args: arguments[1]})", [sp["id"], sp["params"]["args"]])
    time.sleep(2.0)
    check("restored: server badge gone", badge(wd, sp["id"]) is None, str(badge(wd, sp["id"])))
    # warning case: a chain without any action (trigger -> condition -> end): amber badge
    w = js(wd, """const E=window.__editor; const t=E.addAt('trigger',{event:'sing'},{x:-900,y:-380},{exact:true});
      const c=E.addAt('condition',{guard:'mic_active'},{x:-640,y:-380},{exact:true}); const e=E.addAt('end',null,{x:-380,y:-380},{exact:true});
      E.linkNodes(t,'output_1',c); E.linkNodes(c,'output_1',e); const m=E.dfMap(); const inv={}; for(const k in m) inv[m[k]]=k; return inv[t]""")
    js(wd, "document.querySelector('#btnValidate').click()")
    time.sleep(1.6)
    b = badge(wd, w)
    check("warning case (chain without action): amber badge", b and "warn" in b[0] and "aucune action" in b[1], str(b))
    cnt = js(wd, "const b=document.querySelector('#btnDiag'); return [b.className, b.querySelector('.dnw') ? b.querySelector('.dnw').textContent : '']")
    check("counter counts the warning", cnt[1] not in ("", "⚠ 0"), str(cnt))
    wires = js(wd, "return document.querySelectorAll('#drawflow svg.connection.derr').length")
    check("disabled chain: grey info badge only (not counted)", js(wd, "return document.querySelectorAll('.dbadge.info').length") >= 1)
    print("tinted wires", wires)
    js(wd, "window.__editor.loadAll()")
    time.sleep(1.5)
    check("reload: back to a clean graph", js(wd, "return document.querySelectorAll('.dbadge.err,.dbadge.warn').length") == 0)
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


def sc_l6(wd):
    pre = set(glob.glob(ROOT + "/graph.*"))
    try:
        open_editor(wd)
        js(wd, "window.__editor.closeCtx && window.__editor.closeCtx()")
        t = js(wd, TITLE_JS, ["auto-veille"])
        check("default view: Veille column title clear of the jump bar and on screen", t and not t["hit"] and t["inView"], str(t))
        check("default view: no column title under the jump bar", js(wd, ALL_TITLES_JS) == [], str(js(wd, ALL_TITLES_JS)))
        wd.shot("editor12-default.png")
        chips = js(wd, "return [...document.querySelectorAll('#jumpbar .jchip')].map(c=>c.dataset.g)")
        check("jump bar has chips", len(chips) >= 3, str(chips))
        bad = []
        for g in chips:
            js(wd, "document.querySelector('#jumpbar .jchip[data-g=\"'+arguments[0]+'\"]').scrollIntoView({inline:'nearest',block:'nearest'})", [g])
            r = rect(wd, '#jumpbar .jchip[data-g="%s"]' % g)
            lclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
            t = js(wd, TITLE_JS, ["auto-" + g])
            others = js(wd, ALL_TITLES_JS)
            if not t or t["hit"] or not t["inView"] or others:
                bad.append((g, t, others))
        check("each jump-bar chip: its column title clear of the bar and on screen (all titles clear)", not bad, str(bad)[:400])
        r = rect(wd, "#btnFit")
        lclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
        check("Ajuster: no column title under the jump bar", js(wd, ALL_TITLES_JS) == [], str(js(wd, ALL_TITLES_JS)))
        # bar height is measured: a taller bar pushes the titles further down
        js(wd, "document.querySelector('#jumpbar').style.paddingBottom='40px'; window.__editor.fit()")
        time.sleep(0.3)
        check("taller jump bar (measured): Ajuster still clears the titles", js(wd, ALL_TITLES_JS) == [], str(js(wd, ALL_TITLES_JS)))
        js(wd, "document.querySelector('#jumpbar').style.paddingBottom=''")
        # ---- minimap diagnostics ----
        if not js(wd, "return document.querySelector('#minimap').classList.contains('open')"):
            js(wd, "document.querySelector('#minimap .mtog').click()")
            time.sleep(0.3)
        m = js(wd, MINI_JS)
        check("minimap open, no diagnostic dot on the shipped graph", m and m["open"] and m["err"] == 0 and m["warn"] == 0, str(m))
        # CHANGED (lot G1): trigger 520 px left of the condition (was 260): the larger shipped graph shrinks the minimap
        # and the trigger's own red dot (the error lists both nodes) covered the condition's dot pixel
        ids = js(wd, """const E=window.__editor; const t=E.addAt('trigger',{event:'visage'},{x:-1160,y:-600},{exact:true});
          const c=E.addAt('condition',{guard:'var_compare',args:{name:'inconnue',op:'=',value:'1'}},{x:-640,y:-600},{exact:true});
          const a=E.addAt('action',{action:'mic_on'},{x:-380,y:-600},{exact:true});
          E.linkNodes(t,'output_1',c); E.linkNodes(c,'output_1',a); const m=E.dfMap(); const inv={}; for(const k in m) inv[m[k]]=k;
          return [inv[t], inv[c], inv[a]]""")
        js(wd, "document.querySelector('#btnValidate').click()")
        time.sleep(1.6)
        m = js(wd, MINI_JS)
        red = [d for d in (m or {}).get("dots", []) if d[0] == ids[1] and d[1] == "err"]
        check("minimap: red dot on the erroring node (pixel red)", red and red[0][2][0] > 200 and red[0][2][1] < 110 and red[0][2][2] < 110, str(m)[:300])
        check("minimap with errors stays readable (not faded)", float(js(wd, "return getComputedStyle(document.querySelector('#minimap')).opacity")) >= 0.8)
        js(wd, "window.__editor.focusNode(arguments[0])", [ids[1]])
        time.sleep(0.4)
        wd.shot("editor12-minimap-diag.png")
        js(wd, "window.__editor.patchNode(arguments[0], {args:{name:'tours', op:'<', value:3}})", [ids[1]])
        time.sleep(1.6)
        m = js(wd, MINI_JS)
        check("minimap: red dot gone after the fix", m and m["err"] == 0 and not any(d[0] == ids[1] for d in m["dots"]), str(m)[:300])
        w = js(wd, """const E=window.__editor; const t=E.addAt('trigger',{event:'sing'},{x:-900,y:-380},{exact:true});
          const c=E.addAt('condition',{guard:'mic_active'},{x:-640,y:-380},{exact:true}); const e=E.addAt('end',null,{x:-380,y:-380},{exact:true});
          E.linkNodes(t,'output_1',c); E.linkNodes(c,'output_1',e); const m=E.dfMap(); const inv={}; for(const k in m) inv[m[k]]=k; return inv[t]""")
        js(wd, "document.querySelector('#btnValidate').click()")
        time.sleep(1.6)
        m = js(wd, MINI_JS)
        amb = [d for d in (m or {}).get("dots", []) if d[0] == w and d[1] == "warn"]
        check("minimap: amber dot on the warning node", amb and amb[0][2][0] > 200 and 120 < amb[0][2][1] < 210 and amb[0][2][2] < 90, str(m)[:300])
        nv0 = js(wd, "return window.__editor.nav()")
        r = rect(wd, "#minimap canvas")
        lclick(wd, r[0] + r[2] * 0.8, r[1] + r[3] * 0.5)
        nv1 = js(wd, "return window.__editor.nav()")
        check("minimap click still navigates", abs(nv1["x"] - nv0["x"]) > 20 or abs(nv1["y"] - nv0["y"]) > 20, "%s -> %s" % (nv0, nv1))
        js(wd, "window.__editor.loadAll()")
        time.sleep(1.5)
        # ---- save right after a fix (server-sourced error, debounce still pending) ----
        sp = node_of(wd, "n.kind==='action' && n.params.action==='speak_phrase'")
        js(wd, "window.__editor.patchNode(arguments[0], {args:{done: arguments[1]}})", [sp["id"], sp["params"]["args"].get("done", "greeting_done")])
        time.sleep(2.0)
        b = badge(wd, sp["id"])
        check("save test: server error badge present before the fix", b and "err" in b[0], str(b))
        js(wd, "document.querySelectorAll('#toasts .toast').forEach(t=>t.remove())")
        t0 = time.time()
        js(wd, "window.__editor.patchNode(arguments[0], {args: arguments[1]}); document.querySelector('#btnSave').click()", [sp["id"], sp["params"]["args"]])
        saved, toasts = False, ""
        for _ in range(40):
            time.sleep(0.25)
            toasts = js(wd, "return [...document.querySelectorAll('#toasts .toast')].map(e=>e.className+':'+e.textContent).join(' | ')")
            if "enregistr" in toasts.lower():
                saved = True
                break
        dt = time.time() - t0
        check("save right after the fix: saved, no blocked toast", saved and "à corriger" not in toasts and "toast err" not in toasts
              and os.path.exists(ROOT + "/graph.yaml"), "%.2fs %s" % (dt, toasts[:200]))
        check("save right after the fix: no badge left, dirty flag cleared", badge(wd, sp["id"]) is None and js(wd, "return document.querySelector('#dirty').hidden"))
        # a doc the fresh check rejects is never posted: break it and save at once
        mt = os.path.getmtime(ROOT + "/graph.yaml")
        js(wd, "document.querySelectorAll('#toasts .toast').forEach(t=>t.remove())")
        js(wd, "window.__editor.patchNode(arguments[0], {args:{done: arguments[1]}}); document.querySelector('#btnSave').click()", [sp["id"], sp["params"]["args"].get("done", "greeting_done")])
        time.sleep(2.0)
        toasts = js(wd, "return [...document.querySelectorAll('#toasts .toast')].map(e=>e.className+':'+e.textContent).join(' | ')")
        check("save right after breaking: blocked by the fresh check, nothing written", "à corriger" in toasts and os.path.getmtime(ROOT + "/graph.yaml") == mt, toasts[:200])
        check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))
    finally:
        W.http("POST", BASE + "/api/graph/reset", {})
        for f in set(glob.glob(ROOT + "/graph.*")) - pre:
            try:
                os.remove(f)
            except OSError:
                pass
        print("LEFT OVER", sorted(set(glob.glob(ROOT + "/graph.*")) - pre))


def sc_emptylist(wd):
    """L29: server `empty_list` warning (graph.py empty_list_diagnostics) end to end. A new empty phrase list made in
    the Variables panel + a « Dire une phrase au hasard » (say_random) action on it -> amber badge on that action with
    the empty_list message; a « Ajouter à une liste » (list_add) action filling the list -> the badge is gone after the
    check refresh. The warning is server-only (analysis.js only paints it), so disabling the server call fails this.
    Never saves; reloads the shipped graph at the end and leaves no graph.* file behind."""
    pre = set(glob.glob(ROOT + "/graph.*"))
    lname = "l29_vide"
    try:
        open_editor(wd)
        check("emptylist: shipped graph has no warning badge", js(wd, "return document.querySelectorAll('.dbadge.err,.dbadge.warn').length") == 0)
        # ---- new empty phrase list, created like a user in the Variables panel
        js(wd, "document.querySelector('#btnVars').click()")
        time.sleep(2.0)
        _click(wd, "#vars button[data-vtab=lists]")
        time.sleep(0.3)
        _set(wd, "#vars input[data-new=list]", lname)
        _set(wd, "#vars select[data-new=listkind]", "list")
        _set(wd, "#vars select[data-new=listtype]", "phrase")
        _click(wd, "#vars button[data-new=listadd]")
        time.sleep(0.5)
        li = _vmeta(wd, lname, "lists")
        check("emptylist: new phrase list created empty in the Variables panel", li is not None and li.get("type") == "phrase" and not li.get("items"), str(li))
        js(wd, "window.__editor.activateTab('node')")
        # ---- say_random on it: the server check flags the action node (amber, kind empty_list)
        ids = js(wd, """const E=window.__editor; const t=E.addAt('trigger',{event:'visage'},{x:-900,y:-600},{exact:true});
          const a=E.addAt('action',{action:'say_random',args:{list:arguments[0]}},{x:-640,y:-600},{exact:true});
          E.linkNodes(t,'output_1',a); const m=E.dfMap(); const inv={}; for(const k in m) inv[m[k]]=k; return [inv[t], inv[a]]""", [lname])
        tn, an = ids
        js(wd, "document.querySelector('#btnValidate').click()")
        time.sleep(2.0)
        st, chk = W.http("POST", BASE + "/api/graph/check", doc(wd))
        ws = [w for w in (chk or {}).get("warnings", []) if isinstance(w, dict) and w.get("kind") == "empty_list"]
        check("emptylist: /api/graph/check returns an empty_list warning on the say_random node", st == 200 and any(an in (w.get("at"), w.get("node")) for w in ws), str(chk)[:300])
        b = badge(wd, an)
        check("emptylist: amber badge on the say_random node, empty_list message in its tooltip",
              b and "warn" in b[0] and "err" not in b[0].split() and lname in b[1] and "is empty" in b[1], str(b))
        cnt = js(wd, "const b=document.querySelector('#btnDiag'); return [b.className, b.querySelector('.dnw') ? b.querySelector('.dnw').textContent : '']")
        check("emptylist: toolbar counter counts the warning", cnt[1] not in ("", "⚠ 0"), str(cnt))
        js(wd, "window.__editor.focusNode(arguments[0])", [an])
        time.sleep(0.4)
        wd.shot("editor20-emptylist.png")
        # ---- list_add filling the list: the warning goes away on the next check
        js(wd, """const E=window.__editor; const t=E.addAt('trigger',{event:'sing'},{x:-900,y:-380},{exact:true});
          const a=E.addAt('action',{action:'list_add',args:{list:arguments[0],value:'Bonjour !'}},{x:-640,y:-380},{exact:true});
          E.linkNodes(t,'output_1',a); return true""", [lname])
        js(wd, "document.querySelector('#btnValidate').click()")
        time.sleep(2.0)
        st, chk = W.http("POST", BASE + "/api/graph/check", doc(wd))
        ws = [w for w in (chk or {}).get("warnings", []) if isinstance(w, dict) and w.get("kind") == "empty_list"]
        check("emptylist: list filled by list_add -> no empty_list warning from the server", st == 200 and not ws, str(ws)[:300])
        b = badge(wd, an)
        check("emptylist: list filled by list_add -> badge gone after the check refresh", b is None or ("warn" not in b[0] and "err" not in b[0]), str(b))
        check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))
    finally:
        # restore the shipped graph state (nothing was saved; reload drops the list and the added nodes)
        try:
            js(wd, "window.__editor.loadAll()")
            time.sleep(1.5)
            check("emptylist: reload -> shipped graph back, list gone, no warning badge",
                  _vmeta(wd, lname, "lists") is None and js(wd, "return document.querySelectorAll('.dbadge.err,.dbadge.warn').length") == 0)
        except Exception as e:  # keep cleanup going
            check("emptylist: reload", False, repr(e))
        left = set(glob.glob(ROOT + "/graph.*")) - pre
        check("emptylist: no override file left", not left, str(sorted(left)))


# Scenario registry read by tests/web/run.py (order = order of the former single file).
SCENARIOS = {
    "diag": sc_diag,
    "l6": sc_l6,
    "emptylist": sc_emptylist,
}
