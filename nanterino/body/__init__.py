"""Robot body package (lot C3, 2026-11-04): hardware-agnostic motors / joints, calibration, limits, e-stop.

logging: robotlog via nanterino.log.

Purpose
    `create(cfg)` builds the Body the Brain and server.py share: joints from nanterino/body/body.yaml (provisional
    layout), the backend named by cfg["body_backend"] (sim | mujoco | real), and optionally the persistent
    calibration store. Modules: joints.py (layout), calibration.py (records + store), backends.py (interface, sim,
    placeholders), core.py (Body: the single command door), api.py (HTTP handler functions, no FastAPI import).
Boundary
    The live store (state/body-calibration.json) is only passed by server.py; Brain(...) without `body=` gets an
    in-memory simulated body (simulator, tests: nothing written).
Invariants
    - a backend that cannot start (MuJoCo / real placeholders, unknown name) never stops the robot: create() logs an
      error and falls back to the simulator, the reason is in Body.backend_error (dashboard banner) - unless
      strict=True (tests), where the NotImplementedError / ValueError propagates;
How to test
    .venv/bin/python -m tests.test_body
"""
from ..log import log
from .backends import SimBackend, make_backend
from .calibration import CalibrationStore
from .core import Body
from .joints import DEFAULT_LAYOUT, load_layout

__all__ = ["Body", "CalibrationStore", "create"]


def create(cfg=None, calibration_path=None, *, layout_path=DEFAULT_LAYOUT, strict=False, clock=None, wall=None) -> Body:
    cfg = cfg or {}
    name = cfg.get("body_backend", "sim")
    err = None
    try:
        backend = make_backend(name)
    except (NotImplementedError, ValueError) as e:
        if strict:
            raise
        err = str(e)
        log.error("body backend %s unavailable, simulator used instead: %s", name, e)
        backend = SimBackend()
    store = CalibrationStore(calibration_path) if calibration_path else None
    kw = {k: v for k, v in (("clock", clock), ("wall", wall)) if v is not None}
    return Body(load_layout(layout_path), backend, store, backend_error=err, **kw)
