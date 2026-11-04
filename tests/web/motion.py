"""Nanterino editor web scenario `motion` (lot B1): the Mouvement theme in the node menu, a « Regarder (angles) » node
inserted from Actions › Mouvement, its angles set in the inspector, and the Tester simulating it on the SIMULATED body.

Purpose : the theme « Mouvement » (vocabulary themes, icon hand-move) is listed in the three categories of the context
          menu (Déclencheurs, Actions, Conditions: 12 items each, last theme); right-click › Insérer › Actions ›
          Mouvement › « Regarder (angles) » inserts a look_at node; the inspector shows three number fields (rotation,
          inclinaison, vitesse) and typing 30 / 10 / 100 lands in the node arguments; wired to a « visage » trigger, the
          Tester (POST /api/graph/simulate) returns the simulated body with the head at pan 30 / tilt 10 after 3 s while
          the LIVE body (/api/body/state) did not move; no script error.
Boundary: drives the live editor (http://127.0.0.1:8080/editor) through tests/web/driver.py; never imports
          nanterino.server; never saves the graph (the inserted nodes are undone), never POSTs /api/body/command or
          /api/control: the live body is only read.
Test    : .venv/bin/python -m tests.web.run motion     (screenshot tests/results/editor-motion-menu.png)
"""
import time

from tests.web.driver import *  # noqa: F401,F403  (check(), js, W, BASE, doc, rclick, click_item, menu_labels ...)

E = "window.__editor"


def _live_head():
    st, body = W.http("GET", BASE + "/api/body/state")
    js_ = {j["id"]: j for j in (body or {}).get("joints", [])}
    return st, js_.get("head_pan", {}).get("position"), js_.get("head_tilt", {}).get("position")


def sc_motion(wd):
    st, pan0, tilt0 = _live_head()
    check("live body state answers (head_pan %s)" % pan0, st == 200 and pan0 is not None)
    open_editor(wd)
    voc = W.http("GET", BASE + "/api/graph/vocab")[1]
    th = (voc.get("themes") or [{}])[-1]
    check("vocabulary: last theme = mouvement (Mouvement, icon hand-move)", th.get("id") == "mouvement"
          and th.get("label") == "Mouvement" and th.get("icon") == "hand-move", str(th))
    per = js(wd, "return " + E + ".menuTree(['trigger','action','condition']).map(c=>[c.cat.id, (c.themes.find(t=>t.theme.id==='mouvement')||{items:[]}).items.length, c.themes.slice(-1)[0].theme.id])")
    check("Mouvement in the 3 categories, 12 items each, last theme", [p[1] for p in per] == [12, 12, 12]
          and all(p[2] == "mouvement" for p in per), str(per))
    n0 = len(doc(wd)["nodes"])
    e = view_empty_point(wd, 330) or view_empty_point(wd)
    rclick(wd, *e)
    click_item(wd, "Actions")
    lv2 = menu_labels(wd)[-1]
    check("Actions submenu lists Mouvement▸ (last)", lv2 and lv2[-1] == "Mouvement▸", str(lv2))
    click_item(wd, "Mouvement")
    lv3 = menu_labels(wd)[-1]
    check("Actions › Mouvement lists Regarder (angles), Faire un geste, Avancer / reculer, arrêt d'urgence",
          {"Regarder (angles)", "Faire un geste", "Avancer / reculer", "Déclencher l'arrêt d'urgence"} <= set(lv3), str(lv3))
    wd.shot("editor-motion-menu.png")
    click_item(wd, "Regarder (angles)")
    d = doc(wd)
    new = d["nodes"][-1] if d["nodes"] else {}
    check("item click inserts a look_at node", len(d["nodes"]) == n0 + 1 and new.get("params", {}).get("action") == "look_at",
          str(new)[:160])
    nid = new.get("id")
    js(wd, E + ".activateTab('node'); " + E + ".focusNode(arguments[0])", [nid])
    time.sleep(0.6)
    # number arguments render as a text field inside their value-source wrapper (.srcwrap + its ▾ button, lot M5)
    fields = js(wd, "return [...document.querySelectorAll('#inspector .srcwrap button.srcbtn[data-src-for]')].filter(b=>b.closest('.srcwrap').querySelector('input')).map(b=>b.dataset.srcFor)")
    check("inspector: number fields pan / tilt / speed", fields == ["pan", "tilt", "speed"], str(fields))
    for a, v in (("pan", "30"), ("tilt", "10"), ("speed", "100")):
        js(wd, """const b=document.querySelector('#inspector button.srcbtn[data-src-for='+arguments[0]+']'); const e=b&&b.closest('.srcwrap').querySelector('input');
          if(!e) return false; e.value=arguments[1]; e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true})); return true""", [a, v])
        time.sleep(0.3)
    args = ((next((n for n in doc(wd)["nodes"] if n["id"] == nid), {}).get("params") or {}).get("args"))
    check("typed angles land in the node arguments", args == {"pan": 30, "tilt": 10, "speed": 100}, str(args))
    # wire a « visage » trigger to it and simulate (the Tester runs the CURRENT, unsaved document)
    ok = js(wd, """const E=window.__editor; const m=E.dfMap(); const a=m[arguments[0]];
      const t=E.addAt('trigger',{event:'visage'},{x:-900,y:-700},{exact:true}); return E.linkNodes(t,'output_1',a)""", [nid])
    check("visage trigger wired to the look_at node", ok is not False, str(ok))
    js(wd, E + ".activateTab('tester')")
    time.sleep(0.4)
    js(wd, "window.__mb=undefined; const E=window.__editor; E.sim.steps=[{event:'visage'},{wait_s:3}];"
           " E.simRun(false).then(r=>{window.__mb=(r&&r.json)||null})")
    body = None
    for _ in range(40):
        time.sleep(0.25)
        body = js(wd, "return window.__mb === undefined ? 'wait' : window.__mb")
        if body != "wait":
            break
    sb = (body or {}).get("body") if isinstance(body, dict) else None
    check("Tester simulate: the SIMULATED head reaches pan 30 / tilt 10", sb and sb["joints"]["head_pan"] == 30
          and sb["joints"]["head_tilt"] == 10 and sb["backend"] == "sim" and not sb["estop"], str(body)[:300])
    fired = [x.get("actions") for x in (body or {}).get("trace", [])] if isinstance(body, dict) else []
    check("simulated trace runs look_at(pan=30, tilt=10, speed=100)", any(x.startswith("look_at(") and "pan=30" in x and "tilt=10" in x for a in fired for x in (a or [])),
          str(fired)[:300])
    st, pan1, tilt1 = _live_head()
    check("live body untouched by the simulation (/api/body/state head unchanged)", st == 200 and (pan1, tilt1) == (pan0, tilt0),
          "%s %s -> %s %s" % (pan0, tilt0, pan1, tilt1))
    # leave the document as it was (never saved)
    js(wd, E + ".activateTab('node')")
    for _ in range(6):
        if len(doc(wd)["nodes"]) <= n0:
            break
        js(wd, "document.querySelector('#btnUndo').click()")
        time.sleep(0.4)
    check("undo removes the inserted nodes (nothing saved)", len(doc(wd)["nodes"]) == n0, str(len(doc(wd)["nodes"])))
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


SCENARIOS = {"motion": sc_motion}
