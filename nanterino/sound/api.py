"""HTTP handlers of the 360-degree sound API (lot C2): plain functions (tracker, payload) -> (status, JSON-able dict).

logging: robotlog via nanterino.log (the tracker logs offset changes; this layer only shapes requests / answers).

Purpose
    server.py's /api/sound/* routes are thin wrappers around these functions, testable without FastAPI and without
    importing nanterino.server. Contract (French errors):
      GET  /api/sound/state                     -> 200 SoundTracker.state(): {backend, configured, error, message,
                                                   gives_direction, source, last, direction, front_offset_deg, ...}
      WS   /api/sound/stream?hz=15              -> stream_frame() pushed at 1..20 Hz (stream_hz clamps)
      POST /api/sound/front {set_current: true} -> 200 {ok, front_offset_deg} | 409 no direction (mono, silence)
           /api/sound/front {offset_deg: n}     -> 200 {ok, front_offset_deg} | 400 not a number
      GET  /api/sound/history?seconds=N         -> 200 {seconds, samples: [calibrated readings]} (N in 0..60)
      POST /api/sound/sim {azimuth, level?, confidence?, hold_s?} | {clear: true} | {random: true}
                                                -> 200 {ok} | 409 backend is not sim | 400 bad payload
           (azimuth in the CALIBRATED robot frame, as the dashboard shows it; level in dBFS, default -20)
      POST /api/sound/backend {backend: mono|sim} -> 200 {ok, backend} | 400 (array / vendor need config.json and a
                                                   restart: they open hardware)
Boundary
    No I/O besides tracker calls; JSON decoding errors are mapped by server.py to payload=None (-> 400 here).
How to test
    .venv/bin/python -m tests.test_sound   (api section drives every function on a simulated tracker)
"""
import math

from .angles import wrap180
from .sources import SimSoundSource

STREAM_HZ_MIN, STREAM_HZ_MAX, STREAM_HZ_DEFAULT = 1.0, 20.0, 15.0
HISTORY_MAX_S = 60.0


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _bad(msg, status=400):
    return status, {"ok": False, "error": msg}


def state(tr):
    tr.poll()   # lot L45: the screen reads the source itself, not only what the 10 Hz brain heartbeat last polled
    return 200, tr.state()


def stream_frame(tr) -> dict:
    """Compact frame of the WebSocket stream (the dashboard builds its trail from successive frames).

    Lot L45: polls the source first (non-blocking: sources return their latest reading), so the stream follows the
    chip at the stream rate (15 Hz) and keeps moving even when the brain loop is busy."""
    tr.poll()
    s = tr.state()
    return {k: s[k] for k in ("backend", "configured", "error", "message", "gives_direction", "last", "direction",
                              "front_offset_deg", "min_confidence", "t")}


def stream_hz(raw) -> float:
    try:
        hz = float(raw)
    except (TypeError, ValueError):
        return STREAM_HZ_DEFAULT
    if not math.isfinite(hz):
        return STREAM_HZ_DEFAULT
    return max(STREAM_HZ_MIN, min(STREAM_HZ_MAX, hz))


def front(tr, payload, source="api"):
    if not isinstance(payload, dict):
        return _bad("JSON invalide : {set_current: true} ou {offset_deg: n} attendu.")
    if payload.get("set_current"):
        ok, err = tr.set_front_current(source)
        if not ok:
            return 409, {"ok": False, "error": err}
    elif "offset_deg" in payload:
        if not _num(payload["offset_deg"]):
            return _bad("offset_deg : nombre attendu.")
        ok, err = tr.set_front_offset(payload["offset_deg"], source)
        if not ok:
            return 500, {"ok": False, "error": err}
    else:
        return _bad("JSON invalide : {set_current: true} ou {offset_deg: n} attendu.")
    return 200, {"ok": True, "front_offset_deg": round(tr.front_offset, 1)}


def history(tr, seconds=10):
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return _bad("seconds : nombre attendu.")
    if not math.isfinite(s) or s < 0:
        return _bad("seconds : nombre positif attendu.")
    s = min(HISTORY_MAX_S, s)
    return 200, {"seconds": s, "samples": tr.history(s)}


def sim(tr, payload):
    src = tr.source
    if not isinstance(src, SimSoundSource):
        return 409, {"ok": False, "error": "Le backend actuel (%s) n'est pas la simulation." % src.name}
    if not isinstance(payload, dict):
        return _bad("JSON invalide : {azimuth, level?} attendu.")
    now = tr.clock()
    if payload.get("clear"):
        src.clear()
    elif payload.get("random"):
        src.random(now=now)
    else:
        az, lvl = payload.get("azimuth"), payload.get("level", -20.0)
        conf, hold = payload.get("confidence", 1.0), payload.get("hold_s")
        if not _num(az) or not _num(lvl) or not _num(conf) or not (hold is None or (_num(hold) and hold > 0)):
            return _bad("azimuth / level / confidence / hold_s : nombres attendus.")
        if not -120 <= lvl <= 0 or not 0 <= conf <= 1:
            return _bad("level dans -120..0 dB, confidence dans 0..1.")
        # the dashboard speaks the calibrated frame: the virtual source is placed in the raw frame of the "mic"
        src.set(wrap180(az + tr.front_offset), lvl, conf, hold_s=hold, now=now)
    tr.poll(now)
    return 200, {"ok": True}


def backend(tr, payload, make_source, runtime=("mono", "sim")):
    name = payload.get("backend") if isinstance(payload, dict) else None
    if name not in runtime:
        return _bad("backend : %s seulement sans redémarrage (array / vendor : config.json puis redémarrage)."
                    % " ou ".join(runtime))
    tr.replace_source(make_source(name), configured=name)
    return 200, {"ok": True, "backend": tr.source.name}
