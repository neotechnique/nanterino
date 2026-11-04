"""Nanterino editor web scenarios of lot S2 ("espace sans limite" A2 + A3): zoom levels, minimap, fold repack.

Purpose : `zoom3`: semantic zoom on three levels (normal; column cards below 0.25; DOMAIN cards below 0.1 with label,
          icon, colour, column / node counts and error badges; a click on a domain card zooms into that domain), the
          minimum zoom follows the size of the world (no fixed 0.03 floor), column / chain focus fit-to-target at a
          readable zoom. `minimap2`: the minimap draws the domains (empty ones too), resizes by its corner grip
          (persisted per browser), collapses, its wheel zooms the MINIMAP only, a drag on it still pans the canvas, it
          follows the main view, error dots aggregate (and move onto a folded column's card), and a pan / zoom frame
          makes no layout read (counted with wrapped DOM getters). `foldpack`: folding a domain / a column repacks
          the neighbours (space reclaimed), unfolding restores every position, undo / redo, save-gated; a column moved
          into an empty domain keeps the domain post-it clear of its title.
Boundary: drives the live editor through tests/web/driver.py (WebDriver, check()); never imports nanterino.server; never
          saves (every edit stays in the page; the minimap size key in localStorage is restored at the end).
Test    : .venv/bin/python -m tests.web.run zoom3 minimap2 foldpack   (or `area:space`, or `all`); screenshots
          tests/results/editor-s2-*.png
"""
import time

from tests.web.driver import *  # noqa: F401,F403  (shared helpers, check(), W, BASE, ROOT)
from tests.web.savegate import SPY_JS, _writes

DOMS = ["dialogue", "comportement", "mouvement", "systeme"]
SIZE_KEY = "nanterino.editor.minimap.size"


def _open(wd):
    open_editor(wd)
    js(wd, "window.__editor.closeCtx && window.__editor.closeCtx()")
    js(wd, SPY_JS)
    if not js(wd, "return window.__editor.miniMap() && window.__editor.miniMap().open"):
        js(wd, "document.querySelector('#minimap .mtog').click()")
    time.sleep(0.4)


def _nav(wd):
    return js(wd, "return window.__editor.nav()")


def _cls(wd):
    return js(wd, "const c=document.querySelector('#drawflow').classList; return [c.contains('semzoom'), c.contains('domzoom')]")


def _shown_cards(wd):
    return js(wd, """return [...document.querySelectorAll('.dzcard')].filter(e=>getComputedStyle(e).display!=='none')
      .map(e=>({dom:e.dataset.dom, text:e.textContent, err:(e.querySelector('.fbadge.err')||{}).textContent||''}))""")


def _rects(wd):
    return {d: js(wd, "return window.__editor.domainRect(arguments[0])", [d]) for d in DOMS}


def _disjoint(rs):
    ks = [k for k in rs if rs[k]]
    return [(a, b) for i, a in enumerate(ks) for b in ks[i + 1:]
            if rs[a]["x"] < rs[b]["x"] + rs[b]["w"] and rs[b]["x"] < rs[a]["x"] + rs[a]["w"]
            and rs[a]["y"] < rs[b]["y"] + rs[b]["h"] and rs[b]["y"] < rs[a]["y"] + rs[a]["h"]]


def _positions(wd):
    return js(wd, "return Object.fromEntries(window.__editor.serialize().nodes.map(n=>[n.id,[n.x,n.y]]))")


def _undo(wd, n):
    for _ in range(n):
        js(wd, "window.__editor.undo()")
        time.sleep(0.35)


def sc_zoom3(wd):
    _open(wd)
    nodes = js(wd, "return window.__editor.serialize().nodes.map(n=>[n.id,n.group,n.kind])")
    lv = js(wd, "return window.__editor.zoomLevels()")
    check("zoom3: three levels declared (column cards 0.25, domain cards 0.1)", lv["sem"] == 0.25 and lv["dom"] == 0.1, str(lv))
    # ---- level 3: domain cards at the fit zoom of the shipped graph
    js(wd, "window.__editor.fit()")
    time.sleep(0.6)
    z_fit = _nav(wd)["zoom"]
    check("zoom3: fit of the whole robot is below the domain zoom (%.3f)" % z_fit, z_fit < lv["dom"] and _cls(wd) == [True, True], str(_cls(wd)))
    cards = {c["dom"]: c for c in _shown_cards(wd)}
    check("zoom3: one domain card per domain, empty ones too", sorted(cards) == sorted(DOMS), str(cards)[:300])
    n_dia = sum(1 for _i, g, _k in nodes if g and g != "global")
    n_sys = sum(1 for _i, g, _k in nodes if g == "global")
    check("zoom3: Dialogue card = label, 7 columns, its node count", "Dialogue" in cards["dialogue"]["text"] and "7 colonnes" in cards["dialogue"]["text"]
          and ("%d nœuds" % n_dia) in cards["dialogue"]["text"], cards["dialogue"]["text"])
    check("zoom3: Système card = 1 column, the global nodes", "1 colonne" in cards["systeme"]["text"] and ("%d nœuds" % n_sys) in cards["systeme"]["text"], cards["systeme"]["text"])
    check("zoom3: empty domain cards say so", "vide" in cards["mouvement"]["text"] and "vide" in cards["comportement"]["text"])
    look = js(wd, """const e=document.querySelector('.dregion[data-dom=dialogue] .dzcard'), r=e.getBoundingClientRect(), n=e.querySelector('.dzname');
      return {w:r.width, h:r.height, font:parseFloat(getComputedStyle(n).fontSize)*window.__editor.nav().zoom, bg:getComputedStyle(e).backgroundColor,
        icon:!!e.querySelector('.ico'), z:getComputedStyle(document.querySelector('#domains')).zIndex}""")
    check("zoom3: domain card readable on screen (label >= 18 px), icon, coloured, above the columns",
          look["font"] >= 18 and look["icon"] and look["bg"] not in ("rgba(0, 0, 0, 0)", "transparent") and int(look["z"]) > 6, str(look))
    gact = next(i for i, g, k in nodes if g == "global" and k == "action")
    js(wd, "window.__editor.patchNode(arguments[0], {action: 'pas_une_action_s2'})", [gact])
    time.sleep(1.5)
    cards = {c["dom"]: c for c in _shown_cards(wd)}
    check("zoom3: an error in Système shows on its domain card", cards.get("systeme", {}).get("err", "").startswith("✖"), str(cards.get("systeme")))
    _undo(wd, 1)
    time.sleep(1.0)
    wd.shot("editor-s2-domaincards.png")
    # ---- level 2 / level 1
    js(wd, "const r=window.__editor.domainRect('dialogue'); window.__editor.focusRect({x0:r.x,y0:r.y,x1:r.x+r.w,y1:r.y+r.h}, 0.15)")
    time.sleep(0.4)
    check("zoom3: at 0.15 column cards, no domain cards", _cls(wd) == [True, False] and not _shown_cards(wd)
          and js(wd, "return getComputedStyle(document.querySelector('.frame.auto .fcard')).display") == "flex", str(_cls(wd)))
    js(wd, "window.__editor.focusBand('veille', 0.6)")
    time.sleep(0.4)
    check("zoom3: at 0.6 the normal level (no card)", _cls(wd) == [False, False] and not _shown_cards(wd))
    # ---- click a domain card = zoom into that domain
    js(wd, "window.__editor.fit()")
    time.sleep(0.6)
    r = rect(wd, '.dregion[data-dom="systeme"] .dzcard')
    cx, cy = r[0] + r[2] / 2, r[1] + r[3] / 2
    hit = js(wd, "const e=document.elementFromPoint(arguments[0],arguments[1]); return !!(e && e.closest('.dzcard[data-dom=systeme]'))", [cx, cy])
    check("zoom3: the pointer lands on the Système card (not the minimap / a panel)", hit)
    lclick(wd, cx, cy)
    time.sleep(0.6)
    z = _nav(wd)["zoom"]
    vis = js(wd, """const r=document.querySelector('.dregion[data-dom=systeme]').getBoundingClientRect(), s=document.querySelector('#drawflow').getBoundingClientRect();
      return r.left < s.right && r.right > s.left && r.top < s.bottom && r.bottom > s.top""")
    check("zoom3: click on a domain card zooms into it (above the domain level, region on screen)", z >= lv["dom"] * 1.2 and not _cls(wd)[1] and vis, "%s %s" % (z, vis))
    # ---- minimum zoom follows the world
    js(wd, "window.__editor.fit()")
    time.sleep(0.5)
    # (the canvas size changes with the toolbar wrap of the "modifié" mark: recompute now, same canvas, before comparing)
    m1 = js(wd, "window.__editor.updateZoomMin(); return window.__editor.zoomLevels().min")
    z_fit = _nav(wd)["zoom"]
    check("zoom3: min zoom derived from the world (below the fit, about half of it)", 0.25 * z_fit < m1 < z_fit, "%s fit %s" % (m1, z_fit))
    js(wd, "const d=window.__editor.meta().domains.find(x=>x.id==='mouvement'); window.__s2x=d.x; d.x+=80000; window.__editor.redraw()")
    time.sleep(0.4)
    m2 = js(wd, "return window.__editor.zoomLevels().min")
    js(wd, "window.__editor.fit()")
    time.sleep(0.5)
    z_big = _nav(wd)["zoom"]
    check("zoom3: a 10x wider world lowers the min zoom (no fixed 0.03 floor)", m2 < m1 / 4 and m2 < 0.03 and z_big < 0.03 and _cls(wd)[1], "%s -> %s, fit %s" % (m1, m2, z_big))
    js(wd, "const d=window.__editor.meta().domains.find(x=>x.id==='mouvement'); d.x=window.__s2x; window.__editor.redraw()")
    time.sleep(0.4)
    m3 = js(wd, "window.__editor.updateZoomMin(); return window.__editor.zoomLevels().min")
    check("zoom3: back to the shipped world, same min zoom", abs(m3 - m1) < 1e-9, "%s vs %s" % (m3, m1))
    # ---- column / chain focus: fit-to-target, readable
    for g in ("ecoute", "global", "relance"):
        js(wd, "document.querySelector('#jumpbar .jchip[data-g=\"'+arguments[0]+'\"]').click()", [g])
        time.sleep(0.6)
        st = js(wd, """const f=document.querySelector('.frame[data-fid="auto-'+arguments[0]+'"]'), r=f.getBoundingClientRect(), s=document.querySelector('#drawflow').getBoundingClientRect(),
          t=f.querySelector('.ftitle').getBoundingClientRect(), jb=document.querySelector('#jumpbar').getBoundingClientRect();
          return {z:window.__editor.nav().zoom, left:r.left-s.left, right:s.right-r.right, w:r.width, sw:s.width, tt:t.top, jb:jb.bottom}""", [g])
        fits = st["w"] <= st["sw"] + 1
        check("zoom3: column %s focus readable (%.2f in [READABLE, 1]), %s, title clear of the bar" % (g, st["z"], "whole width on screen" if fits else "left edge on screen"),
              lv["readable"] - 1e-6 <= st["z"] <= 1 + 1e-6 and not _cls(wd)[0] and st["left"] >= -1 and (st["right"] >= -1 or not fits) and st["tt"] >= st["jb"] - 1, str(st))
    chain = js(wd, "const c=window.__editor.treeChains().find(x=>!x.orphan && x.ids.length>2); return c ? c.ids : null")
    js(wd, "window.__editor.focusChainIds(arguments[0])", [chain])
    time.sleep(0.4)
    z = _nav(wd)["zoom"]
    check("zoom3: chain focus fit-to-target, readable (no 0.75 cap)", chain and lv["readable"] - 1e-6 <= z <= 1 + 1e-6, "%s %s" % (z, chain))
    check("zoom3: nothing saved, console errors 0", not _writes(wd) and not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors"))[:200])


PERF_JS = r"""
const E = window.__editor, cnt = {n: 0, by: {}}, undo = [];
const hit = (k) => { if (window.__s2count) { cnt.n++; cnt.by[k] = (cnt.by[k] || 0) + 1; } };
for (const [proto, props] of [[HTMLElement.prototype, ['offsetWidth', 'offsetHeight', 'offsetLeft', 'offsetTop']], [Element.prototype, ['clientWidth', 'clientHeight', 'scrollWidth', 'scrollHeight']]]) {
  for (const p of props) { const d = Object.getOwnPropertyDescriptor(proto, p); Object.defineProperty(proto, p, {configurable: true, get() { hit(p); return d.get.call(this); }}); undo.push(() => Object.defineProperty(proto, p, d)); }
}
const gb = Element.prototype.getBoundingClientRect; Element.prototype.getBoundingClientRect = function () { hit('rect'); return gb.call(this); };
undo.push(() => { Element.prototype.getBoundingClientRect = gb; });
const gcs = window.getComputedStyle; window.getComputedStyle = function (e, p) { hit('style'); return gcs.call(window, e, p); };
undo.push(() => { window.getComputedStyle = gcs; });
const df = document.querySelector('#drawflow'), views = new Set();
const st = df.getBoundingClientRect(), x = st.x + st.width * 0.45, y = st.y + st.height * 0.5;
window.__s2perf = null; window.__s2count = true;
const geo0 = E.geoStats().reads, t0 = performance.now();
let i = 0;
function step() {
  if (i < 60) {
    const ctrl = i % 3 === 2;
    df.dispatchEvent(new WheelEvent('wheel', {bubbles: true, cancelable: true, clientX: x, clientY: y, deltaX: ctrl ? 0 : 7, deltaY: ctrl ? (i % 2 ? 40 : -40) : 5, deltaMode: 0, ctrlKey: ctrl}));
    i++;
    requestAnimationFrame(() => { const v = E.miniMap().view; views.add(Math.round(v.x0) + ':' + Math.round(v.y0)); setTimeout(step, 0); });
    return;
  }
  window.__s2count = false;
  undo.forEach((f) => f());
  window.__s2perf = {reads: cnt.n, by: cnt.by, frames: i, views: views.size, geo: E.geoStats().reads - geo0, ms: Math.round(performance.now() - t0)};
}
step();
return true
"""


def _perf(wd):
    js(wd, PERF_JS)
    for _ in range(60):
        time.sleep(0.25)
        p = js(wd, "return window.__s2perf")
        if p:
            return p
    return None


def sc_minimap2(wd):
    _open(wd)
    saved_size = js(wd, "try { return localStorage.getItem(arguments[0]) } catch(e) { return null }", [SIZE_KEY])
    try:
        js(wd, "try { localStorage.removeItem(arguments[0]) } catch(e) {}; window.__editor.resetMiniZoom(); window.__editor.setMiniSize({w:170,h:110}, false)", [SIZE_KEY])
        js(wd, "window.__editor.fit()")
        time.sleep(0.5)
        mm = js(wd, "return window.__editor.miniMap()")
        check("minimap2: draws every domain region, the empty ones too", mm and mm["doms"] == DOMS, str(mm and mm["doms"]))
        wb, m = js(wd, "return window.__editor.worldBounds()"), mm["map"]
        rs = _rects(wd)
        check("minimap2: world box = nodes + frames + regions (empty regions inside it)", all(
            wb["x0"] <= r["x"] and wb["y0"] <= r["y"] and r["x"] + r["w"] <= wb["x1"] and r["y"] + r["h"] <= wb["y1"] for r in rs.values()), str((wb, rs))[:300])
        px = js(wd, """const [r, m] = arguments, cv=document.querySelector('#minimap canvas'), c=cv.getContext('2d'); const out=[];
          for (let k=0;k<12;k++){ const x=Math.round((r.x-m.x0)*m.s), y=Math.round((r.y+r.h*(k+0.5)/12-m.y0)*m.s);
            for (const dx of [-1,0,1]) { const p=c.getImageData(x+dx,y,1,1).data; out.push([p[0],p[1],p[2]]); } } return out""", [rs["mouvement"], m])
        check("minimap2: the empty Mouvement region is outlined in its colour (#e0a030)", any(p[0] > 150 and 100 < p[1] < 200 and p[2] < 110 for p in px), str(px[:6]))
        # ---- resize by the corner grip (real pointer), persisted, reload keeps it
        nv_r = _nav(wd)
        g = rect(wd, "#minimap .mresize")
        gx, gy = g[0] + g[2] / 2, g[1] + g[3] / 2
        hit = js(wd, "const e=document.elementFromPoint(arguments[0],arguments[1]); return !!(e && e.classList.contains('mresize'))", [gx, gy])
        _pt(wd, [_mv(gx, gy, 0), _DOWN, _mv(gx - 40, gy - 25, 120), _mv(gx - 80, gy - 50, 120), _UP], end=True)
        time.sleep(0.4)
        sz = js(wd, "return window.__editor.miniMap().size")
        css = rect(wd, "#minimap canvas")
        stored = js(wd, "try { return JSON.parse(localStorage.getItem(arguments[0])) } catch(e) { return null }", [SIZE_KEY])
        check("minimap2: corner grip resizes (170x110 -> 250x160), canvas follows, size stored", hit and abs(sz["w"] - 250) <= 2 and abs(sz["h"] - 160) <= 2
              and abs(css[2] - sz["w"]) <= 1 and abs(css[3] - sz["h"]) <= 1 and stored == sz, "%s %s %s %s" % (hit, sz, css, stored))
        check("minimap2: the resize never moved the main view", _nav(wd) == nv_r, "%s %s" % (nv_r, _nav(wd)))
        _open(wd)
        check("minimap2: reload keeps the minimap size", js(wd, "return window.__editor.miniMap().size") == sz, str(js(wd, "return window.__editor.miniMap().size")))
        # ---- collapse / expand
        js(wd, "document.querySelector('#minimap .mtog').click()")
        time.sleep(0.3)
        col = js(wd, "const m=document.querySelector('#minimap'); return [m.classList.contains('open'), getComputedStyle(m.querySelector('canvas')).display, getComputedStyle(m.querySelector('.mresize')).display]")
        js(wd, "document.querySelector('#minimap .mtog').click()")
        time.sleep(0.3)
        check("minimap2: collapses (canvas and grip hidden) and expands again", col == [False, "none", "none"] and js(wd, "return window.__editor.miniMap().open"), str(col))
        # ---- wheel over the minimap zooms the MINIMAP only
        js(wd, "window.__editor.fit()")
        time.sleep(0.5)
        nv0 = _nav(wd)
        r = rect(wd, "#minimap canvas")
        how = wheel(wd, r[0] + r[2] * 0.3, r[1] + r[3] * 0.3, 0, -120)
        wheel(wd, r[0] + r[2] * 0.3, r[1] + r[3] * 0.3, 0, -120)
        mm = js(wd, "return window.__editor.miniMap()")
        check("minimap2: wheel over the minimap zooms the minimap (x%.2f), the main view is unchanged (%s)" % (mm["mz"], how), mm["mz"] > 1.4 and _nav(wd) == nv0, "%s %s" % (_nav(wd), nv0))
        check("minimap2: zoomed in, the minimap scale grew", mm["map"]["s"] > m["s"] * 1.4, "%s vs %s" % (mm["map"]["s"], m["s"]))
        # ---- a drag on the (zoomed) minimap still pans the canvas
        x0, y0 = r[0] + r[2] * 0.3, r[1] + r[3] * 0.6
        _pt(wd, [_mv(x0, y0, 0), _DOWN, _mv(x0 + 30, y0 + 5, 120), _mv(x0 + 60, y0 + 10, 120), _UP], end=True)
        time.sleep(0.4)
        nv1 = _nav(wd)
        check("minimap2: drag on the minimap pans the canvas (zoom kept), minimap zoom kept", abs(nv1["x"] - nv0["x"]) > 20 and nv1["zoom"] == nv0["zoom"]
              and js(wd, "return window.__editor.miniMap().mz") == mm["mz"], "%s -> %s" % (nv0, nv1))
        # ---- follow: the main view moves elsewhere, the zoomed minimap brings it back in view
        js(wd, "window.__editor.focusDomain('systeme')")
        time.sleep(0.6)
        mm = js(wd, "return window.__editor.miniMap()")
        cv = js(wd, "const c=document.querySelector('#minimap canvas'); return [c.width, c.height]")
        v, mp = mm["view"], mm["map"]
        vx, vy = (v["x0"] + v["x1"]) / 2, (v["y0"] + v["y1"]) / 2
        check("minimap2: zoomed minimap follows the main view (its centre stays on the map)", mp["x0"] <= vx <= mp["x0"] + cv[0] / mp["s"] and mp["y0"] <= vy <= mp["y0"] + cv[1] / mp["s"], "%s %s" % (mp, (vx, vy)))
        js(wd, "document.querySelector('#minimap .mzreset').click()")
        time.sleep(0.3)
        check("minimap2: the ×N button resets the minimap to the whole world", js(wd, "return window.__editor.miniMap().mz") == 1
              and js(wd, "return document.querySelector('#minimap .mzreset').hidden"))
        # ---- no layout read per pan / zoom frame (wrapped DOM getters), the minimap redrawn every frame
        js(wd, "window.__editor.fit()")
        time.sleep(0.5)
        p = _perf(wd)
        print("PERF", p)
        check("minimap2: 60 pan / zoom frames, 0 layout reads (geometry cache), minimap redrawn", p and p["reads"] == 0 and p["geo"] == 0 and p["views"] >= 30, str(p))
        js(wd, "const r=document.querySelector('#minimap canvas').getBoundingClientRect(); window.__editor.miniZoomAt(r.x+60, r.y+40, 3)")
        p = _perf(wd)
        print("PERF zoomed", p)
        check("minimap2: same with the minimap zoomed in (follow active): 0 layout reads", p and p["reads"] == 0 and p["geo"] == 0, str(p))
        js(wd, "window.__editor.resetMiniZoom()")
        # ---- node boxes: cached, invalidated on edit
        nid = js(wd, "return window.__editor.serialize().nodes.find(n=>n.kind==='action' && n.group==='veille' && n.params && n.params.action==='log_note').id")
        b0 = js(wd, "return window.__editor.nodeBoxOf(arguments[0])", [nid])
        js(wd, "window.__editor.patchNode(arguments[0], {args: {level: 'info', text: 'S2 ' + 'un texte bien plus long pour agrandir la carte du nœud. '.repeat(6)}})", [nid])
        time.sleep(0.6)
        b1 = js(wd, "return window.__editor.nodeBoxOf(arguments[0])", [nid])
        real = js(wd, "const df=window.__editor.dfMap()[arguments[0]]; const e=document.getElementById('node-'+df); return [e.offsetWidth, e.offsetHeight]", [nid])
        check("minimap2: an edited node's cached box follows its new size", b1 and abs((b1["x1"] - b1["x0"]) - real[0]) <= 1 and abs((b1["y1"] - b1["y0"]) - real[1]) <= 1
              and (b1["y1"] - b1["y0"]) != (b0["y1"] - b0["y0"]), "%s %s %s" % (b0, b1, real))
        _undo(wd, 1)
        # ---- aggregated error dots, moved onto a folded column's card
        js(wd, "window.__editor.fit()")
        time.sleep(0.4)
        acts = js(wd, "return window.__editor.serialize().nodes.filter(n=>n.group==='ecoute' && n.kind==='action').map(n=>n.id).slice(0,4)")
        for a in acts:
            js(wd, "window.__editor.patchNode(arguments[0], {action: 'pas_une_action_s2'})", [a])
        time.sleep(1.5)
        mm = js(wd, "return window.__editor.miniMap()")
        errs = [a for a in (mm["agg"] or []) if a["level"] == "err"]
        n_err = int(js(wd, "return document.querySelector('#minimap').dataset.err"))
        check("minimap2: %d error nodes counted, drawn as %d aggregated dot(s) (fewer dots than nodes)" % (n_err, len(errs)),
              n_err >= len(acts) and sum(a["n"] for a in errs) == n_err and len(errs) < n_err, str(errs)[:300])
        red = js(wd, "const [x,y]=arguments, p=document.querySelector('#minimap canvas').getContext('2d').getImageData(Math.round(x),Math.round(y),1,1).data; return [p[0],p[1],p[2]]",
                 [errs[0]["x"], errs[0]["y"]]) if errs else None   # the count is drawn beside the dot: its centre is pure red
        check("minimap2: the aggregated dot is red on the map", red and red[0] > 200 and red[1] < 110, str(red))
        wd.shot("editor-s2-minimap.png")
        js(wd, "window.__editor.foldColumn('ecoute', true)")
        time.sleep(0.8)
        mm = js(wd, "return window.__editor.miniMap()")
        errs = [a for a in (mm["agg"] or []) if a["level"] == "err" and set(a["nids"]) & set(acts)]
        card = js(wd, "const f=window.__editor.frames().find(x=>x.id==='auto-ecoute'); return [f.x+170, f.y+95]")
        mp = mm["map"]
        check("minimap2: folded column: its errors become ONE dot on its card", len(errs) == 1 and errs[0]["n"] == len(acts)
              and abs(errs[0]["x"] - (card[0] - mp["x0"]) * mp["s"]) <= 9 and abs(errs[0]["y"] - (card[1] - mp["y0"]) * mp["s"]) <= 9, "%s %s %s" % (errs, card, mp))
        _undo(wd, 1 + len(acts))
        time.sleep(0.8)
        check("minimap2: undos restore the clean graph (no error, column unfolded)", js(wd, "return document.querySelector('#minimap').dataset.err") == "0"
              and not js(wd, "return !!(window.__editor.meta().columns.ecoute||{}).folded"))
        check("minimap2: nothing saved, console errors 0", not _writes(wd) and not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors"))[:200])
    finally:
        js(wd, "try { const v=arguments[1]; if (v==null) localStorage.removeItem(arguments[0]); else localStorage.setItem(arguments[0], v); } catch(e) {}", [SIZE_KEY, saved_size])


def sc_foldpack(wd):
    _open(wd)
    r0, p0 = _rects(wd), _positions(wd)
    fr0 = js(wd, "return window.__editor.frames().map(f=>[f.id,f.x,f.y])")
    groups = js(wd, "return Object.fromEntries(window.__editor.serialize().nodes.map(n=>[n.id,n.group]))")
    check("foldpack: shipped regions disjoint", not _disjoint(r0))
    # ---- fold the Dialogue domain: row 2 moves up into the space it gave up
    js(wd, "window.__editor.focusDomain('dialogue')")
    time.sleep(0.5)
    r = rect(wd, '.dregion[data-dom="dialogue"] .dfold')
    lclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
    time.sleep(0.8)
    r1 = _rects(wd)
    check("foldpack: Dialogue folded into its card", r1["dialogue"]["w"] == 520 and r1["dialogue"]["h"] == 250 and js(wd, "return !!window.__editor.meta().domains[0].folded"), str(r1["dialogue"]))
    check("foldpack: the regions below moved up (space reclaimed)", all(r1[d]["y"] < r0[d]["y"] - 1000 for d in ("comportement", "mouvement", "systeme")), str(r1))
    check("foldpack: regions still disjoint after the fold", not _disjoint(r1), str(_disjoint(r1)))
    p1 = _positions(wd)
    gl = [i for i in p0 if groups[i] == "global"][:3]
    check("foldpack: Système nodes moved with their region", gl and all(p1[i][1] - p0[i][1] == r1["systeme"]["y"] - r0["systeme"]["y"]
          and p1[i][0] - p0[i][0] == r1["systeme"]["x"] - r0["systeme"]["x"] for i in gl), str([(p0[i], p1[i]) for i in gl]))
    hid = js(wd, "return window.__editor.foldHidden().nodes")
    tree = js(wd, "return window.__editor.buildTree().kids.find(d=>d.key==='d:systeme').kids.map(k=>[k.key, k.kids ? k.kids.length : 0])")
    check("foldpack: hidden Dialogue nodes stay hidden, Système keeps its own hierarchy", hid == sum(1 for i in p0 if groups[i] and groups[i] != "global")
          and tree and tree[0][0] == "col:auto-global" and tree[0][1] > 0, "%s %s" % (hid, tree))
    check("foldpack: fold is save-gated (modified, nothing written)", js(wd, "return window.__editor.dirtyShown()") and not _writes(wd))
    # ---- unfold: everything back
    r = rect(wd, '.dregion[data-dom="dialogue"] .funfold')
    if r and r[2]:
        lclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
    else:
        js(wd, "window.__editor.foldDomain('dialogue', false)")
    time.sleep(0.8)
    check("foldpack: unfold restores every region and every node position", _rects(wd) == r0 and _positions(wd) == p0
          and js(wd, "return window.__editor.frames().map(f=>[f.id,f.x,f.y])") == fr0)
    _undo(wd, 1)
    check("foldpack: undo = folded again (same packed positions)", _rects(wd) == r1 and _positions(wd) == p1)
    _undo(wd, 1)
    check("foldpack: second undo = the shipped layout", _rects(wd) == r0 and _positions(wd) == p0)
    # ---- fold a column: its row neighbours move left by the width it gave up; unfold puts them back
    fs = {f[0]: f for f in js(wd, "return window.__editor.frames().filter(f=>f.auto).map(f=>[f.id,f.x,f.y,f.w,f.h])")}
    row = lambda c, o: o[0] not in (c[0], "auto-global") and o[1] > c[1] + c[3] - 1 and o[2] < c[2] + c[4] and o[2] + o[4] > c[2]
    col = next(c for c in fs.values() if c[0] != "auto-global" and any(row(c, o) for o in fs.values()))
    right = [o[0] for o in fs.values() if row(col, o)]
    js(wd, "window.__editor.foldColumn(arguments[0], true)", [col[0][5:]])
    time.sleep(0.8)
    fs2 = {f[0]: f for f in js(wd, "return window.__editor.frames().filter(f=>f.auto).map(f=>[f.id,f.x,f.y,f.w,f.h])")}
    dw = col[3] - 340
    check("foldpack: column %s folded: its row neighbours %s moved left by %d" % (col[0], right, dw), right and all(fs2[o][1] == fs[o][1] - dw and fs2[o][2] == fs[o][2] for o in right),
          str([(fs[o], fs2[o]) for o in right]))
    nid = next(i for i in p0 if groups[i] == right[0][5:])
    p2 = _positions(wd)
    check("foldpack: their nodes followed", p2[nid][0] == p0[nid][0] - dw and p2[nid][1] == p0[nid][1], "%s %s" % (p0[nid], p2[nid]))
    r2 = _rects(wd)
    check("foldpack: Dialogue region narrower or equal, regions disjoint", r2["dialogue"]["w"] <= r0["dialogue"]["w"] and not _disjoint(r2), str(r2))
    hn = js(wd, "return window.__editor.foldHidden().nodes")
    gn = sum(1 for i in p0 if groups[i] == col[0][5:])
    kids = js(wd, "const c=window.__editor.buildTree().kids[0].kids.find(k=>k.key==='col:'+arguments[0]); return c ? c.kids.length : -1", [right[0]])
    check("foldpack: exactly the folded column's nodes are hidden; the neighbour keeps its hierarchy", hn == gn and kids > 0, "%s %s %s" % (hn, gn, kids))
    js(wd, "window.__editor.foldColumn(arguments[0], false)", [col[0][5:]])
    time.sleep(0.8)
    check("foldpack: column unfold restores every node position and region", _positions(wd) == p0 and _rects(wd) == r0)
    _undo(wd, 2)
    check("foldpack: two undos = shipped layout", _positions(wd) == p0)
    # ---- a column moved into an empty domain: the domain post-it sits beside it, never under its title
    js(wd, "window.__editor.moveColumnToDomain('eteint', 'mouvement')")
    time.sleep(0.8)
    js(wd, "window.__editor.focusDomain('mouvement')")
    time.sleep(0.6)
    ov = js(wd, """const t=document.querySelector('.frame[data-fid=auto-eteint] .ftitle').getBoundingClientRect(), f=document.querySelector('.frame[data-fid=auto-eteint]').getBoundingClientRect(),
      n=document.querySelector('.postit[data-nid=note-dom-mouvement]').getBoundingClientRect();
      const hit=(a,b)=>a.left<b.right&&b.left<a.right&&a.top<b.bottom&&b.top<a.bottom; return [hit(t,n), hit(f,n), n.width>0]""")
    nt = js(wd, "return window.__editor.notes().find(n=>n.id==='note-dom-mouvement')")
    rm = js(wd, "return window.__editor.domainRect('mouvement')")
    check("foldpack: domain post-it clear of the moved column's title and frame, inside its region", ov == [False, False, True]
          and rm["x"] <= nt["x"] and nt["x"] + nt["w"] <= rm["x"] + rm["w"] and rm["y"] <= nt["y"], "%s %s %s" % (ov, nt, rm))
    check("foldpack: regions disjoint after the move", not _disjoint(_rects(wd)))
    _undo(wd, 1)
    check("foldpack: undo = shipped layout; nothing saved, console errors 0", _positions(wd) == p0 and not _writes(wd)
          and not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors"))[:200])


SCENARIOS = {
    "zoom3": sc_zoom3,
    "minimap2": sc_minimap2,
    "foldpack": sc_foldpack,
}
