"""SoundTracker (lot C2): the robot's view of the 360-degree sound - one source, the front offset, the history ring.

logging: robotlog via nanterino.log (front offset changes are INFO records, store failures ERROR).

Purpose
    `brain.sound` is a SoundTracker. The Brain heartbeat calls poll(now) (10 Hz); nodes and the API read
    direction(), level(), history(), state(). The front offset (`front_offset_deg`) is the RAW azimuth of the robot's
    real front as the microphone sees it: every calibrated azimuth is wrap180(raw - front_offset). « Définir comme
    avant » (set_front_current) takes the dominant raw direction of the last DOMINANT_S seconds (circular mean
    weighted by confidence) as the new offset. The offset is persisted in state/sound-calibration.json (atomic).
Boundary
    Knows the SoundSource interface only (sources.py); no HTTP (api.py), no graph (the Brain posts the events). The
    live store path is passed by server.py; any other tracker (tests, simulator) keeps the offset in memory.
Invariants
    - the offset is applied in ONE place (poll -> _calibrate); history and direction() hold calibrated azimuths
      (and the raw one, for the dashboard and the calibration);
    - direction() is None unless the latest reading is fresh (FRESH_S), has an azimuth and a confidence >= MIN_CONF
      and a level >= min_level_db: a mono mic therefore never gives a direction;
    - the history ring keeps HISTORY_S seconds at most HISTORY_HZ samples per second;
    - store writes: temp file in the same folder, fsync, os.replace (never a half-written file);
    - all public methods take one lock (HTTP threads and the brain loop call them concurrently).
How to test
    .venv/bin/python -m tests.test_sound
"""
import collections
import json
import math
import os
import tempfile
import threading
import time

from ..log import log
from .angles import circular_mean, wrap180

SCHEMA = "nanterino.sound-calibration"
FRESH_S = 1.0           # a reading older than this is no direction any more
MIN_CONF = 0.5          # confidence needed for direction() (nodes, « Définir comme avant »)
MIN_LEVEL_DB = -50.0    # default level gate of direction() (cfg sound_min_level_db)
HISTORY_S, HISTORY_HZ = 60.0, 20.0
DOMINANT_S = 1.5        # « Définir comme avant » looks at this window


class CalibrationStore:
    """state/sound-calibration.json: {schema, version, front_offset_deg, updated_at}."""

    def __init__(self, path):
        self.path = path
        self.updated_at, self.last_error, self.writes = None, None, 0

    def load(self) -> float:
        try:
            with open(self.path, encoding="utf-8") as f:
                doc = json.load(f)
        except FileNotFoundError:
            return 0.0
        except (OSError, ValueError) as e:
            self.last_error = "fichier illisible : %s" % e
            log.error("sound calibration %s unreadable, offset 0 used: %s", self.path, e)
            return 0.0
        off = doc.get("front_offset_deg") if isinstance(doc, dict) else None
        if not (isinstance(doc, dict) and doc.get("schema") == SCHEMA and isinstance(off, (int, float))
                and not isinstance(off, bool) and math.isfinite(off)):
            self.last_error = "document invalide"
            log.error("sound calibration %s invalid, offset 0 used", self.path)
            return 0.0
        self.updated_at = doc.get("updated_at")
        return wrap180(off)

    def save(self, offset: float) -> dict:
        doc = {"schema": SCHEMA, "version": 1, "front_offset_deg": round(wrap180(offset), 3),
               "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        folder = os.path.dirname(self.path) or "."
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".sound-calibration.", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self.updated_at, self.last_error = doc["updated_at"], None
        self.writes += 1
        return doc

    def info(self) -> dict:
        return {"path": self.path, "updated_at": self.updated_at, "error": self.last_error}


class SoundTracker:
    def __init__(self, source, store=None, *, clock=time.monotonic, wall=time.time, backend_error=None,
                 min_level_db=MIN_LEVEL_DB, configured=None):
        self._lock = threading.RLock()
        self.source, self.store = source, store
        self.clock, self.wall = clock, wall
        self.backend_error = backend_error           # why the configured backend was replaced by mono (or None)
        self.configured = configured or source.name  # backend named in the configuration
        self.min_level_db = float(min_level_db)
        self.front_offset = store.load() if store else 0.0
        self._latest = None                          # dict: calibrated reading + raw azimuth + wall time
        self._hist = collections.deque(maxlen=int(HISTORY_S * HISTORY_HZ))
        self._last_sample = -1e9
        self.polls = 0

    # ------------------------------------------------------------------ the heartbeat
    def _calibrate(self, r) -> dict:
        d = r.to_dict()
        d["raw_azimuth_deg"] = d["azimuth_deg"]
        if r.azimuth_deg is not None:
            d["azimuth_deg"] = round(wrap180(r.azimuth_deg - self.front_offset), 1)
        d["wall"] = round(self.wall(), 3)
        d["mono_t"] = r.t
        return d

    def poll(self, now=None) -> dict | None:
        """Read the source once (Brain heartbeat); returns the calibrated latest reading."""
        now = self.clock() if now is None else now
        with self._lock:
            r = self.source.poll(now)
            self.polls += 1
            if r is None:
                return self._latest
            d = self._calibrate(r)
            self._latest = d
            if now - self._last_sample >= 1.0 / HISTORY_HZ - 1e-6:
                self._last_sample = now
                self._hist.append(d)
            return d

    # ------------------------------------------------------------------ readers (nodes, API)
    def _fresh(self, d, now, max_age):
        return d is not None and now - d["mono_t"] <= max_age + 1e-9

    def direction(self, max_age=FRESH_S, min_conf=MIN_CONF) -> dict | None:
        """{azimuth_deg (calibrated), raw_azimuth_deg, confidence, level_db, elevation_deg, age_s} or None."""
        with self._lock:
            d, now = self._latest, self.clock()
            if not self._fresh(d, now, max_age) or d["azimuth_deg"] is None or d["confidence"] < min_conf:
                return None
            if d["level_db"] is None or d["level_db"] < self.min_level_db:
                return None
            return {"azimuth_deg": d["azimuth_deg"], "raw_azimuth_deg": d["raw_azimuth_deg"],
                    "confidence": d["confidence"], "level_db": d["level_db"], "elevation_deg": d["elevation_deg"],
                    "age_s": round(now - d["mono_t"], 3)}

    def level(self, max_age=FRESH_S) -> float | None:
        """Latest level in dB (None: microphone closed, or nothing fresh)."""
        with self._lock:
            d = self._latest
            return d["level_db"] if self._fresh(d, self.clock(), max_age) else None

    def history(self, seconds=10.0) -> list:
        """Calibrated readings of the last `seconds` (oldest first, at most HISTORY_HZ per second)."""
        with self._lock:
            seconds = max(0.0, min(HISTORY_S, float(seconds)))
            if not self._hist:
                return []
            last = self._hist[-1]["mono_t"]
            return [{k: v for k, v in d.items() if k != "mono_t"} for d in self._hist if d["mono_t"] >= last - seconds - 1e-9]

    def dominant_raw(self, seconds=DOMINANT_S) -> float | None:
        """Circular mean of the confident raw azimuths of the last `seconds` (None when there is none)."""
        with self._lock:
            now = self.clock()
            pts = [(d["raw_azimuth_deg"], d["confidence"]) for d in self._hist
                   if now - d["mono_t"] <= seconds and d["raw_azimuth_deg"] is not None and d["confidence"] >= MIN_CONF]
            if not pts:
                return None
            m = circular_mean([a for a, _ in pts], [w for _, w in pts])
            return None if m is None else round(m, 1)   # 0.1 degree: no float residue in the stored offset

    # ------------------------------------------------------------------ calibration
    def set_front_offset(self, offset, source="api") -> tuple:
        """(ok, error) - persist a new offset (degrees, raw frame)."""
        if not isinstance(offset, (int, float)) or isinstance(offset, bool) or not math.isfinite(offset):
            return False, "offset_deg : nombre attendu."
        with self._lock:
            self.front_offset = wrap180(offset)
            if self._latest is not None and self._latest["raw_azimuth_deg"] is not None:
                self._latest["azimuth_deg"] = round(wrap180(self._latest["raw_azimuth_deg"] - self.front_offset), 1)
            if self.store:
                try:
                    self.store.save(self.front_offset)
                except OSError as e:
                    log.error("sound calibration save failed: %s", e)
                    return False, "Enregistrement impossible : %s" % e
            log.info("sound front offset = %.1f deg (source=%s)", self.front_offset, source)
            return True, None

    def set_front_current(self, source="api") -> tuple:
        """« Définir comme avant »: the dominant raw direction becomes the robot's front. (ok, error)."""
        if not self.source.gives_direction:
            return False, "Ce micro ne mesure pas de direction (backend %s)." % self.source.name
        raw = self.dominant_raw()
        if raw is None:
            return False, "Aucun son net ces %.1f dernières secondes : tapez dans les mains devant le robot." % DOMINANT_S
        return self.set_front_offset(raw, source)

    # ------------------------------------------------------------------ backend switch (dashboard tests / demo)
    def replace_source(self, source, configured=None) -> None:
        with self._lock:
            try:
                self.source.stop()
            except Exception:   # noqa: BLE001
                log.exception("sound source stop failed")
            self.source, self._latest, self.backend_error = source, None, None
            self._hist.clear()
            if configured:
                self.configured = configured

    # ------------------------------------------------------------------ state
    def message(self) -> str:
        if self.backend_error:
            return "Backend « %s » indisponible : %s Le niveau du micro reste mesuré." % (self.configured, self.backend_error)
        if not self.source.gives_direction:
            return ("Micro actuel : un seul micro (mono). Le niveau est mesuré, mais pas la direction : il faut une "
                    "barrette de micros (voir Notes/HOWTO-sound360.md).")
        return ""

    def state(self) -> dict:
        with self._lock:
            d = self._latest
            last = None if d is None else {k: v for k, v in d.items() if k != "mono_t"}
            si = self.source.info()
            avail = self.backend_error is None and bool(si.get("available", True))
            reason = self.backend_error or ("" if avail else si.get("reason", ""))
            return {"backend": self.source.name, "configured": self.configured, "error": self.backend_error,
                    "available": avail, "reason": reason,
                    "gives_direction": self.source.gives_direction, "message": self.message(),
                    "source": si, "last": last, "direction": self.direction(),
                    "front_offset_deg": round(self.front_offset, 1), "min_level_db": self.min_level_db,
                    "min_confidence": MIN_CONF, "calibration_store": self.store.info() if self.store else None,
                    "t": round(self.wall(), 3)}
