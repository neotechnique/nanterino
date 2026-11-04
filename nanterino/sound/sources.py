"""Sound sources of the 360-degree sound layer (lot C2): the hardware-agnostic `SoundSource` interface and its backends.

logging: robotlog via nanterino.log.

Purpose
    A SoundSource turns some microphone hardware into a stream of `Reading`s: {t, azimuth_deg (RAW, the source's own
    frame; the front offset is applied by tracker.SoundTracker), elevation_deg, level_db, confidence 0..1,
    voice_prob}. Backends:
      SimSoundSource   scripted / random virtual sources (tests, simulator, dashboard demo); never opens a device;
      MonoLevelSource  today's single USB mic (Trust GXT through PipeWire): it reads the level the existing AudioIn
                       already measures and reports NO direction (azimuth None, confidence 0) - honest by design;
      VendorDoaSource  placeholder for arrays that compute the direction themselves (e.g. a ReSpeaker USB v2 through
                       its USB control interface): raises NotConfiguredError until the real model is known;
      ArraySoundSource generic N-channel array (array_source.py, GCC-PHAT / SRP-PHAT in doa.py).
Boundary
    poll(now) is called by the Brain heartbeat (10 Hz) and must never block: hardware backends do their work on their
    own thread and poll() only returns the latest result. start() / stop() open / close a device (only server.py
    starts a source; Brains built by tests and the simulator never do).
Invariants
    - a source that cannot measure a direction says so: azimuth_deg None and confidence 0 (never a made-up angle);
    - level_db is in dB relative to full scale (dBFS) for array / sim; for MonoLevelSource it is 20*log10 of the
      dashboard mic bar (1.0 = full bar = 0 dB); None when the microphone is closed;
    - Reading.to_dict() is the JSON shape of the API (rounded numbers).
How to test
    .venv/bin/python -m tests.test_sound
"""
import math
import random
import threading
import time
from dataclasses import dataclass

from ..log import log
from .angles import wrap180

SILENCE_DB = -90.0        # level reported by the simulator when no virtual source sounds


class NotConfiguredError(RuntimeError):
    """The configured sound backend cannot run yet (unknown hardware, missing geometry file ...)."""


@dataclass
class Reading:
    t: float                                  # monotonic time of the measurement
    azimuth_deg: float | None = None          # raw azimuth (source frame); None = no direction measured
    level_db: float | None = None
    confidence: float = 0.0
    elevation_deg: float | None = None
    voice_prob: float | None = None

    def to_dict(self) -> dict:
        r = lambda v, n=1: None if v is None else round(float(v), n)   # noqa: E731
        return {"t": round(self.t, 3), "azimuth_deg": r(self.azimuth_deg), "elevation_deg": r(self.elevation_deg),
                "level_db": r(self.level_db), "confidence": round(float(self.confidence), 3),
                "voice_prob": r(self.voice_prob, 2)}


class SoundSource:
    """Interface of every backend (see the module header)."""
    name = "base"
    gives_direction = False

    def start(self) -> None:
        """Open the hardware (no-op for software sources)."""

    def stop(self) -> None:
        """Close the hardware (no-op for software sources)."""

    def poll(self, now: float) -> Reading | None:
        """Latest reading, never blocking (None = nothing measured yet)."""
        raise NotImplementedError

    def info(self) -> dict:
        """Static description for GET /api/sound/state (backend name, capabilities, details)."""
        return {"name": self.name, "gives_direction": self.gives_direction}


class MonoLevelSource(SoundSource):
    """Today's single microphone: level only (from AudioIn.level), never a direction."""
    name = "mono"
    gives_direction = False

    def __init__(self, mic=None):
        self.mic = mic   # object with .active / .level (nanterino.audio.AudioIn, sim.FakeIn); None = no mic at all

    def poll(self, now):
        mic = self.mic
        if mic is None or not getattr(mic, "active", False):
            return Reading(t=now, level_db=None)
        level = max(float(getattr(mic, "level", 0.0) or 0.0), 1e-6)
        return Reading(t=now, level_db=max(-120.0, 20.0 * math.log10(level)), confidence=0.0)

    def info(self):
        return {"name": self.name, "gives_direction": False,
                "detail": "Un seul micro : le niveau est mesuré, pas la direction."}


class SimSoundSource(SoundSource):
    """Virtual sources for tests and the demo: set(), clear(), script() of timed steps, random().

    Thread-safe (the API thread sets, the brain loop polls). Optional gaussian jitter `noise_deg` (seeded rng)."""
    name = "sim"
    gives_direction = True

    def __init__(self, seed: int = 0, noise_deg: float = 0.0):
        self._lock = threading.Lock()
        self._rng = random.Random(seed)
        self.noise_deg = float(noise_deg)
        self._src = None          # {"azimuth", "level_db", "confidence", "voice_prob", "until"}
        self._script, self._script_t0 = [], None
        self._random = None       # {"next": t, "seed"} when random() runs

    def set(self, azimuth, level_db=-20.0, confidence=1.0, voice_prob=None, hold_s=None, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            self._script, self._random = [], None
            self._src = {"azimuth": wrap180(azimuth), "level_db": float(level_db),
                         "confidence": max(0.0, min(1.0, float(confidence))), "voice_prob": voice_prob,
                         "until": None if hold_s is None else now + float(hold_s)}

    def clear(self):
        with self._lock:
            self._src, self._script, self._random = None, [], None

    def script(self, steps, now=None):
        """steps = [(duration_s, azimuth or None, level_db), ...] played once from `now` (None azimuth = silence)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._src, self._random = None, None
            self._script, self._script_t0 = [tuple(s) for s in steps], now

    def random(self, now=None):
        """Demo mode: a new virtual source every 2-4 s somewhere around the robot, with short silences."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._src, self._script = None, []
            self._random = {"next": now}

    def _current(self, now):
        if self._script:
            t = now - self._script_t0
            for dur, az, lvl in self._script:
                if t < dur:
                    return None if az is None else {"azimuth": az, "level_db": lvl, "confidence": 1.0,
                                                    "voice_prob": None}
                t -= dur
            self._script = []
            return None
        if self._random is not None:
            if now >= self._random["next"]:
                self._random["next"] = now + self._rng.uniform(2.0, 4.0)
                self._random["src"] = None if self._rng.random() < 0.25 else {
                    "azimuth": self._rng.uniform(-180, 180), "level_db": self._rng.uniform(-40, -10),
                    "confidence": self._rng.uniform(0.6, 1.0), "voice_prob": None}
            return self._random.get("src")
        src = self._src
        if src and src["until"] is not None and now >= src["until"]:
            self._src = src = None
        return src

    def poll(self, now):
        with self._lock:
            src = self._current(now)
            if not src:
                return Reading(t=now, level_db=SILENCE_DB, confidence=0.0)
            az = src["azimuth"] + (self._rng.gauss(0.0, self.noise_deg) if self.noise_deg else 0.0)
            return Reading(t=now, azimuth_deg=wrap180(az), level_db=src["level_db"], confidence=src["confidence"],
                           voice_prob=src.get("voice_prob"))

    def info(self):
        return {"name": self.name, "gives_direction": True, "detail": "Sources virtuelles (simulation)."}


class VendorDoaSource(SoundSource):
    """Placeholder: an array that reports its own direction of arrival (DOA) through a vendor interface.

    Example of what goes here once the model is known: a ReSpeaker USB Mic Array v2.0 exposes DOAANGLE / VOICEACTIVITY
    through USB control transfers (pyusb, vendor tuning protocol); other arrays use HID or a serial port. Until the
    user's spatial microphone is identified, constructing it raises NotConfiguredError with what is missing
    (Notes/HOWTO-sound360.md lists the information to collect)."""
    name = "vendor"
    gives_direction = True
    KNOWN = {}    # model id -> driver class, filled when a real vendor driver is written

    def __init__(self, model=None):
        if not model:
            raise NotConfiguredError("Backend « vendor » : modèle du micro spatial non renseigné (sound_vendor_model). "
                                     "Voir Notes/HOWTO-sound360.md.")
        if model not in self.KNOWN:
            raise NotConfiguredError("Backend « vendor » : aucun pilote pour le modèle %r. Voir Notes/HOWTO-sound360.md."
                                     % (model,))
        raise NotConfiguredError("Backend « vendor » : pilote %r non écrit." % (model,))   # pragma: no cover

    def poll(self, now):   # pragma: no cover - never constructed
        return None


def log_backend_fallback(name, err):
    log.error("sound backend %s unavailable, mono level source used instead: %s", name, err)
