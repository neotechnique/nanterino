"""MuJoCo physics backend of the robot body (lot B3a): a shell around nanterino/body/nanterino.xml.

logging: robotlog via nanterino.log (start / stop of the physics thread are INFO records; nothing on the hot path).

Purpose
    MujocoBackend implements the backends.Backend interface on a MuJoCo model of the (provisional) robot: position
    actuators for the head and arms, velocity actuators for the two driven wheels, a floor, contacts. It lets the
    Mouvement nodes, the dashboard and the gestures run against real rigid-body physics before the hardware exists.
Boundary
    - `mujoco` is imported LAZILY (`status()`); this module imports without it. Without the module, `status()` says
      why in French and the constructor raises NotImplementedError, which nanterino.body.create() turns into a fall
      back to the simulator plus a dashboard banner. Nothing is installed by this code.
    - Body (core.py) stays in front: every target arrives already clamped (Body.clamp) and the latched e-stop calls
      stop_all(); this backend only adds a second, model-level clamp on the joint range and speed (never wider).
    - Hardware units in / out, like SimBackend: position joints in the Joint unit (deg or rad), wheels in m/s (speed)
      and metres (odometer). The wheel radius is READ FROM THE MODEL (geom `<wheel id>_tire`), never duplicated.
    - Collisions are reported through poll_events(); core.py turns them into `collision` body events.
Invariants
    - a physics thread steps the model at RATE_HZ in real time under `self._lock`; every public method takes the same
      lock, so Body can call from any thread; step(dt) is accepted and ignored (the thread owns time);
    - position set points move toward the target with |speed| <= max_speed and braking limited by max_accel (the
      actuator then tracks the set point), clamped to the model joint range; a disabled joint holds its position,
      a disabled / stopped wheel gets ctrl 0;
    - current (A) = |actuator force| * AMP_PER_NM (provisional, NOT a motor model); temperature relaxes like the sim;
    - UNVERIFIED against a real MuJoCo (not installed on the Jetson yet): tests drive this code with a fake `mujoco`
      module (tests/test_body_mjcf.py); run it once with the real module before trusting the physics numbers.
How to test
    .venv/bin/python -m tests.test_body_mjcf   (offline; real-MuJoCo tests are skipped when the module is missing)
"""
import importlib
import math
import os
import threading

from ..log import log
from .backends import Backend, SimBackend

DEFAULT_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nanterino.xml")
RATE_HZ = 100.0           # physics loop rate (wall clock); model.opt.timestep is 0.002 s -> 5 substeps per loop
AMP_PER_NM = 1.0          # provisional torque -> current conversion for the dashboard
_UNAVAILABLE = ("Backend MuJoCo indisponible (lot B3a) : le module Python « mujoco » n'est pas installé (%s). "
                "Installation : « pip install mujoco » dans le .venv, voir Notes/HOWTO-body.md, section « MuJoCo (B3a) ».")


def _import_mujoco():
    return importlib.import_module("mujoco")


def status() -> tuple:
    """(available, French reason or None): can a MujocoBackend be built right now? Never raises, never installs."""
    try:
        _import_mujoco()
    except Exception as e:   # noqa: BLE001 - ImportError, or a broken native library
        return False, _UNAVAILABLE % (type(e).__name__ + ": " + str(e)[:80])
    if not os.path.isfile(DEFAULT_MODEL):
        return False, "Backend MuJoCo indisponible (lot B3a) : modèle introuvable (%s)." % DEFAULT_MODEL
    return True, None


class _J:
    __slots__ = ("id", "mode", "scale", "qadr", "dadr", "aid", "lo", "hi", "radius", "goal", "sp", "sp_vel", "vmax",
                 "amax", "enabled", "current", "temp", "q0")

    def __init__(self, jid, mode):
        self.id, self.mode = jid, mode
        self.goal = self.sp = self.sp_vel = 0.0     # SI set point state (rad or rad/s)
        self.vmax = self.amax = 1.0                 # SI limits (rad/s, rad/s^2)
        self.enabled = True
        self.current, self.temp = 0.0, SimBackend.AMBIENT_C


class MujocoBackend(Backend):
    """Rigid-body backend on nanterino.xml (see the module docstring)."""
    name = "mujoco"

    def __init__(self, model_path: str = DEFAULT_MODEL, *, rate_hz: float = RATE_HZ, start: bool = True):
        ok, why = status()
        if not ok:
            raise NotImplementedError(why)
        self._mj = _import_mujoco()
        self._model_path, self._rate, self._start = model_path, float(rate_hz), bool(start)
        self._lock = threading.RLock()
        self._thread = None
        self._stop = threading.Event()
        self.j: dict = {}
        self._m = self._d = None
        self._contacts = set()      # frozenset({geom a, geom b}) currently reported as colliding
        self._events: list = []

    # ------------------------------------------------------------------ lifecycle
    def configure(self, joints) -> None:
        mj = self._mj
        self.close()
        with self._lock:
            self._m = mj.MjModel.from_xml_path(self._model_path)
            self._d = mj.MjData(self._m)
            self.j = {}
            for jt in joints:
                s = _J(jt.id, jt.mode)
                jid = mj.mj_name2id(self._m, mj.mjtObj.mjOBJ_JOINT, jt.id)
                aid = mj.mj_name2id(self._m, mj.mjtObj.mjOBJ_ACTUATOR, jt.id)
                if jid < 0 or aid < 0:
                    raise ValueError("Modèle MuJoCo : articulation ou actionneur « %s » manquant." % jt.id)
                s.qadr, s.dadr, s.aid = int(self._m.jnt_qposadr[jid]), int(self._m.jnt_dofadr[jid]), aid
                if jt.mode == "velocity":
                    gid = mj.mj_name2id(self._m, mj.mjtObj.mjOBJ_GEOM, jt.id + "_tire")
                    if gid < 0:
                        raise ValueError("Modèle MuJoCo : géométrie « %s_tire » (rayon de roue) manquante." % jt.id)
                    s.radius, s.scale = float(self._m.geom_size[gid][0]), 1.0
                    s.lo = s.hi = 0.0
                else:
                    s.scale = math.pi / 180.0 if jt.unit == "deg" else 1.0
                    s.lo, s.hi = (float(x) for x in self._m.jnt_range[jid])
                    s.sp = s.goal = float(self._d.qpos[s.qadr])
                s.q0 = float(self._d.qpos[s.qadr])
                self.j[jt.id] = s
            mj.mj_forward(self._m, self._d)
            self._contacts, self._events = set(), []
        if self._start:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="mujoco-backend", daemon=True)
            self._thread.start()
            log.info("mujoco backend started model=%s rate=%.0f Hz", os.path.basename(self._model_path), self._rate)

    def close(self) -> None:
        t, self._thread = self._thread, None
        if t is not None:
            self._stop.set()
            t.join(2.0)
            log.info("mujoco backend stopped")

    def _run(self) -> None:
        period = 1.0 / self._rate
        while not self._stop.wait(period):
            try:
                self.advance(period)
            except Exception:   # noqa: BLE001 - a physics failure must not kill the thread silently
                log.exception("mujoco step failed")

    # ------------------------------------------------------------------ interface
    def read_state(self) -> dict:
        with self._lock:
            out = {}
            for k, s in self.j.items():
                q, v = float(self._d.qpos[s.qadr]), float(self._d.qvel[s.dadr])
                if s.mode == "velocity":
                    pos, vel = (q - s.q0) * s.radius, v * s.radius
                else:
                    pos, vel = q / s.scale, v / s.scale
                out[k] = {"position": pos, "velocity": vel, "current": s.current, "temperature": s.temp,
                          "enabled": s.enabled}
            return out

    def command(self, targets: dict) -> None:
        with self._lock:
            for k, t in targets.items():
                s = self.j[k]
                if s.mode == "velocity":
                    f = 1.0 / s.radius                      # m/s -> rad/s
                    s.goal = float(t.value) * f
                    s.vmax, s.amax = max(1e-9, float(t.max_speed) * f), max(1e-9, float(t.max_accel) * f)
                else:
                    s.goal = min(s.hi, max(s.lo, float(t.value) * s.scale))
                    s.vmax = max(1e-9, float(t.max_speed) * s.scale)
                    s.amax = max(1e-9, float(t.max_accel) * s.scale)

    def stop_all(self) -> None:
        with self._lock:
            for s in self.j.values():
                self._halt(s)

    def _halt(self, s: _J) -> None:
        s.sp_vel = 0.0
        if s.mode == "velocity":
            s.goal = s.sp = 0.0
        else:
            s.goal = s.sp = float(self._d.qpos[s.qadr])

    def enable(self, joint_id: str) -> None:
        with self._lock:
            s = self.j[joint_id]
            s.enabled = True
            self._halt(s)

    def disable(self, joint_id: str) -> None:
        with self._lock:
            s = self.j[joint_id]
            s.enabled = False
            self._halt(s)

    def step(self, dt: float) -> None:
        """Ignored: the physics thread owns time (a real bus backend would poll here)."""

    def poll_events(self) -> list:
        with self._lock:
            ev, self._events = self._events, []
            return ev

    # ------------------------------------------------------------------ physics (one loop period)
    def advance(self, dt: float) -> None:
        """One loop period: update set points, step the model for `dt` seconds, refresh currents and contacts."""
        mj = self._mj
        with self._lock:
            n = max(1, int(round(dt / float(self._m.opt.timestep))))
            h = dt / n
            for _ in range(n):
                for s in self.j.values():
                    self._drive(s, h)
                mj.mj_step(self._m, self._d)
            for s in self.j.values():
                s.current = 0.0 if not s.enabled else abs(float(self._d.actuator_force[s.aid])) * AMP_PER_NM
                goal = SimBackend.AMBIENT_C + SimBackend.HEAT_C * s.current * s.current
                s.temp += (goal - s.temp) * (1.0 - math.exp(-dt / SimBackend.TAU_S))
            self._scan_contacts()

    def _drive(self, s: _J, h: float) -> None:
        d = self._d
        if not s.enabled:
            d.ctrl[s.aid] = 0.0 if s.mode == "velocity" else float(d.qpos[s.qadr])
            return
        if s.mode == "velocity":
            want = max(-s.vmax, min(s.vmax, s.goal))
            s.sp += max(-s.amax * h, min(s.amax * h, want - s.sp))
            d.ctrl[s.aid] = s.sp
            return
        err = s.goal - s.sp
        if abs(err) < 1e-9 and abs(s.sp_vel) <= s.amax * h:
            s.sp, s.sp_vel = s.goal, 0.0
        else:
            sign = 1.0 if err > 0 else -1.0
            want = sign * min(s.vmax, math.sqrt(2.0 * s.amax * abs(err)))     # braking-limited speed
            s.sp_vel += max(-s.amax * h, min(s.amax * h, want - s.sp_vel))
            nxt = s.sp + s.sp_vel * h
            if (nxt - s.goal) * sign > 0:                                        # would cross the target: land
                nxt, s.sp_vel = s.goal, 0.0
            s.sp = nxt
        d.ctrl[s.aid] = min(s.hi, max(s.lo, s.sp))

    def _geom_name(self, gid: int) -> str:
        return self._mj.mj_id2name(self._m, self._mj.mjtObj.mjOBJ_GEOM, gid) or ("geom%d" % gid)

    # Contacts that are normal in operation: wheels / casters on the floor.
    _FLOOR_OK = ("base_left_wheel_tire", "base_right_wheel_tire", "caster_front", "caster_rear")

    def _scan_contacts(self) -> None:
        """Queue one `collision` event per NEW penetrating pair (floor support contacts excluded)."""
        now = set()
        for i in range(int(self._d.ncon)):
            c = self._d.contact[i]
            if c.dist >= 0.0:
                continue
            a, b = self._geom_name(int(c.geom1)), self._geom_name(int(c.geom2))
            if "floor" in (a, b) and (a in self._FLOOR_OK or b in self._FLOOR_OK):
                continue
            now.add(frozenset((a, b)))
        for pair in sorted(now - self._contacts, key=sorted):
            names = sorted(pair)
            self._events.append({"joint": None, "message": "Collision : %s / %s" % (names[0], names[-1]),
                                 "geoms": names})
        self._contacts = now
