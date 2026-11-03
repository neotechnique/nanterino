"""Nanterino editor web scenarios: inspector value-source picker (lot M5 properties).

Purpose : inspector area of the editor web suite; scenarios props.
Boundary: drives the live editor through tests/web/driver.py (WebDriver, check()); never imports nanterino.server.
Invariant: verbatim slice (M7) of the former scripts/editor6_wd.py; a scenario is `sc_<name>(wd)` and is listed in
          SCENARIOS at the end of this file, which tests/web/run.py reads.
Test    : .venv/bin/python -m tests.web.run props   (or `area:inspector`, or `all`)
"""
import glob, json, os, sys, time

from tests.web.driver import *  # noqa: F401,F403  (shared helpers, check(), W, BASE, ROOT)


def _src_items(wd, sel):
    """Open the ▾ menu of the source button `sel` (JS click) and return {items: [data-src], groups: [labels]}."""
    r = js(wd, """const b=document.querySelector(arguments[0]); if(!b) return null; document.querySelectorAll('.srcmenu').forEach(m=>m.remove());
      b.click(); const m=b.closest('.srcdd').querySelector('.srcmenu'); if(!m) return null;
      return {items:[...m.querySelectorAll('.srci')].map(e=>e.dataset.src), groups:[...m.querySelectorAll('.srcgrp')].map(e=>e.textContent)}""", [sel])
    time.sleep(0.2)
    return r


def _src_pick(wd, sel, src):
    """Pick source `src` in the ▾ menu of button `sel` (opens it when closed)."""
    ok = js(wd, """const b=document.querySelector(arguments[0]); if(!b) return false; const dd=b.closest('.srcdd');
      if(!dd.querySelector('.srcmenu')) b.click(); const it=dd.querySelector('.srcmenu .srci[data-src="'+arguments[1]+'"]');
      if(!it) return false; it.click(); return true""", [sel, src])
    time.sleep(0.5)
    return ok


def _nargs(wd, nid):
    n = next((n for n in doc(wd)["nodes"] if n["id"] == nid), None)
    return ((n or {}).get("params") or {}).get("args")


def sc_props(wd):
    """M5: value source picker in the inspector (GC2-style ▾). set_var value: Variable source saved as the `$x`
    shorthand, « Au hasard dans une liste » saved as {get: random_from_list, list}, nested calc A = variable,
    op +, B = constant 1 typed as a number, incompatible sources not offered (string vs number fields), depth limit
    (no ▾ inside 4 sources), server type error lands as a badge, « Valeur fixe » restores the plain control, node
    tooltip says the source in words, save + reload keeps everything, Tester simulate gives the computed value.
    Screenshot tests/results/editor18-props.png. Saves once; rolled back at the end (reset, own graph.* removed)."""
    pre = set(glob.glob(ROOT + "/graph.*"))
    state_pre = os.path.exists(ROOT + "/state")
    st_files_pre = set(glob.glob(ROOT + "/state/*")) if state_pre else set()
    E = "window.__editor"
    try:
        st, V = W.http("GET", BASE + "/api/graph/vocab")
        tc = V.get("type_compat") or {}
        check("vocab: type_compat (one entry per type) + config key types", set(tc) == {t["id"] for t in V["var_types"]}
              and any(a.get("types") for e in V["properties"]["get"] for a in e["args"]), str(sorted(tc))[:200])
        open_editor(wd)
        js(wd, "document.querySelector('#btnVars').click()")
        time.sleep(1.5)
        for vid, t, val in (("p5_s", "string", None), ("p5_t", "string", None), ("p5_m", "number", "4"), ("p5_n", "number", None)):
            _set(wd, "#vars input[data-new=var]", vid)
            _set(wd, "#vars select[data-new=vartype]", t)
            _click(wd, "#vars button[data-new=varadd]")
            time.sleep(0.25)
            if val is not None:
                _vsel(wd, vid)
                _set(wd, "#vars .vedit input[data-opt=value]", val)
                time.sleep(0.2)
        check("variables p5_* created", (_vmeta(wd, "p5_m") or {}).get("value") == 4 and _vmeta(wd, "p5_s") is not None, str(_vmeta(wd, "p5_m")))
        # the reset_repairs action of the veille entry chain (it runs at the simulator start)
        nid = js(wd, """const E=window.__editor, d=E.serialize(), ids=E.computeChains(d).keys.get('veille/enter')||[];
          const n=d.nodes.find(n=>ids.includes(n.id) && n.kind==='action' && n.params.action==='reset_repairs'); return n?n.id:null""")
        check("veille entry chain has a reset_repairs action", bool(nid), str(nid))
        js(wd, E + ".activateTab('node'); " + E + ".focusNode(arguments[0])", [nid])
        time.sleep(0.6)
        ok = _pick_dd(wd, "Action", "Changer une variable")
        time.sleep(0.4)
        _set(wd, "#inspector select.varsel", "p5_t")
        time.sleep(0.4)
        BTN = "#inspector button.srcbtn[data-src-for=value]"
        tip = js(wd, "const b=document.querySelector(arguments[0]); return b?[b.dataset.tip, !!b.closest('.srcwrap'), !b.closest('label')]:null", [BTN])
        check("set_var value: ▾ button « Source de la valeur » next to the plain control (outside its label)",
              ok and tip == ["Source de la valeur", True, True], "%s %s" % (ok, tip))
        # a real pointer click opens the grouped menu
        r = rect(wd, BTN)
        lclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
        menu = js(wd, """const m=document.querySelector('#inspector .srcmenu'); return m?{items:[...m.querySelectorAll('.srci')].map(e=>e.dataset.src),
          groups:[...m.querySelectorAll('.srcgrp')].map(e=>e.textContent), first:(m.querySelector('.srci')||{}).textContent||''}:null""")
        print("MENU string", menu)
        check("pointer click opens the menu: Valeur fixe first, groups in order, string field offers variable / phrase / list sources",
              menu and menu["first"].strip() == "Valeur fixe" and menu["items"][0] == "constant"
              and all(x in menu["items"] for x in ("variable", "utterance", "list_item", "random_from_list"))
              and [g for g in ["Variables", "Listes", "Robot", "Hasard", "Temps", "Calcul"] if g in menu["groups"]] == menu["groups"], str(menu))
        check("incompatible sources not offered on a string field (calc, random_number, elapsed, intent_match)",
              menu and not any(x in menu["items"] for x in ("calc", "random_number", "elapsed", "intent_match")), str(menu))
        lclick(wd, r[0] - 120, r[1] - 40)      # click elsewhere closes it
        check("click elsewhere closes the menu", not js(wd, "return !!document.querySelector('.srcmenu')"))
        # Variable source -> "$p5_s" shorthand
        ok = _src_pick(wd, BTN, "variable")
        SUB = "#inspector .srcfld[data-arg=value]"
        opts = js(wd, "const s=document.querySelector(arguments[0]+' .srcsub select.varsel'); return s?[...s.options].map(o=>o.value).filter(Boolean):null", [SUB])
        types = js(wd, "return Object.fromEntries(window.__editor.varDefs().map(d=>[d.id,d.type]))")
        check("Variable source: chip + variable choices limited to types that fit a string (type_compat)",
              ok and opts and "p5_s" in opts and all("string" in tc.get(types.get(o), []) for o in opts)
              and js(wd, "return !!document.querySelector(arguments[0]+'[data-src=variable] .srcchip')", [SUB]), "%s %s" % (ok, opts))
        _set(wd, SUB + " .srcsub select.varsel", "p5_s")
        time.sleep(0.4)
        a1 = _nargs(wd, nid)
        check("picked variable saved as the $x shorthand", a1 == {"name": "p5_t", "value": "$p5_s"}, str(a1))
        # « Au hasard dans une liste »
        ok = _src_pick(wd, BTN, "random_from_list")
        _set(wd, SUB + " .srcsub select.varsel", "salutations")
        time.sleep(0.4)
        a2 = _nargs(wd, nid)
        chip = js(wd, "const c=document.querySelector(arguments[0]+' .srcchip'); return c?c.textContent:null", [SUB])
        tipn = js(wd, E + ".hideTip&&" + E + ".hideTip(); return " + E + ".nodeTip(arguments[0])", [nid])
        card = js(wd, "const m=window.__editor.dfMap(); const e=document.querySelector('#node-'+m[arguments[0]]+' .nsum'); return e?e.textContent:null", [nid])
        print("TIP", tipn)
        check("random_from_list saved as {get: random_from_list, list: salutations}; chip, card and tooltip in words",
              ok and a2 == {"name": "p5_t", "value": {"get": "random_from_list", "list": "salutations"}} and chip and "au hasard dans salutations" in chip
              and "valeur = au hasard dans salutations" in (tipn or "") and "au hasard dans salutations" in (card or ""), "%s %s %s %s" % (a2, chip, tipn, card))
        # number variable: the menu changes
        _set(wd, "#inspector select.varsel", "p5_n")
        time.sleep(0.4)
        mn = _src_items(wd, BTN)
        print("MENU number", mn)
        check("number field: calc / random_number / elapsed offered; phrase, intent_match and string-only list sources not",
              mn and all(x in mn["items"] for x in ("calc", "random_number", "variable", "system")) and not any(x in mn["items"] for x in ("utterance", "intent_match", "random_from_list")), str(mn))
        ok = _src_pick(wd, BTN, "calc")
        BA = SUB + "[data-src=calc] > .srcsub button.srcbtn[data-src-for=a]"
        ok2 = _src_pick(wd, BA, "variable")
        SA = SUB + "[data-src=calc] > .srcsub > .srcfld[data-arg=a]"
        _set(wd, SA + " select.varsel", "p5_m")
        time.sleep(0.4)
        js(wd, """const b=document.querySelector(arguments[0]); const i=b&&b.closest('.srcwrap').querySelector('input'); if(!i) return false;
          i.value='1'; i.dispatchEvent(new Event('input',{bubbles:true})); i.dispatchEvent(new Event('change',{bubbles:true})); return true""",
           [SUB + "[data-src=calc] > .srcsub button.srcbtn[data-src-for=b]"])
        time.sleep(0.4)
        a3 = _nargs(wd, nid)
        b = ((a3 or {}).get("value") or {}).get("b")
        check("nested calc: A = variable ($p5_m), op + pre-filled, B = constant 1 typed as a number in the JSON",
              ok and ok2 and a3 == {"name": "p5_n", "value": {"get": "calc", "op": "+", "a": "$p5_m", "b": 1}} and type(b) is int, "%s %s %s" % (ok, ok2, a3))
        nb_a = js(wd, "return document.querySelectorAll(arguments[0]+' button.srcbtn').length", [SA])
        check("each side of the calc has its own ▾ (A chip ▾ + B ▾)", nb_a == 1 and js(wd, "return !!document.querySelector(arguments[0]+'[data-src=calc] > .srcsub button.srcbtn[data-src-for=b]')", [SUB]), str(nb_a))
        js(wd, "return window.__editor.freshCheck()")
        time.sleep(1.5)
        iss = js(wd, "return (window.__editor.issues()[arguments[0]]||[]).filter(i=>i.level==='err')", [nid])
        st2, chk = W.http("POST", BASE + "/api/graph/check", doc(wd))
        check("valid calc: no error on the node, server check accepts the document", not iss and st2 == 200 and not (chk or {}).get("errors"), "%s %s" % (iss, str(chk)[:300]))
        # depth limit: 4 nested calcs -> the innermost one's fields have no ▾
        deep = {"get": "calc", "op": "+", "b": 1, "a": {"get": "calc", "op": "+", "b": 1, "a": {"get": "calc", "op": "+", "b": 1, "a": {"get": "calc", "op": "+", "a": 1, "b": 1}}}}
        js(wd, E + ".patchNode(arguments[0], {args: arguments[1]}); " + E + ".focusNode(arguments[0])", [nid, {"name": "p5_n", "value": deep}])
        time.sleep(0.6)
        dz = js(wd, """const all=[...document.querySelectorAll('#inspector .srcfld[data-src=calc]')]; const last=all[all.length-1];
          return [all.length, last?last.querySelectorAll(':scope > .srcsub button.srcbtn').length:-1, all.length?all[0].querySelectorAll(':scope > .srcsub button.srcbtn').length:-1]""")
        check("depth limit: 4 nested sources shown, no ▾ inside the 4th (server MAX_DEPTH)", dz and dz[0] == 4 and dz[1] == 0 and dz[2] >= 1, str(dz))
        # server type error -> badge (a hand-written source the menu would not offer)
        js(wd, E + ".patchNode(arguments[0], {args: arguments[1]}); " + E + ".focusNode(arguments[0])", [nid, {"name": "p5_n", "value": {"get": "list_item", "list": "salutations"}}])
        js(wd, "return window.__editor.freshCheck()")
        time.sleep(1.8)
        iss2 = js(wd, "return (window.__editor.issues()[arguments[0]]||[])", [nid])
        bd = badge(wd, nid)
        bad_chip = js(wd, "return !!document.querySelector(arguments[0]+'[data-src=list_item] .srcchip.bad')", [SUB])
        print("TYPE ERR", iss2, bd)
        check("server type error (source list_item gives a string value) lands on the node as an error badge; chip marked",
              any(i["level"] == "err" and "source list_item gives a string value" in i["message"] for i in iss2) and bd and "err" in bd[0] and bad_chip, "%s %s %s" % (iss2, bd, bad_chip))
        # « Valeur fixe » restores the plain control
        ok = _src_pick(wd, BTN, "constant")
        a4 = _nargs(wd, nid)
        plain = js(wd, "return [!!document.querySelector(arguments[0]), !!document.querySelector('#inspector .srcwrap input[type=number]')]", [SUB])
        check("« Valeur fixe » -> plain number control back, value = the type default", ok and a4 == {"name": "p5_n", "value": 0} and plain == [False, True], "%s %s" % (a4, plain))
        # final document: calc(p5_m + 1) -> save + reload
        js(wd, E + ".patchNode(arguments[0], {args: arguments[1]}); " + E + ".focusNode(arguments[0])", [nid, {"name": "p5_n", "value": {"get": "calc", "op": "+", "a": "$p5_m", "b": 1}}])
        time.sleep(0.4)
        saved = _save_and_wait(wd)
        yaml_txt = open(ROOT + "/graph.yaml", encoding="utf-8").read() if os.path.exists(ROOT + "/graph.yaml") else ""
        check("saved; graph.yaml carries the source", saved and "get: calc" in yaml_txt and "$p5_m" in yaml_txt, str(saved))
        W.open_editor(wd, "#quiet")
        time.sleep(1.5)
        a5 = _nargs(wd, nid)
        js(wd, E + ".activateTab('node'); " + E + ".focusNode(arguments[0])", [nid])
        time.sleep(0.6)
        back = js(wd, """const q=(s)=>document.querySelector(s); const bb=q('#inspector .srcfld[data-arg=value][data-src=calc] > .srcsub button.srcbtn[data-src-for=b]'), b=bb&&bb.closest('.srcwrap').querySelector('input');
          return [!!q('#inspector .srcfld[data-arg=value][data-src=calc] > .srcsub > .srcfld[data-arg=a][data-src=variable]'), b?b.value:null]""")
        check("after reload: same args, calc chip with A = Variable chip and B = 1", a5 == {"name": "p5_n", "value": {"get": "calc", "op": "+", "a": "$p5_m", "b": 1}} and back == [True, "1"], "%s %s" % (a5, back))
        # Tester: the simulator computes the source (p5_m 4 + 1 = 5)
        js(wd, E + ".activateTab('tester')")
        time.sleep(0.4)
        js(wd, "const E=window.__editor; E.sim.steps=[{event:'visage'}]; return E.simRun(false)")
        time.sleep(3)
        simv = js(wd, "const t=window.__editor.sim.trace||[]; return t.map(e=>((e.vars||{}).names||{}).p5_n)")
        check("Tester simulate: p5_n = p5_m + 1 = 5 after the veille entry chain", simv and simv[0] == 5, str(simv))
        # screenshot: inspector with the calc source and the B menu open
        js(wd, E + ".activateTab('node'); " + E + ".focusNode(arguments[0])", [nid])
        time.sleep(0.6)
        _src_items(wd, "#inspector .srcfld[data-arg=value][data-src=calc] > .srcsub button.srcbtn[data-src-for=b]")
        js(wd, "const e=document.querySelector('#inspector .srcfld[data-arg=value]'); if(e) e.scrollIntoView({block:'start'})")
        time.sleep(0.4)
        wd.shot("editor18-props.png")
        check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))
    finally:
        W.http("POST", BASE + "/api/graph/reset", {})
        time.sleep(3)
        for f in set(glob.glob(ROOT + "/graph.*")) - pre:
            try:
                os.remove(f)
            except OSError:
                pass
        for f in set(glob.glob(ROOT + "/state/*")) - st_files_pre:
            try:
                os.remove(f)
            except OSError:
                pass
        if not state_pre and os.path.isdir(ROOT + "/state"):
            try:
                os.rmdir(ROOT + "/state")
            except OSError:
                pass
        print("LEFT OVER", sorted(set(glob.glob(ROOT + "/graph.*")) - pre), "state:", os.path.exists(ROOT + "/state"))


# Scenario registry read by tests/web/run.py (order = order of the former single file).
SCENARIOS = {
    "props": sc_props,
}
