"""Nanterino dashboard web scenario `sound360` (lot C2): the « Son 360° » screen of /dash.

Purpose : the screen renders with the robot's FRONT marked (arrow + « AVANT »); with the live backend (mono: one USB mic)
          the honest message is shown, no beam is drawn and « Définir comme avant » is disabled; with the backend
          switched to the simulation at run time (POST /api/sound/backend, mono | sim only: no device is opened) the beam
          follows a virtual source at 3 angles (0, 90 = left, -135 = back right) both in numbers and in the drawing, a
          pointer drag on the drawing moves the virtual source, and « Définir comme avant » turns the frame (a source at
          60 becomes the new front: offset +60, beam straight up, array marker rotated); no script error.
          Lot L45: the sticky section nav (7 links, « Son 360° » scrolls the section below the header and is
          highlighted), the /dash#snd deep link, and the stream reaching the screen at >= 10 Hz.
Boundary: drives the live dashboard (http://127.0.0.1:8080/dash) through tests/web/driver.py; never imports
          nanterino.server; never opens or unmutes a microphone. Everything changed is rolled back at the end: the front
          offset is written back (state/sound-calibration.json keeps the original value) and the backend returns to the
          one it had (mono on the live robot).
Test    : .venv/bin/python -m tests.web.run sound360     (screenshots tests/results/dash-sound360*.png)
"""
import time

from tests.web.driver import *  # noqa: F401,F403  (check(), js, W, BASE)


def _api(method, path, body=None):
    return W.http(method, BASE + path, body)


def _state():
    return _api("GET", "/api/sound/state")[1]


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


def _adiff(a, b):
    return abs((a - b + 180) % 360 - 180)


DRAG = ("const svg=document.getElementById('snd-svg'); const r=svg.getBoundingClientRect();"
        " const a=arguments[0]*Math.PI/180, k=r.width/300;"
        " const x=r.left+(150-110*Math.sin(a))*k, y=r.top+(150-110*Math.cos(a))*k;"
        " for (const t of ['pointerdown','pointermove','pointerup'])"
        "   svg.dispatchEvent(new PointerEvent(t,{clientX:x,clientY:y,pointerId:7,bubbles:true}));")


# Lot L45: section top sits just below the sticky header (not hidden under it) and inside the viewport.
IN_VIEW = ("const t=document.getElementById(arguments[0]).getBoundingClientRect().top,"
           " h=document.querySelector('header').offsetHeight,"
           " bottom=Math.ceil(scrollY+innerHeight) >= document.documentElement.scrollHeight-2;"
           " return t >= h - 2 && (t <= h + 40 || bottom) && t < innerHeight")   # last section: page may end first


def sc_sound360(wd):
    st0 = _state()
    saved_offset, saved_backend = st0["front_offset_deg"], st0["backend"]
    check("sound state endpoint answers (backend %s)" % saved_backend, saved_backend in ("mono", "sim", "array", "vendor", "xvf3800"))
    try:
        if saved_backend != "mono":
            _api("POST", "/api/sound/backend", {"backend": "mono"})
        wd.go("about:blank")
        wd.go(BASE + "/dash")
        ready = _wait(lambda: js(wd, "return !!window.__snd && !!window.__snd.state()"), 15)
        check("Son 360° screen loaded and receiving the stream", ready)
        check("Son 360° module without script error", js(wd, "return window.__snd.errors.length === 0"),
              js(wd, "return window.__snd && window.__snd.errors"))
        # lot L45: sticky section nav; the « Son 360° » link brings the (last) section under the sticky header
        links = js(wd, "return window.__secnav ? window.__secnav.links() : null")
        check("section nav lists the 7 sections, Son 360° last (#snd)",
              links and [l[0] for l in links] == ["Dialogue", "Audio", "Moteurs IA", "Matériel", "Erreurs", "Mécanique",
                                                  "Son 360°"] and links[-1][1] == "#snd"
              and all(js(wd, "return !!document.getElementById(arguments[0])", [h[1:]]) for _, h in links), repr(links))
        js(wd, "window.scrollTo(0,0); [...document.querySelectorAll('#secnav a')].find(a=>a.textContent==='Son 360°').click()")
        in_view = _wait(lambda: js(wd, IN_VIEW, ["snd"]), 4)
        check("« Son 360° » nav link scrolls the section into view below the sticky header", in_view,
              repr(js(wd, "return [document.getElementById('snd').getBoundingClientRect().top,"
                          " document.querySelector('header').offsetHeight, innerHeight]")))
        check("nav highlights « Son 360° » once there",
              _wait(lambda: js(wd, "return window.__secnav.current()") == "Son 360°", 4),
              repr(js(wd, "return window.__secnav.current()")))
        js(wd, "window.scrollTo(0,0)")
        check("nav highlights « Dialogue » back at the top (first of the grid row)",
              _wait(lambda: js(wd, "return window.__secnav.current()") == "Dialogue", 4),
              repr(js(wd, "return window.__secnav.current()")))
        front = js(wd, "const t=[...document.querySelectorAll('#snd-svg text')].find(e=>e.textContent==='AVANT');"
                       " const m=document.getElementById('snd-front-mark').getBBox();"
                       " return [!!t, m.y < 150, m.height > 5]")
        check("front marked: « AVANT » label and arrow above the robot centre", front == [True, True, True], repr(front))
        mono = _wait(lambda: js(wd, "const m=document.getElementById('snd-msg');"
                                    " return !m.hidden && m.textContent.includes('mono')"), 6)
        check("mono backend: the honest « no direction » message is shown", mono,
              js(wd, "return document.getElementById('snd-msg').textContent"))
        check("mono backend: no beam drawn, « Définir comme avant » disabled",
              js(wd, "return !window.__snd.beam().visible && document.getElementById('snd-front').disabled"))
        js(wd, "document.getElementById('snd').scrollIntoView()")
        time.sleep(0.4)
        wd.shot("dash-sound360-mono.png")
        # simulation backend (runtime only, no device)
        st, rep = _api("POST", "/api/sound/backend", {"backend": "sim"})
        check("backend switched to sim at run time", st == 200 and rep.get("backend") == "sim", repr((st, rep)))
        check("sim controls shown, message hidden", _wait(lambda: js(
            wd, "return !document.getElementById('snd-sim').hidden && document.getElementById('snd-msg').hidden"), 6))
        f0 = js(wd, "return window.__snd.frames")
        time.sleep(2.0)
        rate = (js(wd, "return window.__snd.frames") - f0) / 2.0
        check("stream frames reach the screen at >= 10 Hz (%.1f Hz, lot L45)" % rate, rate >= 10)
        for az in (0, 90, -135):
            _api("POST", "/api/sound/sim", {"azimuth": az, "level": -15})
            ok = _wait(lambda: _adiff(js(wd, "return window.__snd.screenAngle()"), az) < 1.5, 6)
            txt = js(wd, "return document.getElementById('snd-az').textContent")
            check("beam follows a sim source at %d degrees (drawing and numbers)" % az,
                  ok and txt.startswith("%.1f°" % az), repr((js(wd, "return window.__snd.screenAngle()"), txt)))
        side = js(wd, "return document.getElementById('snd-az').textContent")
        check("-135 is shown behind on the right", "droite" in side or "derrière" in side, side)
        js(wd, DRAG, [45])
        dragged = _wait(lambda: _state()["direction"] and _adiff(_state()["direction"]["azimuth_deg"], 45) < 3, 5)
        check("dragging on the drawing moves the virtual source (45 degrees)", dragged, repr(_state().get("direction")))
        # « Définir comme avant »: a source at 60 (calibrated) becomes the new front
        _api("POST", "/api/sound/sim", {"azimuth": 60, "level": -12})
        time.sleep(1.8)                                   # the dominant direction is taken over the last 1.5 s
        js(wd, "document.getElementById('snd-front').click()")
        new_off = (saved_offset + 60 + 180) % 360 - 180
        seen = []
        turned = _wait(lambda: seen.append(_state()["front_offset_deg"]) or _adiff(seen[-1], new_off) < 0.6, 6)
        check("« Définir comme avant » stores the offset (+60)", turned, repr((_state()["front_offset_deg"], new_off, saved_offset)))
        up = _wait(lambda: abs(js(wd, "return window.__snd.screenAngle()")) < 1.5
                   and js(wd, "return document.getElementById('snd-az').textContent").startswith("0.0°"), 6)
        check("after it the same source points straight ahead (beam up, 0.0°)", up,
              repr(js(wd, "return [window.__snd.screenAngle(), document.getElementById('snd-az').textContent]")))
        rot = js(wd, "return document.getElementById('snd-array').getAttribute('transform')")
        check("the microphone frame marker turned with the offset", rot.startswith("rotate(%.2f" % new_off), rot)
        check("feedback message after « Définir comme avant »",
              "Nouvel avant" in js(wd, "return document.getElementById('snd-feedback').textContent"))
        for az in (-40, -70, -100):                       # a short trail for the screenshot
            _api("POST", "/api/sound/sim", {"azimuth": az, "level": -18 + az / 10})
            time.sleep(0.5)
        time.sleep(0.6)
        check("history trail drawn", js(wd, "return document.querySelectorAll('#snd-trail circle').length") > 3)
        st, hist = _api("GET", "/api/sound/history?seconds=5")
        check("GET /api/sound/history returns calibrated samples", st == 200 and hist["samples"]
              and all("azimuth_deg" in s for s in hist["samples"]))
        js(wd, "document.getElementById('snd').scrollIntoView()")
        time.sleep(0.4)
        wd.shot("dash-sound360.png")
        check("no script error after the scenario", js(wd, "return window.__snd.errors.length") == 0)
        # lot L45: a deep link /dash#snd lands on the section even though the sections above fill in afterwards
        wd.go("about:blank")
        wd.go(BASE + "/dash#snd")
        time.sleep(2.5)                                   # load + the one re-scroll after the async renders
        check("deep link /dash#snd shows the Son 360° section after the page filled in", js(wd, IN_VIEW, ["snd"]),
              repr(js(wd, "return [document.getElementById('snd').getBoundingClientRect().top, scrollY]")))
    finally:
        _api("POST", "/api/sound/sim", {"clear": True})
        _api("POST", "/api/sound/front", {"offset_deg": saved_offset})
        _api("POST", "/api/sound/backend", {"backend": "mono" if saved_backend not in ("mono", "sim") else saved_backend})
        st = _state()
        check("rollback: backend %s and front offset %.1f restored" % (st["backend"], saved_offset),
              st["backend"] in ("mono", saved_backend) and abs(st["front_offset_deg"] - saved_offset) < 0.05)
        back = _wait(lambda: js(wd, "const m=document.getElementById('snd-msg'); return !m.hidden && m.textContent.includes('mono')"), 6)
        check("page shows the mono message again after the rollback", back)


SCENARIOS = {"sound360": sc_sound360}
