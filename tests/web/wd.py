"""WebDriver session for the Nanterino editor web tests (headless Firefox through geckodriver).

Purpose : open one geckodriver + Firefox session, send W3C WebDriver commands, load the editor and wait until ready.
Boundary: talks HTTP to the live Nanterino server (BASE) and to geckodriver (GD) only; never imports nanterino.
          Copied verbatim (M7) from /opt/robot/scripts/editor2_wd.py so the repo suite has no dependency on scripts/.
Invariant: the snap geckodriver cannot use /tmp as its profile root, hence --profile-root /home/robot/gdprof.
Test    : used by tests/web/run.py; no tests of its own.
"""
import base64, json, os, subprocess, sys, time, urllib.request, urllib.error

BASE = "http://127.0.0.1:8080"
GD = "http://127.0.0.1:4455"
OUT = "/opt/robot/nanterino/tests/results"


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
        except Exception:
            return e.code, raw


class WD:
    def __init__(self):
        os.makedirs("/home/robot/gdprof", exist_ok=True)
        self.proc = subprocess.Popen(["geckodriver", "--port", "4455", "--profile-root", "/home/robot/gdprof"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                urllib.request.urlopen(GD + "/status", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        st, r = http("POST", GD + "/session", {"capabilities": {"alwaysMatch": {
            "browserName": "firefox", "moz:firefoxOptions": {"args": ["-headless"]}}}}, timeout=90)
        if st != 200:
            raise RuntimeError("session: %s %s" % (st, r))
        self.sid = r["value"]["sessionId"]
        self.cmd("POST", "/window/rect", {"width": 1600, "height": 950, "x": 0, "y": 0})

    def cmd(self, m, p, b=None):
        st, r = http(m, "%s/session/%s%s" % (GD, self.sid, p), {} if (b is None and m == "POST") else b)
        if st != 200:
            raise RuntimeError("%s %s -> %s %s" % (m, p, st, r))
        return r.get("value")

    def go(self, url):
        self.cmd("POST", "/url", {"url": url})

    def js(self, script, args=None):
        return self.cmd("POST", "/execute/sync", {"script": script, "args": args or []})

    def shot(self, name):
        b = self.cmd("GET", "/screenshot")
        path = os.path.join(OUT, name)
        with open(path, "wb") as f:
            f.write(base64.b64decode(b))
        print("SHOT", path, os.path.getsize(path))

    def close(self):
        try:
            http("DELETE", "%s/session/%s" % (GD, self.sid))
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except Exception:
            self.proc.kill()


def wait_ready(wd, secs=25):
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            if wd.js("return !!(window.__editor && window.__editor.nodeCount() > 0)"):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def open_editor(wd, hash_=""):
    wd.go("about:blank")
    wd.go(BASE + "/editor" + hash_)
    ok = wait_ready(wd)
    print("ready", ok)
    time.sleep(1.8)
