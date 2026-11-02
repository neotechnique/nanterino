"""Nanterino editor web scenarios: toolbar image export: options popover, progress toast, PNG attachment.

Purpose : export area of the editor web suite; scenarios export.
Boundary: drives the live editor through tests/web/driver.py (WebDriver, check()); never imports nanterino.server.
Invariant: verbatim slice (M7) of the former scripts/editor6_wd.py; a scenario is `sc_<name>(wd)` and is listed in
          SCENARIOS at the end of this file, which tests/web/run.py reads.
Test    : .venv/bin/python -m tests.web.run export   (or `area:export`, or `all`)
"""
import glob, json, os, sys, time

from tests.web.driver import *  # noqa: F401,F403  (shared helpers, check(), W, BASE, ROOT)


def sc_export(wd):
    """L14: toolbar "Exporter l'image" -> options popover -> Exporter -> progress toast -> the PNG is served by
    GET /api/graph/snapshot.png (attachment nanterino-graph-YYYYMMDD-HHMM.png) and is a valid PNG of the job's size.
    The page keeps the download in memory (window.__exportNoSave): nothing lands in ~/Downloads. Never saves the graph."""
    import re
    open_editor(wd)
    b = rect(wd, "#btnExport")
    tip = js(wd, "const b=document.querySelector('#btnExport'); return b ? (b.getAttribute('title') || b.dataset.tip || '') : null")
    check("toolbar has « Exporter l'image » with a tooltip", b and b[2] > 0 and tip is not None and "PNG" in (tip or "")
          and "Exporter l" in js(wd, "return document.querySelector('#btnExport').textContent"), str((b, tip)))
    lclick(wd, b[0] + b[2] / 2, b[1] + b[3] / 2)
    pop = js(wd, """const p=document.querySelector('#exportPop'); if(!p) return null; const r=p.getBoundingClientRect();
      return {hidden:p.hidden, x:r.x, y:r.y, w:r.width, h:r.height, vw:innerWidth, vh:innerHeight,
        groups:[...p.querySelectorAll('legend')].map(l=>l.textContent), radios:[...p.querySelectorAll('input:checked')].map(i=>i.name+'='+i.value)}""")
    check("click opens the options popover inside the viewport (Zoom / Thème / Graphe, defaults 100 % dark saved)",
          pop and not pop["hidden"] and pop["x"] >= 0 and pop["x"] + pop["w"] <= pop["vw"] and pop["y"] + pop["h"] <= pop["vh"]
          and pop["groups"] == ["Zoom", "Thème", "Graphe"] and sorted(pop["radios"]) == ["ex-doc=saved", "ex-scale=1", "ex-theme=dark"], str(pop))
    time.sleep(0.3)
    wd.shot("editor18-export-popover.png")
    # 50 % then back to 100 %: the radios drive the options object
    r50 = rect(wd, "#exportPop input[name=ex-scale][value='0.5']")
    lclick(wd, r50[0] + r50[2] / 2, r50[1] + r50[3] / 2)
    o50 = js(wd, "return window.__editor.exportOpts()")
    r100 = rect(wd, "#exportPop input[name=ex-scale][value='1']")
    lclick(wd, r100[0] + r100[2] / 2, r100[1] + r100[3] / 2)
    o100 = js(wd, "return window.__editor.exportOpts()")
    check("zoom radios set the export scale (0.5 then 1)", o50["scale"] == 0.5 and o100["scale"] == 1, str((o50, o100)))
    js(wd, "window.__exportNoSave = true")
    # every toast text ever shown (a cache hit ends in ~0.2 s, before a poll could read the progress text)
    js(wd, """window.__toastLog=[]; const box=document.querySelector('#toasts'); const rec=()=>box.querySelectorAll('.toast').forEach(t=>{
      if(!window.__toastLog.includes(t.textContent)) window.__toastLog.push(t.textContent);});
      new MutationObserver(rec).observe(box,{subtree:true,childList:true,characterData:true});""")
    g = rect(wd, "#btnExportGo")
    lclick(wd, g[0] + g[2] / 2, g[1] + g[3] / 2)
    time.sleep(0.4)
    first = js(wd, "return window.__toastLog.join(' | ')")
    hidden = js(wd, "return document.querySelector('#exportPop').hidden")
    check("Exporter closes the popover and shows a progress toast", hidden and "Export de l" in first, first)
    t0, info = time.time(), None
    while time.time() - t0 < 300:
        info = js(wd, "return window.__editor.exportInfo()")
        if info and info.get("state") != "running":
            break
        time.sleep(1)
    st, job = W.http("GET", BASE + "/api/graph/snapshot/status")
    job = (job or {}).get("job") or {}
    check("export done: PNG signature, size = the robot job's size", info and info.get("state") == "done" and info.get("png")
          and (info.get("width"), info.get("height")) == (job.get("width"), job.get("height")) and info.get("width", 0) > 1000,
          str({k: (info or {}).get(k) for k in ("state", "error", "width", "height", "bytes", "cache_hit", "seconds")}) + " job=" + str((job.get("width"), job.get("height"))))
    check("download served as attachment nanterino-graph-YYYYMMDD-HHMM.png", info and "attachment" in (info.get("disposition") or "")
          and bool(re.match(r"^nanterino-graph-\d{8}-\d{4}\.png$", info.get("name") or "")), str((info or {}).get("disposition")))
    st2, raw = W.http("GET", BASE + (job.get("url") or "/api/graph/snapshot.png"))
    check("GET /api/graph/snapshot.png serves the same bytes", st2 == 200 and isinstance(raw, bytes) and raw[:8] == b"\x89PNG\r\n\x1a\n"
          and len(raw) == (info or {}).get("bytes"), str((st2, len(raw) if isinstance(raw, bytes) else raw)))
    done = js(wd, "return [...document.querySelectorAll('#toasts .toast')].map(t=>t.textContent).join(' | ')")
    check("toast reports the exported image", "Image exportée" in done and str((info or {}).get("width")) in done, done)
    wd.shot("editor18-export-done.png")
    check("button enabled again, graph not modified", not js(wd, "return document.querySelector('#btnExport').disabled")
          and js(wd, "return document.querySelector('#dirty').hidden") is True)
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


# Scenario registry read by tests/web/run.py (order = order of the former single file).
SCENARIOS = {
    "export": sc_export,
}
