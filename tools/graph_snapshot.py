"""Whole Nanterino graph as ONE full-resolution PNG (headless Firefox, read-only).

Purpose : capture the editor canvas (nodes, wires, groups, post-its) at a chosen zoom (default 100 %) without the
          editor chrome, tile by tile, and stitch the tiles with PIL, so the image is not limited by the window size.
          Used by the editor button "Exporter l'image" through POST /api/graph/snapshot (nanterino/snapshot_jobs.py)
          and runnable by hand.
Boundary: talks only to GET /editor (+ its assets) and GET /api/graph/visual[?source=default] on --base; never saves,
          never POSTs anything, never touches /api/control. Drives its OWN geckodriver (--port, default 4466) with its
          own profile root, so it never collides with the l7 WebDriver suite (geckodriver 4455, /home/robot/gdprof).
          Runs with /usr/bin/python3 (system PIL); the venv has no PIL. Standard library + PIL only (no repo import).
Invariants:
  - The capture view is translate(t) scale(s) with transform-origin 0 0 on Drawflow's precanvas; the bounding box is
    measured at translate(0,0) scale(1) in canvas pixels, so image size = ceil(bbox * s) + 2 * PAD.
  - Every tile is verified (precanvas transform read back, screenshot size == viewport size) and the bounding box is
    measured again after the last tile: any mismatch fails loudly (exit 1, message on stderr), no partial PNG is kept.
  - The output is written to <out>.part then renamed, so a reader never sees a half-written file.
  - Last stdout line on success: `RESULT {"out", "width", "height", "bytes", "tiles", "seconds", ...}` (JSON);
    progress lines `TILE i/n` (the job manager turns them into a progress value).
Usage   : /usr/bin/python3 tools/graph_snapshot.py --out /tmp/g.png [--scale 1.0] [--theme dark|light]
                  [--doc saved|default] [--crop column=veille]
Test    : run it, then check the PNG (python3 -c "from PIL import Image; print(Image.open('/tmp/g.png').size)");
          the route test and the l7 `export` scenario compare its size with the server job's PNG.
"""
import argparse
import base64
import io
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

from PIL import Image

PAD = 40                    # margin around the graph, in image pixels
WIN_W, WIN_H = 1600, 1000   # browser window; the inner viewport (tile size) is read from the page
MAX_PIXELS = 250_000_000    # refuse absurd canvases instead of exhausting the Jetson's RAM

# Capture-only stylesheet: hide the editor chrome (L22: the progress bar too), canvas fills the viewport, no animation
# between tiles.
CHROME_CSS = """
#bar,#banner,#left,#right,#msgs,#btnMsgs,#navBanner,#navHelp,#jumpbar,#minimap,#toasts,#modal,#tip,.ctxmenu,.exportpop,#progress{display:none!important}
#drawflow{position:fixed!important;left:0!important;top:0!important;width:100vw!important;height:100vh!important;z-index:9999!important}
#drawflow > .drawflow{transform-origin:0 0!important}
*,*::before,*::after{transition:none!important;animation:none!important;caret-color:transparent!important}
"""
# Light theme = the editor's own colour tokens redefined (the editor itself is dark only); accents keep their hue.
LIGHT_CSS = """
:root{--bg:#f6f7f9;--panel:#ffffff;--panel2:#eef1f5;--line:#c5ccd6;--fg:#1d2330;--mut:#5b6474;color-scheme:light}
#drawflow{background-color:var(--bg)!important;background-image:radial-gradient(#d3d8e0 1px,transparent 1px)!important}
.drawflow .drawflow-node .nsum,.drawflow .drawflow-node .nhead{color:var(--fg)}
"""
NUM = re.compile(r"-?\d+(?:\.\d+)?")


def http(method, url, body=None, timeout=60):
    data = None if body is None else json.dumps(body).encode()
    rq = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(rq, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw[:1] in b"{[" else raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


class Fail(Exception):
    """A capture problem: reported on stderr, exit code 1."""


class Browser:
    """Minimal W3C WebDriver client over a private geckodriver (own port and profile root)."""

    def __init__(self, port, profile_root):
        self.gd = "http://127.0.0.1:%d" % port
        os.makedirs(profile_root, exist_ok=True)
        self.proc = subprocess.Popen(["geckodriver", "--port", str(port), "--profile-root", profile_root],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.sid = None
        for _ in range(100):
            try:
                urllib.request.urlopen(self.gd + "/status", timeout=1)
                break
            except Exception:  # noqa: BLE001 - geckodriver still starting
                if self.proc.poll() is not None:
                    raise Fail("geckodriver exited at start (port %d busy?)" % port)
                time.sleep(0.2)
        else:
            self.close()
            raise Fail("geckodriver did not answer on port %d" % port)
        st, r = http("POST", self.gd + "/session", {"capabilities": {"alwaysMatch": {
            "browserName": "firefox", "moz:firefoxOptions": {"args": ["-headless"]}}}}, timeout=120)
        if st != 200:
            self.close()
            raise Fail("WebDriver session refused: %s %s" % (st, str(r)[:300]))
        self.sid = r["value"]["sessionId"]

    def cmd(self, method, path, body=None):
        st, r = http(method, "%s/session/%s%s" % (self.gd, self.sid, path),
                     {} if (body is None and method == "POST") else body, timeout=120)
        if st != 200:
            raise Fail("%s %s -> %s %s" % (method, path, st, str(r)[:300]))
        return r.get("value")

    def js(self, script, args=None):
        return self.cmd("POST", "/execute/sync", {"script": script, "args": args or []})

    def js_async(self, script, args=None):
        """`script` gets its callback as the LAST argument (W3C execute/async)."""
        return self.cmd("POST", "/execute/async", {"script": script, "args": args or []})

    def close(self):
        if self.sid:
            try:
                http("DELETE", "%s/session/%s" % (self.gd, self.sid), timeout=20)
            except Exception:  # noqa: BLE001 - best effort, the process is stopped below anyway
                pass
            self.sid = None
        self.proc.terminate()
        try:
            self.proc.wait(8)
        except subprocess.TimeoutExpired:
            self.proc.kill()


BBOX_JS = """const pc=document.querySelector('#drawflow > .drawflow'); if(!pc) return null;
  pc.style.transform='translate(0px, 0px) scale(1)'; const o=pc.getBoundingClientRect(); const sel=arguments[0];
  let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9,n=0;
  for(const e of pc.querySelectorAll(sel)){ const r=e.getBoundingClientRect(); if(!r.width) continue; n++;
    x0=Math.min(x0,r.x-o.x); y0=Math.min(y0,r.y-o.y); x1=Math.max(x1,r.right-o.x); y1=Math.max(y1,r.bottom-o.y); }
  return n ? [x0,y0,x1,y1,n] : null"""


def parse_args(argv):
    p = argparse.ArgumentParser(description="Full-resolution PNG of the Nanterino graph (read-only capture).")
    p.add_argument("--out", required=True, help="output PNG path")
    p.add_argument("--scale", type=float, default=1.0, help="zoom, 1.0 = 100 %% (0.1 - 2.0)")
    p.add_argument("--theme", choices=("dark", "light"), default="dark")
    p.add_argument("--doc", choices=("saved", "default"), default="saved",
                   help="saved = the graph the robot serves now; default = the packaged graph and its automatic layout")
    p.add_argument("--crop", default="", help="column=<state id> (e.g. column=veille): only that state column")
    p.add_argument("--base", default="http://127.0.0.1:8080", help="Nanterino server")
    p.add_argument("--port", type=int, default=4466, help="private geckodriver port (the l7 suite uses 4455)")
    p.add_argument("--profile-root", default="/home/robot/gdprof-snapshot")
    a = p.parse_args(argv)
    if not 0.1 <= a.scale <= 2.0:
        p.error("--scale must be within 0.1 - 2.0")
    if a.crop and not re.fullmatch(r"column=[A-Za-z0-9_-]{1,60}", a.crop):
        p.error("--crop must be column=<id>")
    return a


def selector_for(crop):
    if not crop:
        return ".drawflow-node,.frame,.postit,.dregion"   # S1: domain regions (empty ones too) are part of the graph
    cid = crop.split("=", 1)[1]
    fid = cid if cid.startswith("auto-") else "auto-" + cid
    return '.frame[data-fid="%s"]' % fid


def wait_editor(b, secs=60):
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            if b.js("return !!(window.__editor && window.__editor.nodeCount() > 0)"):
                return
        except Fail:
            pass
        time.sleep(0.3)
    raise Fail("editor not ready after %d s (no node drawn)" % secs)


def settle(b):
    """Fonts loaded + two animation frames painted."""
    b.js_async("const cb=arguments[arguments.length-1]; "
               "document.fonts.ready.then(()=>requestAnimationFrame(()=>requestAnimationFrame(()=>cb(true))))")


def capture(a):
    t0 = time.time()
    b = Browser(a.port, a.profile_root)
    try:
        b.cmd("POST", "/window/rect", {"width": WIN_W, "height": WIN_H, "x": 0, "y": 0})
        b.cmd("POST", "/url", {"url": "about:blank"})
        b.cmd("POST", "/url", {"url": a.base.rstrip("/") + "/editor#quiet"})
        wait_editor(b)
        time.sleep(1.5)             # first check / tree / live poll settle (same pause as the l7 driver)
        if a.doc == "default":
            n = b.js_async("""const cb=arguments[arguments.length-1];
              fetch('/api/graph/visual?source=default').then(r=>r.ok?r.json():null).then(d=>{
                if(!d||!Array.isArray(d.nodes)){cb(-1);return;} window.__editor.rebuild(d); cb(d.nodes.length);}).catch(()=>cb(-2));""")
            if not isinstance(n, int) or n <= 0:
                raise Fail("default graph could not be loaded in the page (%s)" % n)
            time.sleep(1.5)
        b.js("const st=document.createElement('style'); st.id='snapshotCss'; st.textContent=arguments[0]; "
             "document.head.appendChild(st);", [CHROME_CSS + (LIGHT_CSS if a.theme == "light" else "")])
        settle(b)
        time.sleep(0.5)
        vw, vh = b.js("return [window.innerWidth, window.innerHeight]")
        sel = selector_for(a.crop)
        bb = b.js(BBOX_JS, [sel])
        if not bb:
            raise Fail("nothing to capture for selector %s" % sel)
        x0, y0, x1, y1, count = bb
        s = a.scale
        w, h = int(math.ceil((x1 - x0) * s)) + 2 * PAD, int(math.ceil((y1 - y0) * s)) + 2 * PAD
        if w * h > MAX_PIXELS:
            raise Fail("image would be %dx%d px (> %d px): lower --scale" % (w, h, MAX_PIXELS))
        ntiles = int(math.ceil(w / vw)) * int(math.ceil(h / vh))
        print("BBOX", [round(v, 1) for v in bb[:4]], "items", count, "image", w, h, "viewport", vw, vh,
              "tiles", ntiles, flush=True)
        img, k = None, 0
        for ty in range(0, h, vh):
            for tx in range(0, w, vw):
                k += 1
                want = "translate(%dpx, %dpx) scale(%s)" % (int(round(PAD - x0 * s - tx)), int(round(PAD - y0 * s - ty)), s)
                b.js("document.querySelector('#drawflow > .drawflow').style.transform=arguments[0]", [want])
                settle(b)
                got = b.js("return document.querySelector('#drawflow > .drawflow').style.transform") or ""
                # Firefox may normalise the text ("scale(1.0)" -> "scale(1)"): compare the numbers
                if [float(v) for v in NUM.findall(got)] != [float(v) for v in NUM.findall(want)]:
                    raise Fail("tile %d: view transform is %r, expected %r (the editor moved the view)" % (k, got, want))
                tile = Image.open(io.BytesIO(base64.b64decode(b.cmd("GET", "/screenshot")))).convert("RGB")
                if tile.size != (vw, vh):
                    raise Fail("tile %d: screenshot is %s, viewport is %dx%d" % (k, tile.size, vw, vh))
                if img is None:
                    img = Image.new("RGB", (w, h), tile.getpixel((2, 2)))
                img.paste(tile.crop((0, 0, min(vw, w - tx), min(vh, h - ty))), (tx, ty))
                print("TILE %d/%d" % (k, ntiles), flush=True)
        bb2 = b.js(BBOX_JS, [sel])
        if not bb2 or any(abs(p - q) > 0.5 for p, q in zip(bb[:4], bb2[:4])):
            raise Fail("graph layout changed during the capture (%s -> %s)" % (bb[:4], bb2 and bb2[:4]))
        errors = b.js("return (window.__editor.errors || []).slice(0, 5)") or []
    finally:
        b.close()
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    part = out + ".part"
    img.save(part, format="PNG", optimize=True)
    os.replace(part, out)
    res = {"out": out, "width": w, "height": h, "bytes": os.path.getsize(out), "tiles": k, "items": count,
           "scale": s, "theme": a.theme, "doc": a.doc, "crop": a.crop or None, "seconds": round(time.time() - t0, 1),
           "editor_errors": errors}
    print("RESULT " + json.dumps(res), flush=True)
    return res


def main(argv=None):
    a = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        capture(a)
    except Fail as e:
        print("SNAPSHOT FAILED: %s" % e, file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
