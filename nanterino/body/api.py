"""HTTP handlers of the body API (lot C3): plain functions (body, payload) -> (status code, JSON-able dict).

logging: robotlog via nanterino.log (Body logs the safety events; this layer only shapes requests / answers).

Purpose
    server.py's /api/body/* routes are thin wrappers around these functions, so the whole API is testable without
    FastAPI and without importing nanterino.server (which builds the live Brain). Contract (French errors):
      GET  /api/body/state                         -> 200 Body.state()
      WS   /api/body/stream?hz=15                  -> Body.state() pushed at 1..20 Hz (stream_hz clamps)
      POST /api/body/command {targets:{id: v}, speed?: 0..1}  -> 200 {ok, cmd_id, applied, clamped, refused, deadband}
                                                     | 400 bad payload | 409 emergency stop latched
      POST /api/body/stop                          -> 200 soft stop (no latch)
      POST /api/body/estop {reason?}               -> 200 {ok, estop} (latched)
      POST /api/body/estop/reset                   -> 200 {ok, estop}
      POST /api/body/sweep {joint, speed?}         -> 200 | 400 | 409
      GET  /api/body/calibration                   -> 200 {calibration, store}
      PUT  /api/body/calibration {joints:{id:{field: v}}}       -> 200 {ok, changed, calibration} | 400 {errors}
      POST /api/body/calibration/{id}/{set_min|set_max|set_zero} -> 200 | 400 | 404
      GET  /api/body/calibration/export            -> 200 calibration document (schema nanterino.body-calibration)
      POST /api/body/calibration/import <document> -> 200 | 400 {errors}
      GET  /api/body/trace?seconds=N               -> 200 Body.trace(N) (N in 0..120)
Boundary
    No I/O besides Body calls; JSON decoding errors are mapped by server.py to payload=None (-> 400 here).
How to test
    .venv/bin/python -m tests.test_body   (api section drives every function on a simulated Body)
"""
import math

STREAM_HZ_MIN, STREAM_HZ_MAX, STREAM_HZ_DEFAULT = 1.0, 20.0, 15.0


def _bad(msg, status=400, **extra):
    return status, {"ok": False, "error": msg, **extra}


def state(body):
    return 200, body.state()


def stream_hz(raw) -> float:
    try:
        hz = float(raw)
    except (TypeError, ValueError):
        return STREAM_HZ_DEFAULT
    if not math.isfinite(hz):
        return STREAM_HZ_DEFAULT
    return max(STREAM_HZ_MIN, min(STREAM_HZ_MAX, hz))


def command(body, payload, source="api"):
    if not isinstance(payload, dict):
        return _bad("JSON invalide : objet {targets, speed?} attendu.")
    res = body.command(payload.get("targets"), payload.get("speed"), source)
    if res["estop"]:
        return 409, res
    if res["error"]:
        return 400, res
    return 200, res


def stop(body, source="api"):
    body.stop(source)
    return 200, {"ok": True}


def estop(body, payload=None, source="api"):
    reason = (payload or {}).get("reason") if isinstance(payload, dict) else None
    return 200, {"ok": True, "estop": body.stop_all(reason or "arrêt d'urgence", source)}


def estop_reset(body, source="api"):
    return 200, {"ok": True, "estop": body.reset_estop(source)}


def sweep(body, payload, source="api"):
    if not isinstance(payload, dict) or not isinstance(payload.get("joint"), str):
        return _bad("JSON invalide : {joint, speed?} attendu.")
    kw = {} if payload.get("speed") is None else {"speed": payload["speed"]}
    ok, err = body.sweep(payload["joint"], source=source, **kw)
    if not ok:
        return (409 if body.estop["active"] else 400), {"ok": False, "error": err}
    return 200, {"ok": True}


def calibration_get(body):
    return 200, {"ok": True, "calibration": body.calibration(),
                 "store": body.store.info() if body.store else None}


def calibration_put(body, payload, source="api"):
    if not isinstance(payload, dict) or not isinstance(payload.get("joints"), dict):
        return _bad("JSON invalide : {joints: {articulation: {champ: valeur}}} attendu.")
    ok, errs, res = body.set_calibration(payload["joints"], source)
    if not ok:
        return 400, {"ok": False, "errors": errs}
    return 200, {"ok": True, **res, "calibration": body.calibration()}


def calibration_set(body, joint, action, source="api"):
    if joint not in body.joints:
        return _bad("Articulation inconnue : %s." % joint, 404)
    ok, errs, res = body.set_from_position(joint, action, source)
    if not ok:
        return 400, {"ok": False, "errors": errs}
    return 200, {"ok": True, **res, "calibration": body.calibration()[joint]}


def calibration_export(body):
    return 200, body.export_calibration()


def calibration_import(body, payload, source="api"):
    if payload is None:
        return 400, {"ok": False, "errors": ["JSON invalide."]}
    ok, errs, res = body.import_calibration(payload, source)
    if not ok:
        return 400, {"ok": False, "errors": errs}
    return 200, {"ok": True, **res, "calibration": body.calibration()}


def trace(body, seconds=10):
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return _bad("seconds : nombre attendu.")
    if not math.isfinite(s) or s < 0:
        return _bad("seconds : nombre positif attendu.")
    return 200, body.trace(s)
