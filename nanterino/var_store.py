"""Persistent graph variables: one JSON file, atomic writes, at most one write per 2 s (logging: robotlog via nanterino.log).

Purpose
    Lot L11 (2026-11-01): a graph variable or list declared `persist: true` (global scope only) keeps its value across
    service restarts. The brain hands changed values to this store from its heartbeat; the store keeps the whole file in
    memory and writes it when something changed and the last write is at least `min_interval_s` (2 s) old.

Boundary
    - Knows nothing about graphs or types: entries are opaque JSON objects grouped in three parts, `names`, `lists`
      and `system` (the nb_visiteurs_jour counter). Type checks of read-back values are the brain's job
      (graph.persisted_ok); an entry that no longer fits is ignored there and stays in the file until a reset or a
      new value replaces it.
    - Only server.py creates the live store (DEFAULT_PATH = <repo>/state/vars.json, git-ignored). The simulator and the
      tests never get it: tests build a VarStore on a temporary path.

Invariants
    - Atomic: the file is written to a temporary file in the same folder, fsync'ed, then os.replace'd; a crash leaves
      either the old or the new file, never a half-written one.
    - A missing file = empty store (nothing is created until a value changes); an unreadable / corrupt file is logged
      (warning) and treated as empty, and the next write replaces it.
    - put / drop / flush are thread-safe (the brain loop puts, an atexit hook may flush).

How to test
    python -m tests.test_graph_vars2     (round trip, corrupt file, write rate limit, brain integration)
"""
import json
import os
import tempfile
import threading
import time

from .log import log

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state", "vars.json")
MIN_INTERVAL_S = 2.0
VERSION = 1
PARTS = ("names", "lists", "system")


class VarStore:
    def __init__(self, path: str = DEFAULT_PATH, min_interval_s: float = MIN_INTERVAL_S, clock=time.monotonic):
        self.path, self.min_interval_s, self.clock = path, float(min_interval_s), clock
        self._lock = threading.Lock()
        self._dirty, self._last_write = False, None
        self.writes = 0          # successful writes (tests check the rate limit)
        self.data = self._read()

    @staticmethod
    def _empty() -> dict:
        return {p: {} for p in PARTS}

    def _read(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            return self._empty()
        except (OSError, ValueError) as e:
            log.warning("vars store %s unreadable, starting empty: %s", self.path, e)
            return self._empty()
        data = self._empty()
        if not isinstance(raw, dict):
            log.warning("vars store %s is not a JSON object, starting empty", self.path)
            return data
        for p in PARTS:
            if isinstance(raw.get(p), dict):
                data[p] = raw[p]
            elif p in raw:
                log.warning("vars store %s: part %r is not an object, ignored", self.path, p)
        return data

    def has(self, part: str, name: str) -> bool:
        with self._lock:
            return name in self.data[part]

    def put(self, part: str, name: str, entry: dict):
        """Record a value (a JSON-able object); written by the next allowed flush."""
        copy = json.loads(json.dumps(entry))   # detached from the caller's mutable lists / dicts
        with self._lock:
            if self.data[part].get(name) != copy:
                self.data[part][name] = copy
                self._dirty = True

    def drop(self, part: str, name: str):
        with self._lock:
            if name in self.data[part]:
                del self.data[part][name]
                self._dirty = True

    def saved(self) -> dict:
        """Names that currently have a saved value, per part."""
        with self._lock:
            return {p: sorted(self.data[p]) for p in PARTS}

    def maybe_flush(self, now: float | None = None) -> bool:
        """Write if something changed and the previous write is at least min_interval_s old."""
        now = self.clock() if now is None else now
        with self._lock:
            if not self._dirty or (self._last_write is not None and now - self._last_write < self.min_interval_s):
                return False
        return self.flush(now)

    def flush(self, now: float | None = None) -> bool:
        """Write now when dirty (also used at exit). Returns True when the file was written."""
        with self._lock:
            if not self._dirty:
                return False
            payload = json.dumps({"version": VERSION, **self.data}, ensure_ascii=False, indent=1, sort_keys=True)
            self._dirty = False
            self._last_write = self.clock() if now is None else now
        tmp = None
        try:
            folder = os.path.dirname(self.path) or "."
            os.makedirs(folder, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".vars-", suffix=".tmp", dir=folder)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            self.writes += 1
            return True
        except OSError as e:
            log.error("vars store write failed %s: %s", self.path, e)
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            with self._lock:
                self._dirty = True   # retried at the next allowed slot
            return False
