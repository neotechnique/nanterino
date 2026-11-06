"""Tests of lot C3 « Mécanique »: the hardware-agnostic body, its calibration, limits, e-stop, trace and HTTP handlers.

logging: robotlog via nanterino.log (imported by nanterino.body; this file only prints PASS / FAIL lines).

Purpose : prove the safety contract of nanterino/body: the simulator respects max speed / acceleration and lands on
          the target; Body.clamp bounds EVERY command path (API, graph source, look, sweep points, calibration
          change, import); a disabled joint refuses; the emergency stop latches until an explicit reset (API 409);
          calibration validation / atomic persistence / .bak backup / corrupt file / import refusal; set_min /
          set_max / set_zero from the current position; the trace ring buffer; the api.py handlers; the Brain ticks
          its body without changing the graph; server.py declares every /api/body route (read as text).
Boundary: Body on SimBackend with a manual clock; a non-threaded Brain on the fake world of nanterino/sim.py; files
          only under /tmp/test_body. Never imports nanterino.server, never touches state/body-calibration.json.
How to run (repo root):
    .venv/bin/python -m tests.test_body        (~2 s; prints `body tests: n/n passed`, exit 1 on failure)
"""
import ast
import json
import math
import os
import shutil
import sys

sys.path.insert(0, "/opt/robot/lib")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from nanterino import body as B  # noqa: E402
from nanterino.body import api as A, backends as BK, calibration as C, core as CORE, joints as JT  # noqa: E402

TMP = "/tmp/test_body"
results = []


def check(name, ok, info=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  " + str(info)[:600]), flush=True)


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def make(store_path=None, cfg=None):
    clk = Clock()
    b = B.create(cfg or {}, calibration_path=store_path, clock=clk, wall=lambda: 1.7e9 + clk.t)
    b.tick()
    return b, clk


def run(b, clk, seconds, dt=0.05):
    for _ in range(int(round(seconds / dt))):
        clk.t += dt
        b.tick()


def J(b, jid):
    return next(j for j in b.state()["joints"] if j["id"] == jid)


def tmp():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    return TMP


# ---------------------------------------------------------------- layout
def test_layout():
    js = JT.load_layout()
    ids = [j.id for j in js]
    check("layout: default body.yaml has the 8 provisional joints in order", ids == [
        "head_pan", "head_tilt", "arm_l_shoulder", "arm_l_elbow", "arm_r_shoulder", "arm_r_elbow",
        "base_left_wheel", "base_right_wheel"], ids)
    check("layout: groups head / arm_l / arm_r / base, wheels in velocity mode",
          {j.group for j in js} == set(JT.GROUPS) and all((j.mode == "velocity") == (j.kind == "wheel") for j in js))
    good = {"joints": {"a": {"kind": "servo", "unit": "deg", "group": "head"}}}
    check("layout: a minimal joint parses with defaults", JT.parse_layout(good)[0].defaults == {})
    bad = [{"joints": {}}, {"joints": {"A b": {"kind": "servo", "unit": "deg", "group": "head"}}},
           {"joints": {"a": {"kind": "wheel", "unit": "deg", "group": "base"}}},
           {"joints": {"a": {"kind": "servo", "unit": "m/s", "group": "head"}}},
           {"joints": {"a": {"kind": "servo", "unit": "deg", "group": "legs"}}},
           {"joints": {"a": {"kind": "laser", "unit": "deg", "group": "head"}}},
           {"joints": {"a": {"kind": "servo", "unit": "deg", "group": "head", "defaults": {"torque": 3}}}}]
    refused = 0
    for doc in bad:
        try:
            JT.parse_layout(doc)
        except JT.LayoutError:
            refused += 1
    check("layout: 7 invalid layouts refused", refused == len(bad), refused)


# ---------------------------------------------------------------- simulator
def profile(dt, target=80.0, vmax=90.0, amax=300.0):
    sim = BK.SimBackend()
    sim.configure([JT.Joint("p", "p", "pan", "deg", "head")])
    sim.command({"p": BK.Target(target, vmax, amax)})
    states, prev = [], 0.0
    for _ in range(int(3 / dt)):
        sim.step(dt)
        s = sim.read_state()["p"]
        states.append((s["position"], s["velocity"], s["velocity"] - prev))
        prev = s["velocity"]
    return states


def test_sim_profile():
    for dt in (0.05, 0.1, 0.02):
        st = profile(dt)
        vmax_ok = all(abs(v) <= 90.0 + 1e-9 for _, v, _ in st)
        acc_ok = all(abs(dv) <= 300.0 * dt + 1e-9 for _, _, dv in st)
        bad = [(round(p, 3), round(v, 3), round(dv / dt, 1)) for p, v, dv in st if abs(dv) > 300.0 * dt + 1e-9][:3]
        check("sim dt=%g: |velocity| <= max_speed at every step" % dt, vmax_ok)
        check("sim dt=%g: |dv/dt| <= max_accel at every step" % dt, acc_ok, bad)
        check("sim dt=%g: lands exactly on the target, at rest" % dt, st[-1][0] == 80.0 and st[-1][1] == 0.0, st[-1])
        check("sim dt=%g: never overshoots" % dt, max(p for p, _, _ in st) <= 80.0 + 1e-9)
    st = profile(0.05)
    t_reach = next(i for i, (p, _, _) in enumerate(st) if p == 80.0) * 0.05
    # trapezoid: 80 deg at 90 deg/s, 300 deg/s^2 -> 0.3 s ramp each way + cruise: about 1.19 s
    check("sim: duration matches the trapezoid (~1.2 s)", 1.1 <= t_reach <= 1.45, t_reach)
    check("sim: two runs give identical states (deterministic)", profile(0.05) == profile(0.05))
    sim = BK.SimBackend()
    sim.configure([JT.Joint("w", "w", "wheel", "m/s", "base")])
    sim.command({"w": BK.Target(0.4, 0.5, 1.0)})
    sim.step(0.1)
    v1 = sim.read_state()["w"]["velocity"]
    for _ in range(10):
        sim.step(0.1)
    w = sim.read_state()["w"]
    check("sim wheel: ramps at max_accel then holds the target speed",
          abs(v1 - 0.1) < 1e-9 and abs(w["velocity"] - 0.4) < 1e-9 and w["position"] > 0.25, (v1, w))
    sim.stop_all()
    check("sim wheel: stop_all zeroes the speed at once", sim.read_state()["w"]["velocity"] == 0.0)
    check("sim: current / temperature are plausible numbers", 0 < w["current"] < 1 and 25 <= w["temperature"] < 40, w)


# ---------------------------------------------------------------- clamp on every path
def test_clamp_everywhere():
    b, clk = make()
    r = b.command({"head_tilt": 99, "head_pan": -500})
    check("clamp/API-like command: above max -> max, below min -> min",
          r["applied"] == {"head_tilt": 40.0, "head_pan": -90.0} and set(r["clamped"]) == {"head_tilt", "head_pan"}, r)
    run(b, clk, 3)
    check("clamp: the joints really stop at the limits", J(b, "head_tilt")["position"] == 40.0
          and J(b, "head_pan")["position"] == -90.0, (J(b, "head_tilt")["position"], J(b, "head_pan")["position"]))
    r = b.command({"arm_l_elbow": 500}, source="graph")
    check("clamp: graph-sourced command clamped too", r["applied"]["arm_l_elbow"] == 135.0, r)
    check("clamp: a clamp is journaled (warning event)", any(e["kind"] == "clamp" and e["level"] == "warning"
                                                             for e in b.events))
    r = b.look(pan=120, tilt=-90)
    check("clamp: look() (sound turn-to / gaze) clamped", r["applied"] == {"head_pan": 90.0, "head_tilt": -30.0}, r)
    r = b.command({"base_left_wheel": 3.0})
    check("clamp: wheel speed clamped to max", r["applied"]["base_left_wheel"] == 0.5, r)
    st, rep = A.command(b, {"targets": {"head_pan": 1000}})
    check("clamp: api.command clamps and answers 200 with the applied value",
          st == 200 and rep["applied"]["head_pan"] == 90.0 and "head_pan" in rep["clamped"], (st, rep))
    # sweep points come from the calibration: narrow it, sweep, the joint never leaves the range
    ok, errs, _ = b.set_calibration({"arm_r_shoulder": {"min": -10.0, "max": 20.0}})
    b.sweep("arm_r_shoulder", speed=1.0)
    seen = []
    for _ in range(200):
        clk.t += 0.05
        b.tick()
        seen.append(J(b, "arm_r_shoulder")["position"])
    check("clamp: sweep stays within [min, max] and visits both limits",
          ok and min(seen) == -10.0 and max(seen) == 20.0, (errs, min(seen), max(seen)))
    # calibration change: a held target outside the new range is pulled back in
    b.command({"arm_l_shoulder": 150})
    run(b, clk, 5)
    b.set_calibration({"arm_l_shoulder": {"max": 90.0}})
    run(b, clk, 3)
    check("clamp: narrowing max pulls a joint parked above it back to the new max",
          J(b, "arm_l_shoulder")["position"] == 90.0 and J(b, "arm_l_shoulder")["target"] == 90.0,
          J(b, "arm_l_shoulder"))
    r = b.command({"head_pan": float("nan"), "head_tilt": True, "nope": 3})
    check("command: NaN / bool / unknown joint refused, nothing sent", set(r["refused"]) == {"head_pan", "head_tilt", "nope"}
          and not r["applied"] and r["cmd_id"] is None, r)
    r = b.command({"head_pan": 10}, speed=2)
    check("command: speed outside (0, 1] refused", r["error"] and not r["applied"], r)


def test_deadband_and_speed():
    b, clk = make()
    b.command({"head_pan": 10})
    run(b, clk, 2)
    r = b.command({"head_pan": 10.3})
    check("deadband: a change below the deadband (0.5 deg) is not sent", r["deadband"] == ["head_pan"]
          and r["cmd_id"] is None and J(b, "head_pan")["target"] == 10.0, r)
    b.command({"head_pan": 50}, speed=0.25)
    vmax = 0.0
    for _ in range(60):
        clk.t += 0.05
        b.tick()
        vmax = max(vmax, abs(J(b, "head_pan")["velocity"]))
    check("speed fraction 0.25 caps the motion at 25 % of max_speed", 20.0 < vmax <= 22.5 + 1e-9, vmax)


def test_disabled():
    b, clk = make()
    ok, errs, _ = b.set_calibration({"arm_l_elbow": {"enabled": False}})
    r = b.command({"arm_l_elbow": 60})
    run(b, clk, 2)
    check("disabled joint: command refused, joint does not move",
          ok and r["refused"].get("arm_l_elbow") == "articulation désactivée" and J(b, "arm_l_elbow")["position"] == 0.0, r)
    okk, err = b.sweep("arm_l_elbow")
    check("disabled joint: sweep refused", not okk and err)
    b.command({"arm_r_elbow": 100})
    run(b, clk, 0.3)
    b.set_calibration({"arm_r_elbow": {"enabled": False}})
    p = J(b, "arm_r_elbow")["position"]
    run(b, clk, 2)
    check("disabling a moving joint stops it where it is", J(b, "arm_r_elbow")["position"] == p and 0 < p < 100, p)
    b.set_calibration({"arm_l_elbow": {"enabled": True}})
    r = b.command({"arm_l_elbow": 60})
    run(b, clk, 3)
    check("re-enabled joint moves again", r["ok"] and J(b, "arm_l_elbow")["position"] == 60.0, J(b, "arm_l_elbow"))


def test_estop():
    b, clk = make()
    b.command({"head_pan": 80, "base_left_wheel": 0.4})
    run(b, clk, 0.4)
    b.sweep("head_tilt")
    st, rep = A.estop(b, {"reason": "test"})
    p = J(b, "head_pan")["position"]
    check("estop: answers 200 and is active", st == 200 and rep["estop"]["active"], rep)
    run(b, clk, 2)
    check("estop: every motor halted at once (head stays, wheel speed 0, no sweep)",
          J(b, "head_pan")["position"] == p and J(b, "base_left_wheel")["velocity"] == 0.0
          and not J(b, "head_tilt")["sweeping"] and not b.moving(), (p, J(b, "head_pan")))
    st, rep = A.command(b, {"targets": {"head_pan": 0}})
    check("estop LATCHES: a command after the stop is refused with 409", st == 409 and not rep["ok"]
          and rep["refused"].get("head_pan") == "arrêt d'urgence", (st, rep))
    st2, rep2 = A.command(b, {"targets": "garbage"})
    check("estop: even a malformed command answers 409 while latched", st2 == 409, (st2, rep2))
    st3, _ = A.sweep(b, {"joint": "head_tilt"})
    check("estop: sweep refused with 409", st3 == 409)
    run(b, clk, 5)
    check("estop: still latched after 5 s of heartbeat (no auto reset)", b.estop["active"])
    check("estop: journaled as an error event", any(e["kind"] == "estop" and e["level"] == "error" for e in b.events))
    A.estop_reset(b)
    st, rep = A.command(b, {"targets": {"head_pan": 0}})
    run(b, clk, 3)
    check("estop reset: commands accepted again", st == 200 and rep["ok"] and J(b, "head_pan")["position"] == 0.0, rep)
    check("estop: stop interrupted the pending command (event)", any(e["kind"] == "interrupted" for e in b.events))


def test_events_arrival():
    b, clk = make()
    r1 = b.command({"head_pan": 30})
    run(b, clk, 0.2)
    r2 = b.command({"head_pan": -30, "head_tilt": 10})
    run(b, clk, 3)
    kinds = [(e["kind"], e.get("cmd_id")) for e in b.events]
    check("events: a newer command interrupts the older one", ("interrupted", r1["cmd_id"]) in kinds, kinds)
    check("events: arrived once every joint of the command reached its target", ("arrived", r2["cmd_id"]) in kinds
          and not b.moving(), kinds)
    seen = []
    b.add_event_hook(seen.append)
    b.command({"head_pan": 0})
    run(b, clk, 2)
    check("events: hooks receive arrived (B1 trigger seam)", any(e["kind"] == "arrived" for e in seen), seen)


def test_overcurrent():
    b, clk = make()
    b.set_calibration({"head_pan": {"max_current": 0.1}})
    b.command({"head_pan": 80})
    run(b, clk, 2)
    j = J(b, "head_pan")
    check("overcurrent: the joint is held well before its target and an event is journaled",
          j["position"] < 20 and any(e["kind"] == "overcurrent" for e in b.events), j)


# ---------------------------------------------------------------- calibration
def test_validate():
    base = C.defaults_for(JT.load_layout()[0])
    check("validate: defaults are valid", C.validate(base, "x") == [])
    cases = {"min >= max": {"min": 10.0, "max": 5.0}, "zero out of range": {"min": 5.0, "max": 50.0},
             "negative speed": {"max_speed": -1.0}, "zero accel": {"max_accel": 0.0},
             "zero current": {"max_current": 0}, "direction 2": {"direction": 2}, "direction True": {"direction": True},
             "nan": {"max": float("nan")}, "string": {"min": "-10"}, "bool number": {"deadband": True},
             "enabled int": {"enabled": 1}, "deadband too big": {"deadband": 500.0}, "unknown key": {"torque": 1.0}}
    bad = [k for k, v in cases.items() if not C.validate({**base, **v}, "x")]
    check("validate: %d invalid records refused" % len(cases), not bad, bad)
    check("validate: missing field refused", C.validate({k: v for k, v in base.items() if k != "zero"}, "x"))


def test_persist():
    d = tmp()
    path = os.path.join(d, "body-calibration.json")
    b, clk = make(path)
    check("store: nothing written before the first change", not os.path.exists(path))
    ok, errs, res = b.set_calibration({"head_pan": {"min": -60.0}})
    doc1 = json.load(open(path, encoding="utf-8"))
    check("store: file written with schema / version / revision 1 / updated_at",
          ok and doc1["schema"] == C.SCHEMA and doc1["version"] == 1 and doc1["revision"] == 1 and doc1["updated_at"]
          and doc1["joints"]["head_pan"]["min"] == -60.0 and len(doc1["joints"]) == 8, (errs, doc1.get("revision")))
    b.set_calibration({"head_pan": {"max": 60.0}})
    doc2 = json.load(open(path, encoding="utf-8"))
    bak = json.load(open(path + ".bak", encoding="utf-8"))
    check("store: revision 2, previous version kept in .bak", doc2["revision"] == 2 and bak == doc1, bak.get("revision"))
    b2, _ = make(path)
    check("store: a new body reads the saved calibration back", b2.cal["head_pan"]["min"] == -60.0
          and b2.cal["head_pan"]["max"] == 60.0 and b2.store.revision == 2)
    # atomic write: a failure while writing leaves the old file intact and no temp file
    real = C.json.dump

    def boom(*a, **k):
        raise OSError("disk full (test)")
    C.json.dump = boom
    try:
        try:
            b.set_calibration({"head_pan": {"min": -50.0}})
            raised = False
        except OSError:
            raised = True
    finally:
        C.json.dump = real
    left = [f for f in os.listdir(d) if f.endswith(".tmp")]
    check("store: failed write raises, old file intact, no temp file left",
          raised and json.load(open(path, encoding="utf-8")) == doc2 and not left, (raised, left))
    ok, errs, _ = b.set_calibration({"head_pan": {"min": 10.0}})
    check("store: invalid change refused, nothing applied, file unchanged",
          not ok and errs and json.load(open(path, encoding="utf-8"))["revision"] == 2)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    b3, _ = make(path)
    check("store: corrupt file -> defaults + error reported", b3.cal["head_pan"]["min"] == -90.0
          and b3.store.info()["error"], b3.store.info())


def test_set_from_position():
    d = tmp()
    b, clk = make(os.path.join(d, "c.json"))
    b.command({"head_pan": -20})
    run(b, clk, 2)
    ok, errs, _ = b.set_from_position("head_pan", "set_min")
    check("set_min: min = current position (-20)", ok and b.cal["head_pan"]["min"] == -20.0, errs)
    b.command({"head_pan": 30})
    run(b, clk, 2)
    ok, errs, _ = b.set_from_position("head_pan", "set_max")
    check("set_max: max = current position (30)", ok and b.cal["head_pan"]["max"] == 30.0, errs)
    b.command({"head_pan": -40})
    run(b, clk, 2)
    check("set_min then a command below it: clamped at the new min", J(b, "head_pan")["position"] == -20.0)
    b.command({"head_pan": 10})
    run(b, clk, 2)
    ok, errs, _ = b.set_from_position("head_pan", "set_zero")
    j = J(b, "head_pan")
    check("set_zero: position reads 0, hardware zero = 10, physical limits kept (-30, 20)",
          ok and j["position"] == 0.0 and b.cal["head_pan"]["zero"] == 10.0 and b.cal["head_pan"]["min"] == -30.0
          and b.cal["head_pan"]["max"] == 20.0, (errs, j["position"], b.cal["head_pan"]))
    b.command({"head_pan": 20})
    run(b, clk, 2)
    raw = b.backend.read_state()["head_pan"]["position"]
    check("set_zero: logical 20 = hardware 30 (old max)", raw == 30.0, raw)
    ok, errs, _ = b.set_from_position("head_pan", "set_min")
    check("set_min at a positive position refused (zero would leave the range)", not ok and errs, errs)
    ok, errs, _ = b.set_from_position("base_left_wheel", "set_zero")
    check("set_zero on a wheel refused", not ok)
    st, rep = A.calibration_set(b, "nope", "set_min")
    st2, rep2 = A.calibration_set(b, "head_pan", "set_middle")
    check("api.calibration_set: unknown joint 404, unknown action 400", st == 404 and st2 == 400, (st, st2))
    b.set_calibration({"head_tilt": {"direction": -1}})
    b.command({"head_tilt": 20})
    run(b, clk, 2)
    check("direction -1: logical +20 drives hardware -20", b.backend.read_state()["head_tilt"]["position"] == -20.0
          and J(b, "head_tilt")["position"] == 20.0)


def test_import_export():
    d = tmp()
    b, clk = make(os.path.join(d, "c.json"))
    st, doc = A.calibration_export(b)
    check("export: schema document with every joint", st == 200 and doc["schema"] == C.SCHEMA and len(doc["joints"]) == 8)
    bad = {"none (invalid JSON)": None, "list": [1, 2], "wrong schema": {**doc, "schema": "x"},
           "wrong version": {**doc, "version": 9}, "empty joints": {**doc, "joints": {}},
           "unknown joint": {**doc, "joints": {**doc["joints"], "tail": doc["joints"]["head_pan"]}},
           "min > max": {**doc, "joints": {"head_pan": {**doc["joints"]["head_pan"], "min": 50.0, "max": 10.0}}},
           "missing field": {**doc, "joints": {"head_pan": {k: v for k, v in doc["joints"]["head_pan"].items()
                                                              if k != "max_speed"}}}}
    before = b.calibration()
    refused = [k for k, v in bad.items() if A.calibration_import(b, v)[0] == 400]
    check("import: %d invalid documents refused with 400, calibration unchanged" % len(bad),
          len(refused) == len(bad) and b.calibration() == before, set(bad) - set(refused))
    new = json.loads(json.dumps(doc))
    new["joints"]["head_pan"]["max"] = 45.0
    new["joints"] = {"head_pan": new["joints"]["head_pan"]}
    st, rep = A.calibration_import(b, new)
    check("import: a valid partial document applies + persists", st == 200 and b.cal["head_pan"]["max"] == 45.0
          and json.load(open(os.path.join(d, "c.json")))["joints"]["head_pan"]["max"] == 45.0, rep)
    r = b.command({"head_pan": 80})
    check("import: imported limits are enforced at once", r["applied"]["head_pan"] == 45.0)


def test_trace():
    b, clk = make()
    b.command({"head_pan": 40})
    run(b, clk, 3, dt=0.05)
    t = b.trace(1)
    check("trace: ~20 Hz samples, `seconds` filter", 20 <= len(t["samples"]) <= 22 and t["fields"][0] == "position",
          len(t["samples"]))
    s = t["samples"][-1]["joints"]["head_pan"]
    check("trace: sample = [position, velocity, target, current]", s[0] == 40.0 and s[2] == 40.0, s)
    full = b.trace(1000)
    check("trace: seconds capped at the buffer length", full["seconds"] == CORE.TRACE_S and len(full["samples"]) == 61,
          (full["seconds"], len(full["samples"])))
    run(b, clk, 150, dt=0.1)
    span = b._trace[-1][0] - b._trace[0][0]
    check("trace: ring buffer bounded to the last TRACE_S seconds (10 Hz heartbeat)",
          abs(span - CORE.TRACE_S) < 0.11 and len(b._trace) <= int(CORE.TRACE_S * CORE.TRACE_HZ), (span, len(b._trace)))
    st, _ = A.trace(b, "abc")
    st2, _ = A.trace(b, "-3")
    check("api.trace: bad seconds -> 400", st == 400 and st2 == 400)


def test_api_misc():
    b, clk = make()
    st, s = A.state(b)
    check("api.state: 200, 8 joints, groups, estop, backend sim", st == 200 and len(s["joints"]) == 8 and
          [g["id"] for g in s["groups"]] == ["head", "arm_l", "arm_r", "base"] and s["backend"] == "sim"
          and s["estop"]["active"] is False)
    check("api.state: JSON serialisable", bool(json.dumps(s)))
    check("api.stream_hz clamps to 1..20, default 15", (A.stream_hz("100"), A.stream_hz("0"), A.stream_hz(None),
                                                       A.stream_hz("nan")) == (20.0, 1.0, 15.0, 15.0))
    st, _ = A.command(b, None)
    st2, _ = A.command(b, {"targets": {}})
    check("api.command: invalid JSON / empty targets -> 400", st == 400 and st2 == 400, (st, st2))
    st, rep = A.calibration_put(b, {"joints": {"head_pan": {"min": 5.0}}})
    st2, rep2 = A.calibration_put(b, {"joints": {"head_pan": {"min": -45.0}}})
    st3, _ = A.calibration_put(b, "x")
    check("api.calibration_put: invalid 400 with errors, valid 200 applies", st == 400 and rep["errors"]
          and st2 == 200 and rep2["calibration"]["head_pan"]["min"] == -45.0 and st3 == 400, (rep, rep2))
    st, rep = A.sweep(b, {"joint": "base_left_wheel"})
    check("api.sweep: wheel refused 400", st == 400)
    st, rep = A.sweep(b, {"joint": "head_pan"})
    run(b, clk, 0.5)
    check("api.sweep: position joint starts a slow sweep (25 % speed)", st == 200 and J(b, "head_pan")["sweeping"]
          and abs(J(b, "head_pan")["velocity"]) <= 0.25 * 90 + 1e-9)
    A.stop(b)
    check("api.stop: soft stop cancels the sweep without latching", not J(b, "head_pan")["sweeping"]
          and not b.estop["active"])
    st, cal = A.calibration_get(b)
    check("api.calibration_get: 200 with every joint", st == 200 and len(cal["calibration"]) == 8)


def test_factory_and_brain():
    b = B.create({"body_backend": "mujoco"})
    check("factory: unavailable backend falls back to sim with the reason",
          b.backend.name == "sim" and "B3" in (b.backend_error or ""), b.backend_error)
    try:
        B.create({"body_backend": "real"}, strict=True)
        raised = None
    except NotImplementedError as e:
        raised = str(e)
    check("factory strict: real backend raises NotImplementedError with a pointer", raised and "HOWTO-body" in raised,
          raised)
    from nanterino import graph as G, graph_visual as V, sim
    from nanterino.brain import Brain
    from tests.test_graph_vars import CFG, parse
    clock = sim.SimClock()
    rec, tts = sim.Rec(), sim.FakeTTS()
    br = Brain(dict(CFG, power="on"), sim.FakeOut(rec, tts, clock), sim.FakeSTT(), sim.FakeLLM(rec), tts,
               sim.FakeCorpus(), clock=clock, mic=sim.FakeIn(rec), graph=parse(V.load_raw(G.DEFAULT_PATH)),
               threaded=False, start_state="veille")
    br.pump()
    check("brain: a test Brain owns an in-memory simulated body", br.body.backend.name == "sim" and br.body.store is None)
    state0 = br.state
    br.body.command({"head_pan": 30})
    for _ in range(30):
        clock.t += 0.1
        br._on_tick({"t": clock.t})
        br.pump()
    check("brain: the heartbeat ticks the body (head reached 30)", br.body.state()["joints"][0]["position"] == 30.0)
    check("brain: body motion changes nothing in the graph (state, no body event in the queue)",
          br.state == state0 and br.events.empty(), (state0, br.state))
    mine = B.create({})
    br2 = Brain(dict(CFG, power="on"), sim.FakeOut(rec, tts, clock), sim.FakeSTT(), sim.FakeLLM(rec), tts,
                sim.FakeCorpus(), clock=clock, mic=sim.FakeIn(rec), graph=parse(V.load_raw(G.DEFAULT_PATH)),
                threaded=False, start_state="veille", body=mine)
    check("brain: body= is used as given (server.py passes the live one)", br2.body is mine)


def test_server_routes():
    src = open(os.path.join(REPO, "nanterino", "server.py"), encoding="utf-8").read()
    ast.parse(src)
    need = ['@app.get("/api/body/state")', '@app.post("/api/body/command")', '@app.post("/api/body/estop")',
            '@app.post("/api/body/estop/reset")', '@app.get("/api/body/calibration")',
            '@app.put("/api/body/calibration")', '@app.post("/api/body/calibration/{joint}/{action}")',
            '@app.get("/api/body/calibration/export")', '@app.post("/api/body/calibration/import")',
            '@app.get("/api/body/trace")', '@app.websocket("/api/body/stream")', '@app.post("/api/body/sweep")',
            '@app.post("/api/body/stop")', '@app.get("/web/dash/{name}")', "body=body)"]
    missing = [n for n in need if n not in src]
    check("server.py declares every /api/body route and hands the body to the Brain", not missing, missing)
    dash = open(os.path.join(REPO, "web", "dash.html"), encoding="utf-8").read()
    check("dash.html loads the Mécanique module and has the e-stop button",
          '/web/dash/mechanics.js' in dash and 'id="estop"' in dash and 'id="mech"' in dash)


def main():
    for t in (test_layout, test_sim_profile, test_clamp_everywhere, test_deadband_and_speed, test_disabled, test_estop,
              test_events_arrival, test_overcurrent, test_validate, test_persist, test_set_from_position,
              test_import_export, test_trace, test_api_misc, test_factory_and_brain, test_server_routes):
        try:
            t()
        except Exception as e:  # keep going, report
            import traceback
            traceback.print_exc()
            check("%s completed" % t.__name__, False, repr(e))
    ok = sum(1 for _, r in results if r)
    print("body tests: %d/%d passed" % (ok, len(results)))
    sys.exit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    main()
