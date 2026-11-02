"""Nanterino editor web scenarios: hover tooltips of toolbar, ports and nodes.

Purpose : tooltips area of the editor web suite; scenarios tooltips.
Boundary: drives the live editor through tests/web/driver.py (WebDriver, check()); never imports nanterino.server.
Invariant: verbatim slice (M7) of the former scripts/editor6_wd.py; a scenario is `sc_<name>(wd)` and is listed in
          SCENARIOS at the end of this file, which tests/web/run.py reads.
Test    : .venv/bin/python -m tests.web.run tooltips   (or `area:tooltips`, or `all`)
"""
import glob, json, os, sys, time

from tests.web.driver import *  # noqa: F401,F403  (shared helpers, check(), W, BASE, ROOT)


def sc_tooltips(wd):
    open_editor(wd)
    away(wd)
    r = rect(wd, "#btnSave")
    hover(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
    time.sleep(0.15)
    early = tip_state(wd)
    time.sleep(0.75)
    t = tip_state(wd)
    check("toolbar button: no bubble before ~400 ms, bubble after", not early[0] and t[0] and "Envoyer le graphe" in t[1], str([early, t]))
    tr = js(wd, "const t=document.getElementById('tip').getBoundingClientRect(); return [t.left>=0, t.right<=innerWidth, t.top>=0, t.bottom<=innerHeight]")
    check("bubble inside the viewport", all(tr), str(tr))
    check("native title borrowed while hovered (no double bubble)", js(wd, "return !document.querySelector('#btnSave').hasAttribute('title')"))
    away(wd)
    check("bubble hidden when the pointer leaves, title restored", not tip_state(wd)[0] and js(wd, "return document.querySelector('#btnSave').getAttribute('title')||''").startswith("Envoyer"))
    # ADAPTED (L10): no palette; the same vocabulary help is the bubble of the menu entry (Actions › Parole & voix)
    e = view_empty_point(wd, 200) or view_empty_point(wd)
    rclick(wd, *e)
    click_item(wd, "Actions"); click_item(wd, "Parole & voix")
    lab = js(wd, "const m=[...document.querySelectorAll('.ctx')].pop(); const r=m.querySelector('.cit'); r.setAttribute('data-probe','1'); return r.querySelector('.clab').textContent")
    want = js(wd, "const l=arguments[0]; const a=window.__editor.menuItems().find(i=>i.label===l); return a?a.help:''", [lab])
    r = rect(wd, "[data-probe]")
    wd.cmd("POST", "/actions", {"actions": [{"type": "pointer", "id": "m", "parameters": {"pointerType": "mouse"},
                                             "actions": [{"type": "pointerMove", "duration": 0, "x": int(r[0] + r[2] / 2), "y": int(r[1] + r[3] / 2)}]}]})
    time.sleep(0.9)
    t = tip_state(wd)
    check("palette item: bubble = vocabulary help", t and t[0] and want and t[1] == want, "%r / %r" % (t, want))
    js(wd, "window.__editor.closeCtx()")
    away(wd)
    # ports of a condition (Vrai / Faux) and an input
    cond = node_of(wd, "n.kind==='condition'")
    js(wd, "window.__editor.focusNode(arguments[0])", [cond["id"]])   # centred: its input port is not under the palette
    time.sleep(0.5)
    df = dfid(wd, cond["id"])
    t1 = hover_tip(wd, "#node-%s .outputs .output_1" % df)
    away(wd)
    t2 = hover_tip(wd, "#node-%s .outputs .output_2" % df)
    away(wd)
    t3 = hover_tip(wd, "#node-%s .inputs .input" % df)
    check("ports: Vrai / Faux / Entrée explained", t1 and t1[0] and t1[1].startswith("Vrai") and t2 and t2[0] and t2[1].startswith("Faux") and t3 and t3[0] and t3[1].startswith("Entrée"), str([t1, t2, t3]))
    away(wd)
    th = hover_tip(wd, "#node-%s .nhead" % df)
    check("node header: what a condition does", th and th[0] and th[1].startswith("Condition"), str(th))
    away(wd)
    # inspector field help (argument help from the vocabulary)
    act = node_of(wd, "n.kind==='action' && n.params.action==='set_var'")
    js(wd, "window.__editor.focusNode(arguments[0]); window.__editor.activateTab('node')", [act["id"]])
    time.sleep(0.5)
    want = js(wd, "return fetch('/api/graph/vocab').then(r=>r.json()).then(v=>v.actions.find(a=>a.id==='set_var').args[0].help)")
    t = hover_tip(wd, "#inspector .fld .tipi")
    check("inspector field: info icon bubble = argument help", t and t[0] and t[1] == want, "%r / %r" % (t, want))
    js(wd, "document.querySelector('#inspector .fld .tipi').click()")
    time.sleep(0.2)
    check("info icon toggles on click (touch fallback)", not tip_state(wd)[0])
    js(wd, "document.querySelector('#inspector .fld .tipi').click()")
    time.sleep(0.2)
    check("info icon click shows the bubble at once", tip_state(wd)[0])
    away(wd)
    js(wd, "window.__editor.hideTip()")
    # Variables panel column header, jump bar chip, global badge
    js(wd, "window.__editor.activateTab('vars')")
    time.sleep(0.5)
    t = hover_tip(wd, "#vars .vtable th:nth-child(2)")
    check("variables panel: column header explained", t and t[0] and t[1].startswith("Type"), str(t))
    away(wd)
    t = hover_tip(wd, "#jumpbar .jchip")
    check("jump bar chip: bubble", t and t[0] and "Aller à" in t[1], str(t))
    away(wd)
    js(wd, "window.__editor.activateTab('node')")
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


# Scenario registry read by tests/web/run.py (order = order of the former single file).
SCENARIOS = {
    "tooltips": sc_tooltips,
}
