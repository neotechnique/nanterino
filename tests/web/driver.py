"""Shared driver of the Nanterino editor web tests (tests/web/*): checks, summary, pointer / key helpers.

Purpose : everything the scenario files share: `check()` and the `checks` list the runner summarises, JS / pointer /
          menu helpers, and every helper used by scenarios of more than one area.
Boundary: drives the live editor at BASE through the WebDriver session of tests/web/wd.py (aliased `W`, as in the
          former scripts/editor6_wd.py); never imports nanterino.server.
Invariant: the code below is the M7 verbatim slice of scripts/editor6_wd.py (same text, same order); scenario files
          do `from tests.web.driver import *`, so `__all__` (end of file) exports private helpers too.
Test    : .venv/bin/python -m tests.web.run <scenario|area|all>   (VIEWPORT=WxH env, default 1280x700)
"""
import glob, json, os, sys, time

from tests.web import wd as W

BASE, ROOT = W.BASE, "/opt/robot/nanterino"
checks = []


def check(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name, extra, flush=True)


def js(wd, s, a=None):
    return wd.js(s, a)


def actions(wd, button, pts, hold_ms=150):
    """Press `button` (0 left, 1 middle, 2 right) at pts[0], move through the rest, release."""
    acts = [{"type": "pointerMove", "duration": 0, "x": int(pts[0][0]), "y": int(pts[0][1])}, {"type": "pointerDown", "button": button}]
    for x, y in pts[1:]:
        acts.append({"type": "pointerMove", "duration": hold_ms, "x": int(x), "y": int(y)})
    acts.append({"type": "pointerUp", "button": button})
    wd.cmd("POST", "/actions", {"actions": [{"type": "pointer", "id": "m", "parameters": {"pointerType": "mouse"}, "actions": acts}]})
    wd.cmd("DELETE", "/actions")
    time.sleep(0.5)


def rclick(wd, x, y):
    actions(wd, 2, [(x, y)])


def lclick(wd, x, y):
    actions(wd, 0, [(x, y)])


def rect(wd, sel):
    return js(wd, "const e=document.querySelector(arguments[0]); if(!e) return null; const r=e.getBoundingClientRect(); return [r.x,r.y,r.width,r.height]", [sel])


def doc(wd):
    return js(wd, "return window.__editor.serialize()")


def dfid(wd, nid):
    return js(wd, "return window.__editor.dfMap()[arguments[0]]", [nid])


def menu_labels(wd):
    return js(wd, "return [...document.querySelectorAll('.ctx')].map(m=>[...m.querySelectorAll(':scope > .cit')].map(e=>e.textContent.trim()+(e.classList.contains('dis')?' [off]':'')))")


def click_item(wd, label, last=True):
    ok = js(wd, """const rows=[...document.querySelectorAll('.ctx .cit')].filter(e=>e.textContent.trim().startsWith(arguments[0]));
      if(!rows.length) return false; const e=rows[rows.length-1]; e.dispatchEvent(new MouseEvent('mouseenter')); e.click(); return true""", [label])
    time.sleep(0.4)
    return ok


def open_editor(wd):
    W.open_editor(wd, "#quiet")
    time.sleep(1.0)


def node_of(wd, pred):
    """First node of the serialized doc matching a JS predicate on n."""
    return js(wd, "const d=window.__editor.serialize(); return d.nodes.find(n=>(%s))||null" % pred)


def view_empty_point(wd, min_y=0):
    return js(wd, """const st=document.querySelector('#drawflow').getBoundingClientRect();
      for(let y=Math.max(st.y+60, arguments[0]);y<st.bottom-60;y+=20) for(let x=st.x+60;x<st.right-60;x+=20){
        const e=document.elementFromPoint(x,y); if(e && e.closest('#drawflow') && !e.closest('.drawflow-node,.postit,.ftitle,.fresize,path.main-path,.ctx,#jumpbar,#minimap,.rbadge')) return [x,y]; } return null""", [min_y])


def wire_point(wd, filt):
    """Client point on the middle of a wire whose (from kind, to kind) match filt (JS expr on a,b)."""
    return js(wd, """const E=window.__editor; const data=E.serialize(); const m=E.dfMap(); const kinds={}; data.nodes.forEach(n=>kinds[m[n.id]]=n);
      for(const svg of document.querySelectorAll('svg.connection')){ const cl=svg.classList; const a=kinds[cl[2].slice(14)], b=kinds[cl[1].slice(13)];
        if(!a||!b|| !(%s)) continue; const p=svg.querySelector('.main-path'); const L=p.getTotalLength(); const pt=svg.createSVGPoint();
        for(const f of [0.5,0.42,0.58,0.35,0.65]){ const q=p.getPointAtLength(L*f); pt.x=q.x; pt.y=q.y; const c=pt.matrixTransform(p.getScreenCTM());
          const st=document.querySelector('#drawflow').getBoundingClientRect();
          if(c.x<st.x+20||c.x>st.right-20||c.y<st.y+20||c.y>st.bottom-20) continue;
          const e=document.elementFromPoint(c.x,c.y); if(e===p) return {x:c.x,y:c.y,from:a.id,to:b.id,port:cl[3]}; } } return null""" % filt)


def center_on(wd, nid, zoom_node=True):
    wd.js("window.__editor.panDf(arguments[0])", [dfid(wd, nid)])
    time.sleep(0.5)


def key(wd, value, release=True):
    """Press (and by default release) one key; WebDriver keeps a held key until DELETE /actions."""
    acts = [{"type": "keyDown", "value": value}] + ([{"type": "keyUp", "value": value}] if release else [])
    wd.cmd("POST", "/actions", {"actions": [{"type": "key", "id": "k", "actions": acts}]})
    if release:
        wd.cmd("DELETE", "/actions")
    time.sleep(0.3)


def wheel(wd, x, y, dx, dy, mod=None):
    """Real WebDriver wheel at (x, y), optionally with a held modifier (Shift \\ue008, Ctrl \\ue009);
    falls back to a synthetic WheelEvent if this geckodriver has no wheel source."""
    try:
        srcs = [{"type": "wheel", "id": "w", "actions": [{"type": "pause", "duration": 0}, {"type": "scroll", "x": int(x), "y": int(y), "deltaX": int(dx), "deltaY": int(dy), "duration": 0}]}]
        if mod:
            srcs.append({"type": "key", "id": "k", "actions": [{"type": "keyDown", "value": mod}, {"type": "pause", "duration": 0}]})
        wd.cmd("POST", "/actions", {"actions": srcs})
        wd.cmd("DELETE", "/actions")
        how = "webdriver"
    except Exception as e:  # noqa: BLE001 - report which path ran
        js(wd, """const [x,y,dx,dy,m]=arguments; const t=document.elementFromPoint(x,y);
          t.dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,clientX:x,clientY:y,deltaX:dx,deltaY:dy,deltaMode:0,shiftKey:m==='shift',ctrlKey:m==='ctrl'}))""",
           [x, y, dx, dy, {"": "shift", "": "ctrl"}.get(mod)])
        how = "synthetic (%s)" % str(e)[:80]
    time.sleep(0.3)
    return how


def _set(wd, sel, value):
    """Set an input / select value and fire input + change (like a user edit)."""
    return js(wd, """const e=document.querySelector(arguments[0]); if(!e) return false; if(e.type==='checkbox') e.checked=!!arguments[1]; else e.value=arguments[1];
      e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true})); return true""", [sel, value])


def _click(wd, sel):
    return js(wd, "const e=document.querySelector(arguments[0]); if(!e) return false; e.click(); return true", [sel])


WIRE_JS = """
  // every wire touching Drawflow node `arguments[0]`: d, both path ends and both port centres (client px), gradient ends
  const id = arguments[0], out = [];
  const ctr = (el) => { if (!el) return null; const r = el.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; };
  for (const svg of document.querySelectorAll('svg.connection.node_in_node-' + id + ', svg.connection.node_out_node-' + id)) {
    const cl = svg.classList, p = svg.querySelector('.main-path'); if (!p) continue;
    const L = p.getTotalLength(), m = p.getScreenCTM(), pt = svg.createSVGPoint();
    const at = (l) => { const q = p.getPointAtLength(l); pt.x = q.x; pt.y = q.y; const c = pt.matrixTransform(m); return [c.x, c.y]; };
    const inId = cl[1].slice(13), outId = cl[2].slice(14);
    const g = svg.querySelector('linearGradient');
    const nums = (p.getAttribute('d') || '').match(/-?\\d+(?:\\.\\d+)?/g) || [];
    out.push({ key: cl[2] + '>' + cl[1] + ':' + cl[3], d: p.getAttribute('d'), first: svg.firstElementChild.tagName,
      start: at(0), end: at(L),
      pout: ctr(document.querySelector('#node-' + outId + ' .outputs .' + cl[3])), pin: ctr(document.querySelector('#node-' + inId + ' .inputs .' + cl[4])),
      grad: g ? [+g.getAttribute('x1'), +g.getAttribute('y1'), +g.getAttribute('x2'), +g.getAttribute('y2')] : null,
      dEnds: nums.length >= 4 ? [+nums[0], +nums[1], +nums[nums.length - 2], +nums[nums.length - 1]] : null,
      stroke: p.style.stroke });
  }
  return out;
"""


def wires_of(wd, df):
    return js(wd, WIRE_JS, [df])


def _ends_ok(ws, tol=3.0):
    """Every wire: path start on its output port centre, end on its input port centre (client px), gradient on d."""
    bad = []
    for w in ws:
        if not w["pout"] or not w["pin"]:
            bad.append((w["key"], "port missing")); continue
        ds = max(abs(w["start"][0] - w["pout"][0]), abs(w["start"][1] - w["pout"][1]))
        de = max(abs(w["end"][0] - w["pin"][0]), abs(w["end"][1] - w["pin"][1]))
        gd = max(abs(a - b) for a, b in zip(w["grad"], w["dEnds"])) if w["grad"] and w["dEnds"] else 99
        if ds > tol or de > tol or gd > 1.5 or "url(" not in (w["stroke"] or ""):
            bad.append((w["key"], round(ds, 1), round(de, 1), round(gd, 1)))
    return bad


def _press_move(wd, x0, y0, x1, y1, release=True, steps=4):
    acts = [{"type": "pointerMove", "duration": 0, "x": int(x0), "y": int(y0)}, {"type": "pointerDown", "button": 0}]
    for k in range(1, steps + 1):
        acts.append({"type": "pointerMove", "duration": 60, "x": int(x0 + (x1 - x0) * k / steps), "y": int(y0 + (y1 - y0) * k / steps)})
    if release:
        acts.append({"type": "pointerUp", "button": 0})
    wd.cmd("POST", "/actions", {"actions": [{"type": "pointer", "id": "m", "parameters": {"pointerType": "mouse"}, "actions": acts}]})
    if release:
        wd.cmd("DELETE", "/actions")
    time.sleep(0.4)


def _release(wd):
    wd.cmd("POST", "/actions", {"actions": [{"type": "pointer", "id": "m", "parameters": {"pointerType": "mouse"}, "actions": [{"type": "pointerUp", "button": 0}]}]})
    wd.cmd("DELETE", "/actions")
    time.sleep(0.5)


# ---------------------------------------------------------------- lot L5 (2026-11-01): node menu, tooltips, post-it modes, diagnostics
def hover(wd, x, y):
    """Move the pointer (no button) to client (x, y)."""
    wd.cmd("POST", "/actions", {"actions": [{"type": "pointer", "id": "m", "parameters": {"pointerType": "mouse"},
                                             "actions": [{"type": "pointerMove", "duration": 60, "x": int(x), "y": int(y)}]}]})


def tip_state(wd):
    return js(wd, "const t=document.getElementById('tip'); return t ? [!t.hidden && t.classList.contains('on'), t.textContent] : [false, '']")


def hover_tip(wd, sel, wait=0.9):
    """Hover the centre of the first element matching `sel`; return [shown, text] after `wait` s (None if absent)."""
    js(wd, "const e=document.querySelector(arguments[0]); if(e) e.scrollIntoView({block:'nearest'})", [sel])
    r = rect(wd, sel)
    if not r:
        return None
    hover(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
    time.sleep(wait)
    return tip_state(wd)


def away(wd):
    e = view_empty_point(wd) or (640, 650)
    hover(wd, *e)
    time.sleep(0.3)


LONG = ("Accueil du soir : penser à vérifier que la salle est vide avant de couper le micro. " * 5).strip() + "\nDeuxième paragraphe : le robot ne lit jamais ce texte.\nFIN-DU-TEXTE"


def badge(wd, nid):
    return js(wd, "const m=window.__editor.dfMap(); const b=document.querySelector('#node-'+m[arguments[0]]+' > .dbadge'); return b ? [b.className, b.getAttribute('data-tip')||''] : null", [nid])

# ---- lot L6 (2026-11-01): column titles clear of the jump bar, fresh check on save, minimap diagnostics ----
TITLE_JS = r"""const jb=document.querySelector('#jumpbar').getBoundingClientRect(); const st=document.querySelector('#drawflow').getBoundingClientRect();
  const f=document.querySelector('#drawflow .frame[data-fid="'+arguments[0]+'"] > .ftitle'); if(!f) return null; const r=f.getBoundingClientRect();
  const hit=r.right>jb.left && r.left<jb.right && r.bottom>jb.top && r.top<jb.bottom;
  return {hit, title:[r.x,r.y,r.width,r.height], bar:[jb.x,jb.y,jb.width,jb.height], inView: r.top>=st.top && r.bottom<=st.bottom && r.right>st.left && r.left<st.right}"""
ALL_TITLES_JS = r"""const jb=document.querySelector('#jumpbar').getBoundingClientRect(); const st=document.querySelector('#drawflow').getBoundingClientRect();
  return [...document.querySelectorAll('#drawflow .frame.auto > .ftitle')].map(f=>{const r=f.getBoundingClientRect();
    return r.right>st.left && r.left<st.right && r.right>jb.left && r.left<jb.right && r.bottom>jb.top && r.top<jb.bottom ? f.parentElement.dataset.fid : null}).filter(Boolean)"""
MINI_JS = r"""const m=document.querySelector('#minimap'); if(!m) return null; const cv=m.querySelector('canvas'); const ctx=cv.getContext('2d');
  const dots=(m._dots||[]).map(d=>{const px=ctx.getImageData(Math.round(d.x),Math.round(d.y),1,1).data; return [d.nid,d.level,[px[0],px[1],px[2]]]});
  return {open:m.classList.contains('open'), err:+(m.dataset.err||0), warn:+(m.dataset.warn||0), dots}"""


def chord(wd, mod, k):
    acts = [{"type": "keyDown", "value": mod}, {"type": "keyDown", "value": k}, {"type": "keyUp", "value": k}, {"type": "keyUp", "value": mod}]
    wd.cmd("POST", "/actions", {"actions": [{"type": "key", "id": "k", "actions": acts}]})
    wd.cmd("DELETE", "/actions")
    time.sleep(0.8)


def pos_of(wd, nid):
    return js(wd, "const n=window.__editor.serialize().nodes.find(x=>x.id===arguments[0]); return [n.x,n.y]", [nid])



# ---- lot L8 (2026-11-01): node hover tooltips, minimap press-and-drag navigation, nested groups and post-its ----
def _pt(wd, acts, ptype="mouse", end=False):
    """Send one pointer action chain (pointerType mouse / touch). end=True releases the input state afterwards."""
    wd.cmd("POST", "/actions", {"actions": [{"type": "pointer", "id": "m" if ptype == "mouse" else "t", "parameters": {"pointerType": ptype}, "actions": acts}]})
    if end:
        wd.cmd("DELETE", "/actions")


def _mv(x, y, ms=60):
    return {"type": "pointerMove", "duration": ms, "x": int(x), "y": int(y)}


_DOWN, _UP = {"type": "pointerDown", "button": 0}, {"type": "pointerUp", "button": 0}


def _fr(wd, fid):
    return js(wd, "const f=window.__editor.serialize().frames.find(x=>x.id===arguments[0]); return f||null", [fid])


def _ctr(r):
    return r[0] + r[2] / 2, r[1] + r[3] / 2


def _encl(p, c):
    """True when frame box p encloses frame box c."""
    return p["x"] <= c["x"] and p["y"] <= c["y"] and p["x"] + p["w"] >= c["x"] + c["w"] and p["y"] + p["h"] >= c["y"] + c["h"]



def _save_and_wait(wd):
    """Click "Enregistrer et appliquer" and wait for the saved toast (True) or give up after 10 s (False)."""
    js(wd, "document.querySelectorAll('#toasts .toast').forEach(t=>t.remove())")
    js(wd, "document.querySelector('#btnSave').click()")
    for _ in range(40):
        time.sleep(0.25)
        if "enregistr" in js(wd, "return [...document.querySelectorAll('#toasts .toast')].map(e=>e.textContent).join(' | ')").lower():
            return True
    return False


# ---------------------------------------------------------------------------------------------------------------------
# lot L10: flat right-click menu, hierarchy panel (left), inspector (right). Never saves: every edit stays in the page.
L10_ROW = "#tree .hrow[data-key=\"%s\"]"


def _l10_row(wd, key):
    js(wd, "const e=document.querySelector(arguments[0]); if(e) e.scrollIntoView({block:'nearest'})", [L10_ROW % key])
    time.sleep(0.15)
    return rect(wd, L10_ROW % key)


def _l10_rows(wd):
    return js(wd, "return [...document.querySelectorAll('#tree .hrow')].map(r=>[r.dataset.key, +r.getAttribute('aria-level'), r.querySelector('.hlab') ? r.querySelector('.hlab').textContent : '', r.className])")


# ---------------------------------------------------------------- lot L12 (2026-11-01): Variables v2 editor
def _vsel(wd, vid, tab="names"):
    """Select a variable (names) or a list (lists) in the Variables panel without the toggle of a row click."""
    js(wd, "const E=window.__editor; E.activateTab('vars'); E.varsUi.tab=arguments[1]; if(arguments[1]==='names') E.varsUi.sel=arguments[0]; else E.varsUi.list=arguments[0]; E.renderVars()", [vid, tab])
    time.sleep(0.3)


def _vmeta(wd, vid, part="names"):
    return js(wd, "const v=window.__editor.meta().variables[arguments[1]][arguments[0]]; return v?JSON.parse(JSON.stringify(v)):null", [vid, part])


def _pick_dd(wd, label_start, title):
    """Open the inspector's custom dropdown whose field label starts with label_start and click the entry `title`."""
    return js(wd, """const dd=[...document.querySelectorAll('#inspector .dd')].find(x=>x.closest('.fld').textContent.startsWith(arguments[0])); if(!dd) return false;
      dd.querySelector('.ddb').click(); const it=[...dd.querySelectorAll('.ddi')].find(i=>i.title===arguments[1]||i.title.startsWith(arguments[1]+' (')); if(!it) return false; it.click(); return true""", [label_start, title])


# Star-import surface for the scenario files (private `_x` helpers included).
__all__ = [n for n in dict(globals()) if not n.startswith("__")]
