"""360-degree sound package (lot C2, 2026-11-04): hardware-agnostic direction of arrival, level, confidence.

logging: robotlog via nanterino.log.

Purpose
    `create(cfg, mic=...)` builds the SoundTracker the Brain (`brain.sound`) and server.py share, with the backend
    named by cfg["sound_backend"]:
      mono   (default, today's robot) MonoLevelSource on the existing AudioIn: level only, no direction;
      sim    SimSoundSource (tests, demo, dashboard scenario);
      array  ArraySoundSource with the geometry file cfg["sound_array_geometry"] (default nanterino/sound/array.yaml,
             a PLACEHOLDER 4-mic circle until the real spatial microphone is known);
      vendor VendorDoaSource(cfg["sound_vendor_model"]): not configured yet -> falls back to mono.
    Modules: angles.py (frame convention, sectors), sources.py (interface + sim / mono / vendor), doa.py (GCC-PHAT,
    SRP-PHAT, geometry), array_source.py (capture thread), tracker.py (front offset, history), turn.py (head turn-to),
    api.py (HTTP handler functions, no FastAPI import).
Boundary
    The live calibration store (state/sound-calibration.json) and start=True (open the device) come only from
    server.py; Brain(...) without `sound=` gets an in-memory tracker on its own mic object (simulator, tests).
Invariants
    - a backend that cannot start never stops the robot: create() logs an error and falls back to mono, the reason
      is in SoundTracker.backend_error (dashboard message) - unless strict=True (tests);
    - RUNTIME_BACKENDS (mono, sim) are the only ones the dashboard may switch to without a restart: they open no
      device (the robot stays deaf / muted during tests).
How to test
    .venv/bin/python -m tests.test_sound
"""
import os

from ..log import log
from .sources import MonoLevelSource, NotConfiguredError, SimSoundSource, VendorDoaSource, log_backend_fallback
from .tracker import CalibrationStore, SoundTracker

__all__ = ["SoundTracker", "CalibrationStore", "create", "make_source", "BACKENDS", "RUNTIME_BACKENDS"]

BACKENDS = ("mono", "sim", "array", "vendor")
RUNTIME_BACKENDS = ("mono", "sim")
DEFAULT_GEOMETRY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "array.yaml")
DEFAULT_CAL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "state", "sound-calibration.json")


def make_source(name, cfg=None, mic=None):
    """The SoundSource for a backend name (raises NotConfiguredError / ValueError when it cannot run)."""
    cfg = cfg or {}
    if name == "mono":
        return MonoLevelSource(mic)
    if name == "sim":
        return SimSoundSource(seed=int(cfg.get("sound_sim_seed", 0)))
    if name == "array":
        from .array_source import ArraySoundSource
        from .doa import load_geometry
        path = cfg.get("sound_array_geometry") or DEFAULT_GEOMETRY
        try:
            geom = load_geometry(path)
        except FileNotFoundError:
            raise NotConfiguredError("Backend « array » : fichier de géométrie absent (%s)." % path)
        except ValueError as e:
            raise NotConfiguredError("Backend « array » : géométrie invalide (%s)." % e)
        return ArraySoundSource(geom)
    if name == "vendor":
        return VendorDoaSource(cfg.get("sound_vendor_model"))
    raise ValueError("sound_backend inconnu : %r (mono, sim, array, vendor)" % (name,))


def create(cfg=None, mic=None, calibration_path=None, *, strict=False, start=False, clock=None, wall=None) -> SoundTracker:
    cfg = cfg or {}
    name = cfg.get("sound_backend", "mono")
    err = None
    try:
        source = make_source(name, cfg, mic)
        if start:
            source.start()
    except (NotConfiguredError, ValueError, OSError, RuntimeError) as e:
        if strict:
            raise
        err = str(e)
        log_backend_fallback(name, e)
        source = MonoLevelSource(mic)
    except Exception as e:   # noqa: BLE001 - PortAudio errors (sounddevice.PortAudioError) and the like
        if strict:
            raise
        err = "%s: %s" % (type(e).__name__, e)
        log.exception("sound backend %s failed to start", name)
        source = MonoLevelSource(mic)
    store = CalibrationStore(calibration_path) if calibration_path else None
    kw = {k: v for k, v in (("clock", clock), ("wall", wall)) if v is not None}
    return SoundTracker(source, store, backend_error=err, configured=name,
                        min_level_db=float(cfg.get("sound_min_level_db", -50.0)), **kw)
