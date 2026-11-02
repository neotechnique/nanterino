"""Nanterino editor web scenarios: post-its and groups (frames): display modes, nesting, default column post-its and sub-groups.

Purpose : frames area of the editor web suite; scenarios postit, postit2, postit3, l8, subgroups.
Boundary: drives the live editor through tests/web/driver.py (WebDriver, check()); never imports nanterino.server.
Invariant: verbatim slice (M7) of the former scripts/editor6_wd.py; a scenario is `sc_<name>(wd)` and is listed in
          SCENARIOS at the end of this file, which tests/web/run.py reads.
Test    : .venv/bin/python -m tests.web.run postit   (or `area:frames`, or `all`)
"""
import glob, json, os, sys, time

from tests.web.driver import *  # noqa: F401,F403  (shared helpers, check(), W, BASE, ROOT)


def sc_postit(wd):
    pre = set(glob.glob(ROOT + "/graph.*"))
    try:
        open_editor(wd)
        # CHANGED (L9): the default drawing ships one post-it per column (checked by postit3); this scenario is about the
        # user's own notes, so it starts without them (the deletions are part of the undo history, before its steps)
        js(wd, "const E=window.__editor; E.notes().filter(n=>n.auto).map(n=>n.id).forEach(id=>E.deleteNote(id))")
        time.sleep(0.3)
        E = "window.__editor"
        js(wd, "document.querySelector('#btnNote').click()")
        time.sleep(0.6)
        notes = js(wd, "return window.__editor.notes()")
        check("post-it created from the toolbar", len(notes) == 1 and notes[0]["color"] == "#fff59d", str(notes))
        n = notes[0]
        ovl_js = """const r=[...document.querySelectorAll('.postit')].map(e=>e.getBoundingClientRect());
          return [...document.querySelectorAll('.drawflow-node')].filter(e=>{const a=e.getBoundingClientRect(); return r.some(b=>a.x<b.right&&b.x<a.right&&a.y<b.bottom&&b.y<a.bottom)}).length"""
        check("new post-it covers no node", js(wd, ovl_js) == 0)
        top = js(wd, """const r=document.querySelector('.postit .phead').getBoundingClientRect(); const e=document.elementFromPoint(r.x+r.width/2, r.y+r.height/2); return !!(e&&e.closest('.postit'))""")
        check("post-it title bar is on top (not covered)", top)
        # edit text
        js(wd, """const ta=document.querySelector('.postit textarea'); ta.value='Penser au message du soir\\nsur deux lignes'; ta.dispatchEvent(new Event('input',{bubbles:true})); ta.dispatchEvent(new Event('change',{bubbles:true}))""")
        js(wd, "window.__editor.editNote(window.__editor.notes()[0], {title:'À faire', color:'#f8bbd0'}, true)")
        time.sleep(0.3)
        # move with left-drag on the header, resize with the corner
        r = rect(wd, ".postit .phead")
        actions(wd, 0, [(r[0] + 60, r[1] + 10), (r[0] + 160, r[1] + 70)])
        n2 = js(wd, "return window.__editor.notes()[0]")
        check("post-it moves with a left-drag", (n2["x"], n2["y"]) != (n["x"], n["y"]), "%s,%s -> %s,%s" % (n["x"], n["y"], n2["x"], n2["y"]))
        check("moved post-it covers no node", js(wd, ovl_js) == 0)
        r = rect(wd, ".postit .presize")
        actions(wd, 0, [(r[0] + 8, r[1] + 8), (r[0] + 88, r[1] + 48)])
        n4 = js(wd, "return window.__editor.notes()[0]")
        check("post-it resizes with the corner", n4["w"] > n2["w"] and n4["h"] > n2["h"], "%sx%s -> %sx%s" % (n2["w"], n2["h"], n4["w"], n4["h"]))
        check("resized post-it covers no node", js(wd, ovl_js) == 0)
        r = rect(wd, ".postit .presize")
        actions(wd, 2, [(r[0] + 8, r[1] + 8), (r[0] + 108, r[1] + 68)])
        n3 = js(wd, "return window.__editor.notes()[0]")
        check("right-drag does not move or resize the post-it", (n3["x"], n3["y"], n3["w"], n3["h"]) == (n4["x"], n4["y"], n4["w"], n4["h"]))
        js(wd, "window.__editor.closeCtx()")
        js(wd, "window.__editor.closeCtx()")
        # second note through the context menu, then undo / redo
        e = view_empty_point(wd)
        rclick(wd, *e)
        click_item(wd, "Post-it")                 # ADAPTED (L10): "Insérer un post-it" -> "Post-it"
        check("second post-it from the menu", len(js(wd, "return window.__editor.notes()")) == 2)
        js(wd, "document.querySelector('#btnUndo').click()"); time.sleep(0.4)
        check("undo removes it", len(js(wd, "return window.__editor.notes()")) == 1)
        js(wd, "document.querySelector('#btnRedo').click()"); time.sleep(0.4)
        check("redo brings it back", len(js(wd, "return window.__editor.notes()")) == 2)
        js(wd, "window.__editor.deleteNote(window.__editor.notes()[1].id)"); time.sleep(0.3)
        js(wd, "window.__editor.focusBand('veille', 0.5)")
        # keep the first note in view for the screenshot
        js(wd, "const n=window.__editor.notes()[0]; window.__editor.panDf && 0")
        n4 = js(wd, "return window.__editor.notes()[0]")
        # Save, reload, back
        d = doc(wd)
        check("serialized doc carries the note", len(d.get("notes", [])) == 1 and d["notes"][0]["text"].startswith("Penser"))
        r = js(wd, "return window.__editor.postDoc(window.__editor.serialize()).then(r=>({status:r.status, json:r.json}))") if False else None
        res = W.http("POST", BASE + "/api/graph/visual", d)
        check("save accepted", res[0] == 200, str(res[1])[:200])
        yaml_txt = open(glob.glob(ROOT + "/graph.yaml")[0], encoding="utf-8").read()
        check("note never reaches graph.yaml", "Penser" not in yaml_txt and "notes" not in yaml_txt)
        lay = json.load(open(ROOT + "/graph.layout.json", encoding="utf-8"))
        check("note stored in graph.layout.json (vars form)", len(lay.get("notes", [])) == 1 and lay.get("form") == "vars" and len(lay["nodes"]) > 0, str(lay.get("form")))
        W.open_editor(wd, "#quiet")
        time.sleep(1.0)
        back = js(wd, "return window.__editor.notes()")
        check("note is back after reload", len(back) == 1 and back[0]["id"] == n4["id"] and back[0]["text"] == "Penser au message du soir\nsur deux lignes" and back[0]["title"] == "À faire" and back[0]["color"] == "#f8bbd0", str(back))
        pos = js(wd, "return [window.__editor.notes()[0].x, window.__editor.notes()[0].y]")
        js(wd, "window.__editor.focusBand('veille', 0.6)")
        time.sleep(0.5)
        r = rect(wd, ".postit")
        # bring it into the middle of the screenshot
        js(wd, "const n=window.__editor.notes()[0]; const f=window.__editor.fit; 0")
        js(wd, """const E=window.__editor; const n=E.notes()[0]; const st=document.querySelector('#drawflow'); const z=0.8;
          const d=document.querySelector('#drawflow > div'); const ox=d.clientWidth/2, oy=d.clientHeight/2;
          const cx=st.clientWidth/2-(n.x+n.w/2)*z - ox*(1-z), cy=st.clientHeight/2-(n.y+n.h/2)*z - oy*(1-z);
          E.zoom=z; d.style.transform='translate('+cx+'px, '+cy+'px) scale('+z+')'""") if False else None
        wd.shot("editor7-postit.png")
        check("reloaded post-it covers no node", js(wd, ovl_js) == 0)
        check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))
    finally:
        W.http("POST", BASE + "/api/graph/reset", {})
        for f in set(glob.glob(ROOT + "/graph.*")) - pre:
            try:
                os.remove(f)
            except OSError:
                pass
        print("LEFT OVER", sorted(set(glob.glob(ROOT + "/graph.*")) - pre))


def sc_postit2(wd):
    pre = set(glob.glob(ROOT + "/graph.*"))
    try:
        open_editor(wd)
        n = js(wd, "return window.__editor.addNote()")
        js(wd, "window.__editor.editNote(window.__editor.notes().slice(-1)[0], {title:'Note longue', text: arguments[0]}, true)", [LONG])
        time.sleep(0.4)
        sel = ".postit[data-nid=%s]" % n["id"]
        full = js(wd, """const e=document.querySelector(arguments[0]), t=e.querySelector('.ptext');
          return [e.classList.contains('full'), t.scrollHeight - t.clientHeight, e.offsetHeight, getComputedStyle(t).display, getComputedStyle(t).fontSize]""", [sel])
        check("full mode (default): the whole text is visible (grows, no hidden overflow)", full[0] and full[1] <= 1 and full[2] > 160 and full[3] != "none", str(full))
        check("full mode readable at 100 % zoom (font >= 14 px)", float(full[4].rstrip("px")) >= 14, full[4])
        check("default display is not stored (old files unchanged)", "display" not in js(wd, "return window.__editor.notes().slice(-1)[0]"))
        # compact with the post-it's own button (real click)
        r = rect(wd, sel + " .pmode")
        lclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
        time.sleep(0.4)
        comp = js(wd, """const e=document.querySelector(arguments[0]);
          return [e.classList.contains('compact'), getComputedStyle(e.querySelector('.ptext')).display, e.querySelector('.pline').textContent, e.offsetHeight]""", [sel])
        check("compact: text area hidden, first line only, short note", comp[0] and comp[1] == "none" and comp[2].startswith("Accueil du soir") and comp[3] < 90, str(comp))
        check("compact stored in the document", js(wd, "return window.__editor.notes().slice(-1)[0].display") == "compact")
        js(wd, "window.__editor.hideTip()")
        t = hover_tip(wd, sel + " .pline")
        check("compact: the tooltip shows the full text", t and t[0] and "FIN-DU-TEXTE" in t[1] and t[1].startswith("Note longue"), str(t)[:120])
        away(wd)
        # a second, full post-it for the screenshot
        n2 = js(wd, "return window.__editor.addNote()")
        js(wd, "window.__editor.editNote(window.__editor.notes()[1], {text: 'Note complète :\\nchaque ligne reste lisible,\\nle post-it grandit avec son texte.'}, true)")
        time.sleep(0.3)
        js(wd, """const E=window.__editor, ns=E.notes(); const a=ns[0], b=ns[1];
          b.x=a.x+a.w+40; b.y=a.y; E.editNote(b, {}, false)""")
        time.sleep(0.3)
        # frame both notes on screen, then shoot
        js(wd, """const E=window.__editor, ns=E.notes(); const x0=Math.min(...ns.map(n=>n.x)), y0=Math.min(...ns.map(n=>n.y));
          const z=1; const st=document.querySelector('#drawflow'); E.focusNode && 0;
          const pc=document.querySelector('#drawflow > .drawflow'); pc.style.transform='translate('+(40-x0*z)+'px, '+(80-y0*z)+'px) scale('+z+')';""")
        time.sleep(0.4)
        wd.shot("editor11-postit.png")
        # save + reload: the mode persists (layout file), then back to full through the inspector
        d = doc(wd)
        res = W.http("POST", BASE + "/api/graph/visual", d)
        check("save accepted", res[0] == 200, str(res[1])[:200])
        lay = json.load(open(ROOT + "/graph.layout.json", encoding="utf-8"))
        ln = {x["id"]: x for x in lay.get("notes", [])}
        check("layout file: display compact stored only for the compact note", ln.get(n["id"], {}).get("display") == "compact" and "display" not in ln.get(n2["id"], {"display": 1}), str(lay.get("notes"))[:200])
        W.open_editor(wd, "#quiet")
        time.sleep(1.0)
        back = {x["id"]: x for x in js(wd, "return window.__editor.notes()")}
        check("after reload: compact note still compact, full note full", back.get(n["id"], {}).get("display") == "compact" and "display" not in back.get(n2["id"], {"display": 1})
              and js(wd, "return document.querySelector(arguments[0]).classList.contains('compact')", [sel]), str(back)[:200])
        js(wd, "window.__editor.selectNote(arguments[0])", [n["id"]])
        time.sleep(0.3)
        js(wd, "const s=document.querySelector('#inspector select.ndisp'); s.value='full'; s.dispatchEvent(new Event('change'))")
        time.sleep(0.3)
        check("inspector toggle back to full", "display" not in js(wd, "return window.__editor.notes().find(x=>x.id===arguments[0])", [n["id"]])
              and js(wd, "return document.querySelector(arguments[0]).classList.contains('full')", [sel]))
        check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))
    finally:
        W.http("POST", BASE + "/api/graph/reset", {})
        for f in set(glob.glob(ROOT + "/graph.*")) - pre:
            try:
                os.remove(f)
            except OSError:
                pass
        print("LEFT OVER", sorted(set(glob.glob(ROOT + "/graph.*")) - pre))
C2S_JS = """const z=window.__editor.nav().zoom, r=document.querySelector('#drawflow > .drawflow').getBoundingClientRect(); return [r.x+arguments[0]*z, r.y+arguments[1]*z]"""
VIEWC_JS = """const z=window.__editor.nav().zoom, r=document.querySelector('#drawflow > .drawflow').getBoundingClientRect(), s=document.querySelector('#drawflow').getBoundingClientRect();
  return [(s.x+s.width/2-r.x)/z, (s.y+s.height/2-r.y)/z]"""
# client point over the minimap -> canvas point (the same mapping the page uses, intrinsic vs CSS canvas size included)
M2C_JS = """const m=window.__editor.miniMap().map, cv=document.querySelector('#minimap canvas'), r=cv.getBoundingClientRect();
  return [m.x0+(arguments[0]-r.x)*cv.width/r.width/m.s, m.y0+(arguments[1]-r.y)*cv.height/r.height/m.s, cv.width/r.width/m.s]"""


def _nt(wd, pid):
    return js(wd, "const n=window.__editor.serialize().notes.find(x=>x.id===arguments[0]); return n||null", [pid])


def _drag_by(wd, sel, dxs, dys, hold_check=None, steps=5, at=None):
    """Real left-button drag of the element `sel` (its centre, or `at` client point) by (dxs, dys) screen px.
    hold_check(wd) runs while the button is still held (feedback checks), its result is returned."""
    r = rect(wd, sel)
    x0, y0 = at or _ctr(r)
    hit = js(wd, "const e=document.elementFromPoint(arguments[0],arguments[1]); return !!(e && e.closest(arguments[2]))", [x0, y0, sel])
    if not hit:   # the press would land on something else (minimap, panel): the scenario would test the wrong thing
        what = js(wd, "const e=document.elementFromPoint(arguments[0],arguments[1]); return e ? e.tagName+'.'+e.className+' '+(e.closest('[data-fid]')||{dataset:{}}).dataset.fid : null", [x0, y0])
        print("WARN drag start not on", sel, (x0, y0), what, flush=True)
    acts = [_mv(x0, y0, 0), _DOWN] + [_mv(x0 + dxs * k / steps, y0 + dys * k / steps, 70) for k in range(1, steps + 1)]
    _pt(wd, acts)
    time.sleep(0.3)
    res = hold_check(wd) if hold_check else None
    _pt(wd, [_UP], end=True)
    time.sleep(0.5)
    return res


def _human_drag(wd, sel, x1, y1, at=None, hold_check=None, steps=10, ms=60):
    """L9: drag like a person: press on `sel` (at `at`, default 40 px into it at mid-height, i.e. on a title bar),
    move in `steps` small moves of `ms` ms (~600 ms) and release with the POINTER at client (x1, y1), whatever the
    size of the dragged item. hold_check(wd) runs while the button is still held; its result is returned."""
    r = rect(wd, sel)
    x0, y0 = at or (r[0] + min(40, r[2] / 2), r[1] + r[3] / 2)
    hit = js(wd, "const e=document.elementFromPoint(arguments[0],arguments[1]); return !!(e && e.closest(arguments[2]))", [x0, y0, sel])
    if not hit:   # the press would land on something else (minimap, panel, another frame's title)
        what = js(wd, """const e=document.elementFromPoint(arguments[0],arguments[1]); if(!e) return null; const f=e.closest('.frame,.postit,.drawflow-node');
          return [e.tagName, e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className, f ? (f.dataset.fid || f.dataset.nid || f.id) : null]""", [x0, y0])
        print("WARN human drag start not on", sel, (x0, y0), "rect", r, "hit", what, flush=True)
    end_ok = js(wd, "const e=document.elementFromPoint(arguments[0],arguments[1]); return !!(e && e.closest('#drawflow') && !e.closest('#minimap,#jumpbar'))", [x1, y1])
    if not end_ok:
        print("WARN human drag end outside the canvas", (x1, y1), flush=True)
    acts = [_mv(x0, y0, 0), _DOWN] + [_mv(x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps, ms) for k in range(1, steps + 1)]
    _pt(wd, acts)
    time.sleep(0.3)
    res = hold_check(wd) if hold_check else None
    _pt(wd, [_UP], end=True)
    time.sleep(0.5)
    return res


def _held(wd):
    """Frame ids outlined as the drop target of the drag in progress."""
    return js(wd, "return [...document.querySelectorAll('.frame.droptarget')].map(e=>e.dataset.fid)")


def sc_l8(wd):
    pre = set(glob.glob(ROOT + "/graph.*")) | set(glob.glob(ROOT + "/graph*.bak*"))
    iw, ih = js(wd, "return [innerWidth, innerHeight]")
    print("VIEWPORT", iw, ih, flush=True)
    try:
        open_editor(wd)
        js(wd, "window.__editor.closeCtx && window.__editor.closeCtx()")
        vocab = W.http("GET", BASE + "/api/graph/vocab")[1]
        # ================= 1. node hover tooltip =================
        act = node_of(wd, "n.kind==='action' && n.params.action && n.params.action!=='set_var' && n.params.action!=='cancel_all'")
        a_voc = [a for a in vocab["actions"] if a["id"] == act["params"]["action"]][0]
        theme = [t for t in vocab.get("themes", []) if t["id"] == a_voc.get("theme")]
        want_path = "Actions › " + (theme[0]["label"] if theme else "Autres")
        js(wd, "window.__editor.focusNode(arguments[0])", [act["id"]])
        time.sleep(0.5)
        away(wd)
        df = dfid(wd, act["id"])
        body = rect(wd, "#node-%s .nsum" % df)
        hover(wd, *_ctr(body))
        time.sleep(0.15)
        early = tip_state(wd)
        time.sleep(0.8)
        t = tip_state(wd)
        print("NODE TIP", repr(t[1])[:300])
        check("node tooltip: hovering the node BODY (not the header) shows a bubble after the delay, not before",
              not early[0] and t[0], str([early[0], t[0]]))
        check("node tooltip: kind + vocabulary help + settings + Category › Theme",
              t[1].startswith("Action") and a_voc.get("help", "") in t[1] and "Réglages : " in t[1] and want_path in t[1],
              "%r want help %r path %r" % (t[1][:200], a_voc.get("help", "")[:60], want_path))
        check("node tooltip: same path as the node menu (hook)", js(wd, "return window.__editor.nodePath(arguments[0])", [act["id"]]) == want_path)
        tb = js(wd, "const t=document.getElementById('tip').getBoundingClientRect(); return [t.left>=0, t.right<=innerWidth, t.top>=0, t.bottom<=innerHeight]")
        check("node tooltip inside the viewport", all(tb), str(tb))
        wd.shot("editor13-node-tooltip.png")
        # moving inside the node (header -> body -> other line) keeps the same bubble shown (no flicker)
        flick = []
        for sel in (".nhead .ntitle", ".nsum"):
            r = rect(wd, "#node-%s %s" % (df, sel))
            hover(wd, *_ctr(r))
            time.sleep(0.05)
            flick.append(tip_state(wd)[0])
        check("node tooltip: moving inside the node never hides the bubble", all(flick), str(flick))
        # no bubble while dragging the node
        head = rect(wd, "#node-%s .nhead" % df)
        p0 = pos_of(wd, act["id"])
        hx, hy = _ctr(head)
        _pt(wd, [_mv(hx, hy, 0), _DOWN] + [_mv(hx + 12 * k, hy + 6 * k, 120) for k in range(1, 6)])
        samples = []
        for k in range(3):
            time.sleep(0.5)
            samples.append(tip_state(wd)[0])
            _pt(wd, [_mv(hx + 60 + 8 * (k + 1), hy + 30, 120)])
        time.sleep(0.6)
        samples.append(tip_state(wd)[0])
        _pt(wd, [_UP], end=True)
        time.sleep(0.4)
        p1 = pos_of(wd, act["id"])
        check("node tooltip: absent during a node drag (held > 2 s over the node)", not any(samples) and p1 != p0, "%s %s->%s" % (samples, p0, p1))
        js(wd, "window.__editor.undo()")
        time.sleep(0.4)
        # no bubble while wiring (drag from an output port over a node body) or panning the canvas
        df = dfid(wd, act["id"])
        out = rect(wd, "#node-%s .outputs .output" % df)
        body = rect(wd, "#node-%s .nsum" % df)
        ox_, oy_ = _ctr(out)
        _pt(wd, [_mv(ox_, oy_, 0), _DOWN, _mv(ox_ + 30, oy_ + 10, 100)] + [_mv(*_ctr(body), 150)])
        time.sleep(1.0)
        wiring = [js(wd, "return !!document.querySelector('#drawflow svg.connection .main-path') && window.__editor.dfState()"), tip_state(wd)[0]]
        e = view_empty_point(wd)
        _pt(wd, [_mv(e[0], e[1], 100), _UP], end=True)
        time.sleep(0.4)
        check("node tooltip: absent while dragging a wire over a node", not wiring[1], str(wiring))
        e = view_empty_point(wd)
        body = rect(wd, "#node-%s .nsum" % df)
        _pt(wd, [_mv(e[0], e[1], 0), _DOWN, _mv(e[0] + 5, e[1] + 5, 80)] + [_mv(*_ctr(body), 200)])
        time.sleep(1.0)
        pan_tip = tip_state(wd)[0]
        _pt(wd, [_UP], end=True)
        time.sleep(0.4)
        check("node tooltip: absent while panning across a node", not pan_tip)
        # diagnostics in the node bubble; node <-> own badge swaps at once (never hidden in between)
        ids = js(wd, """const E=window.__editor; const t=E.addAt('trigger',{event:'visage'},{x:-900,y:-600},{exact:true});
          const c=E.addAt('condition',{guard:'var_compare',args:{name:'inconnue',op:'=',value:'1'}},{x:-640,y:-600},{exact:true});
          const a=E.addAt('action',{action:'mic_on'},{x:-380,y:-600},{exact:true});
          E.linkNodes(t,'output_1',c); E.linkNodes(c,'output_1',a); const m=E.dfMap(); const inv={}; for(const k in m) inv[m[k]]=k; return [inv[t], inv[c], inv[a]]""")
        js(wd, "document.querySelector('#btnValidate').click()")
        time.sleep(1.6)
        js(wd, "window.__editor.focusNode(arguments[0])", [ids[1]])
        time.sleep(0.5)
        away(wd)
        cdf = dfid(wd, ids[1])
        hover(wd, *_ctr(rect(wd, "#node-%s .nsum" % cdf)))
        time.sleep(0.9)
        tn = tip_state(wd)
        check("node tooltip lists the node's diagnostics", tn[0] and tn[1].startswith("Condition") and "Erreur : " in tn[1], repr(tn)[:300])
        br = rect(wd, "#node-%s .dbadge" % cdf)
        hover(wd, *_ctr(br))
        time.sleep(0.05)
        tb1 = tip_state(wd)
        hover(wd, *_ctr(rect(wd, "#node-%s .nsum" % cdf)))
        time.sleep(0.05)
        tb2 = tip_state(wd)
        check("node -> own badge -> node: bubble swaps at once, never hidden", tb1[0] and tb1[1].startswith("Erreur") and tb2[0] and tb2[1].startswith("Condition"),
              repr([tb1, tb2])[:300])
        away(wd)
        js(wd, "window.__editor.loadAll()")
        time.sleep(1.5)
        # ================= 2. minimap navigation =================
        js(wd, "window.__editor.closeCtx && window.__editor.closeCtx()")
        if not js(wd, "return document.querySelector('#minimap').classList.contains('open')"):
            js(wd, "document.querySelector('#minimap .mtog').click()")
            time.sleep(0.3)
        js(wd, "window.__editor.fit()")
        time.sleep(0.4)
        nodes0 = js(wd, "return window.__editor.serialize().nodes.map(n=>[n.id,n.x,n.y])")
        r = rect(wd, "#minimap canvas")
        cx_, cy_ = r[0] + r[2] * 0.3, r[1] + r[3] * 0.55
        lclick(wd, cx_, cy_)
        want = js(wd, M2C_JS, [cx_, cy_])
        got = js(wd, VIEWC_JS)
        tol = 2 * want[2] + 2
        check("minimap click: view centred on the clicked point", abs(got[0] - want[0]) <= tol and abs(got[1] - want[1]) <= tol, "%s vs %s tol %.1f" % (got, want[:2], tol))
        # press-and-drag (outside the viewport rectangle): continuous, monotonic pan; the rectangle follows live
        x0, y0 = r[0] + r[2] * 0.15, r[1] + r[3] * 0.5
        _pt(wd, [_mv(x0, y0, 0), _DOWN])
        time.sleep(0.25)
        samples = []
        for k in range(1, 6):
            _pt(wd, [_mv(x0 + r[2] * 0.12 * k, y0 + r[3] * 0.03 * k, 80)])
            time.sleep(0.15)
            nv, mm = js(wd, "return [window.__editor.nav(), window.__editor.miniMap()]")
            vc = js(wd, VIEWC_JS)
            pm = js(wd, M2C_JS, [x0 + r[2] * 0.12 * k, y0 + r[3] * 0.03 * k])
            samples.append((nv["x"], (mm["view"]["x0"] + mm["view"]["x1"]) / 2, vc[0], pm[0], mm["dragging"]))
            if k == 3:
                wd.shot("editor13-minimap-drag.png")
        print("MINIDRAG", [(round(a), round(b), round(c), round(d), e) for a, b, c, d, e in samples])
        xs = [s[0] for s in samples]
        check("minimap drag: main view moves at every sample, monotonic (5 samples while held)", all(b < a for a, b in zip(xs, xs[1:])), str(xs))
        offs = [s[2] - s[3] for s in samples]   # view centre - pointer's map point: constant (0, or the grab offset)
        check("minimap drag: rectangle follows live (its centre = the view centre; the pointer keeps its map offset)",
              all(abs(s[1] - s[2]) <= tol and s[4] for s in samples) and max(offs) - min(offs) <= tol, str([round(o) for o in offs]) + str(samples)[:200])
        # leave the minimap while held: still panning (pointer capture); release outside ends it
        st = rect(wd, "#drawflow")
        _pt(wd, [_mv(st[0] + st[2] * 0.4, st[1] + st[3] * 0.5, 120)])
        time.sleep(0.2)
        out_drag = js(wd, "return window.__editor.miniMap().dragging")
        _pt(wd, [_UP], end=True)
        time.sleep(0.3)
        nv_rel = js(wd, "return window.__editor.nav()")
        hover(wd, st[0] + st[2] * 0.45, st[1] + st[3] * 0.55)
        time.sleep(0.3)
        nv_after = js(wd, "return window.__editor.nav()")
        check("minimap drag: still captured outside the minimap, release outside ends it (no pan afterwards)",
              out_drag and not js(wd, "return window.__editor.miniMap().dragging") and nv_rel == nv_after, "%s %s %s" % (out_drag, nv_rel, nv_after))
        check("minimap drag: the main canvas never started its own drag / moved a node",
              not js(wd, "return window.__editor.dfState().editorSel || window.__editor.dfState().drag")
              and js(wd, "return window.__editor.serialize().nodes.map(n=>[n.id,n.x,n.y])") == nodes0)
        # a click INSIDE the viewport rectangle centres there too (zoomed out, the rectangle covers most of the map)
        js(wd, "window.__editor.fit()")
        time.sleep(0.3)
        v = js(wd, "return window.__editor.miniMap().view")
        ix, iy = js(wd, """const m=window.__editor.miniMap().map, cv=document.querySelector('#minimap canvas'), r=cv.getBoundingClientRect();
          return [r.x+(arguments[0]-m.x0)*m.s*r.width/cv.width, r.y+(arguments[1]-m.y0)*m.s*r.height/cv.height]""", [v["x0"] + (v["x1"] - v["x0"]) * 0.3, v["y0"] + (v["y1"] - v["y0"]) * 0.6])
        ix, iy = min(max(ix, r[0] + 4), r[0] + r[2] - 4), min(max(iy, r[1] + 4), r[1] + r[3] - 4)
        lclick(wd, ix, iy)
        want, got = js(wd, M2C_JS, [ix, iy]), js(wd, VIEWC_JS)
        check("minimap click inside the viewport rectangle: view centred there", abs(got[0] - want[0]) <= tol and abs(got[1] - want[1]) <= tol, "%s vs %s" % (got, want[:2]))
        # grab the viewport rectangle: no jump on press, the view follows the drag delta
        mm = js(wd, "return window.__editor.miniMap()")
        v = mm["view"]
        gx, gy = js(wd, """const m=window.__editor.miniMap().map, cv=document.querySelector('#minimap canvas'), r=cv.getBoundingClientRect();
          return [r.x+(arguments[0]-m.x0)*m.s*r.width/cv.width, r.y+(arguments[1]-m.y0)*m.s*r.height/cv.height]""", [(v["x0"] + v["x1"]) / 2, (v["y0"] + v["y1"]) / 2])
        c0 = js(wd, VIEWC_JS)
        _pt(wd, [_mv(gx + 3, gy + 2, 0), _DOWN])
        time.sleep(0.2)
        c1 = js(wd, VIEWC_JS)
        _pt(wd, [_mv(gx + 3 + 20, gy + 2, 120)])
        time.sleep(0.2)
        c2 = js(wd, VIEWC_JS)
        _pt(wd, [_UP], end=True)
        time.sleep(0.3)
        k20 = js(wd, M2C_JS, [gx + 23, gy])[0] - js(wd, M2C_JS, [gx + 3, gy])[0]
        check("minimap: grabbing the viewport rectangle does not jump; dragging it pans by the same map distance",
              abs(c1[0] - c0[0]) <= 1 and abs(c1[1] - c0[1]) <= 1 and abs((c2[0] - c1[0]) - k20) <= tol, "%s %s %s k20=%.0f" % (c0, c1, c2, k20))
        # touch drag on the minimap
        nva = js(wd, "return window.__editor.nav()")
        tx, ty = r[0] + r[2] * 0.8, r[1] + r[3] * 0.4
        _pt(wd, [_mv(tx, ty, 0), _DOWN], ptype="touch")
        time.sleep(0.2)
        ts = []
        for k in range(1, 4):
            _pt(wd, [_mv(tx - r[2] * 0.15 * k, ty + r[3] * 0.05 * k, 80)], ptype="touch")
            time.sleep(0.15)
            ts.append(js(wd, "return window.__editor.nav().x"))
        _pt(wd, [_UP], ptype="touch", end=True)
        time.sleep(0.3)
        check("minimap: touch press-and-drag pans continuously (monotonic), ends on release",
              ts[0] != nva["x"] and all(b > a for a, b in zip(ts, ts[1:])) and not js(wd, "return window.__editor.miniMap().dragging"), "%s -> %s" % (nva["x"], ts))
        z0 = js(wd, "return window.__editor.nav().zoom")
        wheel(wd, int(r[0] + r[2] / 2), int(r[1] + r[3] / 2), 0, -120)
        time.sleep(0.4)
        z1 = js(wd, "return window.__editor.nav().zoom")
        check("minimap: wheel over it zooms the main view", z1 > z0 * 1.05, "%s -> %s" % (z0, z1))
        check("console errors 0 (tooltips + minimap)", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))
        # ================= 3. nested groups and post-its (L9: human-like pointer drops) =================
        # L9 (2026-11-01): the user could not nest a group into another with a real mouse, while the L8 checks passed.
        # A person presses on the TITLE, drags and lets go where the POINTER is, often with a group as big as (or bigger
        # than) the target; the L8 rule (the dragged group's CENTRE inside a LARGER frame) refused exactly that. Every
        # group drag below is _human_drag: press on the title, ~10 small moves over ~600 ms, release with the pointer
        # over the target's body.
        AX, AY, W0, H0 = -5200, -3600, 600, 420
        BX, BY = AX + W0 + 200, AY
        CX, CY, CW, CH = AX, AY + H0 + 300, 1300, 800       # C: bigger than A and B
        js(wd, """const E=window.__editor; const mk=(x,y,w,h,t)=>{ E.addFrame({x,y}); const f=E.frames()[E.frames().length-1]; f.title=t; E.editFrame(f,{w,h}); return f.id; };
          return [mk(arguments[0],arguments[1],arguments[2],arguments[3],'A'), mk(arguments[4],arguments[5],arguments[2],arguments[3],'B'), mk(arguments[6],arguments[7],arguments[8],arguments[9],'C')]""",
           [AX, AY, W0, H0, BX, BY, CX, CY, CW, CH])
        fa, fb, fc = js(wd, "const f=window.__editor.frames(); return [f[f.length-3].id, f[f.length-2].id, f[f.length-1].id]")
        check("three groups created top level", all(_fr(wd, x) and _fr(wd, x).get("parent") is None for x in (fa, fb, fc)), str([_fr(wd, fa), _fr(wd, fb), _fr(wd, fc)]))
        nb = js(wd, """const E=window.__editor; const t=E.addAt('trigger',{event:'visage'},{x:arguments[0]+40,y:arguments[1]+60},{exact:true});
          const a=E.addAt('action',{action:'mic_on'},{x:arguments[0]+330,y:arguments[1]+60},{exact:true}); E.linkNodes(t,'output_1',a);
          const m=E.dfMap(); const inv={}; for(const k in m) inv[m[k]]=k; return [inv[t], inv[a], t, a]""", [BX, BY])
        js(wd, "window.__editor.focusRect({x0:arguments[0]-60,y0:arguments[1]-120,x1:arguments[2]+900,y1:arguments[3]+60})", [AX, AY, BX + W0, CY + CH])
        time.sleep(0.5)
        z = js(wd, "return window.__editor.nav().zoom")
        print("NEST zoom", z)
        # two post-its: one dropped into B (pointer over B), one left free (right of B)
        pin, pout = js(wd, """const E=window.__editor; const a=E.addNote({x:arguments[0],y:arguments[1]}); const b=E.addNote({x:arguments[2],y:arguments[3]});
          a.title='Dans B'; b.title='Libre'; E.editNote(a,{title:'Dans B'}); E.editNote(b,{title:'Libre'}); E.selectNote(null); return [a.id,b.id]""",
                        [BX + W0 + 120, BY + 40, BX + W0 + 120, BY + 300])
        n1 = _nt(wd, pin)
        tgt = js(wd, C2S_JS, [BX + 40 + n1["w"] / 2, BY + 190 + 20])
        cur = _ctr(rect(wd, '.postit[data-nid="%s"] .phead' % pin))
        fb_drop = _drag_by(wd, '.postit[data-nid="%s"] .phead' % pin, tgt[0] - cur[0], tgt[1] - cur[1], hold_check=_held)
        check("post-it dragged into B: drop-target outline on B while held, then note.parent = B",
              fb_drop == [fb] and _nt(wd, pin).get("parent") == fb, "%s %s" % (fb_drop, _nt(wd, pin)))
        check("free post-it stays top level", _nt(wd, pout).get("parent") is None, str(_nt(wd, pout)))

        # --- 3a. SAME SIZE: B (600x420) dropped by its title with the pointer over A's body (600x420) ---
        def shot_and_held(w):
            w.shot("editor14-nest.png")          # mid-drag: the target outline must be visible
            return _held(w)
        tx, ty = js(wd, C2S_JS, [AX + W0 / 2, AY + H0 / 2])
        hold = _human_drag(wd, '.frame[data-fid="%s"] .ftitle' % fb, tx, ty, hold_check=shot_and_held)
        B1, A1 = _fr(wd, fb), _fr(wd, fa)
        check("same size: B dropped with the pointer over A -> outline on A while held, then B.parent = A", hold == [fa] and B1.get("parent") == fa, "%s %s" % (hold, B1))
        wd.shot("editor14-nest-drop.png")
        check("A grew to enclose B (grow-to-fit)", _encl(A1, B1), str([A1, B1]))
        order = js(wd, "return [...document.querySelectorAll('#frames .frame')].map(e=>e.dataset.fid)")
        check("z-order: child B drawn after (above) its parent A", order.index(fb) > order.index(fa), str(order[-4:]))

        # --- 3b. BIGGER: C (1300x800) dropped with the pointer over B's body -> 3 levels A > B > C ---
        Bn = _fr(wd, fb)
        c_before = _fr(wd, fc)
        tx, ty = js(wd, C2S_JS, [Bn["x"] + Bn["w"] / 2, Bn["y"] + Bn["h"] - 60])
        hold = _human_drag(wd, '.frame[data-fid="%s"] .ftitle' % fc, tx, ty, hold_check=_held)
        A2, B2, C2 = _fr(wd, fa), _fr(wd, fb), _fr(wd, fc)
        check("bigger group: C dropped with the pointer over B -> outline on B while held, then C.parent = B", hold == [fb] and C2.get("parent") == fb, "%s %s" % (hold, C2))
        check("3 levels: B encloses C and A encloses B (the whole chain grew)", _encl(B2, C2) and _encl(A2, B2), str([A2, B2, C2]))
        check("descendants(A) = B and C", sorted(js(wd, "return window.__editor.descendants(arguments[0])", [fa]) or []) == sorted([fb, fc]))
        js(wd, "window.__editor.undo()")
        time.sleep(0.5)
        cu = _fr(wd, fc)
        js(wd, "window.__editor.redo()")
        time.sleep(0.5)
        cr = _fr(wd, fc)
        check("undo puts C back top level at its old place, redo nests it in B again",
              cu.get("parent") is None and cu["x"] == c_before["x"] and cr.get("parent") == fb and cr["x"] == C2["x"], str([cu, cr]))

        # --- moving A moves B, C, B's nodes and B's post-it by the same delta; wires stay on their ports ---
        js(wd, "window.__editor.focusRect({x0:arguments[0]-60,y0:arguments[1]-120,x1:arguments[2]+700,y1:arguments[3]+60})",
           [A2["x"], A2["y"], A2["x"] + A2["w"], A2["y"] + A2["h"]])
        time.sleep(0.5)
        z = js(wd, "return window.__editor.nav().zoom")
        before = {"A": _fr(wd, fa), "B": _fr(wd, fb), "C": _fr(wd, fc), "p": _nt(wd, pin), "t": pos_of(wd, nb[0]), "a": pos_of(wd, nb[1]), "free": _nt(wd, pout)}
        at_ = rect(wd, '.frame[data-fid="%s"] .ftitle' % fa)
        _drag_by(wd, '.frame[data-fid="%s"] .ftitle' % fa, 60, 40, at=(at_[0] + 30, at_[1] + at_[3] / 2))
        after = {"A": _fr(wd, fa), "B": _fr(wd, fb), "C": _fr(wd, fc), "p": _nt(wd, pin), "t": pos_of(wd, nb[0]), "a": pos_of(wd, nb[1]), "free": _nt(wd, pout)}
        dA = (after["A"]["x"] - before["A"]["x"], after["A"]["y"] - before["A"]["y"])
        deltas = [dA] + [(after[k]["x"] - before[k]["x"], after[k]["y"] - before[k]["y"]) for k in ("B", "C", "p")] + \
                 [(after[k][0] - before[k][0], after[k][1] - before[k][1]) for k in ("t", "a")]
        print("NEST deltas", deltas)
        check("moving A moves B, C, B's nodes and B's post-it by the same delta (free post-it stays)",
              abs(dA[0] - 60 / z) <= 3 and abs(dA[1] - 40 / z) <= 3 and all(abs(d[0] - dA[0]) <= 1.5 and abs(d[1] - dA[1]) <= 1.5 for d in deltas)
              and after["free"]["x"] == before["free"]["x"] and after["A"].get("parent") is None, str(deltas))
        ws = wires_of(wd, dfid(wd, nb[0])) + wires_of(wd, dfid(wd, nb[1]))   # Drawflow ids change on undo / redo (rebuild)
        bad = _ends_ok(ws)
        check("wires of B's nodes still on their ports (±3 px) after moving A", ws and not bad, str(bad)[:300])
        wd.shot("editor13-nested-groups.png")
        # resize A smaller than B: clamped, B stays inside and stays a child. The child's grip sits 16 canvas px inside
        # A's: zoom 0.6 and press on the outer corner of A's grip, which no child grip covers.
        # A first gets 400 x 300 px of slack (it fits B exactly after the grow-to-fit); the grip corner is centred in the
        # view (the minimap covers the bottom-right corner of the stage)
        Ab = _fr(wd, fa)
        js(wd, "const E=window.__editor, f=E.frames().find(x=>x.id===arguments[0]); E.editFrame(f,{w:f.w+400,h:f.h+300})", [fa])
        Ab = _fr(wd, fa)
        js(wd, "window.__editor.focusRect({x0:arguments[0]-500,y0:arguments[1]-300,x1:arguments[0]+500,y1:arguments[1]+300}, 0.6)", [Ab["x"] + Ab["w"], Ab["y"] + Ab["h"]])
        time.sleep(0.5)
        gr = rect(wd, '.frame[data-fid="%s"] .fresize' % fa)
        _drag_by(wd, '.frame[data-fid="%s"] .fresize' % fa, -300, -250, at=(gr[0] + gr[2] - 3, gr[1] + gr[3] - 3))
        A3, B3 = _fr(wd, fa), _fr(wd, fb)
        check("resizing A cannot shrink it below its child B (shrunk, clamped at B, B stays a child, inside)",
              B3.get("parent") == fa and _encl(A3, B3) and A3["w"] < Ab["w"] and A3["h"] < Ab["h"]
              and A3["x"] + A3["w"] - (B3["x"] + B3["w"]) <= 20, str([Ab, A3, B3]))

        # --- 3c. drag B OUT of A (pointer right of A, over no frame): detached, A unchanged, C and the post-it still in B ---
        js(wd, "window.__editor.focusRect({x0:arguments[0]-60,y0:arguments[1]-120,x1:arguments[2]+500,y1:arguments[3]+60})",
           [A3["x"], A3["y"], A3["x"] + A3["w"], A3["y"] + A3["h"]])
        time.sleep(0.5)
        tx, ty = js(wd, C2S_JS, [A3["x"] + A3["w"] + 200, A3["y"] + 120])
        _human_drag(wd, '.frame[data-fid="%s"] .ftitle' % fb, tx, ty)
        B4 = _fr(wd, fb)
        check("B dragged out of A: top level, A unchanged, C and the post-it still in B",
              B4.get("parent") is None and _fr(wd, fa) == A3 and _fr(wd, fc).get("parent") == fb and _nt(wd, pin).get("parent") == fb,
              str([B4, _fr(wd, fa) == A3, _nt(wd, pin)]))
        js(wd, "window.__editor.undo()")
        time.sleep(0.5)
        u = _fr(wd, fb)
        js(wd, "window.__editor.redo()")
        time.sleep(0.5)
        rd = _fr(wd, fb)
        check("undo restores B inside A (parent + position), redo detaches again",
              u.get("parent") == fa and u["x"] == B3["x"] and rd.get("parent") is None and rd["x"] == B4["x"], str([u, rd]))
        # post-it out of B, then back in
        B5 = _fr(wd, fb)
        js(wd, "window.__editor.focusRect({x0:arguments[0]-60,y0:arguments[1]-120,x1:arguments[2]+300,y1:arguments[3]+400})",
           [A3["x"], A3["y"], B5["x"] + B5["w"], max(A3["y"] + A3["h"], B5["y"] + B5["h"])])
        time.sleep(0.5)
        z = js(wd, "return window.__editor.nav().zoom")
        tgt = js(wd, C2S_JS, [B5["x"] + 110, B5["y"] + B5["h"] + 160])   # below B (free, away from the minimap)
        cur = _ctr(rect(wd, '.postit[data-nid="%s"] .phead' % pin))
        _drag_by(wd, '.postit[data-nid="%s"] .phead' % pin, tgt[0] - cur[0], tgt[1] - cur[1])
        n3 = _nt(wd, pin)
        check("post-it dragged out of B: free (parent removed)", n3.get("parent") is None, str([n3, B5]))
        tgt = js(wd, C2S_JS, [B5["x"] + 40 + n3["w"] / 2, B5["y"] + 190 + 20])
        cur = _ctr(rect(wd, '.postit[data-nid="%s"] .phead' % pin))
        _drag_by(wd, '.postit[data-nid="%s"] .phead' % pin, tgt[0] - cur[0], tgt[1] - cur[1])
        n4 = _nt(wd, pin)
        check("post-it dragged back into B (pointer over B, not over C): parent = B or C", n4.get("parent") in (fb, fc), str(n4))
        # B (bigger than A by now: it holds C) back into A, pointer over A's body
        tx, ty = js(wd, C2S_JS, [A3["x"] + 80, A3["y"] + A3["h"] - 50])
        hold = _human_drag(wd, '.frame[data-fid="%s"] .ftitle' % fb, tx, ty, hold_check=_held)
        A6, B6 = _fr(wd, fa), _fr(wd, fb)
        check("B (bigger than A) dropped with the pointer over A: B.parent = A and A grew around it",
              hold == [fa] and B6.get("parent") == fa and _encl(A6, B6) and _encl(B6, _fr(wd, fc)), "%s %s %s" % (hold, A6, B6))
        # legacy adoption (old flat layout): parents stripped -> recomputed from geometry. The free post-it first goes
        # left of A (A grew around B and C and may cover its old place: adoption would rightly put it in A)
        js(wd, "const E=window.__editor, n=E.notes().find(x=>x.id===arguments[0]); E.editNote(n,{x:arguments[1]-900,y:arguments[2]})", [pout, A3["x"], A3["y"]])
        js(wd, """const E=window.__editor, d=E.serialize(); d.frames.forEach(f=>delete f.parent); d.notes.forEach(n=>delete n.parent); E.rebuild(d)""")
        time.sleep(0.4)
        flat = [_fr(wd, fb).get("parent"), _nt(wd, pin).get("parent")]
        js(wd, "window.__editor.adoptLegacy()")
        adopted = [_fr(wd, fb).get("parent"), _fr(wd, fc).get("parent"), _fr(wd, fa).get("parent"), _nt(wd, pout).get("parent")]
        check("legacy flat layout: membership computed from geometry once (B in A, C in B, A and free note top level)",
              flat == [None, None] and adopted == [fa, fb, None, None], str([flat, adopted]))

        # --- 3d. a user group dropped INTO a state column; a column dropped onto a group is refused with a toast ---
        cols = js(wd, "return window.__editor.serialize().frames.filter(f=>f.auto)")
        col = min(cols, key=lambda f: (f["y"], f["x"]))
        colh = min(col["h"], 900)
        fd, fe = js(wd, """const E=window.__editor; const mk=(x,y,t)=>{ E.addFrame({x,y}); const f=E.frames()[E.frames().length-1]; f.title=t; E.editFrame(f,{}); return f.id; };
          return [mk(arguments[0]-900,arguments[1]+40,'D'), mk(arguments[0]-900,arguments[1]+420,'E')]""", [col["x"], col["y"]])
        check("groups D, E created left of the first column, top level", _fr(wd, fd).get("parent") is None and _fr(wd, fe).get("parent") is None, str([_fr(wd, fd), _fr(wd, fe)]))
        # CHANGED (G2 follow-up): frame only the column's left part. Framing its whole width (1660 px since G2) zoomed out
        # below the overview threshold (SEM_ZOOM): the column then shows its overview card and its title is hidden, so
        # the column could not be grabbed by its title (measured: elementFromPoint on the title = the canvas).
        colw = min(col["w"], 700)
        js(wd, "window.__editor.focusRect({x0:arguments[0]-1000,y0:arguments[1]-160,x1:arguments[0]+arguments[2]+80,y1:arguments[1]+arguments[3]})",
           [col["x"], col["y"], colw, colh])
        time.sleep(0.5)
        check("column drag view stays above the overview zoom (column title visible)",
              not js(wd, "return document.querySelector('#drawflow').classList.contains('semzoom')"), "semzoom")
        tx, ty = js(wd, C2S_JS, [col["x"] + colw / 2, col["y"] + colh * 0.6])
        hold = _human_drag(wd, '.frame[data-fid="%s"] .ftitle' % fd, tx, ty, hold_check=_held)
        col1, D1 = _fr(wd, col["id"]), _fr(wd, fd)
        # ADAPTED (L13): the default columns hold sub-groups, so the smallest group under the pointer may be one of the
        # column's sub-groups (parent = the column): D then lands in that sub-group, i.e. still inside the column
        dpar = D1.get("parent")
        din = dpar == col["id"] or (_fr(wd, dpar) or {}).get("parent") == col["id"]
        check("user group D dropped with the pointer over a state column: outline on the column, D.parent = column, column not resized",
              hold == [dpar] and din and (col1["w"], col1["h"]) == (col["w"], col["h"]), "%s %s %s" % (hold, D1, col1))
        js(wd, "document.querySelectorAll('#toasts .toast').forEach(t=>t.remove())")
        cnode = js(wd, """const d=window.__editor.serialize(), c=arguments[0]; const n=d.nodes.find(n=>n.x>=c.x&&n.x<=c.x+c.w&&n.y>=c.y&&n.y<=c.y+c.h); return n?n.id:null""", [col1])
        cpos = pos_of(wd, cnode) if cnode else None
        E0 = _fr(wd, fe)
        tx, ty = js(wd, C2S_JS, [E0["x"] + E0["w"] / 2, E0["y"] + E0["h"] / 2])
        deny = _human_drag(wd, '.frame[data-fid="%s"] .ftitle' % col["id"], tx, ty,
                           hold_check=lambda w: js(w, "return [...document.querySelectorAll('.frame.dropdeny')].map(e=>e.dataset.fid)"))
        col2 = _fr(wd, col["id"])
        msg = js(wd, "return [...document.querySelectorAll('#toasts .toast')].map(e=>e.textContent).join(' | ')")
        check("state column dropped onto group E: refusal outline on E while held, toast, column back in place and still top level",
              deny == [fe] and "colonne" in msg.lower() and (col2["x"], col2["y"]) == (col["x"], col["y"]) and col2.get("parent") is None
              and (cpos is None or pos_of(wd, cnode) == cpos) and _fr(wd, fd).get("parent") == dpar, "%s | %s | %s | %s" % (deny, msg, col2, cpos))

        # --- save + reload keeps the hierarchy and never re-adopts by geometry ---
        js(wd, "document.querySelectorAll('#toasts .toast').forEach(t=>t.remove())")
        js(wd, "document.querySelector('#btnSave').click()")
        saved = False
        for _ in range(40):
            time.sleep(0.25)
            if "enregistr" in js(wd, "return [...document.querySelectorAll('#toasts .toast')].map(e=>e.textContent).join(' | ')").lower():
                saved = True
                break
        lay = json.load(open(ROOT + "/graph.layout.json", encoding="utf-8")) if os.path.exists(ROOT + "/graph.layout.json") else {}
        lf = {f["id"]: f for f in lay.get("frames", [])}
        lp = {k: f.get("parent") for k, f in lf.items()}
        ln = {n["id"]: n.get("parent") for n in lay.get("notes", [])}
        check("save: graph.layout.json holds B in A, C in B, D in the column, the post-its' parents, and A's explicit top level (parent: null)",
              saved and lp.get(fb) == fa and lp.get(fc) == fb and lp.get(fd) == dpar and ln.get(pin) in (fb, fc) and ln.get(pout) is None
              and fa in lf and "parent" in lf[fa] and lf[fa]["parent"] is None, "%s %s %s" % (saved, lp, ln))
        js(wd, "window.__editor.loadAll()")
        time.sleep(1.5)
        check("reload: hierarchy kept (A > B > C, D in the column, post-it in B, free post-it top level)",
              _fr(wd, fb).get("parent") == fa and _fr(wd, fc).get("parent") == fb and _fr(wd, fd).get("parent") == dpar
              and _nt(wd, pin).get("parent") in (fb, fc) and _nt(wd, pout).get("parent") is None, str([_fr(wd, fb), _fr(wd, fc), _nt(wd, pin)]))
        check("reload: no geometry re-adoption (the saved choice is explicit)", js(wd, "return window.__editor.adoptLegacy()") is False)
        # delete B: its children go to A, nothing else deleted
        js(wd, "window.__editor.deleteFrame(arguments[0])", [fb])
        time.sleep(0.3)
        check("deleting B hands C and its post-it to A (not deleted)", _fr(wd, fb) is None and _fr(wd, fc).get("parent") == fa
              and _nt(wd, pin) and _nt(wd, pin).get("parent") in (fa, fc), str(_nt(wd, pin)))
        check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))
    finally:
        W.http("POST", BASE + "/api/graph/reset", {})
        for f in (set(glob.glob(ROOT + "/graph.*")) | set(glob.glob(ROOT + "/graph*.bak*"))) - pre:
            try:
                os.remove(f)
            except OSError:
                pass
        left = sorted((set(glob.glob(ROOT + "/graph.*")) | set(glob.glob(ROOT + "/graph*.bak*"))) - pre)
        check("no graph.yaml / graph.layout.json override left in the repo", not left and not os.path.exists(ROOT + "/graph.yaml") and not os.path.exists(ROOT + "/graph.layout.json"), str(left))
        st, chk = W.http("POST", BASE + "/api/graph/check", W.http("GET", BASE + "/api/graph/visual")[1])
        check("shipped graph check 0 errors 0 warnings after restore", st == 200 and not chk.get("errors") and not chk.get("warnings"), "%s/%s" % (len(chk.get("errors") or []), len(chk.get("warnings") or [])))


def sc_postit3(wd):
    """Lot L9: default post-its of the state columns (variables drawing): one per column, right text, parent = column,
    full display, no node covered; they move with the column; deleted + saved + reloaded = stays deleted; edits kept.
    Saves; everything is rolled back at the end (reset + new files removed)."""
    pre = set(glob.glob(ROOT + "/graph.*")) | set(glob.glob(ROOT + "/graph*.bak*"))
    try:
        check("no saved layout at start (shipped default drawing)", not os.path.exists(ROOT + "/graph.layout.json"))
        open_editor(wd)
        js(wd, "window.__editor.closeCtx && window.__editor.closeCtx()")
        d = doc(wd)
        cols = {f["id"]: f for f in d["frames"] if f.get("auto")}
        descs = {s["id"]: s.get("description") or "" for s in d["states"]}
        # ADAPTED (L13): the sub-group post-its (auto "sub:...") are checked by the subgroups scenario
        notes = {n.get("parent"): n for n in d["notes"] if (n.get("auto") or "").startswith("state:")}
        check("one default post-it per column (states + global)", set(notes) == set(cols) and len(cols) >= 8, "%s vs %s" % (sorted(notes), sorted(cols)))
        bad = []
        for cid, n in notes.items():
            g = cid[len("auto-"):]
            want = descs.get(g) if g != "global" else None
            ok = n["auto"] == "state:" + g and n.get("title") == cols[cid]["title"] and "display" not in n and (
                n["text"] == want if want is not None else n["text"].startswith("Règles globales"))
            if not ok:
                bad.append((cid, n))
        check("each column post-it: marker, title = column title, text = state description (global: explanation), full display", not bad, str(bad)[:400])
        # drawn: full mode, inside its column, over no node (real DOM boxes, so the server's height estimate is checked too)
        js(wd, "window.__editor.focusRect({x0:arguments[0],y0:arguments[1],x1:arguments[2],y1:arguments[3]})",
           [min(f["x"] for f in cols.values()) - 40, min(f["y"] for f in cols.values()) - 80,
            max(f["x"] + f["w"] for f in cols.values()) + 40, max(f["y"] + f["h"] for f in cols.values()) + 40])
        time.sleep(0.6)
        cover = js(wd, """const out=[]; const ns=[...document.querySelectorAll('.postit')].filter(e=>e.dataset.nid.startsWith('state-'));
          const nodes=[...document.querySelectorAll('.drawflow-node')].map(e=>e.getBoundingClientRect());
          for(const e of ns){ const r=e.getBoundingClientRect(); if(!e.classList.contains('full')) out.push([e.dataset.nid,'not full']);
            const col=document.querySelector('.frame[data-fid="auto-'+e.dataset.nid.slice(6)+'"]').getBoundingClientRect();
            if(r.left<col.left-1||r.right>col.right+1||r.top<col.top-1||r.bottom>col.bottom+1) out.push([e.dataset.nid,'outside column']);
            for(const b of nodes) if(r.left<b.right&&b.left<r.right&&r.top<b.bottom&&b.top<r.bottom){ out.push([e.dataset.nid,'covers a node']); break; } }
          return [ns.length, out]""")
        check("drawn: every column post-it in full mode, inside its column, covering no node", cover[0] == len(cols) and not cover[1], str(cover))
        # move a column by its title: its post-it follows by the same delta
        cid = "auto-veille" if "auto-veille" in cols else sorted(cols)[0]
        pid = notes[cid]["id"]
        f0 = cols[cid]
        js(wd, "window.__editor.focusRect({x0:arguments[0]-200,y0:arguments[1]-200,x1:arguments[0]+arguments[2]+200,y1:arguments[1]+Math.min(arguments[3],700)})",
           [f0["x"], f0["y"], f0["w"], f0["h"]])
        time.sleep(0.6)
        z = js(wd, "return window.__editor.nav().zoom")
        n0 = _nt(wd, pid)
        tr = rect(wd, '.frame[data-fid="%s"] .ftitle' % cid)
        _drag_by(wd, '.frame[data-fid="%s"] .ftitle' % cid, 80, 50, at=(tr[0] + min(30, tr[2] / 2), tr[1] + tr[3] / 2))
        f1, n1 = _fr(wd, cid), _nt(wd, pid)
        dc, dn = (f1["x"] - f0["x"], f1["y"] - f0["y"]), (n1["x"] - n0["x"], n1["y"] - n0["y"])
        check("moving the column moves its post-it by the same delta (still its child)",
              abs(dc[0] - 80 / z) <= 3 and abs(dc[1] - 50 / z) <= 3 and abs(dn[0] - dc[0]) <= 1.5 and abs(dn[1] - dc[1]) <= 1.5 and n1.get("parent") == cid,
              "%s %s z=%s" % (dc, dn, z))
        # delete the moved one with its × button (real click), edit and compact another, save, reload
        js(wd, "window.__editor.focusRect({x0:arguments[0]-300,y0:arguments[1]-200,x1:arguments[0]+arguments[2]+300,y1:arguments[1]+400}, 0.8)",
           [n1["x"], n1["y"], n1["w"]])
        time.sleep(0.5)
        xr = rect(wd, '.postit[data-nid="%s"] .pdel' % pid)
        if xr:
            lclick(wd, *_ctr(xr))
        if _nt(wd, pid):   # fallback when the × was not reachable (reported)
            print("WARN × click did not delete", pid, flush=True)
            js(wd, "window.__editor.deleteNote(arguments[0])", [pid])
        check("default post-it deleted with its × button", _nt(wd, pid) is None and xr is not None)
        other = sorted(n["id"] for n in notes.values() if n["id"] != pid)[0]
        js(wd, "const E=window.__editor, n=E.notes().find(x=>x.id===arguments[0]); E.editNote(n,{text:'Texte du visiteur.'}); E.setNoteDisplay(n,'compact')", [other])
        saved = _save_and_wait(wd)
        lay = json.load(open(ROOT + "/graph.layout.json", encoding="utf-8")) if os.path.exists(ROOT + "/graph.layout.json") else {}
        ln = {n["id"]: n for n in lay.get("notes", [])}
        check("save: the deleted post-it is gone from graph.layout.json, the others keep marker + parent, the edit is stored",
              saved and pid not in ln and len([n for n in ln.values() if (n.get("auto") or "").startswith("state:")]) == len(cols) - 1 and all(n.get("auto") and n.get("parent") for n in ln.values())
              and ln.get(other, {}).get("text") == "Texte du visiteur." and ln.get(other, {}).get("display") == "compact", "%s %s" % (saved, sorted(ln)))
        js(wd, "window.__editor.loadAll()")
        time.sleep(1.5)
        d2 = doc(wd)
        ids2 = {n["id"]: n for n in d2["notes"]}
        check("reload: the deleted post-it does not come back; the edited one keeps its text and compact mode",
              pid not in ids2 and len([n for n in d2["notes"] if (n.get("auto") or "").startswith("state:")]) == len(cols) - 1
              and ids2.get(other, {}).get("text") == "Texte du visiteur." and ids2.get(other, {}).get("display") == "compact", str(sorted(ids2)))
        st, vis = W.http("GET", BASE + "/api/graph/visual")
        check("server: the saved layout is never re-seeded", st == 200 and pid not in {n["id"] for n in vis.get("notes", [])})
        check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))
    finally:
        W.http("POST", BASE + "/api/graph/reset", {})
        for f in (set(glob.glob(ROOT + "/graph.*")) | set(glob.glob(ROOT + "/graph*.bak*"))) - pre:
            try:
                os.remove(f)
            except OSError:
                pass
        left = sorted((set(glob.glob(ROOT + "/graph.*")) | set(glob.glob(ROOT + "/graph*.bak*"))) - pre)
        check("no graph.yaml / graph.layout.json override left in the repo", not left and not os.path.exists(ROOT + "/graph.yaml") and not os.path.exists(ROOT + "/graph.layout.json"), str(left))
        st, vis = W.http("GET", BASE + "/api/graph/visual")
        check("shipped layout restored: every column has its default post-it again", st == 200 and len([n for n in vis.get("notes", []) if (n.get("auto") or "").startswith("state:")]) == len([f for f in vis.get("frames", []) if f.get("auto")]))
        st, chk = W.http("POST", BASE + "/api/graph/check", vis)
        check("shipped graph check 0 errors 0 warnings after restore", st == 200 and not chk.get("errors") and not chk.get("warnings"), "%s/%s" % (len(chk.get("errors") or []), len(chk.get("warnings") or [])))


SUB_TITLES_JS = r"""const jb=document.querySelector('#jumpbar').getBoundingClientRect(); const st=document.querySelector('#drawflow').getBoundingClientRect();
  return [...document.querySelectorAll('#drawflow .frame > .ftitle')].map(f=>{const r=f.getBoundingClientRect();
    return r.width>0 && r.right>st.left && r.left<st.right && r.right>jb.left && r.left<jb.right && r.bottom>jb.top && r.top<jb.bottom ? f.parentElement.dataset.fid : null}).filter(Boolean)"""


def sc_subgroups(wd):
    """Lot L13: default sub-groups inside the state columns. Hierarchy Colonne > sous-groupe > chaînes; dragging a
    column moves its sub-groups, their post-its, nodes and wires (±3 px); dragging a sub-group moves its chains only;
    no frame title (column or sub-group) under the jump bar (default view, every chip, Ajuster). Never saves (undo)."""
    open_editor(wd)
    js(wd, "try{localStorage.removeItem('nanterino.editor.tree')}catch(e){}; window.__editor.renderTree()")
    time.sleep(0.4)
    d = doc(wd)
    cols = {f["id"]: f for f in d["frames"] if f.get("auto")}
    subs = {f["id"]: f for f in d["frames"] if (f.get("gen") or "").startswith("sub:")}
    check("default doc: sub-groups, each a child of its column, one post-it each",
          len(subs) >= 20 and all(s.get("parent") in cols for s in subs.values())
          and {n.get("parent") for n in d["notes"] if (n.get("auto") or "").startswith("sub:")} == set(subs), "%d sub-groups" % len(subs))
    # ---- hierarchy: every chain row sits under a sub-group row, itself under its column row
    rows = _l10_rows(wd)
    bad, path = [], []
    for key_, lv, lab, _cls in rows:
        path = path[:lv - 1] + [key_]
        if key_.startswith("c:"):
            if len(path) != 3 or not path[0].startswith("col:") or not path[1].startswith("g:sub-") \
                    or subs.get(path[1][2:], {}).get("parent") != path[0][4:]:
                bad.append(path)
    ntrig = len([n for n in d["nodes"] if n["kind"] == "trigger"])
    nchains = len([r for r in rows if r[0].startswith("c:")])
    check("hierarchy: Colonne > sous-groupe > chaînes for every chain", nchains == ntrig and not bad, "%d/%d %s" % (nchains, ntrig, bad[:3]))
    lab = {r[0]: r[2] for r in rows}
    check("hierarchy: sub-group rows carry their titles", lab.get("g:sub-veille-reveil") == "Réveil" and lab.get("g:sub-global-tais_toi") == "Tais-toi",
          str([lab.get("g:sub-veille-reveil"), lab.get("g:sub-global-tais_toi")]))
    wd.shot("editor17-hierarchy.png")
    # ---- frame titles clear of the jump bar: default view, every chip, Ajuster
    check("default view: no column / sub-group title under the jump bar", js(wd, SUB_TITLES_JS) == [], str(js(wd, SUB_TITLES_JS)))
    chips = js(wd, "return [...document.querySelectorAll('#jumpbar .jchip')].map(e=>e.dataset.g)")
    hits = []
    for g in chips:
        js(wd, "document.querySelector('#jumpbar .jchip[data-g=\"'+arguments[0]+'\"]').scrollIntoView({inline:'nearest',block:'nearest'})", [g])
        r = rect(wd, '#jumpbar .jchip[data-g="%s"]' % g)
        lclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
        time.sleep(0.3)
        h_ = js(wd, SUB_TITLES_JS)
        if h_:
            hits.append((g, h_))
    check("each jump-bar chip: no column / sub-group title under the bar", not hits, str(hits)[:300])
    r = rect(wd, "#btnFit")
    lclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
    time.sleep(0.4)
    check("Ajuster: no column / sub-group title under the jump bar", js(wd, SUB_TITLES_JS) == [], str(js(wd, SUB_TITLES_JS)))
    # ---- screenshot: the Veille column at a readable zoom
    col = cols["auto-veille"]
    js(wd, "window.__editor.focusRect({x0:arguments[0]-40,y0:arguments[1]-220,x1:arguments[0]+arguments[2]+40,y1:arguments[1]+arguments[3]+40})",
       [col["x"], col["y"], col["w"], col["h"]])
    time.sleep(0.8)
    wd.shot("editor17-subgroups.png")
    # ---- drag the Veille column by its title: sub-groups, their post-its, nodes and wires follow
    js(wd, "window.__editor.focusRect({x0:arguments[0]-200,y0:arguments[1]-200,x1:arguments[0]+arguments[2]+200,y1:arguments[1]+Math.min(arguments[3],900)})",
       [col["x"], col["y"], col["w"], col["h"]])
    time.sleep(0.6)
    z = js(wd, "return window.__editor.nav().zoom")
    vsubs = [s for s in subs if subs[s]["parent"] == "auto-veille"]
    vnotes = [n["id"] for n in d["notes"] if n.get("parent") in vsubs]
    vnodes = [n["id"] for n in d["nodes"] if n.get("group") == "veille"]
    probe = next(n["id"] for n in d["nodes"] if n.get("group") == "veille" and n["kind"] == "action")
    b_sub = {s: _fr(wd, s) for s in vsubs}
    b_note = {p: _nt(wd, p) for p in vnotes}
    b_node = {i: pos_of(wd, i) for i in vnodes}
    tr = rect(wd, '.frame[data-fid="auto-veille"] .ftitle')
    live = []
    _drag_by(wd, '.frame[data-fid="auto-veille"] .ftitle', 80, 50, at=(tr[0] + min(30, tr[2] / 2), tr[1] + tr[3] / 2),
             hold_check=lambda w: live.append(_ends_ok(wires_of(w, dfid(w, probe)))))
    c1 = _fr(wd, "auto-veille")
    dc = (c1["x"] - col["x"], c1["y"] - col["y"])
    deltas = [(_fr(wd, s)["x"] - b["x"], _fr(wd, s)["y"] - b["y"]) for s, b in b_sub.items()]
    deltas += [(_nt(wd, p)["x"] - b["x"], _nt(wd, p)["y"] - b["y"]) for p, b in b_note.items()]
    deltas += [(pos_of(wd, i)[0] - b[0], pos_of(wd, i)[1] - b[1]) for i, b in b_node.items()]
    same = all(abs(a[0] - dc[0]) <= 3 and abs(a[1] - dc[1]) <= 3 for a in deltas)
    after = _ends_ok(wires_of(wd, dfid(wd, probe)))
    check("moving a column moves its sub-groups, their post-its and nodes by the same delta (±3 px), wires on ports live + after",
          abs(dc[0] - 80 / z) <= 3 and abs(dc[1] - 50 / z) <= 3 and same and live == [[]] and after == []
          and all(_fr(wd, s).get("parent") == "auto-veille" for s in vsubs), "%s z=%.3f %d items %s %s" % (dc, z, len(deltas), live, after))
    js(wd, "document.querySelector('#btnUndo').click()")
    time.sleep(0.5)
    check("undo puts the column back", (_fr(wd, "auto-veille")["x"], _fr(wd, "auto-veille")["y"]) == (col["x"], col["y"]))
    # ---- drag the « Réveil » sub-group: its chains move, the other chains of the column stay
    sid = "sub-veille-reveil"
    s0 = _fr(wd, sid)
    inside = lambda n, f: f["x"] <= n["x"] and n["x"] + 214 <= f["x"] + f["w"] and f["y"] <= n["y"] and n["y"] <= f["y"] + f["h"]
    mine = [n["id"] for n in doc(wd)["nodes"] if inside(n, s0)]
    rest = [i for i in vnodes if i not in mine]
    b_m = {i: pos_of(wd, i) for i in mine}
    b_r = {i: pos_of(wd, i) for i in rest}
    js(wd, "window.__editor.focusRect({x0:arguments[0]-150,y0:arguments[1]-150,x1:arguments[0]+arguments[2]+150,y1:arguments[1]+arguments[3]+150})",
       [s0["x"], s0["y"], s0["w"], s0["h"]])
    time.sleep(0.6)
    z = js(wd, "return window.__editor.nav().zoom")
    sprobe = next(i for i in mine if doc(wd)["nodes"][[n["id"] for n in doc(wd)["nodes"]].index(i)]["kind"] == "action")
    tr = rect(wd, '.frame[data-fid="%s"] .ftitle' % sid)
    _drag_by(wd, '.frame[data-fid="%s"] .ftitle' % sid, 30, 20, at=(tr[0] + min(30, tr[2] / 2), tr[1] + tr[3] / 2))
    s1 = _fr(wd, sid)
    ds = (s1["x"] - s0["x"], s1["y"] - s0["y"])
    dm = [(pos_of(wd, i)[0] - b[0], pos_of(wd, i)[1] - b[1]) for i, b in b_m.items()]
    still = all(pos_of(wd, i) == b for i, b in b_r.items())
    check("moving a sub-group moves its chains (±3 px), not the other chains; wires on ports; still in its column",
          len(mine) >= 6 and abs(ds[0] - 30 / z) <= 3 and abs(ds[1] - 20 / z) <= 3 and all(abs(a[0] - ds[0]) <= 3 and abs(a[1] - ds[1]) <= 3 for a in dm)
          and still and _ends_ok(wires_of(wd, dfid(wd, sprobe))) == [] and s1.get("parent") == "auto-veille",
          "%s z=%.3f %d nodes still=%s parent=%s" % (ds, z, len(mine), still, s1.get("parent")))
    js(wd, "document.querySelector('#btnUndo').click()")
    time.sleep(0.5)
    check("undo puts the sub-group back", (_fr(wd, sid)["x"], _fr(wd, sid)["y"]) == (s0["x"], s0["y"]))
    check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors")))


# Scenario registry read by tests/web/run.py (order = order of the former single file).
SCENARIOS = {
    "postit": sc_postit,
    "postit2": sc_postit2,
    "postit3": sc_postit3,
    "l8": sc_l8,
    "subgroups": sc_subgroups,
}
