"""Tests of the Mouvement theme (lot B1, 2026-11-04): nanterino/body/motion.py and its 36 graph nodes on the sim body.

logging: robotlog via tests.test_brain_graph (imported through tests.test_nodes_n1 for the shared helpers).

Purpose
    The gesture / pose library (validation refusals), the parser enumerations and the vocabulary (theme mouvement last,
    hand-move icon, 12 / 12 / 12), then one behaviour test per concept on a non-threaded Brain of the fake world with
    its in-memory SIMULATED body: each ACTION's effect within the calibration limits, each TRIGGER posted by the real
    Body event path (a global transition counts it), each CONDITION reading the real state; the emergency stop blocks
    every motion action; out-of-range targets clamp and post motion_clamped (anti-burst); a dashboard / API command
    posts the same triggers; nothing is posted when nothing moves (trace parity); the simulator returns the simulated
    body; the vocabulary goldens change only additively (pre-B1 copies).
Boundary
    Simulated body only (body_backend sim, no calibration store): no motor, no file written, nanterino.server never
    imported (its wiring is read as text). Library refusal cases write under /tmp/test_nodes_motion.
How to run (repo root)
    .venv/bin/python -m tests.test_nodes_motion        # ~5 s; --only name1,name2
    prints PASS / FAIL lines and `nodes_motion tests: n/n passed`
"""
import copy
import json
import os
import shutil
import sys

sys.path.insert(0, "/opt/robot/lib")

from nanterino import graph as G, nodes, sim  # noqa: E402
from nanterino.body import api as body_api  # noqa: E402
from nanterino.body import motion as M  # noqa: E402
from tests.test_nodes_n1 import GOLDEN, act, adv, brain, counter, counts, guard, ints, strip_ids  # noqa: E402
from tests.test_graph_vars import CFG, mini, parse, refused  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = "/tmp/test_nodes_motion"
# The lot B1 node ids (strip them, and the `mouvement` theme row, and the vocabulary is the pre-B1 golden byte for byte).
B1 = {
    "actions": ["look_at", "look_center", "nod_head", "shake_head", "play_gesture", "set_pose", "arm_to", "base_move",
                "base_turn", "motion_stop", "emergency_stop", "set_face_tracking"],
    "triggers": ["motion_done", "motion_interrupted", "motion_stopped", "motion_refused", "motion_clamped",
                 "overcurrent_detected", "estop_pressed", "estop_released", "gesture_done", "pose_reached",
                 "base_move_done", "face_tracking_changed"],
    "conditions": ["is_moving", "at_pose", "gesture_playing", "estop_active", "body_available", "body_simulated",
                   "head_pan_between", "head_tilt_between", "joint_at_limit", "overcurrent_active", "face_tracking_on",
                   "motion_idle_since"],
}
TRIG_VARS = {t: "n_" + t[:28] for t in B1["triggers"]}


def strip_b1(v: dict) -> dict:
    """The vocabulary without the lot B1 entries and without the `mouvement` theme row (used first by
    tests.test_sound.strip_c2, hence by every older additive check)."""
    v = strip_ids(v, B1)
    v["themes"] = [t for t in v["themes"] if t["id"] != "mouvement"]
    return v


def fresh_tmp():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    return TMP


def world(extra=(), **cfg):
    """Brain whose global transitions count every B1 trigger (n_<trigger>) plus the `extra` transitions."""
    glob = [counter(t, v) for t, v in TRIG_VARS.items()] + list(extra)
    names = list(TRIG_VARS.values()) + [t["do"][0]["add_var"]["name"] for t in extra]
    return brain(mini(glob=glob, variables=ints(*names)), **cfg)


def n(b, trig):
    return b.var_value(TRIG_VARS[trig])


def pos(b, jid):
    return next(j for j in b.body.state()["joints"] if j["id"] == jid)["position"]


def ticks(b, clock, seconds, probe=None):
    """Advance in 0.1 s heartbeats; `probe(b)` is called after each one (records extremes of a gesture)."""
    for _ in range(int(round(seconds / 0.1))):
        adv(b, clock, 0.1)
        if probe:
            probe(b)


# ---------------------------------------------------------------- library, parser, vocabulary
def test_library_contents_and_refusals():
    lib = M.LIB
    assert list(lib["gestures"]) == ["salut", "oui", "non", "montrer_gauche", "montrer_droite", "hausser", "curieux"]
    assert list(lib["poses"]) == ["repos", "accueil", "bras_leves", "pensif"]
    assert lib["base"] == {"left": "base_left_wheel", "right": "base_right_wheel", "track_m": 0.3}
    d = fresh_tmp()
    src = open(M.LIBRARY, encoding="utf-8").read()
    bad = {
        "wheel": src.replace("head_tilt: -15}, speed: 0.8}\n      - {targets: {head_tilt: 10}",
                             "base_left_wheel: -15}, speed: 0.8}\n      - {targets: {head_tilt: 10}", 1),
        "joint": src.replace("arm_r_shoulder: 150", "arm_x_shoulder: 150", 1),
        "speed": src.replace("speed: 0.8}", "speed: 1.5}", 1),
        "nooui": src.replace("  oui:\n", "  ouii:\n", 1),
        "schema": src.replace("schema: nanterino.gestures", "schema: other", 1),
        "track": src.replace("track_m: 0.30", "track_m: 0", 1),
    }
    for k, text in bad.items():
        assert text != src, k
        p = os.path.join(d, k + ".yaml")
        open(p, "w", encoding="utf-8").write(text)
        try:
            M.load_library(p)
        except M.LibraryError:
            continue
        raise AssertionError("library accepted although invalid: " + k)
    assert M.speed_fraction(50) == 0.5 and M.speed_fraction(500) == 1.0 and M.speed_fraction(-3) == M.SPEED_MIN
    assert M.speed_fraction("x") == 0.5 and M.speed_fraction(float("nan")) == 0.5


def test_parser_enums_and_vocabulary():
    ok = mini(veille=[{"on": "start", "do": [{"play_gesture": {"gesture": "salut"}}, {"set_pose": {"pose": "accueil", "speed": 50}},
                                             {"arm_to": {"arm": "both", "shoulder": 10, "elbow": 5, "speed": 40}}],
                       "when": [{"is_moving": {"group": "head"}}, {"at_pose": {"pose": "repos", "tolerance": 2}}]}],
              glob=[{"on": "gesture_done", "value": "oui", "do": []}, {"on": "pose_reached", "do": []}])
    parse(ok)
    refused(mini(veille=[{"on": "start", "do": [{"play_gesture": {"gesture": "danse"}}]}]), "unknown gesture 'danse'")
    refused(mini(veille=[{"on": "start", "do": [{"set_pose": {"pose": "x", "speed": 50}}]}]), "unknown pose 'x'")
    refused(mini(veille=[{"on": "start", "do": [{"arm_to": {"arm": "left", "shoulder": 1, "elbow": 1, "speed": 1}}]}]), "unknown arm")
    refused(mini(veille=[{"on": "start", "do": [], "when": [{"is_moving": {"group": "legs"}}]}]), "unknown bodygroup 'legs'")
    refused(mini(veille=[{"on": "start", "do": [], "when": [{"at_pose": {"pose": "nope", "tolerance": 1}}]}]), "unknown pose 'nope'")
    refused(mini(glob=[{"on": "gesture_done", "value": "danse", "do": []}]), "must be one of")
    refused(mini(glob=[{"on": "pose_reached", "var": "x", "do": []}]), "takes no `var:`")
    refused(mini(veille=[{"on": "start", "do": [{"look_at": {"pan": "gauche", "tilt": 0, "speed": 50}}]}]), "expected a number")
    v = G.vocabulary(CFG)
    th = v["themes"][-1]
    assert th["id"] == "mouvement" and th["icon"] == "hand-move" and th["label"] == "Mouvement", th
    assert [t["id"] for t in v["themes"]][:-1] == ["conversation", "parole", "micro", "vision", "intentions", "variables",
                                                 "listes", "etat", "temps", "systeme", "evenements"]
    for fam, key in (("actions", "actions"), ("conditions", "guards"), ("triggers", "events")):
        got = [e["id"] for e in v[key] if e.get("theme") == "mouvement"]
        assert got == B1[fam], (fam, got)
    ac = {a["id"]: a for a in v["actions"]}
    g = ac["play_gesture"]["args"][0]
    assert g["type"] == "enum" and g["options"] == list(M.LIB["gestures"]) and g["labels"]["salut"] == "Saluer de la main"
    assert [a["name"] for a in ac["look_at"]["args"]] == ["pan", "tilt", "speed"] and ac["look_at"]["args"][0]["type"] == "number"
    assert ac["set_face_tracking"]["args"][0]["options"] == ["on", "off"]
    ev = {e["id"]: e for e in v["events"]}
    assert ev["gesture_done"]["args"][0]["options"] == list(M.LIB["gestures"]) and ev["gesture_done"]["args"][0]["optional"]
    assert ev["pose_reached"]["args"][0]["options"] == list(M.LIB["poses"])
    assert "motion_done" in ac["emit"]["args"][0]["options"] and "gesture_done" not in ac["emit"]["args"][0]["options"]
    gd = {x["id"]: x for x in v["guards"]}
    assert gd["is_moving"]["args"][0]["options"] == ["all", "head", "arm_l", "arm_r", "base"]
    assert {"gesture_done", "pose_reached"} <= set(G.WATCH_EVENTS)
    assert "hand-move" in G.all_icons() and all(nodes.ACTIONS[i].icon in G.all_icons() for i in B1["actions"])
    c = counts()
    assert [c[f]["themes"].get("mouvement") for f in ("triggers", "actions", "conditions")] == [12, 12, 12], c


# ---------------------------------------------------------------- head
def test_look_at_center_clamp_and_head_conditions():
    b, clock, _ = world()
    assert guard(b, "head_pan_between", start=-1, end=1) and guard(b, "body_simulated") and guard(b, "body_available")
    act(b, "look_at", pan=30, tilt=10, speed=100)
    assert guard(b, "is_moving", group="head") and guard(b, "is_moving", group="all") and not guard(b, "is_moving", group="base")
    ticks(b, clock, 2.0)
    assert (pos(b, "head_pan"), pos(b, "head_tilt")) == (30, 10), (pos(b, "head_pan"), pos(b, "head_tilt"))
    assert n(b, "motion_done") == 1 and not guard(b, "is_moving", group="all")
    assert guard(b, "head_pan_between", start=40, end=20) and not guard(b, "head_pan_between", start=-40, end=20)
    assert guard(b, "head_tilt_between", start=5, end=15) and not guard(b, "head_tilt_between", start=-30, end=0)
    act(b, "look_at", pan=200, tilt=-100, speed=100)          # beyond both calibration limits: clamped
    ticks(b, clock, 3.0)
    assert (pos(b, "head_pan"), pos(b, "head_tilt")) == (90, -30), (pos(b, "head_pan"), pos(b, "head_tilt"))
    assert n(b, "motion_clamped") == 2, n(b, "motion_clamped")   # one per joint
    assert guard(b, "joint_at_limit", group="head") and not guard(b, "joint_at_limit", group="arm_l")
    act(b, "look_at", pan=95, tilt=0, speed=100)              # a new clamp (the last one is 3 s old)
    act(b, "look_at", pan=96, tilt=0, speed=100)              # same joint again within CLAMP_GAP_S: anti-burst
    act(b, "look_at", pan=-120, tilt=0, speed=100)
    assert n(b, "motion_clamped") == 3, n(b, "motion_clamped")
    ticks(b, clock, 1.2)
    act(b, "look_at", pan=97, tilt=0, speed=100)
    assert n(b, "motion_clamped") == 4, n(b, "motion_clamped")
    ticks(b, clock, 3.0)
    act(b, "look_center")
    ticks(b, clock, 3.0)
    assert (pos(b, "head_pan"), pos(b, "head_tilt")) == (0, 0)
    assert not guard(b, "joint_at_limit", group="all")


# ---------------------------------------------------------------- gestures
def test_nod_shake_and_gesture_done():
    extra = [counter("gesture_done", "g_oui", value="oui"), counter("gesture_done", "g_salut", value="salut")]
    b, clock, _ = world(extra)
    seen = {"tmin": 0, "tmax": 0, "pmin": 0, "pmax": 0, "playing": 0}

    def probe(bb):
        t, p = pos(bb, "head_tilt"), pos(bb, "head_pan")
        seen.update(tmin=min(seen["tmin"], t), tmax=max(seen["tmax"], t), pmin=min(seen["pmin"], p), pmax=max(seen["pmax"], p))
        seen["playing"] += guard(bb, "gesture_playing")

    act(b, "nod_head")
    assert guard(b, "gesture_playing") and guard(b, "is_moving", group="head")
    ticks(b, clock, 5.0, probe)
    assert seen["tmin"] <= -14.9 and seen["tmax"] >= 9.9 and seen["pmin"] == seen["pmax"] == 0, seen   # the real steps
    assert pos(b, "head_tilt") == 0 and not guard(b, "gesture_playing")
    assert (n(b, "gesture_done"), b.var_value("g_oui"), b.var_value("g_salut")) == (1, 1, 0)
    assert n(b, "motion_done") == 1, n(b, "motion_done")          # one per gesture, not one per step
    seen.update(tmin=0, tmax=0, pmin=0, pmax=0)
    act(b, "shake_head")
    ticks(b, clock, 5.0, probe)
    assert seen["pmin"] <= -19.9 and seen["pmax"] >= 19.9 and pos(b, "head_pan") == 0, seen
    assert (n(b, "gesture_done"), b.var_value("g_oui")) == (2, 1)
    act(b, "play_gesture", gesture="salut")
    peak = {"s": 0}
    ticks(b, clock, 14.0, lambda bb: peak.update(s=max(peak["s"], pos(bb, "arm_r_shoulder"))))
    assert peak["s"] >= 149.9 and pos(b, "arm_r_shoulder") == 0 and b.var_value("g_salut") == 1, peak
    assert n(b, "motion_interrupted") == 0


def test_gesture_interrupted_by_newer_command_and_by_new_gesture():
    b, clock, _ = world([counter("gesture_done", "g_any")])
    act(b, "play_gesture", gesture="salut")
    ticks(b, clock, 0.5)
    act(b, "arm_to", arm="arm_r", shoulder=20, elbow=20, speed=100)   # takes the arm back from the gesture
    ticks(b, clock, 4.0)
    assert not guard(b, "gesture_playing") and n(b, "motion_interrupted") == 1 and b.var_value("g_any") == 0
    assert (pos(b, "arm_r_shoulder"), pos(b, "arm_r_elbow")) == (20, 20)
    act(b, "play_gesture", gesture="montrer_gauche")
    ticks(b, clock, 0.3)
    act(b, "nod_head")                                              # a new gesture interrupts the previous one
    ticks(b, clock, 6.0)
    assert n(b, "motion_interrupted") == 2 and b.var_value("g_any") == 1, (n(b, "motion_interrupted"), b.var_value("g_any"))


# ---------------------------------------------------------------- poses, arms
def test_pose_and_arm_to():
    b, clock, _ = world([counter("pose_reached", "p_acc", value="accueil")])
    assert guard(b, "at_pose", pose="repos", tolerance=0.1) and not guard(b, "at_pose", pose="accueil", tolerance=1)
    act(b, "set_pose", pose="accueil", speed=100)
    ticks(b, clock, 4.0)
    assert guard(b, "at_pose", pose="accueil", tolerance=0.1) and not guard(b, "at_pose", pose="repos", tolerance=5)
    assert (n(b, "pose_reached"), b.var_value("p_acc"), n(b, "motion_done")) == (1, 1, 1)
    act(b, "set_pose", pose="accueil", speed=100)                   # already there: reached at once, no motion
    assert (n(b, "pose_reached"), n(b, "motion_done")) == (2, 1)
    act(b, "arm_to", arm="both", shoulder=170, elbow=200, speed=100)   # elbow beyond 135: clamped
    ticks(b, clock, 5.0)
    for side in ("arm_l", "arm_r"):
        assert (pos(b, side + "_shoulder"), pos(b, side + "_elbow")) == (170, 135), side
    assert n(b, "motion_clamped") == 2 and guard(b, "joint_at_limit", group="arm_r")
    assert guard(b, "at_pose", pose="accueil", tolerance=200) and not guard(b, "at_pose", pose="accueil", tolerance=10)


# ---------------------------------------------------------------- base
def test_base_move_and_turn_by_odometry():
    b, clock, _ = world()
    L, R = "base_left_wheel", "base_right_wheel"
    act(b, "base_move", distance=0.5, speed=50)
    ticks(b, clock, 0.5)
    assert guard(b, "is_moving", group="base") and not guard(b, "is_moving", group="head")
    ticks(b, clock, 5.0)
    d = (pos(b, L) + pos(b, R)) / 2
    assert abs(d - 0.5) <= 0.04, d
    assert n(b, "base_move_done") == 1 and n(b, "motion_done") == 1 and not guard(b, "is_moving", group="base")
    act(b, "base_move", distance=-0.3, speed=100)
    ticks(b, clock, 5.0)
    d2 = (pos(b, L) + pos(b, R)) / 2
    assert abs(d2 - 0.2) <= 0.05, d2
    l0, r0 = pos(b, L), pos(b, R)
    act(b, "base_turn", angle=90, speed=50)
    ticks(b, clock, 5.0)
    import math
    ang = math.degrees(((pos(b, R) - r0) - (pos(b, L) - l0)) / M.LIB["base"]["track_m"])
    assert abs(ang - 90) <= 6, ang                                  # + = left: right wheel forward
    assert pos(b, R) > r0 and pos(b, L) < l0 and n(b, "base_move_done") == 3
    # the wheels never block the head and stop at 0 velocity
    js = {j["id"]: j for j in b.body.state()["joints"]}
    assert js[L]["velocity"] == 0 and js[R]["velocity"] == 0
    # a disabled wheel: the move times out (stopped, motion_interrupted)
    b.body.set_calibration({L: {"enabled": False}})
    i0 = n(b, "motion_interrupted")
    act(b, "base_move", distance=0.2, speed=50)
    ticks(b, clock, 1.0)
    assert not guard(b, "is_moving", group="base") and n(b, "base_move_done") == 3 and n(b, "motion_interrupted") >= i0


# ---------------------------------------------------------------- stops
def test_emergency_stop_blocks_every_motion_action():
    b, clock, _ = world()
    act(b, "play_gesture", gesture="salut")
    ticks(b, clock, 0.3)
    act(b, "emergency_stop")
    assert guard(b, "estop_active") and not guard(b, "body_available") and n(b, "estop_pressed") == 1
    ticks(b, clock, 0.2)
    assert not guard(b, "gesture_playing") and n(b, "motion_interrupted") >= 1
    before = {j["id"]: j["position"] for j in b.body.state()["joints"]}
    for call, args in (("look_at", {"pan": 40, "tilt": 0, "speed": 100}), ("look_center", {}), ("nod_head", {}),
                       ("shake_head", {}), ("play_gesture", {"gesture": "hausser"}), ("set_pose", {"pose": "bras_leves", "speed": 100}),
                       ("arm_to", {"arm": "both", "shoulder": 90, "elbow": 90, "speed": 100}),
                       ("base_move", {"distance": 0.5, "speed": 100}), ("base_turn", {"angle": 90, "speed": 100})):
        act(b, call, **args)
        assert not guard(b, "gesture_playing") and b.motion.base is None, call
    ticks(b, clock, 2.0)
    after = {j["id"]: j["position"] for j in b.body.state()["joints"]}
    assert after == before, (before, after)
    assert n(b, "motion_refused") == 1, n(b, "motion_refused")     # anti-burst: 9 refusals within 1 s -> one post
    ticks(b, clock, 1.0)
    act(b, "look_at", pan=10, tilt=0, speed=100)
    assert n(b, "motion_refused") == 2
    body_api.estop_reset(b.body)                                     # only a human re-arms (dashboard / API)
    b.pump()
    assert n(b, "estop_released") == 1 and not guard(b, "estop_active") and guard(b, "body_available")
    act(b, "look_at", pan=10, tilt=0, speed=100)
    ticks(b, clock, 2.0)
    assert pos(b, "head_pan") == 10


def test_motion_stop_and_idle_since():
    b, clock, _ = world()
    ticks(b, clock, 1.0)
    assert guard(b, "motion_idle_since", seconds=0.5) and not guard(b, "motion_idle_since", seconds=5)
    act(b, "play_gesture", gesture="hausser")
    act(b, "base_move", distance=1.0, speed=50)
    ticks(b, clock, 0.3)
    assert not guard(b, "motion_idle_since", seconds=0)
    act(b, "motion_stop")
    ticks(b, clock, 0.1)
    assert n(b, "motion_stopped") == 1 and not guard(b, "gesture_playing") and b.motion.base is None
    assert n(b, "motion_interrupted") >= 2 and not guard(b, "estop_active")
    ticks(b, clock, 1.0)
    assert not guard(b, "is_moving", group="all")
    act(b, "look_at", pan=-20, tilt=0, speed=100)                   # no latch: the next command runs
    ticks(b, clock, 2.0)
    assert pos(b, "head_pan") == -20
    ticks(b, clock, 3.0)
    assert guard(b, "motion_idle_since", seconds=2.5)


def test_overcurrent_detected_and_condition():
    b, clock, _ = world()
    ok, errs, _ = b.body.set_calibration({"head_pan": {"max_current": 0.12}})
    assert ok, errs
    oc = []
    act(b, "look_at", pan=80, tilt=0, speed=100)
    for _ in range(30):
        adv(b, clock, 0.1)
        oc.append(guard(b, "overcurrent_active"))
    assert n(b, "overcurrent_detected") >= 1 and pos(b, "head_pan") < 80, (n(b, "overcurrent_detected"), pos(b, "head_pan"))
    assert n(b, "overcurrent_detected") <= 2                          # anti-burst per joint (OVERCURRENT_GAP_S)
    assert n(b, "motion_interrupted") >= 1                            # the latch interrupted the look_at
    assert any(oc) and not oc[-1], oc                                 # true while over the limit, false once held


# ---------------------------------------------------------------- face tracking
def test_face_tracking_no_op_and_with_vision():
    b, clock, _ = world()
    act(b, "set_face_tracking", state="on")
    assert guard(b, "face_tracking_on") and n(b, "face_tracking_changed") == 1
    ticks(b, clock, 1.0)
    assert pos(b, "head_pan") == 0                                  # no vision on this brain: logged no-op
    act(b, "set_face_tracking", state="on")
    assert n(b, "face_tracking_changed") == 1                       # unchanged: nothing posted
    face = {"present": True, "x": 0.5, "y": -0.4}                   # right of the image and high
    b.motion.face_source = lambda: dict(face)
    ticks(b, clock, 1.0)
    assert pos(b, "head_pan") < -5 and pos(b, "head_tilt") > 3, (pos(b, "head_pan"), pos(b, "head_tilt"))
    assert n(b, "motion_done") == 0                                 # owned corrections are not reported one by one
    face.update(x=0.0, y=0.0)
    ticks(b, clock, 1.0)
    p = pos(b, "head_pan")
    ticks(b, clock, 1.0)
    assert pos(b, "head_pan") == p                                  # centred: no more correction
    act(b, "play_gesture", gesture="oui")
    face.update(x=0.9)
    ticks(b, clock, 0.4)
    assert pos(b, "head_pan") == p                                  # tracking pauses during a gesture
    ticks(b, clock, 5.0)
    act(b, "set_face_tracking", state="off")
    assert not guard(b, "face_tracking_on") and n(b, "face_tracking_changed") == 2
    q = pos(b, "head_pan")
    ticks(b, clock, 1.0)
    assert pos(b, "head_pan") == q


# ---------------------------------------------------------------- real paths, parity, simulator, goldens
def test_dashboard_commands_post_the_same_triggers():
    b, clock, _ = world()
    st, res = body_api.command(b.body, {"targets": {"head_tilt": 20}, "speed": 1})
    assert st == 200 and res["ok"], res
    ticks(b, clock, 2.0)
    assert n(b, "motion_done") == 1
    body_api.estop(b.body, {"reason": "test"})
    b.pump()
    assert n(b, "estop_pressed") == 1 and guard(b, "estop_active")
    body_api.estop_reset(b.body)
    b.body.stop(source="api")
    b.pump()
    assert n(b, "estop_released") == 1 and n(b, "motion_stopped") == 1


def test_nothing_posted_when_nothing_moves():
    b, clock, _ = world()
    posted = []
    orig = b.post
    b.post = lambda kind, **kw: (posted.append(kind), orig(kind, **kw))
    ticks(b, clock, 5.0)
    assert not [p for p in posted if p in B1["triggers"]], posted
    assert all(n(b, t) == 0 for t in B1["triggers"])


def test_simulator_returns_the_simulated_body():
    raw = mini(glob=[{"on": "visage", "do": [{"look_at": {"pan": 30, "tilt": 10, "speed": 100}}, "nod_head"],
                      "description": "regarde et hoche"}])
    r = sim.simulate(copy.deepcopy(raw), dict(CFG), "veille", [{"event": "visage"}, {"wait_s": 0.5}])
    assert r["body"]["gesture"] == "oui" and r["body"]["moving"] and r["body"]["backend"] == "sim", r["body"]
    r = sim.simulate(copy.deepcopy(raw), dict(CFG), "veille", [{"event": "visage"}, {"wait_s": 6}])
    assert r["body"]["joints"]["head_pan"] == 30 and r["body"]["joints"]["head_tilt"] == 0 and not r["body"]["moving"], r["body"]
    assert set(r["final"]) == {"state", "turns", "expression", "gaze_mode", "vars"}   # `final` unchanged (additive key)


def test_goldens_b1_only_gained_entries():
    from tests.test_nodes_registry import golden_diff, vocab_dumps
    dumps = vocab_dumps(G)
    assert not golden_diff(dumps), "the B1 goldens differ: %s" % golden_diff(dumps)
    for name, text in dumps.items():
        with open(os.path.join(GOLDEN, name.replace(".json", ".pre-b1.json")), "rb") as f:
            old = f.read()
        stripped = json.dumps(strip_b1(json.loads(text)), ensure_ascii=False, indent=1) + "\n"
        assert stripped.encode("utf-8") == old, name


def test_shipped_graph_uses_no_motion_node_and_server_wiring():
    import re
    text = open(G.DEFAULT_PATH, encoding="utf-8").read()
    mine = set(B1["actions"]) | set(B1["triggers"]) | set(B1["conditions"])
    assert not [i for i in mine if re.search(r"\b%s\b" % i, text)], [i for i in mine if re.search(r"\b%s\b" % i, text)]
    src = open(os.path.join(ROOT, "nanterino", "server.py"), encoding="utf-8").read()
    assert "brain.motion.face_source = lambda: vision.state" in src
    import ast
    ast.parse(src)
    bsrc = open(os.path.join(ROOT, "nanterino", "brain.py"), encoding="utf-8").read()
    assert "self.motion.tick(now)" in bsrc and bsrc.index("self.body.tick(now)") < bsrc.index("self.motion.tick(now)")


TESTS = [test_library_contents_and_refusals, test_parser_enums_and_vocabulary, test_look_at_center_clamp_and_head_conditions,
         test_nod_shake_and_gesture_done, test_gesture_interrupted_by_newer_command_and_by_new_gesture, test_pose_and_arm_to,
         test_base_move_and_turn_by_odometry, test_emergency_stop_blocks_every_motion_action, test_motion_stop_and_idle_since,
         test_overcurrent_detected_and_condition, test_face_tracking_no_op_and_with_vision,
         test_dashboard_commands_post_the_same_triggers, test_nothing_posted_when_nothing_moves,
         test_simulator_returns_the_simulated_body, test_goldens_b1_only_gained_entries,
         test_shipped_graph_uses_no_motion_node_and_server_wiring]


def main(argv):
    only = argv[argv.index("--only") + 1].split(",") if "--only" in argv else None
    failed = 0
    for fn in TESTS:
        if only and fn.__name__ not in only:
            continue
        try:
            fn()
            print("PASS", fn.__name__, flush=True)
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print("FAIL", fn.__name__, "%s: %s" % (type(e).__name__, e), flush=True)
    shutil.rmtree(TMP, ignore_errors=True)
    ran = len([f for f in TESTS if not only or f.__name__ in only])
    print("nodes_motion tests: %d/%d passed" % (ran - failed, ran))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
