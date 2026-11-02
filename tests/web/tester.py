"""Nanterino editor web scenarios: the Tester tab: simulate a chain, variables seen by the simulator.

Purpose : tester area of the editor web suite; scenarios tester, testervars.
Boundary: drives the live editor through tests/web/driver.py (WebDriver, check()); never imports nanterino.server.
Invariant: verbatim slice (M7) of the former scripts/editor6_wd.py; a scenario is `sc_<name>(wd)` and is listed in
          SCENARIOS at the end of this file, which tests/web/run.py reads.
Test    : .venv/bin/python -m tests.web.run tester   (or `area:tester`, or `all`)
"""
import glob, json, os, sys, time

from tests.web.driver import *  # noqa: F401,F403  (shared helpers, check(), W, BASE, ROOT)


def lit_ids(wd, cls):
    return set(js(wd, "const m=window.__editor.dfMap(); const inv={}; Object.keys(m).forEach(k=>inv[m[k]]=k); return [...document.querySelectorAll('.drawflow-node.%s')].map(e=>inv[e.id.replace('node-','')])" % cls))


def sc_tester(wd):
    open_editor(wd)
    wd.js("window.__editor.activateTab('tester')")
    time.sleep(0.5)
    wd.js("const E=window.__editor; E.sim.steps=[{event:'visage'},{wait_s:4},{say:'au revoir'}]; return E.simRun(false)")
    time.sleep(4)
    tr = js(wd, "return window.__editor.sim.trace.map(e=>e.chain+':'+e.from+'>'+e.to)")
    print("TRACE", tr)
    d = doc(wd)
    kinds = {n["id"]: n for n in d["nodes"]}
    ch = js(wd, "const E=window.__editor; return [...E.computeChains(E.serialize()).keys.entries()]")
    keys = dict(ch)
    last = js(wd, "return window.__editor.sim.trace.length-1")
    lastchain = js(wd, "return window.__editor.sim.trace[arguments[0]].chain", [last])
    lastto = js(wd, "return window.__editor.sim.trace[arguments[0]].to", [last])
    expected = set(keys[lastchain])
    now = lit_ids(wd, "lit-now")
    check("lit-now == nodes of the last fired chain", now == expected, "%s vs %s" % (sorted(now), sorted(expected)))
    tgt = [i for i in expected if kinds[i]["kind"] == "action" and kinds[i]["params"].get("action") == "set_var" and (kinds[i]["params"].get("args") or {}).get("value") == lastto]
    check("its 'Changer d'état' action is lit", len(tgt) == 1 and tgt[0] in now, "to=%s" % lastto)
    simf = js(wd, "return [...document.querySelectorAll('.frame.auto.sim')].map(e=>e.dataset.fid)")
    check("simulated state = its column frame", simf == ["auto-" + lastto], str(simf))
    past = set()
    for e in js(wd, "return window.__editor.sim.trace.slice(0,-1).map(e=>e.chain)"):
        past |= set(keys.get(e, []))
    pl = lit_ids(wd, "lit-past")
    check("lit-past == union of earlier chains minus now", pl == (past - now), "%d vs %d" % (len(pl), len(past - now)))
    first = js(wd, "const E=window.__editor; return (E.computeChains(E.serialize()).keys.get(arguments[0])||[])[0]||null", [lastchain])
    check("the chain starts on its trigger", first is not None and kinds[first]["kind"] == "trigger", str(first))
    st = js(wd, """const c=document.querySelector('#drawflow'); return [c.classList.contains('simdim'), document.querySelectorAll('svg.connection.wlit-now').length,
      +getComputedStyle(document.querySelector('.drawflow-node:not(.lit-now):not(.lit-past)')).opacity]""")
    check("sim: active wires glow, the rest dimmed ~35 %", st[0] and st[1] > 0 and abs(st[2] - 0.35) < 0.05, str(st))
    time.sleep(0.5)
    cen = js(wd, """const s=document.querySelector('#drawflow').getBoundingClientRect(); const els=[...document.querySelectorAll('.drawflow-node.lit-now:not(.node-state)')];
      if(!els.length) return null; const rs=els.map(e=>e.getBoundingClientRect()); const x0=Math.min(...rs.map(r=>r.x)), x1=Math.max(...rs.map(r=>r.right)), y0=Math.min(...rs.map(r=>r.y)), y1=Math.max(...rs.map(r=>r.bottom));
      const cx=(x0+x1)/2, cy=(y0+y1)/2;
      return [Math.abs(cx-(s.x+s.width/2))/s.width, Math.abs(cy-(s.y+s.height/2))/s.height, document.querySelector('#drawflow > .drawflow').style.transform]""")
    check("tester auto-focus: active chain centred on the canvas", cen is not None and cen[0] < 0.3 and cen[1] < 0.3, str(cen))
    wid = js(wd, "const p=document.querySelector('svg.connection.wlit-now .main-path'); return p?parseFloat(getComputedStyle(p).strokeWidth):0")
    check("active wire stroke >= 5 px", wid >= 5, str(wid))
    bad = js(wd, "return [...document.querySelectorAll('svg.connection.ret:not(.wlit-now):not(.wlit-past) .main-path')].filter(p=>+getComputedStyle(p).opacity>0.2).length")
    check("no non-active returning wire painted over the dimming", bad == 0, str(bad))
    wd.shot("editor7-tester.png")
    js(wd, "[...document.querySelectorAll('#tester button, button')].find(b=>b.textContent.includes('Réinitialiser')).click()")
    time.sleep(1.5)
    st = js(wd, "return [document.querySelector('#drawflow').classList.contains('simdim'), document.querySelectorAll('.lit-now,.lit-past,svg.wlit-now,svg.wlit-past').length]")
    check("Réinitialiser clears the highlight", not st[0] and st[1] == 0, str(st))
    # one live hush: the journal must show the fired chain and the live blink must hit the same nodes
    st0 = W.http("GET", BASE + "/api/status")[1]["state"]
    before = len(W.http("GET", BASE + "/api/graph/trace")[1]["trace"])
    r = W.http("POST", BASE + "/api/control", {"action": "hush"})
    print("HUSH", r)
    blink_js = "const m=window.__editor.dfMap(); const inv={}; Object.keys(m).forEach(k=>inv[m[k]]=k); return [...document.querySelectorAll('.drawflow-node.blink')].map(e=>inv[e.id.replace('node-','')])"
    best = set()
    for _ in range(16):
        time.sleep(0.25)
        best |= set(js(wd, blink_js))
    tr2 = W.http("GET", BASE + "/api/graph/trace")[1]["trace"]
    print("LIVE TRACE tail", tr2[-1:])
    live = tr2[-1] if len(tr2) > before or tr2 else None
    ids = js(wd, "return window.__editor.liveChains().keys.get(arguments[0])||null", [live["chain"]]) if live else None
    check("live hush: its chain exists in the drawn graph", ids is not None, live["chain"] if live else "none")
    if ids:
        check("live blink hits exactly the chain nodes", best == set(ids), "%s vs %s" % (sorted(best), sorted(ids)))
    # click on the journal row of the simulated-free live trace if any
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


def sc_testervars(wd):
    """Vars L2: the Tester shows the simulated variables of each step; etat changes are highlighted."""
    open_editor(wd)
    js(wd, "window.__editor.activateTab('tester')")
    time.sleep(0.5)
    js(wd, "const E=window.__editor; E.sim.steps=[{event:'visage'},{wait_s:4},{say:'au revoir'}]; return E.simRun(false)")
    time.sleep(3)
    tr = js(wd, "return window.__editor.sim.trace.map(e=>[e.chain, e.to, !!e.vars, e.vars&&e.vars.names.etat])")
    print("TRACE", tr)
    check("every trace entry carries vars (etat = to)", tr and all(t[2] and t[3] == t[1] for t in tr), str(tr))
    seen, chg = [], []
    for i in range(len(tr)):
        js(wd, "window.__editor.selectTrace(arguments[0], false)", [i])
        time.sleep(0.2)
        r = js(wd, "const e=document.querySelector('#simStatus .sv[data-svar=etat]'); return e?[e.textContent, e.classList.contains('chg')]:null")
        seen.append(r[0] if r else None)
        chg.append(r[1] if r else None)
    print("ETAT CHIPS", seen, chg)
    want = js(wd, "return window.__editor.sim.trace.map(e=>e.to)")
    labels = {"veille": "Veille", "accueil": "Accueil", "ecoute": "Écoute", "cloture": "Clôture", "reponse": "Réponse", "relance": "Relance", "eteint": "Éteint"}
    check("Tester shows etat changing step by step", all(s and s.endswith(labels.get(w, w)) for s, w in zip(seen, want)) and len(set(want)) >= 3, str(seen))
    moved = js(wd, "return window.__editor.sim.trace.map((e,i)=>i>0 && e.vars.names.etat!==window.__editor.sim.trace[i-1].vars.names.etat)")
    check("changed etat highlighted exactly when it changes", chg == moved, "%s vs %s" % (chg, moved))
    js(wd, "window.__editor.selectTrace(1, true)")
    time.sleep(0.6)
    wd.shot("editor8-tester.png")
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


# Scenario registry read by tests/web/run.py (order = order of the former single file).
SCENARIOS = {
    "tester": sc_tester,
    "testervars": sc_testervars,
}
