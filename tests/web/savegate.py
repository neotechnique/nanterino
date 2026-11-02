"""Nanterino editor web scenarios: the save rule of post-its, groups and the hierarchy panel (lot L23).

Purpose : savegate area of the editor web suite; scenario postitsave. Every post-it change (create, text, title, colour,
          display mode, move, delete), for a user post-it, a default column post-it (`auto: state:*`) and a default
          sub-group post-it (`auto: sub:*`), and every hierarchy action on groups (rename, delete, drag-reparent) only
          changes the page: visible, "modifié" shown, undo / redo, lost on reload without saving, kept after
          "Enregistrer et appliquer". A fetch spy proves no write request leaves the page before the save click.
Boundary: drives the live editor through tests/web/driver.py (WebDriver, check()); never imports nanterino.server.
          Saves (real button); everything is rolled back at the end (POST /api/graph/reset + new graph.* files removed).
Invariant: a scenario is `sc_<name>(wd)` listed in SCENARIOS at the end of this file, which tests/web/run.py reads.
          Allowed POSTs before a save are the dry runs /api/graph/check and /api/graph/simulate (they never write).
Test    : .venv/bin/python -m tests.web.run postitsave   (or `area:savegate`, or `all`)
"""
import glob, os, time

from tests.web.driver import *  # noqa: F401,F403  (shared helpers, check(), W, BASE, ROOT)
from tests.web.driver import _save_and_wait
from tests.web.frames import _drag_by
from tests.web.hierarchy import _l10_click_row, _l10_drag_row

# Fetch spy, installed after every page load: records [method, url] of each request the editor makes. The real fetch
# must be called with `window` as this (the editor's module code calls it bare: this = undefined would throw).
SPY_JS = """if(!window.__spy){window.__spy=[]; const of=window.fetch;
  window.fetch=function(u,o){ window.__spy.push([((o&&o.method)||'GET').toUpperCase(), String(u)]); return of.apply(window, arguments); };}
  return true"""
DRY = ("/api/graph/check", "/api/graph/simulate")
F2, ENTER, DEL = "\ue032", "\ue007", "\ue017"   # WebDriver key codes (F1 is \ue031)


def _writes(wd):
    """Requests of the page so far that could write something (any non-GET outside the dry runs)."""
    spy = js(wd, "return window.__spy || []") or []
    return [s for s in spy if s[0] != "GET" and not any(d in s[1] for d in DRY)]


def _open(wd):
    open_editor(wd)
    js(wd, "window.__editor.closeCtx && window.__editor.closeCtx()")
    js(wd, SPY_JS)


def _reload_unsaved(wd, what):
    """Reload without saving; first assert that nothing was written by the page for `what`."""
    w = _writes(wd)
    check("%s: no write request before Enregistrer" % what, not w, str(w)[:200])
    _open(wd)
    check("%s: clean after reload (no 'modifié')" % what, not js(wd, "return window.__editor.dirtyShown()"))


def _save(wd, what):
    before = _writes(wd)
    check("%s: no write request before the save click" % what, not before, str(before)[:200])
    ok = _save_and_wait(wd)
    w = _writes(wd)
    if not ok:   # say why (refusal toast / server errors) before the failing check
        print("SAVE", js(wd, "return [[...document.querySelectorAll('#toasts .toast')].map(e=>e.textContent).join(' | '), document.querySelector('#msgs') ? document.querySelector('#msgs').textContent.slice(0, 400) : '']"), flush=True)
    check("%s: saved by the button (one POST /api/graph/visual)" % what,
          ok and [s[1] for s in w] == ["/api/graph/visual"], str(w)[:200])
    check("%s: 'modifié' gone after the save" % what, not js(wd, "return window.__editor.dirtyShown()"))
    _open(wd)


def _note(wd, pid):
    return js(wd, "return window.__editor.serialize().notes.find(n=>n.id===arguments[0]) || null", [pid])


def _frame(wd, fid):
    return js(wd, "return window.__editor.serialize().frames.find(f=>f.id===arguments[0]) || null", [fid])


def _dirty(wd):
    time.sleep(0.2)
    return js(wd, "return window.__editor.dirtyShown()")


def _show_note(wd, pid):
    js(wd, """const n=window.__editor.notes().find(x=>x.id===arguments[0]);
      window.__editor.focusRect({x0:n.x-150,y0:n.y-150,x1:n.x+n.w+150,y1:n.y+n.h+150})""", [pid])
    time.sleep(0.5)


def sc_postitsave(wd):
    pre = set(glob.glob(ROOT + "/graph.*")) | set(glob.glob(ROOT + "/graph*.bak*"))
    try:
        check("no saved layout at start (shipped default drawing)", not os.path.exists(ROOT + "/graph.layout.json"))
        _open(wd)
        d = doc(wd)
        col = next((n for n in d["notes"] if (n.get("auto") or "") == "state:veille"), None) or \
            next(n for n in d["notes"] if (n.get("auto") or "").startswith("state:"))
        sub = next(n for n in d["notes"] if (n.get("auto") or "").startswith("sub:"))
        cid, sid = col["id"], sub["id"]
        check("default column and sub-group post-its present", bool(cid and sid), "%s %s" % (cid, sid))

        # ---- 1. creating a user post-it: shown, 'modifié', lost on reload; kept once saved
        check("clean right after load", not js(wd, "return window.__editor.dirtyShown()"))
        js(wd, "document.querySelector('#btnNote').click()")
        time.sleep(0.5)
        uid = js(wd, "return window.__editor.selNote()")
        js(wd, "window.__editor.editNote(window.__editor.notes().find(n=>n.id===arguments[0]), {title:'Mémo L23', text:'NOTE-UTILISATEUR'}, true)", [uid])
        check("create: post-it shown", js(wd, "return !!document.querySelector('.postit[data-nid=\"'+arguments[0]+'\"]')", [uid]))
        check("create: 'modifié' shown", _dirty(wd))
        _reload_unsaved(wd, "create")
        check("create: an unsaved post-it is gone after reload", _note(wd, uid) is None)
        js(wd, "document.querySelector('#btnNote').click()")
        time.sleep(0.5)
        uid = js(wd, "return window.__editor.selNote()")
        js(wd, "window.__editor.editNote(window.__editor.notes().find(n=>n.id===arguments[0]), {title:'Mémo L23', text:'NOTE-UTILISATEUR'}, true)", [uid])
        _save(wd, "create")
        u0 = _note(wd, uid)
        check("create + save: the user post-it is back after reload", u0 is not None and u0["text"] == "NOTE-UTILISATEUR", str(u0)[:160])
        c0, s0 = _note(wd, cid), _note(wd, sid)
        check("default post-its kept by the first save (markers too)", c0 and s0 and c0.get("auto") == col["auto"] and s0.get("auto") == sub["auto"])
        ids = [uid, cid, sid]

        # ---- 2. delete (the post-it's own × button) -> 'modifié', undo / redo, reload without save = back
        for pid in ids:
            js(wd, "document.querySelector('.postit[data-nid=\"'+arguments[0]+'\"] .pdel').click()", [pid])
            time.sleep(0.3)
            check("delete %s: gone from the page" % pid, _note(wd, pid) is None and not js(wd, "return !!document.querySelector('.postit[data-nid=\"'+arguments[0]+'\"]')", [pid]))
            check("delete %s: 'modifié' shown" % pid, _dirty(wd))
        js(wd, "document.querySelector('#btnUndo').click()"); time.sleep(0.4)
        check("undo of the last delete brings the sub-group post-it back", _note(wd, sid) is not None and _note(wd, cid) is None)
        js(wd, "document.querySelector('#btnRedo').click()"); time.sleep(0.4)
        check("redo deletes it again", _note(wd, sid) is None)
        check("beforeunload would warn (unsaved deletes)", js(wd, "return window.__editor.isDirty()"))
        _reload_unsaved(wd, "delete")
        check("delete without save: all three post-its are back after reload",
              all(_note(wd, p) is not None for p in ids), str([_note(wd, p) is not None for p in ids]))

        # ---- 3. edits (typing, title, colour, display mode, move) -> reload without save = reverted
        before = {p: _note(wd, p) for p in ids}
        # typing only (input events, no change / blur): the mark appears after the typing pause, beforeunload at once
        js(wd, """const ta=document.querySelector('.postit[data-nid="'+arguments[0]+'"] textarea'); ta.value=ta.value+' TAPÉ';
          ta.dispatchEvent(new Event('input',{bubbles:true}))""", [cid])
        check("typing: beforeunload warns at once (edit not yet committed)", js(wd, "return window.__editor.isDirty()"))
        time.sleep(0.9)
        check("typing: 'modifié' shown after the typing pause, without leaving the field", js(wd, "return window.__editor.dirtyShown()"))
        js(wd, "window.__editor.editNote(window.__editor.notes().find(n=>n.id===arguments[0]), {title:'Titre L23', color:'#f8bbd0'}, true)", [sid])
        check("title / colour: 'modifié' shown", _dirty(wd))
        js(wd, "document.querySelector('.postit[data-nid=\"'+arguments[0]+'\"] .pmode').click()", [cid])
        time.sleep(0.3)
        check("display mode: compact in the document", (_note(wd, cid) or {}).get("display") == "compact")
        _show_note(wd, uid)
        _drag_by(wd, '.postit[data-nid="%s"] .phead' % uid, 90, 60, at=None)
        moved = _note(wd, uid)
        check("move (real drag): the user post-it moved", (moved["x"], moved["y"]) != (before[uid]["x"], before[uid]["y"]), str((moved["x"], moved["y"])))
        js(wd, "window.__editor.editNote(window.__editor.notes().find(n=>n.id===arguments[0]), {x: arguments[1]+37, y: arguments[2]+23}, false)",
           [sid, before[sid]["x"], before[sid]["y"]])
        check("move: 'modifié' shown", _dirty(wd))
        js(wd, "document.querySelector('#btnUndo').click()"); time.sleep(0.4)
        check("undo of the sub-group post-it move", (_note(wd, sid)["x"], _note(wd, sid)["y"]) == (before[sid]["x"], before[sid]["y"]))
        js(wd, "document.querySelector('#btnRedo').click()"); time.sleep(0.4)
        _reload_unsaved(wd, "edit")
        after = {p: _note(wd, p) for p in ids}
        check("edits without save: the three post-its are reverted after reload", after == before,
              str([(p, before[p] == after[p]) for p in ids]))

        # ---- 4. the same edits saved -> kept
        js(wd, """const ta=document.querySelector('.postit[data-nid="'+arguments[0]+'"] textarea'); ta.value=ta.value+' GARDÉ';
          ta.dispatchEvent(new Event('input',{bubbles:true}))""", [cid])
        time.sleep(0.9)
        js(wd, "document.querySelector('.postit[data-nid=\"'+arguments[0]+'\"] .pmode').click()", [cid])
        js(wd, "window.__editor.editNote(window.__editor.notes().find(n=>n.id===arguments[0]), {title:'Titre L23', color:'#f8bbd0', x: arguments[1]+37, y: arguments[2]+23}, true)",
           [sid, before[sid]["x"], before[sid]["y"]])
        js(wd, "window.__editor.editNote(window.__editor.notes().find(n=>n.id===arguments[0]), {text:'NOTE-MODIFIÉE'}, true)", [uid])
        time.sleep(0.3)
        _save(wd, "edit")
        c1, s1, u1 = _note(wd, cid), _note(wd, sid), _note(wd, uid)
        check("edits + save: column post-it text and compact mode kept", c1 and c1["text"].endswith("GARDÉ") and c1.get("display") == "compact", str(c1)[:160])
        check("edits + save: sub-group post-it title, colour, position kept", s1 and s1.get("title") == "Titre L23" and s1["color"] == "#f8bbd0"
              and (s1["x"], s1["y"]) == (before[sid]["x"] + 37, before[sid]["y"] + 23), str(s1)[:160])
        check("edits + save: user post-it text kept", u1 and u1["text"] == "NOTE-MODIFIÉE")

        # ---- 5. delete + save -> gone after reload (default post-its are not re-seeded)
        for pid in ids:
            js(wd, "window.__editor.deleteNote(arguments[0])", [pid])
        time.sleep(0.3)
        _save(wd, "delete")
        check("delete + save: the three post-its stay deleted after reload (no re-seeding)",
              all(_note(wd, p) is None for p in ids), str([_note(wd, p) is not None for p in ids]))

        # ---- 6. hierarchy panel: rename, delete, drag-reparent of a group -> same rule
        fr = doc(wd)["frames"]
        subs = [f for f in fr if (f.get("gen") or "").startswith("sub:")]
        g1, g2 = subs[0], subs[1]
        col_ids = [f["id"] for f in fr if f.get("auto")]
        dest = next(c for c in col_ids if c != g2.get("parent"))
        js(wd, "document.querySelector('#tree').scrollIntoView && 0")
        # rename (F2 on the row, Enter)
        _l10_click_row(wd, "g:" + g1["id"])
        js(wd, "const r=document.querySelector('#tree .hrow[data-key=\"g:'+arguments[0]+'\"]'); r.focus()", [g1["id"]])
        key(wd, F2)
        ok = js(wd, "const i=document.querySelector('#tree input.hrename'); if(!i) return false; i.value='Groupe L23'; return true")
        key(wd, ENTER)
        check("hierarchy rename (F2): title changed in the page", ok and (_frame(wd, g1["id"]) or {}).get("title") == "Groupe L23")
        check("hierarchy rename: 'modifié' shown", _dirty(wd))
        # drag-reparent: sub-group row dropped on another column row
        _l10_drag_row(wd, "g:" + g2["id"], "col:" + dest)
        check("hierarchy drag: the sub-group moved to the other column", (_frame(wd, g2["id"]) or {}).get("parent") == dest, str((_frame(wd, g2["id"]) or {}).get("parent")))
        # delete: select the row, Suppr
        _l10_click_row(wd, "g:" + g1["id"])
        js(wd, "const r=document.querySelector('#tree .hrow[data-key=\"g:'+arguments[0]+'\"]'); r.focus()", [g1["id"]])
        key(wd, DEL)
        check("hierarchy delete (Suppr): group gone from the page", _frame(wd, g1["id"]) is None)
        check("hierarchy delete: 'modifié' shown", _dirty(wd))
        js(wd, "document.querySelector('#btnUndo').click()"); time.sleep(0.4)
        check("undo of the hierarchy delete brings the group back", _frame(wd, g1["id"]) is not None)
        js(wd, "document.querySelector('#btnRedo').click()"); time.sleep(0.4)
        _reload_unsaved(wd, "hierarchy")
        f1, f2 = _frame(wd, g1["id"]), _frame(wd, g2["id"])
        check("hierarchy edits without save: rename, delete and reparent reverted after reload",
              f1 is not None and f1.get("title") == g1.get("title") and f2 is not None and f2.get("parent") == g2.get("parent"),
              str((f1 or {}).get("title")) + " / " + str((f2 or {}).get("parent")))
        # the same, saved
        _l10_click_row(wd, "g:" + g1["id"])
        js(wd, "const r=document.querySelector('#tree .hrow[data-key=\"g:'+arguments[0]+'\"]'); r.focus()", [g1["id"]])
        key(wd, F2)
        js(wd, "const i=document.querySelector('#tree input.hrename'); if(i) i.value='Groupe L23'")
        key(wd, ENTER)
        _l10_drag_row(wd, "g:" + g2["id"], "col:" + dest)
        g3 = subs[2] if len(subs) > 2 else None
        if g3:
            js(wd, "window.__editor.deleteFrame(arguments[0])", [g3["id"]])
        time.sleep(0.3)
        _save(wd, "hierarchy")
        f1, f2 = _frame(wd, g1["id"]), _frame(wd, g2["id"])
        check("hierarchy edits + save: rename and reparent kept, delete kept",
              (f1 or {}).get("title") == "Groupe L23" and (f2 or {}).get("parent") == dest and (not g3 or _frame(wd, g3["id"]) is None),
              str((f1 or {}).get("title")) + " / " + str((f2 or {}).get("parent")))
        check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors"))[:200])
    finally:
        W.http("POST", BASE + "/api/graph/reset", {})
        for f in (set(glob.glob(ROOT + "/graph.*")) | set(glob.glob(ROOT + "/graph*.bak*"))) - pre:
            try:
                os.remove(f)
            except OSError:
                pass
        print("LEFT OVER", sorted((set(glob.glob(ROOT + "/graph.*")) | set(glob.glob(ROOT + "/graph*.bak*"))) - pre))


SCENARIOS = {
    "postitsave": sc_postitsave,
}
