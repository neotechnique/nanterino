"""Tests of lot B3a: the provisional MuJoCo model (MJCF) and the MujocoBackend shell, WITHOUT the mujoco module.

logging: robotlog via nanterino.log (imported by nanterino.body; this file only prints PASS / FAIL / SKIP lines).

Purpose : prove that nanterino/body/nanterino.xml stays consistent with nanterino/body/body.yaml (one joint + one
          actuator per body.yaml id, ranges = calibration defaults, wheel track / radius, unique names, camera, floor,
          front marker, PROVISIONAL header); that a missing `mujoco` module falls back to the simulator with a French
          reason and never crashes; that the default backend is still sim; and that MujocoBackend's own logic (set
          point profile, range / speed clamps, disable, stop_all, odometer, collision events, Body integration) is right
          against a FAKE `mujoco` module that parses the same XML. Tests that need the real module are written but
          skipped with a message when it is not installed.
Boundary: writes no file; never imports nanterino.server, never touches state/body-calibration.json; the fake module
          lives in this file and is removed from sys.modules after use.
How to run (repo root):
    .venv/bin/python -m tests.test_body_mjcf      (~2 s; prints `body_mjcf tests: n/n passed`, exit 1 on failure)
"""
import math
import os
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, "/opt/robot/lib")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import yaml  # noqa: E402

from nanterino import body as B  # noqa: E402
from nanterino.body import backends as BK, calibration as C, joints as JT  # noqa: E402

XML = os.path.join(REPO, "nanterino", "body", "nanterino.xml")
GESTURES = os.path.join(REPO, "nanterino", "body", "gestures.yaml")
CONFIG_PY = os.path.join(REPO, "nanterino", "config.py")
results = []


def check(name, ok, info=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  " + str(info)[:600]), flush=True)


def skip(name, why):
    print("SKIP %s (%s)" % (name, why), flush=True)


def layout():
    return JT.load_layout()


def body_yaml():
    with open(JT.DEFAULT_LAYOUT, encoding="utf-8") as f:
        return yaml.safe_load(f)


def tree():
    return ET.parse(XML).getroot()


# --------------------------------------------------------------------------------------------- the MJCF file
def test_mjcf_static():
    raw = open(XML, encoding="utf-8").read()
    root = tree()
    check("mjcf: well-formed XML with a <mujoco> root", root.tag == "mujoco")
    check("mjcf: header says PROVISIONAL dimensions and gives units", "PROVISIONAL" in raw and "Units:" in raw)
    comp = root.find("compiler")
    check("mjcf: compiler angle is degree (ranges are written in body.yaml units)",
          comp is not None and comp.get("angle") == "degree")
    for tag in ("joint", "geom", "body", "camera"):
        names = [e.get("name") for e in root.iter(tag) if e.get("name")]
        check("mjcf: <%s> names are unique (%d)" % (tag, len(names)), len(names) == len(set(names)), names)
    acts = [e.get("name") for e in root.find("actuator")]
    check("mjcf: actuator names are unique", len(acts) == len(set(acts)), acts)

    joints = {e.get("name"): e for e in root.iter("joint")}
    actuators = {e.get("name"): e for e in root.find("actuator")}
    for j in layout():
        je, ae = joints.get(j.id), actuators.get(j.id)
        check("mjcf: joint + actuator exist for %s" % j.id, je is not None and ae is not None)
        if je is None or ae is None:
            continue
        check("mjcf: actuator %s drives the joint of the same name" % j.id, ae.get("joint") == j.id, ae.attrib)
        check("mjcf: actuator %s kind matches the mode (%s)" % (j.id, j.mode),
              ae.tag == ("velocity" if j.mode == "velocity" else "position"), ae.tag)
    extra = set(actuators) - {j.id for j in layout()}
    check("mjcf: no actuator without a body.yaml joint", not extra, extra)

    for j in layout():
        if j.mode != "position":
            continue
        rec = C.defaults_for(j)
        lo, hi = (float(x) for x in joints[j.id].get("range").split())
        check("mjcf: range of %s equals the calibration defaults (%g..%g)" % (j.id, rec["min"], rec["max"]),
              abs(lo - rec["min"]) < 1e-9 and abs(hi - rec["max"]) < 1e-9, (lo, hi))
        check("mjcf: %s is in degrees like the model" % j.id, j.unit == "deg")


def test_mjcf_geometry():
    root = tree()
    geo = body_yaml()["geometry"]
    with open(GESTURES, encoding="utf-8") as f:
        gest = yaml.safe_load(f)
    check("geometry: body.yaml track_m equals gestures.yaml base.track_m",
          abs(geo["track_m"] - gest["base"]["track_m"]) < 1e-12, (geo, gest["base"]))
    wheels = [j for j in layout() if j.mode == "velocity"]
    ys = []
    for j in wheels:
        link = next((b for b in root.iter("body") if b.get("name") == j.id + "_link"), None)
        tire = next((g for g in root.iter("geom") if g.get("name") == j.id + "_tire"), None)
        check("geometry: wheel body and tire geom exist for %s" % j.id, link is not None and tire is not None)
        if link is None or tire is None:
            continue
        ys.append(float(link.get("pos").split()[1]))
        check("geometry: tire radius of %s = body.yaml wheel_radius_m" % j.id,
              abs(float(tire.get("size").split()[0]) - geo["wheel_radius_m"]) < 1e-12, tire.get("size"))
        rec = C.defaults_for(j)
        lim = float(next(a for a in root.find("actuator") if a.get("name") == j.id).get("ctrlrange").split()[1])
        check("geometry: wheel ctrlrange of %s = max_speed / radius" % j.id,
              abs(lim - rec["max_speed"] / geo["wheel_radius_m"]) < 1e-9, lim)
        check("geometry: wheel joint %s is continuous (no range)" % j.id,
              next(e for e in root.iter("joint") if e.get("name") == j.id).get("range") is None)
    check("geometry: wheel track in the model = body.yaml track_m (symmetric on y)",
          len(ys) == 2 and abs(abs(ys[0] - ys[1]) - geo["track_m"]) < 1e-12 and abs(ys[0] + ys[1]) < 1e-12, ys)
    geoms = {g.get("name"): g for g in root.iter("geom")}
    check("model: floor plane, front markers and a head camera exist",
          geoms.get("floor") is not None and geoms["floor"].get("type") == "plane"
          and "base_front_marker" in geoms and "head_front_marker" in geoms
          and any(c.get("name") == "head_cam" for c in root.iter("camera")))
    check("model: a free base joint exists (mobile base)", any(True for _ in root.iter("freejoint")))


# --------------------------------------------------------------------------------------------- fallback / selection
class _Hidden:
    """Context manager: `import mujoco` fails (sys.modules entry None => ImportError), whatever is installed."""

    def __enter__(self):
        self.old = sys.modules.get("mujoco", "__absent__")
        sys.modules["mujoco"] = None
        return self

    def __exit__(self, *a):
        if self.old == "__absent__":
            sys.modules.pop("mujoco", None)
        else:
            sys.modules["mujoco"] = self.old


def test_fallback_and_default():
    mjb = __import__("nanterino.body.mujoco_backend", fromlist=["x"])
    with _Hidden():
        ok, why = mjb.status()
        check("fallback: status() says unavailable with a French reason", ok is False and "MuJoCo indisponible" in why
              and "pip install mujoco" in why, why)
        try:
            BK.make_backend("mujoco")
            raised = None
        except NotImplementedError as e:
            raised = str(e)
        check("fallback: make_backend('mujoco') raises NotImplementedError with the reason", raised == why, raised)
        b = B.create({"body_backend": "mujoco"})
        s = b.state()
        check("fallback: create() falls back to the simulator without crashing",
              b.backend.name == "sim" and s["backend"] == "sim", s["backend"])
        check("fallback: state exposes requested name, availability and the reason",
              s["backend_requested"] == "mujoco" and s["backend_available"] is False
              and "MuJoCo indisponible" in (s["backend_error"] or ""), (s["backend_requested"], s["backend_available"]))
        av = BK.availability()
        check("fallback: availability() lists sim ok, mujoco missing, real missing",
              av["sim"]["available"] and not av["mujoco"]["available"] and not av["real"]["available"], av)
    b = B.create({})
    s = b.state()
    check("default: no config key = sim, available, no error",
          s["backend"] == "sim" and s["backend_requested"] == "sim" and s["backend_available"] is True
          and s["backend_error"] is None, s)
    check("default: config.py ships body_backend = sim", '"body_backend": "sim"' in open(CONFIG_PY, encoding="utf-8").read())
    try:
        B.create({"body_backend": "nope"}, strict=True)
        err = None
    except ValueError as e:
        err = str(e)
    check("default: unknown backend name is refused in strict mode", err and "inconnu" in err, err)


# --------------------------------------------------------------------------------------------- fake mujoco
class _Obj:
    mjOBJ_JOINT, mjOBJ_ACTUATOR, mjOBJ_GEOM = 3, 19, 5


class _Contact:
    def __init__(self, g1, g2, dist):
        self.geom1, self.geom2, self.dist = g1, g2, dist


class _FakeModel:
    """Parses the REAL nanterino.xml: hinge joints (radians), actuators, named geoms; ideal actuators."""

    class opt:
        timestep = 0.002

    @classmethod
    def from_xml_path(cls, path):
        root = ET.parse(path).getroot()
        m = cls()
        m.jnames, m.jrange = [], []
        for e in root.iter("joint"):
            m.jnames.append(e.get("name"))
            r = e.get("range")
            m.jrange.append([math.radians(float(x)) for x in r.split()] if r else [0.0, 0.0])
        m.jnt_qposadr = list(range(len(m.jnames)))
        m.jnt_dofadr = list(range(len(m.jnames)))
        m.jnt_range = m.jrange
        m.anames = [e.get("name") for e in root.find("actuator")]
        m.gnames = [e.get("name") for e in root.iter("geom")]
        m.geom_size = [[float(x) for x in (e.get("size") or "0").split()] + [0.0] for e in root.iter("geom")]
        return m


class _FakeData:
    def __init__(self, m):
        n = len(m.jnames)
        self.qpos, self.qvel, self.ctrl = [0.0] * n, [0.0] * n, [0.0] * len(m.anames)
        self.actuator_force = [0.0] * len(m.anames)
        self.contact, self.ncon = [], 0


def _names(m, obj):
    return {_Obj.mjOBJ_JOINT: m.jnames, _Obj.mjOBJ_ACTUATOR: m.anames, _Obj.mjOBJ_GEOM: m.gnames}[obj]


def _fake_name2id(m, obj, name):
    names = _names(m, obj)
    return names.index(name) if name in names else -1


def _fake_step(m, d):
    h = m.opt.timestep
    for ai, an in enumerate(m.anames):
        ji = m.jnames.index(an)
        if an.endswith("wheel"):
            d.qvel[ji] = d.ctrl[ai]
            d.qpos[ji] += d.qvel[ji] * h
        else:
            d.qvel[ji] = (d.ctrl[ai] - d.qpos[ji]) / h
            d.qpos[ji] = d.ctrl[ai]
        d.actuator_force[ai] = 0.1 * d.qvel[ji]


class _FakeMujoco:
    mjtObj = _Obj
    MjModel = _FakeModel
    MjData = _FakeData
    mj_name2id = staticmethod(_fake_name2id)
    mj_id2name = staticmethod(lambda m, obj, i: _names(m, obj)[i])
    mj_forward = staticmethod(lambda m, d: None)
    mj_step = staticmethod(_fake_step)


class _WithFake:
    def __enter__(self):
        self.old = sys.modules.get("mujoco", "__absent__")
        sys.modules["mujoco"] = _FakeMujoco
        return self

    def __exit__(self, *a):
        if self.old == "__absent__":
            sys.modules.pop("mujoco", None)
        else:
            sys.modules["mujoco"] = self.old


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def build():
    from nanterino.body.mujoco_backend import MujocoBackend
    be = MujocoBackend(start=False)
    clk = Clock()
    body = B.Body(layout(), be, None, clock=clk, wall=lambda: 1.7e9 + clk.t, backend_requested="mujoco")
    body.tick()
    return body, be, clk


def run(body, be, clk, seconds, dt=0.02, hook=None):
    for _ in range(int(round(seconds / dt))):
        clk.t += dt
        be.advance(dt)
        body.tick()
        if hook:
            hook()


def state(body, jid):
    return next(j for j in body.state()["joints"] if j["id"] == jid)


def collisions(body):
    return [e for e in body.events if e["kind"] == "collision"]


def test_backend_with_fake_module():
    with _WithFake():
        mjb = __import__("nanterino.body.mujoco_backend", fromlist=["x"])
        ok, why = mjb.status()
        check("backend[fake]: status() available when the module imports", ok and why is None, why)
        be0 = B.create({"body_backend": "mujoco"})
        s = be0.state()
        check("backend[fake]: create() selects mujoco, available, no error",
              s["backend"] == "mujoco" and s["backend_available"] and s["backend_error"] is None, s["backend"])
        be0.backend.close()
        body, be, clk = build()
        worst = [0.0]
        body.command({"head_pan": 60})
        run(body, be, clk, 3.0, hook=lambda: worst.__setitem__(0, max(worst[0], abs(state(body, "head_pan")["velocity"]))))
        st = state(body, "head_pan")
        check("backend: head_pan lands on 60 deg", abs(st["position"] - 60) < 0.2, st["position"])
        check("backend: speed bounded by max_speed (90 deg/s)", 5 < worst[0] <= 90 * 1.05, worst[0])
        be.command({"head_pan": BK.Target(500.0, 90.0, 300.0)})
        run(body, be, clk, 4.0)
        check("backend: set point clamped to the model joint range (90 deg) even if Body is bypassed",
              abs(state(body, "head_pan")["position"] - 90) < 0.2, state(body, "head_pan")["position"])
        body.command({"head_tilt": 500})
        run(body, be, clk, 3.0)
        check("body: Body.clamp bounds the command before the backend (tilt <= 40)",
              abs(state(body, "head_tilt")["position"] - 40) < 0.2, state(body, "head_tilt")["position"])
        body.command({"arm_l_shoulder": 150})
        run(body, be, clk, 0.3)
        body.stop_all("test")
        p = state(body, "arm_l_shoulder")["position"]
        run(body, be, clk, 1.0)
        check("estop: arm holds its position after the latched stop",
              abs(state(body, "arm_l_shoulder")["position"] - p) < 0.3 and body.estop["active"],
              (p, state(body, "arm_l_shoulder")["position"]))
        body.command({"arm_l_shoulder": 0})
        run(body, be, clk, 1.0)
        check("estop: commands refused while latched (arm does not move)",
              abs(state(body, "arm_l_shoulder")["position"] - p) < 0.3)
        body.reset_estop()
        body.command({"base_left_wheel": 0.3})
        run(body, be, clk, 1.0)
        w = state(body, "base_left_wheel")
        check("backend: wheel reaches 0.3 m/s", abs(w["velocity"] - 0.3) < 0.01, w["velocity"])
        check("backend: wheel odometer in metres (0.3 * 1 s minus the 0.3 s ramp: 0.255)", 0.24 < w["position"] < 0.27,
              w["position"])
        body.command({"base_left_wheel": 9.0})
        run(body, be, clk, 2.0)
        check("backend: wheel speed clamped to 0.5 m/s", abs(state(body, "base_left_wheel")["velocity"] - 0.5) < 0.01,
              state(body, "base_left_wheel")["velocity"])
        be.disable("head_pan")
        be.command({"head_pan": BK.Target(-60.0, 90.0, 300.0)})
        p = state(body, "head_pan")["position"]
        run(body, be, clk, 1.0)
        check("backend: a disabled joint holds its position", abs(state(body, "head_pan")["position"] - p) < 0.3)
        be.enable("head_pan")
        be.poll_events()
        names, d = be._m.gnames, be._d
        d.contact = [_Contact(names.index("floor"), names.index("base_left_wheel_tire"), -0.001),
                     _Contact(names.index("floor"), names.index("caster_front"), -0.001)]
        d.ncon = 2
        run(body, be, clk, 0.1)
        check("events: wheel / caster support contacts are not collisions", not collisions(body))
        d.contact = [_Contact(names.index("arm_l_fore_geom"), names.index("torso"), -0.002)]
        d.ncon = 1
        run(body, be, clk, 0.3)
        col = collisions(body)
        check("events: a new arm / torso contact becomes ONE collision body event (warning, French)",
              len(col) == 1 and col[0]["level"] == "warning" and "Collision" in col[0]["message"]
              and "torso" in col[0]["message"], col)
        d.contact, d.ncon = [], 0
        run(body, be, clk, 0.1)
        d.contact = [_Contact(names.index("arm_l_fore_geom"), names.index("torso"), -0.002)]
        d.ncon = 1
        run(body, be, clk, 0.1)
        check("events: contact released then made again is reported again", len(collisions(body)) == 2)
        from nanterino.body.mujoco_backend import MujocoBackend
        be2 = MujocoBackend(rate_hz=200)
        b2 = B.Body(layout(), be2, None)
        b2.command({"head_pan": 20})
        time.sleep(0.6)
        pos = b2.state()["joints"][0]["position"]
        be2.close()
        check("thread: the physics loop advances on its own and stops on close()", pos > 5 and be2._thread is None, pos)


# --------------------------------------------------------------------------------------------- real mujoco (optional)
def test_real_mujoco():
    try:
        import mujoco  # noqa: F401
    except Exception as e:   # noqa: BLE001
        skip("real mujoco: model loads, rests on its wheels, joints and wheels move", "module mujoco not installed: %s" % e)
        return
    from nanterino.body.mujoco_backend import MujocoBackend
    be = MujocoBackend(start=False)
    clk = Clock()
    body = B.Body(layout(), be, None, clock=clk, wall=lambda: 1.7e9 + clk.t)
    run(body, be, clk, 1.0, dt=0.01)
    check("real: no collision event while resting on wheels and casters", not collisions(body), body.events)
    body.command({"head_pan": 45, "arm_l_shoulder": 90, "base_left_wheel": 0.2, "base_right_wheel": 0.2})
    run(body, be, clk, 3.0, dt=0.01)
    check("real: head and arm reach their targets", abs(state(body, "head_pan")["position"] - 45) < 3
          and abs(state(body, "arm_l_shoulder")["position"] - 90) < 6)
    check("real: wheels roll forward (odometer > 0.3 m)", state(body, "base_left_wheel")["position"] > 0.3)


def main():
    for t in (test_mjcf_static, test_mjcf_geometry, test_fallback_and_default, test_backend_with_fake_module,
              test_real_mujoco):
        try:
            t()
        except Exception as e:  # keep going, report
            import traceback
            traceback.print_exc()
            check("%s completed" % t.__name__, False, repr(e))
    ok = sum(1 for _, r in results if r)
    print("body_mjcf tests: %d/%d passed" % (ok, len(results)))
    sys.exit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    main()
