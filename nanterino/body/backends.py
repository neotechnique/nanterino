"""Motor backends of the robot body (lot C3): the interface, the kinematic simulator, and placeholders.

logging: robotlog via nanterino.log (backends log nothing on the hot path; Body logs safety events).

Purpose
    A backend moves the motors and reports their state in HARDWARE units (calibration offset / direction are applied
    by Body, never here). SimBackend is a deterministic first-order kinematic model used by the tests, the traces,
    the dashboard and the Mouvement nodes (lot B1) until real hardware exists; MujocoBackend (lot B3a) lives in
    mujoco_backend.py (lazy import: needs the optional `mujoco` module, refuses to start with a French reason when it
    is missing); HardwareBackend (servos over serial / PWM / ROS 2, plan B4) is a placeholder that refuses to start.
Boundary
    Interface used by Body only: configure(joints), read_state(), command(targets), stop_all(), enable(id),
    disable(id), step(dt), plus the optional poll_events() / close(). Body holds its lock around every call, so backends need no locking of their own.
    `step(dt)` advances the simulation; a real backend would poll / stream its bus there (or ignore dt).
Invariants (SimBackend)
    - position joints: |velocity| <= target.max_speed and |velocity change| <= max_accel * dt at every step; with a
      constant dt the joint never crosses the target (a jittering live dt may overshoot by ~speed * dt jitter, then
      it comes back and lands exactly); discrete trapezoidal profile with an exact braking condition;
    - velocity joints (wheels): velocity ramps toward the target speed at max_accel, position = odometer (m);
    - a disabled joint, or every joint after stop_all(), stops at once (velocity 0, target = position);
    - current (A) = idle + speed term + acceleration term; temperature (degC) relaxes toward 25 + 15 * current^2 with a
      60 s time constant: plausible numbers for the dashboard, NOT a motor model;
    - no randomness, no clock: the same commands and dt give the same states.
How to test
    .venv/bin/python -m tests.test_body   (sim section: speed / accel bounds, arrival, wheels, stop, determinism)
"""
import math
from dataclasses import dataclass

NOT_READY_HINT = ("Notes/HOWTO-body.md, section « Brancher un vrai backend » (plan B3 MuJoCo / B4 matériel réel)")


@dataclass
class Target:
    """One command for a backend, hardware units: value = position (position mode) or speed (velocity mode)."""
    value: float
    max_speed: float
    max_accel: float


class Backend:
    """Interface every backend implements (all values in hardware units)."""
    name = "abstract"

    def configure(self, joints) -> None:   # joints: list of joints.Joint (ids, modes)
        raise NotImplementedError

    def read_state(self) -> dict:          # {id: {position, velocity, current, temperature}}
        raise NotImplementedError

    def command(self, targets: dict) -> None:   # {id: Target}
        raise NotImplementedError

    def stop_all(self) -> None:
        raise NotImplementedError

    def enable(self, joint_id: str) -> None:
        raise NotImplementedError

    def disable(self, joint_id: str) -> None:
        raise NotImplementedError

    def step(self, dt: float) -> None:
        raise NotImplementedError

    def poll_events(self) -> list:
        """Optional: new physical events since the last call, [{"joint": id | None, "message": French text, ...}].
        Body turns each into a `collision` body event. Backends without contact sensing return nothing."""
        return []

    def close(self) -> None:
        """Optional: release threads / devices (no-op by default)."""


class _SimJoint:
    __slots__ = ("mode", "pos", "vel", "acc", "target", "vmax", "amax", "enabled", "current", "temp")

    def __init__(self, mode: str):
        self.mode = mode
        self.pos = self.vel = self.acc = 0.0
        self.target = 0.0
        self.vmax, self.amax = 1.0, 1.0
        self.enabled = True
        self.current, self.temp = 0.0, 25.0


class SimBackend(Backend):
    """Deterministic first-order kinematic simulator (see the module invariants)."""
    name = "sim"
    IDLE_A, SPEED_A, ACCEL_A = 0.05, 0.2, 0.6
    AMBIENT_C, HEAT_C, TAU_S = 25.0, 15.0, 60.0

    def __init__(self, initial: dict | None = None):
        self._initial = dict(initial or {})   # {id: hardware position} at configure time (tests)
        self.j: dict = {}

    def configure(self, joints) -> None:
        self.j = {}
        for jt in joints:
            s = _SimJoint(jt.mode)
            if jt.mode == "position":
                s.pos = s.target = float(self._initial.get(jt.id, 0.0))
            self.j[jt.id] = s

    def read_state(self) -> dict:
        return {k: {"position": s.pos, "velocity": s.vel, "current": s.current, "temperature": s.temp,
                    "enabled": s.enabled} for k, s in self.j.items()}

    def command(self, targets: dict) -> None:
        for k, t in targets.items():
            s = self.j[k]
            s.target, s.vmax, s.amax = float(t.value), max(1e-9, float(t.max_speed)), max(1e-9, float(t.max_accel))

    def stop_all(self) -> None:
        for s in self.j.values():
            self._halt(s)

    @staticmethod
    def _halt(s: _SimJoint) -> None:
        s.vel = s.acc = 0.0
        s.target = s.pos if s.mode == "position" else 0.0

    def enable(self, joint_id: str) -> None:
        s = self.j[joint_id]
        s.enabled = True
        self._halt(s)

    def disable(self, joint_id: str) -> None:
        s = self.j[joint_id]
        s.enabled = False
        self._halt(s)

    def step(self, dt: float) -> None:
        if dt <= 0:
            return
        for s in self.j.values():
            v0 = s.vel
            if not s.enabled:
                s.vel = 0.0
            elif s.mode == "velocity":
                want = max(-s.vmax, min(s.vmax, s.target))
                dv = max(-s.amax * dt, min(s.amax * dt, want - s.vel))
                s.vel += dv
                s.pos += s.vel * dt
            else:
                self._step_position(s, dt)
            s.acc = (s.vel - v0) / dt
            # plausible electrical / thermal numbers for the dashboard (not a motor model)
            s.current = (0.0 if not s.enabled else self.IDLE_A + self.SPEED_A * abs(s.vel) / s.vmax
                         + self.ACCEL_A * min(1.0, abs(s.acc) / s.amax))
            goal = self.AMBIENT_C + self.HEAT_C * s.current * s.current
            s.temp += (goal - s.temp) * (1.0 - math.exp(-dt / self.TAU_S))

    @staticmethod
    def _stop_steps(v: float, da: float) -> float:
        """Sum of the speeds v, v - da, v - 2 da, ... (positive terms): stopping distance / dt, this step included."""
        if v <= 0:
            return 0.0
        m = math.floor(v / da - 1e-12)        # number of full decrements before the speed reaches (0, da]
        return (m + 1) * (v - m * da / 2.0)

    @classmethod
    def _step_position(cls, s: _SimJoint, dt: float) -> None:
        err = s.target - s.pos
        da = s.amax * dt
        if abs(err) < 1e-9 and abs(s.vel) <= da:
            s.pos, s.vel = s.target, 0.0
            return
        # Work in the direction of the error (sign = +1 toward the target). Pick the LARGEST speed of this step,
        # within one acceleration step of the current speed and within vmax, from which braking one step at a time
        # (v, v - da, ...) still stops before the target: dt * stop_steps(v) <= |err|. That discrete condition is
        # exact (the continuous sqrt(2 a |err|) curve overshoots by up to one step), so the joint never crosses the
        # target, then the final step lands on it.
        sign = 1.0 if err > 0 else -1.0
        e, v0 = abs(err), sign * s.vel
        lo, hi = max(-s.vmax, v0 - da), min(s.vmax, v0 + da)
        if dt * cls._stop_steps(hi, da) <= e:
            v = hi
        elif dt * cls._stop_steps(lo, da) > e:
            v = lo                             # target moved behind a fast joint: overshoot is unavoidable
        else:
            for _ in range(60):                # bisection: stop_steps is monotone in v
                mid = (lo + hi) / 2.0
                if dt * cls._stop_steps(mid, da) <= e:
                    lo = mid
                else:
                    hi = mid
            v = lo
        s.pos += sign * v * dt
        s.vel = sign * v
        if abs(s.target - s.pos) < 1e-9:
            s.pos = s.target


class HardwareBackend(Backend):
    """Placeholder of the real motors (servos over serial bus / PWM, ROS 2; plan B4): refuses to start."""
    name = "real"
    REASON = "Backend matériel réel pas encore disponible (matériel non choisi) : voir " + NOT_READY_HINT

    def __init__(self, *_a, **_k):
        raise NotImplementedError(self.REASON)


BACKENDS = ("sim", "mujoco", "real")


def _mujoco_module():
    from . import mujoco_backend    # lazy: nothing heavy is imported until the backend is asked for
    return mujoco_backend


def availability() -> dict:
    """{name: {"available": bool, "reason": French text or None}} of every backend (additive state field)."""
    ok, why = _mujoco_module().status()
    return {"sim": {"available": True, "reason": None}, "mujoco": {"available": ok, "reason": why},
            "real": {"available": False, "reason": HardwareBackend.REASON}}


def make_backend(name: str) -> Backend:
    """Build the named backend; NotImplementedError (French reason) when it cannot start, ValueError when unknown."""
    if name not in BACKENDS:
        raise ValueError("body_backend inconnu : %r (attendu %s)" % (name, " | ".join(BACKENDS)))
    if name == "mujoco":
        return _mujoco_module().MujocoBackend()
    return SimBackend() if name == "sim" else HardwareBackend()
