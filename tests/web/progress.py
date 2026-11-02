"""Nanterino editor web scenarios: the one non-blocking progress bar (lot L22, web/editor/core/progress.js).

Purpose : progress area of the editor web suite; scenario `progress`: boot bar from the first paint, fast fetches
          never flash, slow fetches show after 300 ms, aggregation of concurrent tasks + cancel chip, error = red + toast,
          the bar never overlaps a control and never catches the pointer, no blocking overlay during a (stubbed) save,
          and a REAL non-cached PNG export whose determinate bar only grows while the canvas stays usable (pan +
          context menu); screenshot tests/results/editor19-progress.png mid-export.
Boundary: drives the live editor through tests/web/driver.py; never imports nanterino.server. The save is stubbed in the
          page (fetch of POST /api/graph/visual answered locally): nothing is written on the robot. The export removes
          the cache entries of ITS options (scale 1, light, saved) under exports/graph-snapshots first, so the robot
          really captures; the new entry stays in that gitignored cache like any export.
Test    : .venv/bin/python -m tests.web.run progress   (or `area:progress`, or `all`)
"""
import glob, json, os, sys, time

from tests.web.driver import *  # noqa: F401,F403  (shared helpers, check(), W, BASE, ROOT)

P = "return window.__editor.progress()"
SNAP_DIR = os.path.join(ROOT, "exports", "graph-snapshots")
EXPORT_OPTS = {"scale": 1, "theme": "light", "doc": "saved"}

# Records every state the bar / chip goes through (attribute + text mutations), so short states are not missed.
WATCH_JS = """window.__pw=[]; const b=document.querySelector('#progress'), c=document.querySelector('#progChip');
  const rec=()=>window.__pw.push({t:Date.now(), hidden:b.hidden, fade:b.classList.contains('fade'), err:b.classList.contains('err'),
    indet:b.classList.contains('indet'), v:b.getAttribute('aria-valuenow'), chip:c.hidden?null:c.textContent});
  if(window.__pwObs) window.__pwObs.disconnect();
  window.__pwObs=new MutationObserver(rec); window.__pwObs.observe(b,{attributes:true}); window.__pwObs.observe(c,{attributes:true,childList:true,characterData:true,subtree:true});"""

# Visible interactive elements whose box intersects the bar strip (should be none) + pointer test on the strip.
OVERLAP_JS = """const b=document.querySelector('#progress').getBoundingClientRect(); const out=[];
  for(const e of document.querySelectorAll('button,input,select,textarea,a[href],[role=button],[role=menuitem],[tabindex]')){
    if(e.closest('#progress')) continue; const r=e.getBoundingClientRect(); if(!r.width||!r.height) continue;
    const cs=getComputedStyle(e); if(cs.visibility==='hidden'||cs.display==='none') continue;
    if(r.top<b.bottom && r.bottom>b.top && r.left<b.right && r.right>b.left) out.push((e.id||e.className||e.tagName)+'@'+Math.round(r.top));}
  const hits=[]; for(let x=5;x<innerWidth;x+=Math.floor(innerWidth/9)){ const e=document.elementFromPoint(x,1); hits.push(!!(e&&e.closest('#progress'))); }
  return {bar:[b.top,b.bottom,b.width], overlaps:out, stripHitsBar:hits.some(Boolean), pe:getComputedStyle(document.querySelector('#progress')).pointerEvents}"""

# Grid of points over the window: every hit must be a normal page region, never a modal / a cover.
OVERLAY_JS = """const bad=[]; const modal=document.querySelector('#modal');
  for(let y=40;y<innerHeight-10;y+=Math.floor(innerHeight/6)) for(let x=20;x<innerWidth-10;x+=Math.floor(innerWidth/8)){
    const e=document.elementFromPoint(x,y); if(!e) continue;
    if(e.closest('#modal') || !e.closest('#bar,#left,#right,#stage,#banner,.exportpop,#tip')) bad.push([x,y,e.id||e.className||e.tagName]); }
  return {bad, modalHidden: modal.hidden, busyCursor: getComputedStyle(document.body).cursor}"""


def _wait_hidden(wd, secs=3.0):
    t0 = time.time()
    while time.time() - t0 < secs:
        p = js(wd, P)
        if p["hidden"]:
            return p
        time.sleep(0.1)
    return js(wd, P)


def sc_progress(wd):
    """L22: one non-blocking progress bar for every slow operation (boot, fetch > 300 ms, save, validate, export)."""
    st, html = W.http("GET", BASE + "/editor")
    html = html.decode("utf-8", "replace") if isinstance(html, bytes) else str(html)
    check("editor.html carries the bar from the first paint (visible, indeterminate, role=progressbar)",
          'id="progress" class="progress on indet" role="progressbar"' in html and 'aria-valuemin="0"' in html
          and 'aria-valuemax="100"' in html and 'id="progChip"' in html, str(st))
    open_editor(wd)
    p = js(wd, P)
    boot = [t for t in p["log"] if t["label"].startswith("Chargement de l")]
    fcp = js(wd, "const e=performance.getEntriesByType('paint').find(x=>x.name==='first-contentful-paint')||performance.getEntriesByType('paint')[0]; return e ? performance.timeOrigin + e.startTime : null")
    check("boot task shown, ended after the first paint (the bar covered the whole boot)",
          boot and boot[0]["shown"] and boot[0]["t1"] and not boot[0]["failed"] and fcp and fcp <= boot[0]["t1"],
          str((boot[:1], fcp)))
    check("after boot the bar is hidden, no aria-busy left", p["hidden"] and p["busy"] in (None, "false") and p["chip"] is None, str({k: p[k] for k in ("hidden", "busy", "chip")}))
    errs0 = js(wd, "return window.__editor.errors.length")

    # ---- fast fetch: never shown
    js(wd, WATCH_JS)
    ms = wd.cmd("POST", "/execute/async", {"script": """const cb=arguments[arguments.length-1]; const t=performance.now();
      window.__editor.api('/api/live').then(()=>cb(performance.now()-t)).catch(e=>cb(-1));""", "args": []})
    time.sleep(0.5)
    pw = js(wd, "return window.__pw")
    last = js(wd, P)["log"][-1]
    check("fast fetch (< 300 ms) never shows the bar", ms is not None and 0 <= ms < 300 and last["auto"] and not last["shown"]
          and not any(not s["hidden"] for s in pw), str((round(ms or -1), last, pw[:3])))

    # ---- slow fetch (stubbed 700 ms delay): shown after the delay, with its label, then fades out
    js(wd, WATCH_JS)
    js(wd, """const orig=window.fetch; window.__origFetch=orig;
      window.fetch=(p,o)=>String(p).startsWith('/api/graph/versions') ? new Promise(r=>setTimeout(()=>r(orig(p,o)),700)) : orig(p,o);
      window.__slow=window.__editor.api('/api/graph/versions');""")
    time.sleep(0.15)
    early = js(wd, P)
    time.sleep(0.35)
    mid = js(wd, P)
    time.sleep(0.6)
    endp = _wait_hidden(wd)
    js(wd, "window.fetch=window.__origFetch")
    check("slow fetch: hidden for the first 300 ms, then indeterminate bar + chip label, hidden at the end",
          early["hidden"] and mid["visible"] and mid["indeterminate"] and (mid["chip"] or "").startswith("Chargement des versions")
          and mid["busy"] == "true" and endp["hidden"], str((early["hidden"], {k: mid[k] for k in ("visible", "indeterminate", "chip", "busy")}, endp["hidden"])))
    fades = js(wd, "return window.__pw.filter(s=>s.fade).length")
    check("the end is a fade (class fade before hidden)", fades >= 1, str(fades))

    # ---- no overlap with any control, pointer goes through the strip, toolbar does not move with the chip
    bar0 = rect(wd, "#bar")
    js(wd, "window.__t1=window.__editor.startTask('Tâche de test A', {progress: 0.2}); window.__t2=window.__editor.startTask('Tâche de test B', {progress: 0.6})")
    time.sleep(0.4)
    agg = js(wd, P)
    ov = js(wd, OVERLAP_JS)
    bar1 = rect(wd, "#bar")
    sb = rect(wd, "#btnSave")
    hit = js(wd, "const e=document.elementFromPoint(arguments[0],arguments[1]); return e ? (e.closest('#btnSave') ? 'btnSave' : (e.id||e.className)) : null", [sb[0] + sb[2] / 2, sb[1] + sb[3] / 2])
    check("two tasks aggregate: one determinate bar at the mean (40 %), chip « A… 20 % · +1 »",
          agg["visible"] and not agg["indeterminate"] and agg["value"] == 40 and (agg["chip"] or "").startswith("Tâche de test A… 20 %")
          and "+1" in (agg["chip"] or ""), str({k: agg[k] for k in ("visible", "indeterminate", "value", "chip")}))
    check("bar: 3 px strip at the top, overlaps no control, pointer-events none (the strip hits what is below)",
          ov["bar"][0] == 0 and 2 <= ov["bar"][1] <= 4 and not ov["overlaps"] and not ov["stripHitsBar"] and ov["pe"] == "none", str(ov))
    chipr = js(wd, """const c=document.querySelector('#progChip'), r=c.getBoundingClientRect(), b=document.querySelector('#bar').getBoundingClientRect();
      return {right: Math.round(b.right - r.right), w: Math.round(r.width), clipped: c.scrollWidth > c.clientWidth + 1}""")
    check("toolbar unchanged by the chip (no move / wrap) and its buttons still hit-testable", bar0 == bar1 and hit == "btnSave", str((bar0, bar1, hit)))
    check("chip at the right end of the toolbar, label not clipped", chipr["right"] <= 12 and chipr["w"] > 60 and not chipr["clipped"], str(chipr))
    js(wd, "window.__t2.set(0.9); window.__t1.done()")
    time.sleep(0.3)
    one = js(wd, P)
    js(wd, "window.__t2.set(0.5)")
    time.sleep(0.2)
    back = js(wd, P)
    check("one task left: bar follows it; it never steps back while the same task runs", one["value"] == 90 and back["value"] == 90
          and (back["chip"] or "").startswith("Tâche de test B… 50 %"), str((one["value"], back["value"], back["chip"])))
    js(wd, "window.__t2.done(); window.__cancelled=0; window.__t3=window.__editor.startTask('Tâche annulable', {cancel: ()=>{ window.__cancelled++; window.__t3.done(); }})")
    time.sleep(0.3)
    c = rect(wd, "#progChip")
    cls = js(wd, "return document.querySelector('#progChip').className")
    lclick(wd, c[0] + c[2] / 2, c[1] + c[3] / 2)
    after = _wait_hidden(wd)
    check("cancellable task: chip marked .cancel, a click cancels it, the bar hides", "cancel" in cls
          and js(wd, "return window.__cancelled") == 1 and after["hidden"], str((cls, js(wd, "return window.__cancelled"), after["hidden"])))

    # ---- error path: Réinitialiser a variable, robot answers 500 (stubbed in the page) -> red bar + the existing toast
    js(wd, WATCH_JS)
    js(wd, """const orig=window.fetch; window.__origFetch=orig;
      window.fetch=(p,o)=>String(p).startsWith('/api/graph/vars/reset') ? new Promise(r=>setTimeout(()=>r(new Response(JSON.stringify({error:'panne simulée'}),{status:500,headers:{'Content-Type':'application/json'}})),400)) : orig(p,o);
      window.__editor.resetVar('compteur_test_l22');""")
    time.sleep(0.6)
    red = js(wd, P)
    toasts = js(wd, "return [...document.querySelectorAll('#toasts .toast.err')].map(t=>t.textContent).join(' | ')")
    js(wd, "window.fetch=window.__origFetch")
    check("error: the bar turns red and the existing error toast shows", red["err"] and "panne simulée" in toasts, str((red["err"], toasts[-160:])))
    endr = _wait_hidden(wd, 4)
    check("red is brief: the bar hides afterwards", endr["hidden"] and not endr["err"], str((endr["hidden"], endr["err"])))

    # ---- « Enregistrer et appliquer » (POST stubbed in the page, nothing written): one covering task, no overlay, usable
    js(wd, WATCH_JS)
    js(wd, """const orig=window.fetch; window.__origFetch=orig;
      window.fetch=(p,o)=>(String(p)==='/api/graph/visual' && o && o.method==='POST') ? new Promise(r=>setTimeout(()=>r(new Response(JSON.stringify({ok:true,applied:true,message:'Enregistré (test L22, rien écrit).'}),{status:200,headers:{'Content-Type':'application/json'}})),1500)) : orig(p,o);
      window.__saveP=window.__editor.save();""")
    time.sleep(0.8)
    sv = js(wd, P)
    over = js(wd, OVERLAY_JS)
    nav0 = js(wd, "return window.__editor.nav()")
    pt = view_empty_point(wd)
    wheel(wd, pt[0], pt[1], 0, 120)
    nav1 = js(wd, "return window.__editor.nav()")
    time.sleep(1.4)
    js(wd, "window.fetch=window.__origFetch")
    sv_end = _wait_hidden(wd)
    toasts = js(wd, "return [...document.querySelectorAll('#toasts .toast')].map(t=>t.textContent).join(' | ')")
    check("save: one bar + chip « Enregistrement et application… » (its fetches add no second task)",
          sv["visible"] and (sv["chip"] or "").startswith("Enregistrement et application") and "+" not in (sv["chip"] or "")
          and len([t for t in sv["running"] if t["shown"]]) == 1, str({k: sv[k] for k in ("visible", "chip", "running")}))
    check("save: no blocking overlay, no busy cursor, the canvas pans meanwhile", not over["bad"] and over["modalHidden"]
          and over["busyCursor"] not in ("wait", "progress") and (nav0["x"], nav0["y"]) != (nav1["x"], nav1["y"]), str((over, nav0, nav1)))
    check("save ends: bar hidden, toast shown", sv_end["hidden"] and "Enregistré (test L22" in toasts, toasts[-160:])

    # ---- « Valider »: covering task too (fresh dry run), ends hidden
    js(wd, "document.querySelector('#btnValidate').click()")
    time.sleep(1.6)
    vl = [t for t in js(wd, P)["log"] if t["label"] == "Vérification du graphe" and not t["auto"]]
    check("« Valider » runs as one progress task and ends", vl and vl[-1]["t1"] and _wait_hidden(wd)["hidden"], str(vl[-1:]))

    # ---- REAL export (cache entry of these options removed first): determinate, grows, canvas usable, then hidden
    removed = 0
    for meta in glob.glob(os.path.join(SNAP_DIR, "*.json")):
        try:
            o = json.load(open(meta, encoding="utf-8")).get("options") or {}
        except (OSError, ValueError):
            continue
        if float(o.get("scale", 0)) == 1.0 and o.get("theme") == "light" and o.get("doc") == "saved" and not o.get("crop"):
            for f in (meta, meta[:-5] + ".png"):
                try:
                    os.remove(f); removed += 1
                except OSError:
                    pass
    print("cache entries removed", removed)
    js(wd, "window.__exportNoSave = true")
    js(wd, WATCH_JS)
    js(wd, "window.__editor.startExport(arguments[0])", [EXPORT_OPTS])
    samples, shot, ctx_ok, pan_ok, overlay = [], False, None, None, None
    t0 = time.time()
    while time.time() - t0 < 300:
        p = js(wd, P)
        info = js(wd, "return window.__editor.exportInfo()") or {}
        samples.append((round(time.time() - t0, 1), p["visible"], p["indeterminate"], p["value"], p["chip"]))
        if info.get("state") != "running":
            break
        if p["value"] is not None and p["value"] >= 10 and not shot:
            # mid-export: pan, open + close the context menu, look for covers, screenshot
            overlay = js(wd, OVERLAY_JS)        # before the context menu (a real menu is not a cover)
            n0 = js(wd, "return window.__editor.nav()")
            q = view_empty_point(wd)
            wheel(wd, q[0], q[1], 0, 160)
            n1 = js(wd, "return window.__editor.nav()")
            pan_ok = (n0["x"], n0["y"]) != (n1["x"], n1["y"])
            q = view_empty_point(wd)
            rclick(wd, q[0], q[1])
            ctx_ok = js(wd, "return window.__editor.ctxOpen()")
            key(wd, "")      # Escape closes the menu
            time.sleep(0.3)
            wd.shot("editor19-progress.png")
            shot = True
        time.sleep(0.5)
    info = js(wd, "return window.__editor.exportInfo()") or {}
    det = [s[3] for s in samples if s[1] and not s[2] and s[3] is not None]
    chips = [s[4] for s in samples if s[4]]
    print("samples", samples[:6], "...", samples[-4:])
    check("real export (no cache hit) completed", info.get("state") == "done" and info.get("cache_hit") is False and info.get("png"),
          str({k: info.get(k) for k in ("state", "cache_hit", "error", "seconds", "width", "height")}))
    check("export: the bar is determinate during the tiles and only grows", len(set(det)) >= 2 and all(a <= b for a, b in zip(det, det[1:])),
          str(det))
    check("export: chip shows « Export de l'image… NN % »", any(c.startswith("Export de l'image… ") and c.endswith("%") for c in chips), str(chips[-3:]))
    check("export: canvas pans and the context menu opens while it runs", shot and pan_ok and ctx_ok, str((shot, pan_ok, ctx_ok)))
    check("export: no blocking overlay while it runs", overlay is not None and not overlay["bad"] and overlay["modalHidden"], str(overlay))
    fin = _wait_hidden(wd)
    check("export: bar hidden at the end, export button enabled", fin["hidden"] and not js(wd, "return document.querySelector('#btnExport').disabled"), str(fin["hidden"]))
    check("reduced motion: a CSS rule stops the stripe animation", js(wd, """for(const s of document.styleSheets){ let rules; try{rules=s.cssRules;}catch(e){continue;}
        for(const r of rules) if(r.media && /prefers-reduced-motion/.test(r.media.mediaText) && /progress/.test(r.cssText) && /animation: *none/.test(r.cssText)) return true; } return false"""))
    check("console errors 0 (no new ones)", js(wd, "return window.__editor.errors.length") == errs0, str(js(wd, "return window.__editor.errors")))


# Scenario registry read by tests/web/run.py.
SCENARIOS = {
    "progress": sc_progress,
}
