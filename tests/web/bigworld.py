"""Nanterino editor web scenario of lot S3 ("espace sans limite" A4 + A5): the editor on a graph ten times the shipped one.

Purpose : `bigworld`: a synthetic 10x document (tests/bigworld_gen.py: ~2,300 nodes, 15 domains, 84 columns) is loaded
          through the path a user document takes (GET /api/graph/visual answered by a fetch stub in the page, then
          loadAll()); the scenario MEASURES it against the shipped graph (load to interactive, pan / zoom frames, minimap
          frame, column fold + unfold, DOM size) and prints one `BIGWORLD <label> {...}` line per graph.
Boundary: drives the live editor through tests/web/driver.py; never imports nanterino.server; never saves (the fetch stub
          only answers GET /api/graph/visual, every other request goes to the robot; the dry-run checks of the big document
          are POSTs to /api/graph/check, which write nothing); never touches graph.yaml / graph.layout.json.
Test    : .venv/bin/python -m tests.web.run bigworld
"""
import json
import os
import time
import urllib.request

from tests.web.driver import *  # noqa: F401,F403  (shared helpers, check(), W, BASE, ROOT)
from tests.web.savegate import SPY_JS, _writes
from tests.bigworld_gen import replicate

COPIES = int(os.environ.get("BIGWORLD_COPIES", "12"))      # 12 Dialogue copies = ~2,300 nodes (smaller values for profiling)
SKIP_SHIPPED = bool(os.environ.get("BIGWORLD_SKIP_SHIPPED"))


def shipped_doc():
    """The packaged default document, as the editor receives it."""
    with urllib.request.urlopen(BASE + "/api/graph/visual?source=default", timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _async(wd, body, args=None, wait=900, step=0.25):
    """Run `body` (async function body, may `return` a value) in the page and poll for its result."""
    js(wd, "window.__s3res = null; (async (...args) => { try { window.__s3res = {v: await (async () => {%s})()}; } catch (e) { window.__s3res = {err: String(e)}; } })(...arguments); return true" % body, args or [])
    for _ in range(int(wait / step)):
        time.sleep(step)
        try:
            r = js(wd, "return window.__s3res")
        except (TimeoutError, OSError):      # the page is busy (a 10x rebuild blocks its main thread for a while): ask again
            continue
        if r:
            if "err" in r:
                raise RuntimeError(r["err"])
            return r["v"]
    raise RuntimeError("page job timed out")


LOAD_JS = """
const doc = args[0], orig = window.fetch;
window.fetch = (p, o) => (String(p).startsWith('/api/graph/visual') && !(o && o.method === 'POST'))
  ? Promise.resolve(new Response(JSON.stringify(doc), {status: 200, headers: {'Content-Type': 'application/json'}})) : orig(p, o);
const t0 = performance.now();
try { await window.__editor.loadAll(); } finally { window.fetch = orig; }
const t1 = performance.now();
await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
return {load_ms: Math.round(t1 - t0), interactive_ms: Math.round(performance.now() - t0), nodes: window.__editor.nodeCount(), dom: document.querySelectorAll('*').length, phases: (window.__editor.perf() || {}).marks};
"""

# Pan / zoom frames: wheel events (the editor's own navigation path) one per frame; dx / dy per frame, ctrl zoom every
# third frame when `zoom` is set. Returns total ms for the frames and the layout reads counted meanwhile.
FRAMES_JS = """
const [dx, dy, zoom] = args, E = window.__editor, df = document.querySelector('#drawflow'), cnt = {n: 0};
const undo = [], hit = () => { if (cnt.on) cnt.n++; };
for (const [proto, props] of [[HTMLElement.prototype, ['offsetWidth', 'offsetHeight', 'offsetLeft', 'offsetTop']], [Element.prototype, ['clientWidth', 'clientHeight', 'scrollWidth', 'scrollHeight']]]) {
  for (const p of props) { const d = Object.getOwnPropertyDescriptor(proto, p); Object.defineProperty(proto, p, {configurable: true, get() { hit(); return d.get.call(this); }}); undo.push(() => Object.defineProperty(proto, p, d)); }
}
const gb = Element.prototype.getBoundingClientRect; Element.prototype.getBoundingClientRect = function () { hit(); return gb.call(this); }; undo.push(() => { Element.prototype.getBoundingClientRect = gb; });
const st = df.getBoundingClientRect(), x = st.x + st.width * 0.45, y = st.y + st.height * 0.5;
cnt.on = true;
const t0 = performance.now(), n = 60, per = [];
for (let i = 0; i < n; i++) {
  const ctrl = zoom && i % 3 === 2, f0 = performance.now();
  df.dispatchEvent(new WheelEvent('wheel', {bubbles: true, cancelable: true, clientX: x, clientY: y, deltaX: ctrl ? 0 : dx, deltaY: ctrl ? (i % 2 ? 40 : -40) : dy, deltaMode: 0, ctrlKey: ctrl}));
  await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));
  per.push(performance.now() - f0);
}
cnt.on = false; undo.forEach((f) => f());
per.sort((a, b) => a - b);
return {ms: Math.round(performance.now() - t0), frame_ms: Math.round((performance.now() - t0) / n), p90_ms: Math.round(per[Math.floor(n * 0.9)]), reads: cnt.n, zoom: E.nav().zoom};
"""

MINI_JS = """
const E = window.__editor; E.drawMinimap(); const t0 = performance.now(); for (let i = 0; i < 30; i++) E.drawMinimap();
return {mini_ms: Math.round((performance.now() - t0) / 30 * 100) / 100};
"""

FOLD_JS = """
const E = window.__editor, g = args[0], nextFrame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
let t0 = performance.now(); E.foldColumn(g, true); const f1 = performance.now() - t0; await nextFrame(); const f2 = performance.now() - t0;
t0 = performance.now(); E.foldColumn(g, false); const u1 = performance.now() - t0; await nextFrame(); const u2 = performance.now() - t0;
return {fold_ms: Math.round(f1), fold_settle_ms: Math.round(f2), unfold_ms: Math.round(u1), unfold_settle_ms: Math.round(u2)};
"""


# Shown wires (no `cull` class) that have no path or no gradient: must be 0 whatever was culled before.
UNDRAWN_JS = ("return [...document.querySelectorAll('svg.connection:not(.cull)')].filter(s => s.classList.length >= 5 && "
              "!((s.querySelector('.main-path') || {getAttribute: () => ''}).getAttribute('d') && s.querySelector('linearGradient'))).length")


def load(wd, doc):
    js(wd, SPY_JS)
    return _async(wd, LOAD_JS, [doc])


def measure(wd, label, doc, col):
    """All numbers of one graph; `col` = a column id of that graph (the one folded and focused)."""
    out = {"label": label}
    out.update(load(wd, doc))
    time.sleep(2.0)                                     # let the dry-run check and the tree settle
    js(wd, "window.__editor.fit()")
    time.sleep(0.8)
    out["fit"] = _async(wd, FRAMES_JS, [7, 5, True])
    js(wd, "document.querySelector('#jumpbar .jchip[data-g=\"' + arguments[0] + '\"]').click()", [col])
    time.sleep(0.8)
    out["col"] = _async(wd, FRAMES_JS, [7, 5, True])    # readable zoom, small moves (in-place frames)
    out["travel"] = _async(wd, FRAMES_JS, [400, 60, False])   # readable zoom, long pan across columns
    # right after the long pan (columns never seen before, nothing moved: only the cull pass can have drawn their wires)
    time.sleep(0.3)
    out["undrawn_travel"] = js(wd, UNDRAWN_JS)
    # a jump to the far end of the document (the last node: last copy, never shown so far), then back to the column
    js(wd, "const ks = Object.keys(window.__editor.dfMap()); window.__editor.focusNode(ks[ks.length - 1])")
    time.sleep(0.8)
    out["undrawn_jump"] = js(wd, UNDRAWN_JS)
    out["shown_jump"] = js(wd, "return document.querySelectorAll('svg.connection:not(.cull)').length")
    out.update(_async(wd, MINI_JS))
    js(wd, "document.querySelector('#jumpbar .jchip[data-g=\"' + arguments[0] + '\"]').click()", [col])
    time.sleep(0.5)
    out.update(_async(wd, FOLD_JS, [col]))
    out["culled"] = js(wd, "return document.querySelectorAll('.parent-node.cull').length")   # the cull class sits on the wrapper
    # correctness of the deferred drawing: after the travel and the fold, every SHOWN wire has a path and a gradient
    out["undrawn"] = js(wd, UNDRAWN_JS)
    out["shown_wires"] = js(wd, "return document.querySelectorAll('svg.connection:not(.cull)').length")
    print("BIGWORLD", json.dumps(out), flush=True)
    return out


def sc_bigworld(wd):
    open_editor(wd)
    js(wd, "window.__editor.closeCtx && window.__editor.closeCtx()")
    base = shipped_doc()
    big = replicate(base, COPIES)
    m0 = None if SKIP_SHIPPED else measure(wd, "shipped", base, "veille")
    m1 = measure(wd, "x10", big, "veille_5" if COPIES >= 5 else "veille_2")
    # Thresholds: the S3 after-numbers on the Orin (headless Firefox) with generous headroom (about 3x), so a loaded robot
    # does not flake while a return to the pre-S3 behaviour (62 s load, 2.3 s overview frames, 33 s fold) is still caught.
    for m, lim in ((m0, {"load": 4000, "ready": 6000, "frame": 300, "fold": 3000}),
                   (m1, {"load": 12000, "ready": 20000, "frame": 300, "fold": 6000})):
        if m is None:
            continue
        lb = m["label"]
        check("bigworld %s: load <= %d ms, ready <= %d ms" % (lb, lim["load"], lim["ready"]),
              m["load_ms"] <= lim["load"] and m["interactive_ms"] <= lim["ready"], "%s %s" % (m["load_ms"], m["interactive_ms"]))
        check("bigworld %s: pan / zoom frames (overview, column, travel) <= %d ms each" % (lb, lim["frame"]),
              all(m[k]["frame_ms"] <= lim["frame"] for k in ("fit", "col", "travel")), str([m[k]["frame_ms"] for k in ("fit", "col", "travel")]))
        check("bigworld %s: one minimap frame <= 50 ms" % lb, m["mini_ms"] <= 50, str(m["mini_ms"]))
        check("bigworld %s: fold and unfold settle <= %d ms" % (lb, lim["fold"]),
              m["fold_settle_ms"] <= lim["fold"] and m["unfold_settle_ms"] <= lim["fold"], "%s %s" % (m["fold_settle_ms"], m["unfold_settle_ms"]))
    check("bigworld x10: off-screen nodes are culled", m1["culled"] > 0, str(m1["culled"]))
    for m in (m0, m1):
        if m is not None:
            check("bigworld %s: every shown wire has a path and a gradient (after the long pan, after the fold)" % m["label"],
                  m["shown_wires"] > 0 and m["shown_jump"] > 0 and m["undrawn"] == 0 and m["undrawn_travel"] == 0 and m["undrawn_jump"] == 0,
                  "travel %s, jump %s of %s, fold %s of %s" % (m["undrawn_travel"], m["undrawn_jump"], m["shown_jump"], m["undrawn"], m["shown_wires"]))
    check("bigworld: console errors 0, nothing saved", not js(wd, "return window.__editor.errors.length") and not _writes(wd),
          str(js(wd, "return window.__editor.errors"))[:200])


SCENARIOS = {"bigworld": sc_bigworld}
