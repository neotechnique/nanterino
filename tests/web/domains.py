"""Nanterino editor web scenario `domains` (lot S1): the level above the state columns.

Purpose : the hierarchy's top level is the domains (Dialogue, Comportement, Mouvement, Système); the jump bar has two
          levels (domain chip, then its column chips) and its framing stays clear of the bar; a column dragged onto
          another domain row in the hierarchy moves there (meta + geometry), undo / redo; a domain and a column fold
          into cards (node count, error / warning badges, content and wires hidden), undo; everything is save-gated,
          then saved and reloaded (kept); console errors 0.
Boundary: drives the live editor through tests/web/driver.py (WebDriver, check()); never imports nanterino.server.
          Saves once with the real button; rolled back at the end (POST /api/graph/reset + new graph.* files removed).
Test    : .venv/bin/python -m tests.web.run domains   (or `area:domains`, or `all`)
"""
import glob, json, os, sys, time

from tests.web.driver import *  # noqa: F401,F403  (shared helpers, check(), W, BASE, ROOT)
from tests.web.hierarchy import _l10_drag_row
from tests.web.savegate import SPY_JS, _writes

DOMS = ["dialogue", "comportement", "mouvement", "systeme"]


def _open(wd):
    open_editor(wd)
    js(wd, "window.__editor.closeCtx && window.__editor.closeCtx()")
    js(wd, SPY_JS)
    js(wd, "try{localStorage.removeItem('nanterino.editor.tree')}catch(e){}; window.__editor.renderTree()")
    time.sleep(0.3)


def _meta(wd):
    return js(wd, "const m=window.__editor.meta(); return {domains: m.domains, columns: m.columns}")


def _rect(wd, d):
    return js(wd, "return window.__editor.domainRect(arguments[0])", [d])


def _inside(f, r):
    return r and r["x"] <= f["x"] and r["y"] <= f["y"] and f["x"] + f["w"] <= r["x"] + r["w"] and f["y"] + f["h"] <= r["y"] + r["h"]


def _clear_of_bar(wd, sel):
    """[title top, jump bar bottom] in client px, None when the element is missing."""
    return js(wd, """const t=document.querySelector(arguments[0]); const jb=document.querySelector('#jumpbar');
      if(!t||!jb) return null; return [t.getBoundingClientRect().top, jb.getBoundingClientRect().bottom]""", [sel])


def _click(wd, sel):
    r = rect(wd, sel)
    if not r or not r[2]:
        return False
    lclick(wd, r[0] + r[2] / 2, r[1] + r[3] / 2)
    time.sleep(0.4)
    return True


def _hidden_nodes(wd):
    return js(wd, "return document.querySelectorAll('#drawflow .parent-node.fold-hide').length")


def sc_domains(wd):
    pre = set(glob.glob(ROOT + "/graph.*")) | set(glob.glob(ROOT + "/graph*.bak*"))
    try:
        check("domains: no saved layout at start (shipped default drawing)", not os.path.exists(ROOT + "/graph.layout.json"))
        _open(wd)
        m = _meta(wd)
        check("domains: 4 domains in order", [d["id"] for d in m["domains"] or []] == DOMS, str(m["domains"])[:300])
        check("domains: states in Dialogue, global rules in Système",
              m["columns"] and m["columns"].get("global", {}).get("domain") == "systeme"
              and all(e["domain"] == "dialogue" for g, e in m["columns"].items() if g != "global"), str(m["columns"])[:300])
        regs = js(wd, "return [...document.querySelectorAll('#domains .dregion')].map(e=>[e.dataset.dom, e.classList.contains('empty')])")
        check("domains: one region per domain, Comportement and Mouvement drawn empty", regs == [["dialogue", False], ["comportement", True], ["mouvement", True], ["systeme", False]], str(regs))
        notes = {n.get("auto"): n for n in doc(wd)["notes"]}
        check("domains: each empty region shows its explanatory post-it inside it",
              all(_inside(notes.get("domain:" + d) or {"x": -1e9, "y": 0, "w": 1, "h": 1}, _rect(wd, d)) for d in ("comportement", "mouvement")))

        # ---- 1 hierarchy: top level = domains, columns below
        rows = js(wd, "return [...document.querySelectorAll('#tree .hrow')].map(r=>[r.dataset.key, +r.getAttribute('aria-level')])")
        top = [k for k, lv in rows if lv == 1]
        check("domains: hierarchy top level = the 4 domains", top == ["d:" + d for d in DOMS], str(top))
        tree = js(wd, "return window.__editor.buildTree().kids.map(d=>[d.key, d.kids.filter(k=>k.type==='col').map(k=>k.key)])")
        check("domains: columns under their domain (7 states in Dialogue, global in Système)",
              tree and tree[0][0] == "d:dialogue" and len(tree[0][1]) == 7 and tree[3][1] == ["col:auto-global"] and tree[1][1] == [] and tree[2][1] == [], str(tree))
        check("domains: column rows are level 2", all(lv == 2 for k, lv in rows if k.startswith("col:")))

        # ---- 2 jump bar: two levels, framing clear of the bar
        bar = js(wd, "return [...document.querySelectorAll('#jumpbar > *')].map(e=>(e.classList.contains('jdom')?'D:'+e.dataset.d:'C:'+e.dataset.g))")
        want = ["D:dialogue"] + ["C:" + s for s in ("veille", "accueil", "ecoute", "reponse", "relance", "cloture", "eteint")] + \
               ["D:comportement", "D:mouvement", "D:systeme", "C:global"]
        check("domains: jump bar = domain chip then its column chips", bar == want, str(bar))
        for d in ("mouvement", "dialogue", "systeme"):
            js(wd, "document.querySelector('#jumpbar .jdom[data-d=\"'+arguments[0]+'\"]').click()", [d])
            time.sleep(0.6)
            t = _clear_of_bar(wd, '.dregion[data-dom="%s"] .dtitle' % d)
            vis = js(wd, """const r=document.querySelector('.dregion[data-dom="'+arguments[0]+'"]').getBoundingClientRect(), s=document.querySelector('#drawflow').getBoundingClientRect();
              return r.right>s.left && r.left<s.right && r.bottom>s.top && r.top<s.bottom""", [d])
            check("domains: chip %s frames its region, title clear of the jump bar" % d, vis and t and t[0] >= t[1] - 1, str(t))
        js(wd, "document.querySelector('#jumpbar .jchip[data-g=ecoute]').click()")
        time.sleep(0.6)
        t = js(wd, """const f=document.querySelector('.frame[data-fid=auto-ecoute] .ftitle').getBoundingClientRect(); return [f.top, document.querySelector('#jumpbar').getBoundingClientRect().bottom]""")
        check("domains: second-level column chip still frames its column clear of the bar", t and t[0] >= t[1], str(t))

        # ---- 3 move a column to another domain by dragging its hierarchy row (save-gated, undo / redo)
        # fold the column rows first (UI fold of the tree, per browser) so the source and target rows are on screen together
        js(wd, "for (let i=0;i<8;i++){ const c=document.querySelector('#tree .hrow.h-col[aria-expanded=true] .hcar'); if(!c) break; c.click(); }")
        time.sleep(0.5)
        f0 = js(wd, "return window.__editor.frames().find(f=>f.id==='auto-relance')")
        held, hit = _l10_drag_row(wd, "col:auto-relance", "d:comportement", lambda w: js(w, "return [...document.querySelectorAll('#tree .hrow.hdrop')].map(r=>r.dataset.key)"))
        check("domains: drag press on the column row, drop outline on the domain row", hit and held == ["d:comportement"], str(held))
        m = _meta(wd)
        f1 = js(wd, "return window.__editor.frames().find(f=>f.id==='auto-relance')")
        check("domains: column moved to Comportement (meta)", m["columns"]["relance"]["domain"] == "comportement", str(m["columns"].get("relance")))
        check("domains: the column frame moved inside the Comportement region", _inside(f1, _rect(wd, "comportement")) and (f1["x"], f1["y"]) != (f0["x"], f0["y"]), "%s %s" % (f1, _rect(wd, "comportement")))
        nodes_in = js(wd, """const f=window.__editor.frames().find(f=>f.id==='auto-relance'); const d=window.__editor.serialize();
          const out=d.nodes.filter(n=>n.group==='relance' && !(n.x>=f.x && n.x<=f.x+f.w && n.y>=f.y && n.y<=f.y+f.h)); return [out.length, out.slice(0,3).map(n=>[n.id,n.x,n.y]), f]""")
        check("domains: its nodes followed it", nodes_in and nodes_in[0] == 0, str(nodes_in)[:400] + " " + str([_rect(wd, d) for d in DOMS]))
        check("domains: Comportement region no longer empty", js(wd, "return !document.querySelector('.dregion[data-dom=comportement]').classList.contains('empty')"))
        rs = [_rect(wd, d) for d in DOMS]
        over = [(DOMS[i], DOMS[j]) for i in range(4) for j in range(i + 1, 4) if rs[i]["x"] < rs[j]["x"] + rs[j]["w"] and rs[j]["x"] < rs[i]["x"] + rs[i]["w"]
                and rs[i]["y"] < rs[j]["y"] + rs[j]["h"] and rs[j]["y"] < rs[i]["y"] + rs[i]["h"]]
        check("domains: regions still never overlap (the grown region pushed its neighbours)", not over, str(over))
        tree = js(wd, "return window.__editor.buildTree().kids.find(d=>d.key==='d:comportement').kids.map(k=>k.key)")
        check("domains: hierarchy shows the column under Comportement", "col:auto-relance" in (tree or []), str(tree))
        check("domains: move marks the document modified, nothing written", _dirty(wd) and not _writes(wd))
        js(wd, "window.__editor.undo()")
        time.sleep(0.4)
        f2 = js(wd, "return window.__editor.frames().find(f=>f.id==='auto-relance')")
        check("domains: undo puts the column back in Dialogue at its place", _meta(wd)["columns"]["relance"]["domain"] == "dialogue" and (f2["x"], f2["y"]) == (f0["x"], f0["y"]), str(f2))
        js(wd, "window.__editor.redo()")
        time.sleep(0.4)
        check("domains: redo moves it again", _meta(wd)["columns"]["relance"]["domain"] == "comportement")
        held2, _h = _l10_drag_row(wd, "p:note-dom-mouvement", "d:systeme", lambda w: js(w, "return [...document.querySelectorAll('#tree .hrow.hdeny')].map(r=>r.dataset.key)"))
        check("domains: only a column row can be filed in a domain (red outline for a post-it)", held2 == ["d:systeme"], str(held2))
        check("domains: the refused post-it did not move", js(wd, "const n=window.__editor.notes().find(x=>x.id==='note-dom-mouvement'); const r=window.__editor.domainRect('mouvement'); return n.x>=r.x && n.x<=r.x+r.w"))
        js(wd, "try{localStorage.removeItem('nanterino.editor.tree')}catch(e){}; window.__editor.renderTree()")

        # ---- 4 fold a domain into a card (badges), unfold, undo
        gl = js(wd, "return window.__editor.serialize().nodes.filter(n=>n.group==='global').map(n=>n.id)")
        js(wd, "window.__editor.patchNode(arguments[0], {action: 'pas_une_action_s1'})",
           [next(n["id"] for n in doc(wd)["nodes"] if n["group"] == "global" and n["kind"] == "action")])
        time.sleep(1.5)
        bad = js(wd, "const i=window.__editor.issues(); return Object.keys(i).filter(k=>i[k].some(x=>x.level==='err'))")
        js(wd, "window.__editor.focusDomain('systeme')")
        time.sleep(0.5)
        check("domains: fold button of Système clicked", _click(wd, '.dregion[data-dom="systeme"] .dfold'))
        card = js(wd, """const e=document.querySelector('.dregion[data-dom=systeme]'); return e ? [e.classList.contains('folded'), !!e.querySelector('.dcard'),
          (e.querySelector('.dcard .fcount')||{}).textContent||'', (e.querySelector('.dcard .fbadge.err')||{}).textContent||''] : null""")
        check("domains: Système folded into a card with node count", card and card[0] and card[1] and card[2].startswith("%d n" % len(gl)), str(card))
        check("domains: the card carries the error badge of its hidden content", bool(set(bad) & set(gl)) and card and card[3].startswith("✖"), "%s %s" % (bad, card))
        check("domains: folded content hidden (column frame, nodes)", _hidden_nodes(wd) == len(gl)
              and js(wd, "return document.querySelector('.frame[data-fid=auto-global]').classList.contains('fold-hide')"))
        check("domains: fold persisted in the document (meta), modified", _meta(wd)["domains"][3].get("folded") is True and _dirty(wd))
        check("domains: hierarchy row of Système still there", any(k == "d:systeme" for k, _lv in js(wd, "return [...document.querySelectorAll('#tree .hrow')].map(r=>[r.dataset.key,0])")))
        js(wd, "window.__editor.undo()")
        time.sleep(0.4)
        check("domains: undo unfolds the domain", not _meta(wd)["domains"][3].get("folded") and _hidden_nodes(wd) == 0)
        js(wd, "window.__editor.redo()")
        time.sleep(0.4)
        check("domains: Déplier button of the card unfolds", _click(wd, '.dregion[data-dom="systeme"] .funfold') and not _meta(wd)["domains"][3].get("folded") and _hidden_nodes(wd) == 0)
        for _ in range(3):                    # Déplier -> fold -> patch -> back to: relance moved, nothing patched
            js(wd, "window.__editor.undo()")
            time.sleep(0.4)
        check("domains: three undos restore the patched action, relance still in Comportement",
              not any(n["params"].get("action") == "pas_une_action_s1" for n in doc(wd)["nodes"])
              and _meta(wd)["columns"]["relance"]["domain"] == "comportement")

        # ---- 5 fold a column into a card (wires hidden), undo
        vn = js(wd, "return window.__editor.serialize().nodes.filter(n=>n.group==='veille').length")
        js(wd, "document.querySelector('#jumpbar .jchip[data-g=veille]').click()")
        time.sleep(0.6)
        check("domains: fold button of the veille column clicked", _click(wd, '.frame[data-fid="auto-veille"] .ffold'))
        fc = js(wd, """const e=document.querySelector('.frame[data-fid=auto-veille]'); return e ? [e.classList.contains('folded'), !!e.querySelector('.foldcard'),
          (e.querySelector('.foldcard .fcount')||{}).textContent||'', e.getBoundingClientRect().height] : null""")
        check("domains: column folded into a card with its node count", fc and fc[0] and fc[1] and fc[2].startswith("%d n" % vn), str(fc))
        check("domains: column nodes and their wires hidden", _hidden_nodes(wd) == vn
              and js(wd, "return document.querySelectorAll('svg.connection.fold-hide').length") > 0)
        check("domains: column fold in meta.columns", _meta(wd)["columns"]["veille"].get("folded") is True)
        js(wd, "window.__editor.undo()")
        time.sleep(0.4)
        check("domains: undo unfolds the column", not _meta(wd)["columns"]["veille"].get("folded") and _hidden_nodes(wd) == 0)
        js(wd, "window.__editor.redo()")
        time.sleep(0.4)

        # ---- 6 save (relance in Comportement, veille folded), reload: kept
        m = _meta(wd)
        check("domains: before save relance in Comportement, veille folded",
              m["columns"]["relance"]["domain"] == "comportement" and m["columns"]["veille"].get("folded") is True, str(m["columns"]))
        ok = _save_and_wait(wd)
        w = _writes(wd)
        check("domains: saved by the button (one POST /api/graph/visual)", ok and [s[1] for s in w] == ["/api/graph/visual"], str(w)[:200])
        _open(wd)
        m = _meta(wd)
        check("domains: reload keeps the column domain and the column fold",
              m["columns"]["relance"]["domain"] == "comportement" and m["columns"]["veille"].get("folded") is True, str(m["columns"]))
        check("domains: reload draws the column card and the moved column in its region",
              js(wd, "return !!document.querySelector('.frame[data-fid=auto-veille] .foldcard')")
              and _inside(js(wd, "return window.__editor.frames().find(f=>f.id==='auto-relance')"), _rect(wd, "comportement")))
        lay = json.load(open(ROOT + "/graph.layout.json"))
        check("domains: graph.layout.json holds columns + domains, graph.yaml none",
              lay.get("columns", {}).get("relance", {}).get("domain") == "comportement" and len(lay.get("domains", [])) == 4
              and "domain" not in open(ROOT + "/graph.yaml", encoding="utf-8").read())
        check("console errors 0", not js(wd, "return window.__editor.errors.length"), str(js(wd, "return window.__editor.errors"))[:200])
    finally:
        W.http("POST", BASE + "/api/graph/reset", {})
        for f in (set(glob.glob(ROOT + "/graph.*")) | set(glob.glob(ROOT + "/graph*.bak*"))) - pre:
            try:
                os.remove(f)
            except OSError:
                pass
        print("LEFT OVER", sorted((set(glob.glob(ROOT + "/graph.*")) | set(glob.glob(ROOT + "/graph*.bak*"))) - pre))


def _dirty(wd):
    time.sleep(0.2)
    return js(wd, "return window.__editor.dirtyShown()")


SCENARIOS = {
    "domains": sc_domains,
}
