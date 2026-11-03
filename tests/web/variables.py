"""Nanterino editor web scenarios: the Variables panel (v1 and v2 manager).

Purpose : variables area of the editor web suite; scenarios vars, vars2.
Boundary: drives the live editor through tests/web/driver.py (WebDriver, check()); never imports nanterino.server.
Invariant: verbatim slice (M7) of the former scripts/editor6_wd.py; a scenario is `sc_<name>(wd)` and is listed in
          SCENARIOS at the end of this file, which tests/web/run.py reads.
Test    : .venv/bin/python -m tests.web.run vars   (or `area:variables`, or `all`)
"""
import glob, json, os, sys, time

from tests.web.driver import *  # noqa: F401,F403  (shared helpers, check(), W, BASE, ROOT)


def sc_vars(wd):
    """Vars L2: Variables panel: create a number variable and a list, use the variable in a var_compare condition through
    the inspector, save, reload (persisted), delete-while-used refused (client) and 400 shown (server). Rolled back."""
    pre = set(glob.glob(ROOT + "/graph.*"))
    try:
        open_editor(wd)
        E = "window.__editor"
        js(wd, "document.querySelector('#btnVars').click()")
        time.sleep(2.5)
        rows = js(wd, "return [...document.querySelectorAll('#vars tr.vrow')].map(r=>[r.dataset.var, !!r.querySelector('.lock')])")
        check("Noms: system variables listed with a lock", ["etat", True] in rows and ["tours", True] in rows and ["max_tours", True] in rows, str(rows))
        live = js(wd, "const e=document.querySelector('#vars [data-live=\"names:etat\"]'); return e?e.textContent:null")
        check("live column filled from /api/graph/vars", live in ("veille", "eteint", "accueil", "ecoute", "reponse", "relance", "cloture"), str(live))
        # new number variable
        _set(wd, "#vars input[data-new=var]", "score_test")
        _set(wd, "#vars select[data-new=vartype]", "number")
        _click(wd, "#vars button[data-new=varadd]")
        time.sleep(0.4)
        v = js(wd, "return window.__editor.meta().variables.names.score_test||null")
        check("number variable created", v == {"type": "number", "value": 0}, str(v))
        _set(wd, "#vars .vedit input[type=number]", "3")
        time.sleep(0.3)
        v = js(wd, "return window.__editor.meta().variables.names.score_test||null")
        check("initial value edited (typed number)", v and v.get("value") == 3, str(v))
        bad = js(wd, """const i=document.querySelector('#vars input[data-new=var]'); i.value='Mauvais Nom'; document.querySelector('#vars button[data-new=varadd]').click();
          return Object.keys(window.__editor.meta().variables.names)""")
        check("invalid name refused", "Mauvais Nom" not in bad, str(bad))
        # lists tab
        _click(wd, "#vars button[data-vtab=lists]")
        time.sleep(0.3)
        _set(wd, "#vars input[data-new=list]", "mots_test")
        _set(wd, "#vars select[data-new=listtype]", "string")
        _click(wd, "#vars button[data-new=listadd]")
        time.sleep(0.3)
        for w in ("bonjour", "salut"):
            _set(wd, "#vars [data-new=item]", w)
            _click(wd, "#vars button[data-new=itemadd]")
            time.sleep(0.3)
        _click(wd, "#vars .vitems li:first-child button[title=Descendre]")
        time.sleep(0.3)
        lst = js(wd, "return window.__editor.meta().variables.lists.mots_test||null")
        check("list created, items added and reordered", lst == {"type": "string", "items": ["salut", "bonjour"]}, str(lst))
        _click(wd, "#vars .vlitem[data-list=mots_refus]")
        time.sleep(0.3)
        ro = js(wd, "const r=document.querySelector('#vars .vlright'); return [r.textContent.includes('refusal_words'), !!r.querySelector('[data-new=item]'), !!document.querySelector('#vars .vlitem[data-list=mots_refus] .lock')]")
        check("source-bound list read-only with its source note", ro == [True, False, True], str(ro))
        # use the variable in a condition through the inspector
        d = doc(wd)
        cond = next(n for n in d["nodes"] if n["kind"] == "condition" and n["params"].get("guard") == "not_busy")
        js(wd, "window.__editor.activateTab('node'); window.__editor.focusNode(arguments[0])", [cond["id"]])
        time.sleep(0.5)
        js(wd, "const dd=[...document.querySelectorAll('#inspector .dd')].find(x=>x.closest('.fld').textContent.startsWith('Condition')); dd.querySelector('.ddb').click(); [...dd.querySelectorAll('.ddi')].find(i=>i.title==='Comparer une variable').click()")
        time.sleep(0.4)
        opts = js(wd, "const s=document.querySelector('#inspector select.varsel'); return s?[...s.options].map(o=>o.value):null")
        check("inspector: variable dropdown lists etat and score_test", opts and "etat" in opts and "score_test" in opts, str(opts))
        _set(wd, "#inspector select.varsel", "score_test")
        time.sleep(0.4)
        ops = js(wd, "const s=[...document.querySelectorAll('#inspector select')].find(s=>[...s.options].some(o=>o.value==='>=')); return s?[...s.options].map(o=>o.value):null")
        check("op select offers order operators for a number", ops and ">" in ops and "<=" in ops, str(ops))
        js(wd, "const s=[...document.querySelectorAll('#inspector select')].find(s=>[...s.options].some(o=>o.value==='>=')); s.value='>'; s.dispatchEvent(new Event('change',{bubbles:true}))")
        time.sleep(0.3)
        _set(wd, "#inspector input[type=number]", "2")
        time.sleep(0.3)
        p = next(n for n in doc(wd)["nodes"] if n["id"] == cond["id"])["params"]
        check("condition = var_compare(score_test > 2)", p.get("guard") == "var_compare" and p.get("args") == {"name": "score_test", "op": ">", "value": 2}, str(p))
        summ = js(wd, "const m=window.__editor.dfMap(); return document.querySelector('#node-'+m[arguments[0]]+' .nsum').textContent", [cond["id"]])
        check("node card reads 'score_test > 2'", summ == "score_test > 2", str(summ))
        # save through the toolbar, reload, all persisted
        js(wd, "document.querySelector('#btnSave').click()")
        time.sleep(3)
        yaml_txt = open(ROOT + "/graph.yaml", encoding="utf-8").read() if os.path.exists(ROOT + "/graph.yaml") else ""
        check("saved: graph.yaml carries the variable and the list", "score_test" in yaml_txt and "mots_test" in yaml_txt)
        W.open_editor(wd, "#quiet")
        time.sleep(1.2)
        back = js(wd, "const v=window.__editor.meta().variables; return [v.names.score_test||null, v.lists.mots_test||null]")
        check("after reload: variable and list persisted", back[0] and back[0].get("value") == 3 and back[0].get("type") == "number" and back[1] and back[1].get("items") == ["salut", "bonjour"], str(back))
        cn = next((n for n in doc(wd)["nodes"] if n["kind"] == "condition" and (n["params"].get("args") or {}).get("name") == "score_test"), None)
        check("after reload: the condition still compares score_test > 2", cn is not None and cn["params"]["args"].get("op") == ">" and str(cn["params"]["args"].get("value")) in ("2", "2.0"), str(cn and cn["params"]))
        if cn:
            js(wd, "window.__editor.focusNode(arguments[0])", [cn["id"]])
            time.sleep(0.6)
            wd.shot("editor8-vars.png")
        # delete while used: refused client-side with the using node listed
        js(wd, "window.__editor.activateTab('vars')")
        time.sleep(0.4)
        _click(wd, "#vars button[data-vtab=names]")
        _click(wd, "#vars tr.vrow[data-var=score_test]")
        time.sleep(0.3)
        wd.shot("editor8-varpanel.png")
        js(wd, "[...document.querySelectorAll('#vars .vedit button.danger')].find(b=>b.textContent.includes('Supprimer')).click()")
        time.sleep(0.4)
        still = js(wd, "return [!!window.__editor.meta().variables.names.score_test, (document.querySelector('#vars .vuses')||{}).textContent||'']")
        check("delete while used refused, using node listed", still[0] and cn is not None and cn["id"] in still[1], str(still))
        # server 400 when a used variable is removed anyway (located on the node), nothing written
        mt = os.path.getmtime(ROOT + "/graph.yaml")
        st = js(wd, "const E=window.__editor; const d=E.serialize(); delete d.variables.names.score_test; return E.postDoc(d).then(r=>[r.status, (r.json.errors||[]).map(e=>[e.node, e.message])])")
        msgs = js(wd, "return document.querySelector('#msgs').textContent")
        # contract: the error is located on the trigger of the chain that uses the variable (or on the node itself)
        chain = js(wd, "const E=window.__editor; const ids=new Set([arguments[0]]); E.computeChains(E.serialize()).keys.forEach(v=>{ if(v.includes(arguments[0])) v.forEach(x=>ids.add(x)); }); return [...ids]", [(cn or {}).get("id")])
        enode = st[1][0][0] if st[1] else None
        marked = js(wd, "const m=window.__editor.dfMap(); const e=document.getElementById('node-'+m[arguments[0]]); return !!(e && e.classList.contains('err'))", [enode]) if enode else False
        check("server refuses (400), error on the using chain, shown in the list and on the node", st[0] == 400 and enode in chain and marked and "score_test" in msgs and os.path.getmtime(ROOT + "/graph.yaml") == mt, "%s chain=%s marked=%s" % (str(st)[:200], chain, marked))
        check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))
    finally:
        W.http("POST", BASE + "/api/graph/reset", {})
        for f in set(glob.glob(ROOT + "/graph.*")) - pre:
            try:
                os.remove(f)
            except OSError:
                pass
        print("LEFT OVER", sorted(set(glob.glob(ROOT + "/graph.*")) - pre))


def _fake_vars(wd, timer_name, ignored):
    """Wrap fetch: GET /api/graph/vars answers the real body with a ticking chrono and fake store.ignored entries."""
    js(wd, """if(!window.__ofetch) window.__ofetch=window.fetch; const of=window.__ofetch; window.__tick=75;
      window.fetch=(u,o)=>{ if(String(u).endsWith('/api/graph/vars') && !(o&&o.method==='POST')) return of(u,o).then(r=>r.json()).then(j=>{
        j.names[arguments[0]]=window.__tick++; j.store.ignored=arguments[1];
        return new Response(JSON.stringify(j),{status:200,headers:{'Content-Type':'application/json'}}); }); return of(u,o); }""", [timer_name, ignored])


def sc_vars2(wd):
    """L12: Variables v2 manager + typed inspector. One variable of each vocabulary type (default value, typed control),
    bounds (clamp, min <= max), scope / persist, dict (key -> value) and shuffle / history lists, save + reload (all
    kept), Réinitialiser (POST /api/graph/vars/reset), chrono ticking and persisted-value conflict (fetch stub),
    Tester grouped by scope with dict / shuffle visible, time conditions with typed fields (hh:mm, week days, elapsed
    seconds), operators filtered by op_sets, out_of_bounds warning badge from /api/graph/check. Screenshots
    tests/results/editor16-*.png. Saves once; rolled back at the end (reset, own graph.* files and state/ removed)."""
    pre = set(glob.glob(ROOT + "/graph.*"))
    state_pre = os.path.exists(ROOT + "/state")
    st_files_pre = set(glob.glob(ROOT + "/state/*")) if state_pre else set()
    try:
        st, V = W.http("GET", BASE + "/api/graph/vocab")
        types = V["var_types"]
        open_editor(wd)
        js(wd, "document.querySelector('#btnVars').click()")
        time.sleep(2.0)
        heads = js(wd, "return [...document.querySelectorAll('#vars .vtable thead th')].map(t=>t.textContent)")
        check("Noms table has a Portée column", heads == ["Nom", "Type", "Portée", "Initiale", "Live"], str(heads))
        # ---- one variable of each type: vocabulary default + typed control
        bad = []
        for t in types:
            vid = "v2_" + t["id"]
            _set(wd, "#vars input[data-new=var]", vid)
            _set(wd, "#vars select[data-new=vartype]", t["id"])
            _click(wd, "#vars button[data-new=varadd]")
            time.sleep(0.25)
            v = _vmeta(wd, vid)
            if t["id"] == "choice":
                want = "a"
            elif t["control"] == "select" and not t.get("nullable"):
                cs = [c["id"] for c in t.get("choices", [])]
                want = t["default"] if t["default"] in cs or not cs else cs[0]
            else:
                want = t.get("default")
            ctl = js(wd, "const e=document.querySelector('#vars .vedit [data-opt=value]'); return e?e.dataset.ctl:null")
            if not v or v.get("type") != t["id"] or v.get("value") != want or ctl != t["control"]:
                bad.append((t["id"], v, want, ctl))
        check("one variable of each of the %d types: vocabulary default + its control" % len(types), not bad and len(types) >= 19, str(bad))
        # ---- typed controls write typed values
        _vsel(wd, "v2_color")
        _set(wd, "#vars .vedit input[type=color]", "#ff8800")
        _vsel(wd, "v2_vector3")
        for ax, n in (("x", 1), ("y", 2.5), ("z", -3)):
            _set(wd, "#vars .vedit input[data-axis=%s]" % ax, str(n))
        _vsel(wd, "v2_datetime")
        _click(wd, "#vars .vedit [data-act=now]")
        _vsel(wd, "v2_percent")
        pr = js(wd, "const r=document.querySelector('#vars .vedit [data-opt=value] input[type=range]'); return r?[r.min,r.max]:null")
        _vsel(wd, "v2_expression")
        ex = js(wd, "const s=document.querySelector('#vars .vedit select[data-opt=value]'); return s?[...s.options].map(o=>o.value):null")
        got = [(_vmeta(wd, k) or {}).get("value") for k in ("v2_color", "v2_vector3", "v2_datetime")]
        import re as _re
        check("color / vector3 / datetime(Maintenant) / percent slider / expression choices typed",
              got[0] == "#ff8800" and got[1] == [1, 2.5, -3] and bool(_re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d$", str(got[2])))
              and pr == ["0", "100"] and ex and "content" in ex and "" not in ex, "%s pr=%s ex=%s" % (got, pr, ex))
        # ---- bounds on an integer: min / max / step, clamp of the initial value, min > max refused
        _vsel(wd, "v2_integer")
        for k, n in (("min", "0"), ("max", "10"), ("step", "1")):
            _set(wd, "#vars .vedit input[data-opt=%s]" % k, n)
            time.sleep(0.2)
        _vsel(wd, "v2_integer")
        _set(wd, "#vars .vedit [data-opt=value] input[type=number]", "7")
        time.sleep(0.2)
        _vsel(wd, "v2_integer")
        _set(wd, "#vars .vedit input[data-opt=max]", "5")
        time.sleep(0.2)
        _vsel(wd, "v2_integer")
        _set(wd, "#vars .vedit input[data-opt=min]", "8")
        time.sleep(0.2)
        vi = _vmeta(wd, "v2_integer")
        rng = js(wd, "const r=document.querySelector('#vars .vedit [data-opt=value] input[type=range]'); return r?[r.min,r.max,r.step]:null")
        check("integer bounds: min 0 / max 5 / step 1, value clamped 7 -> 5, min > max refused, slider follows",
              vi == {"type": "integer", "value": 5, "min": 0, "max": 5, "step": 1} and rng == ["0", "5", "1"], "%s %s" % (vi, rng))
        # ---- scope / persist
        _vsel(wd, "v2_number")
        _set(wd, "#vars .vedit input[data-opt=persist]", True)
        time.sleep(0.2)
        _vsel(wd, "v2_bool")
        _set(wd, "#vars .vedit input[data-opt=persist]", True)
        time.sleep(0.2)
        _vsel(wd, "v2_bool")
        _set(wd, "#vars .vedit select[data-opt=scope]", "conversation")
        time.sleep(0.2)
        _vsel(wd, "v2_bool")
        dis = js(wd, "const c=document.querySelector('#vars .vedit input[data-opt=persist]'); return c?[c.disabled,c.checked]:null")
        sc_cell = js(wd, "const r=document.querySelector('#vars tr.vrow[data-var=v2_bool] td.vscope'); return r?[r.dataset.scope,r.textContent]:null")
        pbadge = js(wd, "return !!document.querySelector('#vars tr.vrow[data-var=v2_number] .vbadge.persist')")
        check("persist on a global (badge P); conversation scope drops persist and disables the box",
              (_vmeta(wd, "v2_number") or {}).get("persist") is True and _vmeta(wd, "v2_bool") == {"type": "bool", "value": False, "scope": "conversation"}
              and dis == [True, False] and sc_cell and sc_cell[0] == "conversation" and pbadge, "%s %s %s %s" % (_vmeta(wd, "v2_bool"), dis, sc_cell, pbadge))
        # ---- lists: dict with a key -> value sub-table, shuffle and history lists
        _click(wd, "#vars button[data-vtab=lists]")
        time.sleep(0.3)
        _set(wd, "#vars input[data-new=list]", "v2_dict")
        _set(wd, "#vars select[data-new=listkind]", "dict")
        _set(wd, "#vars select[data-new=listtype]", "string")
        _click(wd, "#vars button[data-new=listadd]")
        time.sleep(0.3)
        for k, val in (("paris", "France"), ("rome", "Italie")):
            _set(wd, "#vars input[data-new=dkey]", k)
            _set(wd, "#vars [data-new=dval]", val)
            _click(wd, "#vars button[data-new=dadd]")
            time.sleep(0.3)
        _set(wd, "#vars input[data-dkey=rome]", "roma")
        time.sleep(0.3)
        rows = js(wd, "return [...document.querySelectorAll('#vars .vdict tr.drow')].map(r=>r.dataset.dictKey)")
        dct = _vmeta(wd, "v2_dict", "lists")
        check("dict created: key -> value sub-table, add + rename key", dct == {"type": "string", "kind": "dict", "items": {"paris": "France", "roma": "Italie"}} and rows == ["paris", "roma"], "%s %s" % (dct, rows))
        _set(wd, "#vars input[data-new=list]", "v2_sac")
        _set(wd, "#vars select[data-new=listkind]", "list")
        _set(wd, "#vars select[data-new=listtype]", "phrase")
        _click(wd, "#vars button[data-new=listadd]")
        time.sleep(0.3)
        for w in ("Bonjour !", "Salut !", "Coucou !"):
            _set(wd, "#vars [data-new=item]", w)
            _click(wd, "#vars button[data-new=itemadd]")
            time.sleep(0.25)
        _set(wd, "#vars .vlright select[data-opt=mode]", "shuffle")
        time.sleep(0.25)
        _set(wd, "#vars .vlright input[data-opt=max]", "5")
        time.sleep(0.25)
        _set(wd, "#vars input[data-new=list]", "v2_hist")
        _set(wd, "#vars select[data-new=listtype]", "string")
        _click(wd, "#vars button[data-new=listadd]")
        time.sleep(0.3)
        _set(wd, "#vars .vlright select[data-opt=mode]", "history")
        time.sleep(0.25)
        _set(wd, "#vars .vlright select[data-opt=scope]", "conversation")
        time.sleep(0.25)
        sac, hist = _vmeta(wd, "v2_sac", "lists"), _vmeta(wd, "v2_hist", "lists")
        check("shuffle list (phrase items, max 5) and history list (max auto 10, conversation scope)",
              sac == {"type": "phrase", "items": ["Bonjour !", "Salut !", "Coucou !"], "mode": "shuffle", "max": 5}
              and hist == {"type": "string", "items": [], "mode": "history", "max": 10, "scope": "conversation"}, "%s %s" % (sac, hist))
        snap_before = js(wd, "return JSON.parse(JSON.stringify(window.__editor.meta().variables))")
        # ---- save + reload
        saved = _save_and_wait(wd)
        yaml_txt = open(ROOT + "/graph.yaml", encoding="utf-8").read() if os.path.exists(ROOT + "/graph.yaml") else ""
        check("saved (toast) and graph.yaml carries the v2 variables / lists", saved and all(x in yaml_txt for x in ("v2_vector3", "v2_dict", "v2_sac", "v2_timer")), str(saved))
        time.sleep(1.5)
        st2, live = W.http("GET", BASE + "/api/graph/vars")
        store = (live or {}).get("store", {}) if isinstance(live, dict) else {}
        check("robot: v2_number persisted, v2_bool conversation scope, v2_timer stopped (null), dict live",
              "v2_number" in store.get("persist", {}).get("names", []) and store.get("scopes", {}).get("names", {}).get("v2_bool") == "conversation"
              and live["names"].get("v2_timer", 1) is None and live["lists"].get("v2_dict") == {"paris": "France", "roma": "Italie"}, str(store)[:400])
        W.open_editor(wd, "#quiet")
        time.sleep(1.2)
        back = js(wd, "return JSON.parse(JSON.stringify(window.__editor.meta().variables))")
        diff = []
        for part in ("names", "lists"):
            for k, v in snap_before[part].items():
                if not k.startswith("v2_"):
                    continue
                b = back[part].get(k)
                if k == "v2_datetime" and b and str(b.get("value", "")).startswith(str(v["value"])):
                    continue
                if b != v:
                    diff.append((k, v, b))
        check("after reload: every v2 variable / list kept (type, value, bounds, scope, persist, kind, mode, max)", not diff, str(diff)[:600])
        # ---- Réinitialiser (POST /api/graph/vars/reset) + 404 for a system variable
        _vsel(wd, "v2_number")
        js(wd, "document.querySelectorAll('#toasts .toast').forEach(t=>t.remove())")
        _click(wd, "#vars .vedit button[data-act=reset]")
        time.sleep(1.2)
        toasts = js(wd, "return [...document.querySelectorAll('#toasts .toast')].map(e=>[e.className,e.textContent])")
        r404 = js(wd, "return window.__editor.resetVar('etat')")
        st3, rr = W.http("POST", BASE + "/api/graph/vars/reset", {"name": "v2_sac"})
        check("Réinitialiser: 200 + ok toast; system variable refused (404 path); route ok for a list",
              any("ok" in c and "remise" in t for c, t in toasts) and r404 is False and st3 == 200, "%s %s %s" % (toasts, r404, st3))
        # ---- chrono ticking + persisted-value conflict (fetch stub on GET /api/graph/vars)
        _fake_vars(wd, "v2_timer", [{"part": "names", "name": "v2_number", "reason": "type changé"}])
        _vsel(wd, "v2_timer")
        time.sleep(2.3)
        t1 = js(wd, "const e=document.querySelector('#vars td.vlive[data-live=\"names:v2_timer\"]'); return e?e.textContent:null")
        time.sleep(1.2)
        t2 = js(wd, "const e=document.querySelector('#vars td.vlive[data-live=\"names:v2_timer\"]'); return e?e.textContent:null")
        check("live chrono ticks as m:ss", bool(t1 and t2 and _re.match(r"^\d+:\d\d$", t1)) and t1 != t2 and t1.startswith("1:"), "%s -> %s" % (t1, t2))
        conf = js(wd, """return [!!document.querySelector('#vars .vconf[data-conf="names:v2_number"]'), !!document.querySelector('#vars tr.vrow.conf[data-var=v2_number]'),
          window.__editor.globalIssues().some(i=>i.level==='warn' && i.message.includes('v2_number'))]""")
        check("persisted-value conflict: panel line, row mark and a global warning", conf == [True, True, True], str(conf))
        js(wd, "window.fetch=window.__ofetch; window.__editor.refreshVarStore()")
        time.sleep(0.6)
        _vsel(wd, "v2_integer")
        js(wd, "document.querySelectorAll('#toasts .toast').forEach(t=>t.remove()); const e=document.querySelector('#vars .vedit'); if(e) e.scrollIntoView({block:'start'})")
        time.sleep(0.3)
        wd.shot("editor16-vars.png")
        # ---- Tester: grouped by scope, conversation marked, dict and shuffle list visible
        js(wd, "window.__editor.activateTab('tester')")
        time.sleep(0.5)
        js(wd, "const E=window.__editor; E.sim.steps=[{event:'visage'},{wait_s:3}]; return E.simRun(false)")
        time.sleep(3)
        tv = js(wd, """const q=(s)=>document.querySelector('#simStatus '+s); const d=q('.sv[data-svar=v2_dict]'), s=q('.sv[data-svar=v2_sac]');
          return [!!q('.svgroup[data-group=system] .sv[data-svar=etat]'), !!q('.svgroup[data-group=conversation] .sv.conv[data-svar=v2_bool]'),
            !!q('.svgroup[data-group=conversation] .sv.conv[data-svar=v2_hist]'), !!q('.svgroup[data-group=global] .sv[data-svar=v2_number]'),
            d?[d.dataset.mode, d.title]:null, s?s.dataset.mode:null, (q('.svgroup[data-group=conversation] .svglab')||{}).textContent||'']""")
        print("TESTER", tv)
        check("Tester: variables by scope, conversation marked ↺, dict and shuffle list shown",
              tv[0] and tv[1] and tv[2] and tv[3] and tv[4] and tv[4][0] == "dict" and "paris → France" in tv[4][1] and tv[5] == "shuffle" and "nouvelle conversation" in tv[6], str(tv))
        wd.shot("editor16-tester.png")
        # ---- inspector: time conditions with typed fields
        d = doc(wd)
        cond = next(n for n in d["nodes"] if n["kind"] == "condition" and n["params"].get("guard") == "not_busy")
        js(wd, "window.__editor.activateTab('node'); window.__editor.focusNode(arguments[0])", [cond["id"]])
        time.sleep(0.5)
        ok1 = _pick_dd(wd, "Condition", "Entre deux heures")
        time.sleep(0.4)
        nt = js(wd, "return document.querySelectorAll('#inspector input[type=time]').length")
        _set(wd, "#inspector input[data-arg=start]", "08:30")
        time.sleep(0.3)
        _set(wd, "#inspector input[data-arg=end]", "18:00")
        time.sleep(0.3)
        p1 = next(n for n in doc(wd)["nodes"] if n["id"] == cond["id"])["params"]
        check("time_between: two hh:mm fields -> args start / end", ok1 and nt == 2 and p1.get("args") == {"start": "08:30", "end": "18:00"}, "%s %s %s" % (ok1, nt, p1))
        ok2 = _pick_dd(wd, "Condition", "Jour de la semaine")
        time.sleep(0.4)
        nb = js(wd, "return document.querySelectorAll('#inspector .multichk input[type=checkbox]').length")
        _set(wd, "#inspector .multichk input[data-opt=mer]", True)
        time.sleep(0.3)
        _set(wd, "#inspector .multichk input[data-opt=lun]", True)
        time.sleep(0.3)
        p2 = next(n for n in doc(wd)["nodes"] if n["id"] == cond["id"])["params"]
        check("weekday_in: 7 day boxes -> days in week order", ok2 and nb == 7 and p2.get("args") == {"days": ["lun", "mer"]}, "%s %s %s" % (ok2, nb, p2))
        ok3 = _pick_dd(wd, "Condition", "Temps écoulé depuis")
        time.sleep(0.4)
        opts = js(wd, "const s=document.querySelector('#inspector select.varsel'); return s?[...s.options].map(o=>o.value):null")
        _set(wd, "#inspector select.varsel", "v2_timer")
        time.sleep(0.4)
        ops = js(wd, "const s=[...document.querySelectorAll('#inspector select')].find(s=>[...s.options].some(o=>o.value==='!=')); return s?[...s.options].map(o=>o.value):null")
        smin = js(wd, "const i=document.querySelector('#inspector input[data-arg=seconds]'); return i?i.min:null")
        _set(wd, "#inspector input[data-arg=seconds]", "30")
        time.sleep(0.3)
        p3 = next(n for n in doc(wd)["nodes"] if n["id"] == cond["id"])["params"]
        check("elapsed_since: only datetime / chrono variables, order ops, seconds field min 0",
              ok3 and opts and "v2_timer" in opts and "v2_datetime" in opts and "v2_number" not in opts and ops and "<" in ops and smin == "0"
              and (p3.get("args") or {}).get("name") == "v2_timer" and (p3.get("args") or {}).get("seconds") == 30, "%s %s %s %s" % (opts, ops, smin, p3))
        ok4 = _pick_dd(wd, "Condition", "Comparer une variable")
        time.sleep(0.4)
        _set(wd, "#inspector select.varsel", "v2_color")
        time.sleep(0.4)
        ops2 = js(wd, "const s=[...document.querySelectorAll('#inspector select')].find(s=>[...s.options].some(o=>o.value==='!=')); return s?[...s.options].map(o=>o.value):null")
        col = js(wd, "return !!document.querySelector('#inspector input[type=color]')")
        check("var_compare on a colour: ops filtered to = / != (op_sets), colour picker as value", ok4 and ops2 == ["=", "!="] and col, "%s %s" % (ops2, col))
        wd.shot("editor16-inspector.png")
        # ---- out_of_bounds warning badge (server /api/graph/check) on set_var(v2_integer, 50), max 5
        act = next(n for n in d["nodes"] if n["kind"] == "action" and n["params"].get("action") not in ("set_var", "end", None))
        js(wd, "window.__editor.focusNode(arguments[0])", [act["id"]])
        time.sleep(0.5)
        ok5 = _pick_dd(wd, "Action", "Changer une variable")
        time.sleep(0.4)
        _set(wd, "#inspector select.varsel", "v2_integer")
        time.sleep(0.4)
        _set(wd, "#inspector input[type=number]", "50")
        time.sleep(0.4)
        js(wd, "return window.__editor.freshCheck()")
        time.sleep(1.0)
        ws = js(wd, "return (window.__editor.fanInfo().warnings||[]).filter(w=>w.kind==='out_of_bounds')")
        bd = badge(wd, act["id"])
        iss = js(wd, "return (window.__editor.issues()[arguments[0]]||[])", [act["id"]])
        print("OOB", ws, bd, iss)
        check("out_of_bounds: server warning lands on the set_var node as a warning badge",
              ok5 and ws and any(w.get("at") == act["id"] or w.get("node") == act["id"] or act["id"] in (w.get("nodes") or []) for w in ws)
              and bd and "warn" in bd[0] and any(i["level"] == "warn" and i["message"] == ws[0]["message"] for i in iss), "%s %s %s" % (ws, bd, iss))
        # ---- client type mismatch: 2.5 into an integer variable = error badge before any save
        _set(wd, "#inspector input[type=number]", "2.5")
        time.sleep(0.6)
        iss2 = js(wd, "return (window.__editor.issues()[arguments[0]]||[])", [act["id"]])
        check("type mismatch: 2.5 for an integer variable is a client error on the node", any(i["level"] == "err" and "entier" in i["message"] for i in iss2), str(iss2))
        check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))
    finally:
        W.http("POST", BASE + "/api/graph/reset", {})
        time.sleep(3)   # the variable store writes at most every 2 s: let a pending write land before cleaning
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
    "vars": sc_vars,
    "vars2": sc_vars2,
}
