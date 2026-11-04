"""Turn the head toward the sound (lot C2): the one bridge from the sound layer to the body (nanterino/body).

logging: robotlog via nanterino.log (a saturated turn is an INFO record; the body logs its own clamps).

Purpose
    turn_head_toward(body, azimuth) points `head_pan` at a calibrated azimuth (robot frame, + = left, the head pan
    sign). Used by the graph action `turn_toward_sound` and testable alone.
Boundary
    Only Body.look(pan=..., source="sound") is called: the body's single clamp still applies and the WHEELS NEVER
    MOVE (a sound behind the robot saturates the head at its pan limit; turning the base is a later Mouvement node).
Invariants
    - the requested pan is the azimuth folded into (-180, 180]; beyond the calibrated head_pan [min, max] it is
      saturated here (and reported `saturated`), so the body receives an in-range target;
    - no head_pan joint, a latched emergency stop or a disabled joint: nothing moves, the reason is returned.
How to test
    .venv/bin/python -m tests.test_sound   (sim body: arrival, saturation, wheels untouched)
"""
from ..log import log
from .angles import wrap180


def turn_head_toward(body, azimuth, speed=None) -> dict:
    """{ok, requested, pan, saturated, result (Body.command reply), error}."""
    out = {"ok": False, "requested": None, "pan": None, "saturated": False, "result": None, "error": None}
    if body is None or "head_pan" not in getattr(body, "joints", {}):
        out["error"] = "pas d'articulation head_pan"
        return out
    req = wrap180(azimuth)
    cal = body.calibration()["head_pan"]
    pan = min(cal["max"], max(cal["min"], req))
    out.update(requested=round(req, 2), pan=round(pan, 2), saturated=pan != req)
    if out["saturated"]:
        log.info("turn_toward_sound: sound at %.1f deg beyond the head pan range [%g, %g], head saturated at %g",
                 req, cal["min"], cal["max"], pan)
    res = body.look(pan=pan, speed=speed, source="sound")
    out["result"] = res
    out["ok"] = bool(res.get("ok"))
    out["error"] = res.get("error")
    return out
