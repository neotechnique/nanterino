"""Nanterino dashboard web scenario `mechanics` (lot C3): the « Mécanique » screen of /dash on the simulated body.

Purpose : the screen renders every joint grouped Tête / Bras gauche / Bras droit / Base with live values; each slider is
          bounded by the joint calibration; « Définir mini » takes the current position and updates the limit (API +
          slider + label); the ARRÊT D'URGENCE button (sticky header, visible after scrolling) latches: a command
          from the page answers 409 and nothing moves, « Réarmer » restores commands; the export gives a calibration
          document, an invalid import is refused (400); the SVG schematic follows the head; no script error.
Boundary: drives the live dashboard (http://127.0.0.1:8080/dash) through tests/web/driver.py; never imports
          nanterino.server. Only /api/body/* is touched (simulated motors; never /api/control). Everything changed is
          rolled back at the end: calibration re-imported from the export taken first, e-stop reset, head back to 0.
          Note: the first run creates state/body-calibration.json (same values as the defaults after the rollback).
Test    : .venv/bin/python -m tests.web.run mechanics     (screenshots tests/results/dash-mechanics*.png)
"""
import json
import time

from tests.web.driver import *  # noqa: F401,F403  (check(), js, W, BASE)


def _api(method, path, body=None):
    return W.http(method, BASE + path, body)


def _joint(jid):
    st, s = _api("GET", "/api/body/state")
    return next(j for j in s["joints"] if j["id"] == jid)


def _wait(cond, secs=8.0):
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            if cond():
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


SLIDE = ("const s=document.querySelector('.mech-slider[data-joint=head_pan]'); s.value=arguments[0];"
         " s.dispatchEvent(new Event('input')); s.dispatchEvent(new Event('change'))")


def sc_mechanics(wd):
    st, saved = _api("GET", "/api/body/calibration/export")
    check("export endpoint answers a calibration document",
          st == 200 and isinstance(saved, dict) and saved.get("schema") == "nanterino.body-calibration", repr(st))
    _api("POST", "/api/body/estop/reset")
    _api("POST", "/api/body/command", {"targets": {"head_pan": 0, "head_tilt": 0}})
    try:
        wd.go("about:blank")
        wd.go(BASE + "/dash")
        ready = _wait(lambda: js(wd, "return document.querySelectorAll('.mech-row').length") == 8, 15)
        check("Mécanique screen renders the 8 joints", ready, js(wd, "return document.querySelectorAll('.mech-row').length"))
        check("Mécanique module loaded without script error", js(wd, "return !!window.__mech && window.__mech.errors.length === 0"))
        groups = js(wd, "return [...document.querySelectorAll('.mech-group h3')].map(e=>e.textContent)")
        check("joints grouped Tête / Bras gauche / Bras droit / Base", groups == ["Tête", "Bras gauche", "Bras droit", "Base"],
              repr(groups))
        st, state = _api("GET", "/api/body/state")
        cal = {j["id"]: j["calibration"] for j in state["joints"]}
        bounds = js(wd, "return Object.fromEntries([...document.querySelectorAll('.mech-slider')].map(s=>[s.dataset.joint,[+s.min,+s.max]]))")
        check("every slider is bounded by its calibration min..max",
              all(bounds.get(k) == [c["min"], c["max"]] for k, c in cal.items()), repr(bounds))
        live = js(wd, "return ['pos','vel','cur','tmp'].map(k=>document.getElementById('mech-'+k+'-head_pan').textContent)")
        check("live position / speed / current / temperature shown", all(v not in ("", "–") for v in live), repr(live))
        check("wheel rows: calibration buttons disabled (velocity joints)",
              js(wd, "return [...document.querySelectorAll('[data-joint=base_left_wheel][data-act]')].every(b=>b.disabled)"))
        # the slider drives the joint through the page code path (input / change -> POST /api/body/command)
        js(wd, SLIDE, [-20])
        # exact landing (the live heartbeat dt jitters: the sim may overshoot by ~0.01 deg, then lands exactly)
        moved = _wait(lambda: _joint("head_pan")["position"] == -20.0 and not _joint("head_pan")["moving"], 8)
        check("slider moves head_pan to -20 (simulated)", moved, repr(_joint("head_pan")["position"]))
        js(wd, "document.querySelector('.mech-slider[data-joint=head_pan]').value=-500")
        check("the browser keeps a slider value inside the bounds",
              float(js(wd, "return document.querySelector('.mech-slider[data-joint=head_pan]').value")) >= cal["head_pan"]["min"])
        # « Définir mini » from the current position
        js(wd, "document.querySelector('[data-joint=head_pan][data-act=set_min]').click()")
        ok = _wait(lambda: _api("GET", "/api/body/calibration")[1]["calibration"]["head_pan"]["min"] == -20.0, 6)
        check("« Définir mini » stores the current position as the min", ok)
        ui = _wait(lambda: js(wd, "return +document.querySelector('.mech-slider[data-joint=head_pan]').min") == -20.0
                   and js(wd, "return document.getElementById('mech-min-head_pan').textContent") == "-20.0", 6)
        check("slider bound and min label updated to -20", ui)
        st, rep = _api("POST", "/api/body/command", {"targets": {"head_pan": -60}})
        check("server clamps a command below the new min", st == 200 and rep["applied"]["head_pan"] == -20.0, repr(rep))
        # the schematic follows the head
        x_before = js(wd, "return document.getElementById('sch-pan').getAttribute('x2')")
        _api("POST", "/api/body/command", {"targets": {"head_pan": 40, "arm_r_shoulder": 60}})
        _wait(lambda: abs(_joint("head_pan")["position"] - 40) < 0.06, 6)
        time.sleep(0.6)
        x_after = js(wd, "return document.getElementById('sch-pan').getAttribute('x2')")
        check("top-view schematic follows head_pan", x_before != x_after and float(x_after) < 100, repr((x_before, x_after)))
        # emergency stop: visible after scrolling, latches, blocks a command from the page, reset restores
        js(wd, "document.getElementById('mech').scrollIntoView()")
        time.sleep(0.4)
        vis = js(wd, "const r=document.getElementById('estop').getBoundingClientRect(); return r.top>=0 && r.bottom<=innerHeight && r.width>60")
        check("ARRÊT D'URGENCE stays visible after scrolling to the screen (sticky header)", vis)
        wd.shot("dash-mechanics.png")
        js(wd, "document.getElementById('estop').click()")
        latched = _wait(lambda: _api("GET", "/api/body/state")[1]["estop"]["active"], 5)
        check("e-stop button latches the body", latched)
        check("e-stop shown in the page (reset button visible)", _wait(lambda: js(
            wd, "return document.body.classList.contains('estop-on') && !document.getElementById('estop-reset').hidden"), 4))
        p0 = _joint("head_pan")["position"]
        js(wd, "window.__mech.lastReply=null")
        js(wd, SLIDE, [0])
        _wait(lambda: js(wd, "return window.__mech.lastReply && window.__mech.lastReply.status") == 409, 4)
        check("a command from the page is refused with 409 while latched",
              js(wd, "return window.__mech.lastReply && window.__mech.lastReply.status") == 409,
              repr(js(wd, "return window.__mech.lastReply")))
        time.sleep(1.0)
        check("nothing moved while latched", _joint("head_pan")["position"] == p0)
        wd.shot("dash-mechanics-estop.png")
        js(wd, "document.getElementById('estop-reset').click()")
        check("« Réarmer » clears the e-stop", _wait(lambda: not _api("GET", "/api/body/state")[1]["estop"]["active"], 5))
        time.sleep(0.3)
        js(wd, SLIDE, [0])
        check("commands work again after the reset", _wait(lambda: abs(_joint("head_pan")["position"]) < 0.06, 8))
        # export / invalid import
        js(wd, "window.__mech.lastExport=null; document.getElementById('mech-export').click()")
        _wait(lambda: js(wd, "return !!window.__mech.lastExport"), 5)
        exp = js(wd, "return window.__mech.lastExport")
        try:
            doc = json.loads(exp or "null")
        except ValueError:
            doc = None
        check("« Exporter la calibration » produces the JSON document", isinstance(doc, dict)
              and doc.get("schema") == "nanterino.body-calibration" and doc["joints"]["head_pan"]["min"] == -20.0)
        js(wd, "window.__mech.importDoc({schema:'x', joints:{}})")
        _wait(lambda: js(wd, "return window.__mech.lastReply.status") == 400, 4)
        check("an invalid calibration import is refused (400)", js(wd, "return window.__mech.lastReply.status") == 400)
        check("no script error after the scenario", js(wd, "return window.__mech.errors.length") == 0)
    finally:
        _api("POST", "/api/body/estop/reset")
        st, _ = _api("POST", "/api/body/calibration/import", saved)
        _api("POST", "/api/body/command", {"targets": {"head_pan": 0, "head_tilt": 0, "arm_r_shoulder": 0}})
        st2, cal = _api("GET", "/api/body/calibration")
        check("rollback: calibration restored from the export", st == 200 and cal["calibration"] == saved["joints"])


SCENARIOS = {"mechanics": sc_mechanics}
