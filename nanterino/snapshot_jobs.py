"""Single-flight job manager for the full-resolution graph PNG export (lot L14).

Purpose : run tools/graph_snapshot.py as a low-priority subprocess for POST /api/graph/snapshot, report its progress
          to GET /api/graph/snapshot/status (`progress` 0-1 = tiles done / total; L22 adds `phase`: launch -> tiles ->
          encode -> done | failed, for the editor progress bar) and keep the produced PNGs as a small cache keyed by a hash of
          (served visual document + options + editor/tool code), so an unchanged graph is answered instantly.
Boundary: pure standard library, no FastAPI / Brain import (unit-testable: tests/test_graph_snapshot_jobs.py). The
          server gives it `build_cmd(options, out_path) -> argv`; this module never decides what the command is.
          The capture runs in a daemon thread + its own process group: the asyncio loop and the robot loop never
          wait for it.
Invariants:
  - At most ONE capture runs at a time; start() while one runs returns that running job (`already_running`).
  - A key whose PNG is already in the cache gives a `done` job with `cache_hit: True` at once (no subprocess).
  - A capture that exceeds `timeout_s` is killed as a whole process group (geckodriver + Firefox too): SIGTERM,
    then SIGKILL after 5 s; the job ends `failed` with error "timeout".
  - A cache entry is <key>.png + <key>.json (meta); the PNG is renamed into place only after its PNG signature
    was checked, so a served file is always complete. At most `keep` entries are kept (oldest removed first).
Test    : .venv/bin/python -m tests.test_graph_snapshot_jobs   (no pytest in the venv)
"""
import hashlib
import json
import os
import signal
import subprocess
import threading
import time

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def snapshot_key(doc: dict, options: dict, code_sig: str = "") -> str:
    """Cache key: the visual document as served (volatile `error` / `pending` dropped), the options and a code
    signature (editor assets + capture tool), so a deploy that changes the drawing invalidates the cache."""
    clean = {k: v for k, v in (doc or {}).items() if k not in ("error", "pending")}
    blob = json.dumps({"doc": clean, "opt": options, "code": code_sig}, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def files_signature(paths) -> str:
    """Cheap signature of files (path, size, mtime): changes when one of them is redeployed."""
    parts = []
    for p in paths:
        try:
            st = os.stat(p)
            parts.append("%s:%d:%d" % (p, st.st_size, st.st_mtime_ns))
        except OSError:
            parts.append("%s:missing" % p)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def png_size(path: str):
    """(width, height) from the IHDR chunk, or None when the file is not a PNG."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != PNG_SIG or head[12:16] != b"IHDR":
        return None
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


class SnapshotJobs:
    def __init__(self, out_dir: str, build_cmd, timeout_s: float = 360.0, keep: int = 12, clock=time.time):
        self.out_dir, self.build_cmd, self.timeout_s, self.keep, self.clock = out_dir, build_cmd, timeout_s, keep, clock
        self._lock = threading.Lock()
        self._job = None          # last / current job (dict, copied on read)
        self._seq = 0
        self._thread = None

    # ---- paths
    def png_path(self, key: str) -> str:
        return os.path.join(self.out_dir, key + ".png")

    def _meta_path(self, key: str) -> str:
        return os.path.join(self.out_dir, key + ".json")

    def cached(self, key: str):
        """Meta of a complete cache entry, or None."""
        png, meta = self.png_path(key), self._meta_path(key)
        if not (os.path.isfile(png) and os.path.isfile(meta)) or png_size(png) is None:
            return None
        try:
            with open(meta, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    # ---- API
    def start(self, key: str, options: dict) -> dict:
        with self._lock:
            if self._job and self._job["state"] == "running":
                return {**self._job, "already_running": True}
            self._seq += 1
            now = self.clock()
            meta = self.cached(key)
            if meta is not None:
                try:
                    os.utime(self.png_path(key))     # recently used entries survive pruning
                except OSError:
                    pass
                self._job = {"id": self._seq, "key": key, "state": "done", "cache_hit": True, "options": options,
                             "started": now, "finished": now, "seconds": 0.0, "progress": 1.0, "phase": "done",
                             "width": meta.get("width"), "height": meta.get("height"), "bytes": meta.get("bytes"),
                             "created": meta.get("created"), "error": None}
                return dict(self._job)
            self._job = {"id": self._seq, "key": key, "state": "running", "cache_hit": False, "options": options,
                         "started": now, "finished": None, "seconds": None, "progress": 0.0, "phase": "launch",
                         "width": None,
                         "height": None, "bytes": None, "created": None, "error": None}
            job_id = self._seq
            self._thread = threading.Thread(target=self._run, args=(job_id, key, options), daemon=True,
                                            name="graph-snapshot")
            self._thread.start()
            return dict(self._job)

    def status(self) -> dict | None:
        with self._lock:
            if self._job is None:
                return None
            j = dict(self._job)
        if j["state"] == "running":
            j["seconds"] = round(self.clock() - j["started"], 1)
        return j

    def wait(self, timeout: float | None = None) -> bool:
        """Test helper: wait for the running capture thread; True when it ended."""
        t = self._thread
        if t is None:
            return True
        t.join(timeout)
        return not t.is_alive()

    # ---- worker
    def _update(self, job_id: int, **kw):
        with self._lock:
            if self._job and self._job["id"] == job_id:
                self._job.update(kw)

    def _run(self, job_id: int, key: str, options: dict):
        os.makedirs(self.out_dir, exist_ok=True)
        tmp = os.path.join(self.out_dir, "tmp-%s-%d.png" % (key, job_id))
        lines: list[str] = []
        t0 = self.clock()
        try:
            cmd = self.build_cmd(options, tmp)
            # own session = own process group, so a timeout kills geckodriver and Firefox along with the tool
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                                    start_new_session=True)
        except Exception as e:  # noqa: BLE001 - report any launch problem on the job
            self._finish(job_id, t0, error="launch failed: %s" % e)
            return

        def reader():
            for line in proc.stdout:
                line = line.rstrip("\n")
                lines.append(line)
                del lines[:-200]
                if line.startswith("BBOX "):
                    # the page is loaded and measured: tiles come next (L22 phase, additive field)
                    self._update(job_id, phase="tiles")
                elif line.startswith("TILE "):
                    try:
                        i, n = line.split()[1].split("/")
                        i, n = int(i), max(1, int(n))
                        # last tile done: the tool now stitches and encodes the PNG (no progress line until RESULT)
                        self._update(job_id, progress=round(i / n, 3), phase="encode" if i >= n else "tiles")
                    except ValueError:
                        pass

        rt = threading.Thread(target=reader, daemon=True)
        rt.start()
        try:
            rc = proc.wait(self.timeout_s)
        except subprocess.TimeoutExpired:
            self._kill_group(proc)
            rt.join(5)
            self._cleanup(tmp)
            self._finish(job_id, t0, error="timeout after %d s" % self.timeout_s)
            return
        rt.join(5)
        result = None
        for line in reversed(lines):
            if line.startswith("RESULT "):
                try:
                    result = json.loads(line[7:])
                except ValueError:
                    pass
                break
        size = png_size(tmp)
        if rc != 0 or result is None or size is None:
            self._cleanup(tmp)
            tail = [ln for ln in lines if not ln.startswith("TILE ")][-6:]
            self._finish(job_id, t0, error="capture failed (exit %s): %s" % (rc, " | ".join(tail)[-600:]))
            return
        created = time.strftime("%Y%m%d-%H%M", time.localtime(self.clock()))
        meta = {"key": key, "width": size[0], "height": size[1], "bytes": os.path.getsize(tmp), "created": created,
                "options": options, "tool": result}
        try:
            os.replace(tmp, self.png_path(key))
            with open(self._meta_path(key), "w", encoding="utf-8") as f:
                json.dump(meta, f)
        except OSError as e:
            self._cleanup(tmp)
            self._finish(job_id, t0, error="cache write failed: %s" % e)
            return
        self._prune()
        self._finish(job_id, t0, width=size[0], height=size[1], bytes=meta["bytes"], created=created, progress=1.0)

    def _finish(self, job_id: int, t0: float, error: str | None = None, **kw):
        now = self.clock()
        self._update(job_id, state="failed" if error else "done", phase="failed" if error else "done", error=error,
                     finished=now,
                     seconds=round(now - t0, 1), **kw)

    @staticmethod
    def _kill_group(proc):
        for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                return
            try:
                proc.wait(wait)
                return
            except subprocess.TimeoutExpired:
                continue

    @staticmethod
    def _cleanup(path: str):
        for p in (path, path + ".part"):
            try:
                os.remove(p)
            except OSError:
                pass

    def _prune(self):
        try:
            pngs = [os.path.join(self.out_dir, n) for n in os.listdir(self.out_dir)
                    if n.endswith(".png") and not n.startswith("tmp-")]
        except OSError:
            return
        pngs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        for p in pngs[self.keep:]:
            self._cleanup(p)
            try:
                os.remove(p[:-4] + ".json")
            except OSError:
                pass
