"""Tests of the graph PNG export job manager (lot L14, 2026-11-01): nanterino/snapshot_jobs.py.

Purpose
    Single-flight (a second start while a capture runs gets the running job), cache hit by key (no subprocess,
    instant), cache key sensitivity (doc / options / code; volatile `error` / `pending` ignored), timeout handling
    (the whole process group is killed, job `failed`, no temp file left), failed capture (exit code, no RESULT line,
    not a PNG), progress from `TILE i/n` lines, pruning of old cache entries, and a static check that server.py runs
    the capture without blocking (threadpool / thread) and never touches /api/control from these routes.

Boundary
    The capture tool is replaced by tiny `sys.executable -c` programs that write a real minimal PNG (no Firefox, no
    server). Files are only written under /tmp/test_graph_snapshot_jobs. nanterino.server is never imported (its
    module level builds the live Brain): server.py is read as text / parsed with ast.

How to run (repo root):
    .venv/bin/python -m tests.test_graph_snapshot_jobs          # ~10 s
"""
import ast
import os
import shutil
import sys
import time

from nanterino import snapshot_jobs as SJ

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = "/tmp/test_graph_snapshot_jobs"

# A fake capture: optional sleep, TILE lines, then writes a WxH PNG to argv[-1] and prints RESULT.
FAKE = r'''
import json, struct, sys, time, zlib
mode, w, h, delay, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
for i in range(1, 4):
    print("TILE %d/3" % i, flush=True)
    time.sleep(delay / 3)
if mode == "fail":
    print("SNAPSHOT FAILED: boom", flush=True); sys.exit(1)
if mode == "notpng":
    open(out, "wb").write(b"nope"); print("RESULT {}", flush=True); sys.exit(0)
def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
open(out, "wb").write(png)
if mode != "noresult":
    print("RESULT " + json.dumps({"width": w, "height": h}), flush=True)
'''


def fresh(sub):
    d = os.path.join(TMP, sub)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    return d


def builder(calls, mode="ok", w=30, h=20, delay=0.3):
    def build(options, out):
        calls.append((dict(options), out))
        return [sys.executable, "-c", FAKE, options.get("mode", mode), str(options.get("w", w)), str(h),
                str(options.get("delay", delay)), out]
    return build


def leftovers(d):
    return [n for n in os.listdir(d) if n.startswith("tmp-")]


def test_key_sensitivity():
    doc = {"nodes": [{"id": "n1"}], "links": [], "error": None, "pending": False}
    k = SJ.snapshot_key(doc, {"scale": 1.0}, "c1")
    assert k == SJ.snapshot_key({**doc, "error": "x", "pending": True}, {"scale": 1.0}, "c1"), "volatile keys ignored"
    assert k != SJ.snapshot_key({**doc, "nodes": [{"id": "n2"}]}, {"scale": 1.0}, "c1"), "doc change"
    assert k != SJ.snapshot_key(doc, {"scale": 0.5}, "c1"), "option change"
    assert k != SJ.snapshot_key(doc, {"scale": 1.0}, "c2"), "code change"
    assert len(k) == 24 and k == SJ.snapshot_key(doc, {"scale": 1.0}, "c1"), "stable"


def test_files_signature_changes():
    d = fresh("sig")
    p = os.path.join(d, "a.js")
    open(p, "w").write("1")
    s1 = SJ.files_signature([p])
    time.sleep(0.01)
    open(p, "w").write("22")
    assert SJ.files_signature([p]) != s1
    assert SJ.files_signature([p + ".missing"]) != SJ.files_signature([p])


def test_capture_then_cache_hit():
    d, calls = fresh("cache"), []
    m = SJ.SnapshotJobs(d, builder(calls), timeout_s=30)
    j = m.start("k1", {"w": 33})
    assert j["state"] == "running" and not j["cache_hit"], j
    assert m.wait(20)
    s = m.status()
    assert s["state"] == "done" and (s["width"], s["height"]) == (33, 20) and s["progress"] == 1.0, s
    assert SJ.png_size(m.png_path("k1")) == (33, 20) and not leftovers(d)
    t0 = time.time()
    j2 = m.start("k1", {"w": 33})
    assert j2["state"] == "done" and j2["cache_hit"] and (j2["width"], j2["height"]) == (33, 20), j2
    assert time.time() - t0 < 0.2 and len(calls) == 1, "cache hit must not run the tool"
    assert j2["id"] == j["id"] + 1


def test_single_flight():
    d, calls = fresh("single"), []
    m = SJ.SnapshotJobs(d, builder(calls, delay=1.5), timeout_s=30)
    a = m.start("kA", {})
    b = m.start("kB", {"w": 99})          # another key while A runs: gets A
    assert b["already_running"] and b["id"] == a["id"] and b["key"] == "kA", b
    assert m.wait(20) and m.status()["state"] == "done"
    assert len(calls) == 1, "the refused start must not have launched a second capture"
    c = m.start("kB", {"w": 99})          # A finished: B may start now
    assert c["state"] == "running" and c["key"] == "kB"
    assert m.wait(20) and m.status()["width"] == 99 and len(calls) == 2


def test_progress_reported():
    d, calls = fresh("progress"), []
    m = SJ.SnapshotJobs(d, builder(calls, delay=2.4), timeout_s=30)
    m.start("kp", {})
    seen = set()
    t0 = time.time()
    while time.time() - t0 < 10:
        s = m.status()
        seen.add(s["progress"])
        if s["state"] != "running":
            break
        assert s["seconds"] is not None
        time.sleep(0.1)
    assert any(0 < p < 1 for p in seen), seen


def test_timeout_kills_group():
    d, calls = fresh("timeout"), []
    m = SJ.SnapshotJobs(d, builder(calls, delay=60), timeout_s=1.0)
    m.start("kt", {})
    t0 = time.time()
    assert m.wait(15), "timeout must end the job"
    s = m.status()
    assert s["state"] == "failed" and "timeout" in s["error"], s
    assert time.time() - t0 < 10
    assert not os.path.exists(m.png_path("kt")) and not leftovers(d)
    # the next start runs again (no stuck single-flight)
    m2 = m.start("kt", {"delay": 0.1})
    assert m2["state"] == "running" and m.wait(20) and m.status()["state"] == "done"


def test_failures_are_reported():
    for mode, word in (("fail", "exit 1"), ("notpng", "capture failed"), ("noresult", "capture failed")):
        d, calls = fresh("fail-" + mode), []
        m = SJ.SnapshotJobs(d, builder(calls, mode=mode, delay=0.1), timeout_s=30)
        m.start("kf", {})
        assert m.wait(20)
        s = m.status()
        assert s["state"] == "failed" and word in s["error"], (mode, s)
        assert m.cached("kf") is None and not leftovers(d), mode
    d = fresh("launch")
    m = SJ.SnapshotJobs(d, lambda o, out: ["/nonexistent/tool"], timeout_s=5)
    m.start("kl", {})
    assert m.wait(10) and "launch failed" in m.status()["error"]


def test_prune_keeps_newest():
    d, calls = fresh("prune"), []
    m = SJ.SnapshotJobs(d, builder(calls, delay=0), timeout_s=30, keep=2)
    for k in ("p1", "p2", "p3"):
        m.start(k, {})
        assert m.wait(20) and m.status()["state"] == "done"
        time.sleep(0.05)
    names = sorted(os.listdir(d))
    assert names == ["p2.json", "p2.png", "p3.json", "p3.png"], names


def test_server_routes_static():
    """server.py (never imported): the snapshot routes exist, start the job off the event loop and leave
    /api/control alone."""
    src = open(os.path.join(ROOT, "nanterino", "server.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    routes = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in n.decorator_list:
                if isinstance(dec, ast.Call) and getattr(dec.func, "attr", "") in ("get", "post") and dec.args:
                    routes[(dec.func.attr, getattr(dec.args[0], "value", None))] = n
    for r in (("post", "/api/graph/snapshot"), ("get", "/api/graph/snapshot/status"), ("get", "/api/graph/snapshot.png")):
        assert r in routes, r
    post = ast.get_source_segment(src, routes[("post", "/api/graph/snapshot")])
    assert "run_in_threadpool" in post, "the POST must compute the doc / start the job off the event loop"
    for fn in routes.values():
        seg = ast.get_source_segment(src, fn)
        assert "/api/control" not in seg and "brain.control" not in seg
    assert "nice" in src and "/usr/bin/python3" in src and "graph_snapshot.py" in src
    assert "attachment" in src and "nanterino-graph-" in src


TESTS = [test_key_sensitivity, test_files_signature_changes, test_capture_then_cache_hit, test_single_flight,
         test_progress_reported, test_timeout_kills_group, test_failures_are_reported, test_prune_keeps_newest,
         test_server_routes_static]


def main(only):
    failed = 0
    for fn in TESTS:
        if only and fn.__name__ not in only:
            continue
        try:
            fn()
            print("PASS", fn.__name__, flush=True)
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print("FAIL", fn.__name__, "%s: %s" % (type(e).__name__, e), flush=True)
    ran = len([f for f in TESTS if not only or f.__name__ in only])
    print("graph_snapshot_jobs tests: %d passed, %d failed" % (ran - failed, failed))
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
