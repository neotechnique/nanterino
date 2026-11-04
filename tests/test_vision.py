"""Tests of the camera retry loop of nanterino.vision (lot L45, 2026-11-04): no pipe.start() without a device.

logging: robotlog via nanterino.log (the Vision log calls are captured by a recorder here).

Purpose
    Root cause of the L45 server stalls: with the RealSense unplugged, pyrealsense2's pipeline.start() searched for
    ~15 s WITHOUT releasing the GIL, freezing every server thread every 20 s (brain watchdog trips, audio underflows,
    slow HTTP). Vision._run now probes Vision._device_count() (query_devices, ~20 ms) first and never enters _loop()
    (which calls pipe.start) while no device is seen. Checked here: no device -> _loop never called, state
    camera=False, on_faces(0), ONE warning per absence; device seen -> _loop called; a _loop failure is still logged
    and retried; a new absence logs again.
Boundary
    No camera and no pyrealsense2 call: _device_count and _loop are overridden in a subclass; the module's `time` and
    `log` are swapped for fast/recording shims (restored at the end). nanterino.server is never imported.
How to run (repo root)
    .venv/bin/python -m tests.test_vision      # ~2 s; prints PASS / FAIL and `vision tests: n/n passed`
"""
import sys
import threading
import time

sys.path.insert(0, "/opt/robot/lib")
sys.path.insert(0, "/opt/robot/nanterino")
from nanterino import vision as VM  # noqa: E402

res = []


def check(name, ok):
    res.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, flush=True)


class _FastTime:
    """vision's `time` during the test: the 5 s retry sleeps become 10 ms."""
    monotonic = staticmethod(time.monotonic)

    @staticmethod
    def sleep(_s):
        time.sleep(0.01)


class _Log:
    def __init__(self):
        self.lines, self.lock = [], threading.Lock()

    def _add(self, fmt, *a):
        with self.lock:
            self.lines.append(fmt % a if a else fmt)

    warning = info = error = debug = _add

    def count(self, part):
        with self.lock:
            return sum(1 for x in self.lines if part in x)


class FakeVision(VM.Vision):
    """Device count scripted by the test; _loop records calls (it is where pipe.start lives)."""
    devices = 0
    loop_calls = 0
    loop_error = "unplugged"

    def _device_count(self):
        return type(self).devices

    def _loop(self):
        type(self).loop_calls += 1
        raise RuntimeError(type(self).loop_error)


def wait_until(pred, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def main():
    real_time, real_log = VM.time, VM.log
    rec = _Log()
    VM.time, VM.log = _FastTime, rec
    try:
        faces = []
        FakeVision.devices, FakeVision.loop_calls = 0, 0
        v = FakeVision.__new__(FakeVision)
        # Same state as __init__ but on_faces is wired BEFORE the thread starts (no race on the first poll).
        v.max_dist_m, v.lost_face_s = 3.0, 10.0
        v.state = {"present": True, "x": 0.0, "y": 0.0, "dist_m": None, "track_id": 1, "fps": 0.0,
                   "camera": True, "faces": 2}
        v._box, v._last_seen, v._next_id, v._lost_fired = None, 0.0, 1, False
        v.on_face = v.on_face_lost = None
        v.on_faces = faces.append
        threading.Thread(target=v._run, daemon=True, name="vision-test").start()

        # 1. No device: many polls, pipe.start (_loop) never reached, one warning only.
        wait_until(lambda: len(faces) >= 20)
        check("no device: polled repeatedly", len(faces) >= 20)
        check("no device: _loop (pipe.start) never called", FakeVision.loop_calls == 0)
        check("no device: state says no camera, no face",
              v.state["camera"] is False and v.state["present"] is False and v.state["faces"] == 0)
        check("no device: on_faces(0) reported", faces and set(faces) == {0})
        check("no device: one warning per absence", rec.count("no RealSense camera connected") == 1)
        check("no device: no 'vision stopped' spam", rec.count("vision stopped") == 0)

        # 2. Device seen: _loop runs; its failure is still logged and retried.
        FakeVision.devices = 1
        check("device seen: _loop called", wait_until(lambda: FakeVision.loop_calls >= 2))
        check("device seen: failure logged as vision stopped", rec.count("vision stopped: unplugged") >= 1)

        # 3. Device gone again: the absence warning re-arms (logged a second time, once).
        FakeVision.devices = 0
        time.sleep(0.05)
        calls = FakeVision.loop_calls
        time.sleep(0.2)
        check("gone again: _loop no longer called", FakeVision.loop_calls == calls)
        check("gone again: absence logged once more", rec.count("no RealSense camera connected") == 2)

        # 4. The real probe uses query_devices (not pipeline.start) - static check of the seam.
        import inspect
        src = inspect.getsource(VM.Vision._device_count)
        check("real probe is query_devices, not pipeline", "query_devices()" in src and "rs.pipeline" not in src)
        run_src = inspect.getsource(VM.Vision._run)
        check("_run probes before _loop", run_src.index("_device_count()") < run_src.index("self._loop()"))
    finally:
        VM.time, VM.log = real_time, real_log
    print(f"vision tests: {sum(res)}/{len(res)} passed")
    sys.exit(0 if all(res) else 1)


if __name__ == "__main__":
    main()
