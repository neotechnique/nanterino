"""Motion layer of the graph (lot B1, 2026-11-04): gesture / pose library and the runtime behind the Mouvement nodes.

logging: robotlog via nanterino.log (no-op face tracking, base timeouts and refused sequences are INFO / WARNING records).

Purpose
    `LIB` is the validated gesture / pose library of nanterino/body/gestures.yaml (graph.py builds the `gesture` /
    `pose` argument enumerations from it). `MotionRuntime` (brain.motion, one per Brain) is what the Mouvement nodes
    call: head look / center, named gestures played step by step, poses, arm targets, base moves by odometry (distance)
    and turns (angle) on the differential base, soft stop, emergency stop, face tracking; it turns Body events into
    graph events and answers the Mouvement conditions from the REAL body state.
Boundary
    Talks to the robot only through brain.body (nanterino/body/core.py Body: every target is clamped there, the
    emergency stop latches there) and posts graph events with brain.post (never dispatches, never blocks). Knows
    nothing about HTTP. The live vision state reaches it only through `face_source` (server.py sets
    `lambda: vision.state`; tests inject a fake; the simulator and test Brains have none = face tracking is a logged
    no-op). Brain calls `tick(now)` from its heartbeat AFTER body.tick, in its own try block.
Invariants
    - the Body event hook (`_hook`) runs under the body lock: it only records notes and calls brain.post;
    - commands the runtime issues itself (gesture steps, base wheel commands, face-tracking corrections) are OWNED:
      their arrived / interrupted body events never become motion_done / motion_interrupted directly; the runtime
      posts one high-level event per gesture / base move instead (gesture_done + motion_done, base_move_done +
      motion_done, or one motion_interrupted when a newer command, a stop, an emergency stop or a timeout cut it);
    - anti-burst: motion_clamped at most once per joint per CLAMP_GAP_S, overcurrent_detected once per joint per
      OVERCURRENT_GAP_S, motion_refused once per REFUSED_GAP_S (a slider dragged at a limit, a stalled motor or a
      graph looping on a latched stop cannot flood the queue);
    - gesture_done / pose_reached carry `value` = the name and are posted only when an enabled transition listens to
      them (brain._watch, like sound_from_direction); face_tracking_changed goes through brain._changed (anti-loop);
    - nothing is posted when nothing moves: trace parity of the shipped graph is unchanged (it uses no Mouvement node).
How to test
    .venv/bin/python -m tests.test_nodes_motion   (sim body; part of tests/run_graph_tests.sh)
"""
import math
import os

import yaml

from ..log import log
from .joints import DEFAULT_LAYOUT, load_layout

LIBRARY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gestures.yaml")
SCHEMA = "nanterino.gestures"
# Argument enumerations of the Mouvement nodes (graph.MOTION_ENUMS adds the gesture / pose names of the library).
GROUP_LABELS = {"all": "Tout le corps", "head": "Tête", "arm_l": "Bras gauche", "arm_r": "Bras droit", "base": "Base"}
ARM_LABELS = {"arm_r": "Bras droit", "arm_l": "Bras gauche", "both": "Les deux bras"}
CLAMP_GAP_S, OVERCURRENT_GAP_S, REFUSED_GAP_S = 1.0, 2.0, 1.0   # anti-burst of the warning-like triggers
TRACK_PERIOD_S = 0.2       # face tracking: at most 5 head corrections per second
TRACK_DEAD = 0.08          # face centre within +-8 % of the image half-width / height: no correction
TRACK_GAIN = 0.6           # fraction of the angular error corrected per step (no overshoot on a 10 Hz loop)
CAM_HFOV_DEG, CAM_VFOV_DEG = 69.0, 42.0   # RealSense D435i colour stream (vision.py frame, x right, y down)
BASE_TIMEOUT_K, BASE_TIMEOUT_EXTRA_S = 2.0, 3.0   # a base move longer than K x expected + extra is stopped
LIMIT_TOL = 0.5            # joint_at_limit: within this many units (or the deadband) of min / max
SPEED_MIN = 0.05           # node speeds are percentages, kept in [5, 100]


class LibraryError(ValueError):
    """gestures.yaml is invalid (raised at import: the robot does not start with a broken library)."""


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def load_library(path: str = LIBRARY, layout_path: str = DEFAULT_LAYOUT) -> dict:
    """Validated {"gestures": {id: {label, steps}}, "poses": {id: {label, targets}}, "base": {...}} (order kept).
    Every target joint must be a POSITION joint of body.yaml; the base wheels must be velocity joints."""
    joints = {j.id: j for j in load_layout(layout_path)}
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    where = os.path.basename(path)
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA or raw.get("version") != 1:
        raise LibraryError("%s : schema %s version 1 attendu." % (where, SCHEMA))

    def targets(what, t):
        if not isinstance(t, dict) or not t:
            raise LibraryError("%s : %s.targets doit être un objet {articulation: valeur} non vide." % (where, what))
        for jid, v in t.items():
            if jid not in joints or joints[jid].mode != "position":
                raise LibraryError("%s : %s : %r n'est pas une articulation en position de body.yaml." % (where, what, jid))
            if not _num(v):
                raise LibraryError("%s : %s.%s doit être un nombre." % (where, what, jid))
        return {k: float(v) for k, v in t.items()}

    def ident(k):
        return isinstance(k, str) and k.replace("_", "").isalnum() and k[:1].isalpha() and k == k.lower()

    out = {"gestures": {}, "poses": {}, "base": {}}
    for gid, g in (raw.get("gestures") or {}).items():
        if not ident(gid) or not isinstance(g, dict) or not isinstance(g.get("label"), str) or not g.get("steps"):
            raise LibraryError("%s : geste %r : id en minuscules, label et steps attendus." % (where, gid))
        steps = []
        for i, st in enumerate(g["steps"]):
            what = "gestures.%s.steps[%d]" % (gid, i)
            if not isinstance(st, dict) or set(st) - {"targets", "speed", "hold_s"}:
                raise LibraryError("%s : %s : clés targets, speed, hold_s seulement." % (where, what))
            sp, hold = st.get("speed", 1.0), st.get("hold_s", 0.0)
            if not (_num(sp) and 0 < sp <= 1) or not (_num(hold) and 0 <= hold <= 10):
                raise LibraryError("%s : %s : speed dans ]0, 1], hold_s dans [0, 10]." % (where, what))
            steps.append({"targets": targets(what, st.get("targets")), "speed": float(sp), "hold_s": float(hold)})
        out["gestures"][gid] = {"label": g["label"], "steps": steps}
    for pid, p in (raw.get("poses") or {}).items():
        if not ident(pid) or not isinstance(p, dict) or not isinstance(p.get("label"), str):
            raise LibraryError("%s : pose %r : id en minuscules et label attendus." % (where, pid))
        out["poses"][pid] = {"label": p["label"], "targets": targets("poses.%s" % pid, p.get("targets"))}
    b = raw.get("base") or {}
    for side in ("left", "right"):
        if b.get(side) not in joints or joints[b[side]].mode != "velocity":
            raise LibraryError("%s : base.%s doit être une roue (articulation en vitesse) de body.yaml." % (where, side))
    if not (_num(b.get("track_m")) and 0.05 <= b["track_m"] <= 2):
        raise LibraryError("%s : base.track_m (écart des roues) doit être entre 0.05 et 2 m." % where)
    out["base"] = {"left": b["left"], "right": b["right"], "track_m": float(b["track_m"])}
    for need in ("oui", "non"):
        if need not in out["gestures"]:
            raise LibraryError("%s : le geste %r est obligatoire (« Hocher / Secouer la tête »)." % (where, need))
    if not out["poses"]:
        raise LibraryError("%s : au moins une pose attendue." % where)
    return out


LIB = load_library()


def speed_fraction(pct) -> float:
    """Node speed in percent (5..100) -> Body speed fraction; out-of-range values are kept in range."""
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return 0.5
    if not math.isfinite(p):
        return 0.5
    return min(1.0, max(SPEED_MIN, p / 100.0))


class MotionRuntime:
    """brain.motion: the Mouvement nodes' door to brain.body (see the module invariants)."""

    def __init__(self, brain, library=None):
        self.brain = brain
        self.lib = library or LIB
        self.face_source = None          # server.py: lambda: vision.state ({"present", "x", "y", ...}); None = no vision
        self.tracking = False
        self.seq = None                  # gesture in progress {"name", "steps", "i", "cmd", "joints", "hold_until"}
        self.base = None                 # base move in progress {"kind", "goal", "v", "start", "deadline", ...}
        self._owned = set()              # cmd ids issued by this runtime (never reported one by one)
        self._pose_cmds = {}             # cmd id -> pose name (pose_reached on arrival)
        self._clamped = {}               # joint -> applied limit of its last CLAMPED target (joint_at_limit)
        self._notes = []                 # (cmd id, reason) interrupts of owned commands, read by tick()
        self._issuing = False            # True while the runtime replaces its OWN command (no self-interrupt note)
        self._last_post = {}             # anti-burst key -> brain.now() of the last post
        self._idle_since = brain.now()
        self._track_at = -1e9
        self._body = None
        self.attach(brain.body)

    # ------------------------------------------------------------------ body events -> graph events
    def attach(self, body) -> None:
        """Subscribe to `body` events (called again by tick() if brain.body was replaced)."""
        self._body = body
        body.add_event_hook(self._hook)

    def _burst_ok(self, key, gap) -> bool:
        now = self.brain.now()
        if now - self._last_post.get(key, -1e9) < gap:
            return False
        self._last_post[key] = now
        return True

    def _post_watched(self, event, value, **kw) -> None:
        """gesture_done / pose_reached: posted only when a transition listens (any value, or this value)."""
        sub = self.brain._watch.get(event)
        if sub and ("*" in sub or value in sub):
            self.brain.post(event, value=value, **kw)

    def _hook(self, ev) -> None:
        """Body event hook. RUNS UNDER THE BODY LOCK: record and post only."""
        if self._body is not self.brain.body:   # an old body replaced by tick(): its events are ignored
            return
        k, cid, b = ev.get("kind"), ev.get("cmd_id"), self.brain
        if k in ("arrived", "interrupted") and cid in self._owned:
            self._owned.discard(cid)
            if k == "interrupted" and not self._issuing:
                self._notes.append((cid, ev.get("reason") or "interrompu"))
            return
        if k == "arrived":
            pose = self._pose_cmds.pop(cid, None)
            b.post("motion_done", cmd_id=cid, what="pose" if pose else "commande")
            if pose:
                self._post_watched("pose_reached", pose, cmd_id=cid)
        elif k == "interrupted":
            self._pose_cmds.pop(cid, None)
            b.post("motion_interrupted", cmd_id=cid, reason=ev.get("reason") or "interrompu")
        elif k == "clamp":
            self._clamped[ev.get("joint")] = ev.get("applied")   # joint_at_limit: last target was clamped
            if self._burst_ok(("clamp", ev.get("joint")), CLAMP_GAP_S):
                b.post("motion_clamped", joint=ev.get("joint"), requested=ev.get("requested"),
                       applied=ev.get("applied"), source=ev.get("source"))
        elif k == "refused":
            if self._burst_ok(("refused",), REFUSED_GAP_S):
                b.post("motion_refused", reason=ev.get("message"), source=ev.get("source"))
        elif k == "overcurrent":
            if self._burst_ok(("overcurrent", ev.get("joint")), OVERCURRENT_GAP_S):
                b.post("overcurrent_detected", joint=ev.get("joint"), message=ev.get("message"))
        elif k == "estop":
            b.post("estop_pressed", source=ev.get("source"), message=ev.get("message"))
        elif k == "estop_reset":
            b.post("estop_released", source=ev.get("source"))
        elif k == "stop":
            b.post("motion_stopped", source=ev.get("source"))

    def _command(self, targets, speed, source, owned=False) -> dict:
        body = self.brain.body
        self._issuing = owned
        try:
            r = body.command(targets, speed, source)
        finally:
            self._issuing = False
        if owned and r.get("cmd_id") is not None:
            self._owned.add(r["cmd_id"])
        return r

    # ------------------------------------------------------------------ actions
    def look(self, pan, tilt, speed_pct, source="graph") -> dict:
        """Head to (pan, tilt) degrees (pan 0 = front, + = left); limits applied by the Body (clamp event)."""
        return self.brain.body.look(pan=pan, tilt=tilt, speed=speed_fraction(speed_pct), source=source)

    def arm_to(self, arm, shoulder, elbow, speed_pct) -> dict:
        sides = ("arm_l", "arm_r") if arm == "both" else (arm,)
        t = {}
        for s in sides:
            for part, v in (("shoulder", shoulder), ("elbow", elbow)):
                if "%s_%s" % (s, part) in self.brain.body.joints:
                    t["%s_%s" % (s, part)] = v
        if not t:
            log.info("arm_to: no joint for arm %r in body.yaml, nothing moved", arm)
            return {"ok": False}
        return self._command(t, speed_fraction(speed_pct), "graph")

    def set_pose(self, pose, speed_pct) -> dict:
        p = self.lib["poses"].get(pose)
        if p is None:
            log.warning("set_pose: unknown pose %r", pose)
            return {"ok": False}
        t = {k: v for k, v in p["targets"].items() if k in self.brain.body.joints}
        r = self._command(t, speed_fraction(speed_pct), "graph")
        if r.get("cmd_id") is not None:
            self._pose_cmds[r["cmd_id"]] = pose
        elif r.get("ok"):                 # already there (deadband): the pose is reached now
            self._post_watched("pose_reached", pose, cmd_id=None)
        return r

    def play(self, name) -> bool:
        """Start gesture `name` (a gesture in progress is interrupted first). False when it cannot start."""
        g = self.lib["gestures"].get(name)
        if g is None:
            log.warning("play_gesture: unknown gesture %r", name)
            return False
        if self.seq is not None:
            self._end_seq(interrupted="nouveau geste")
        self.seq = {"name": name, "steps": g["steps"], "i": 0, "cmd": None, "joints": (), "hold_until": None}
        return self._step()

    def _step(self) -> bool:
        s = self.seq
        st = s["steps"][s["i"]]
        t = {k: v for k, v in st["targets"].items() if k in self.brain.body.joints}
        r = self._command(t, st["speed"], "gesture", owned=True)
        if not r.get("ok") and not r.get("applied"):
            log.info("gesture %s stopped at step %d: %s", s["name"], s["i"], r.get("error") or r.get("refused"))
            self.seq = None               # motion_refused already posted by the hook (estop, disabled joints)
            return False
        s["cmd"], s["joints"], s["hold_until"] = r.get("cmd_id"), tuple(t), None
        return True

    def _end_seq(self, interrupted=None) -> None:
        s, self.seq = self.seq, None
        if s is None:
            return
        if interrupted:
            self.brain.post("motion_interrupted", cmd_id=s["cmd"], reason=interrupted, gesture=s["name"])
        else:
            self._post_watched("gesture_done", s["name"])
            self.brain.post("motion_done", cmd_id=None, what="geste", gesture=s["name"])

    def base_move(self, distance_m, speed_pct) -> bool:
        return self._base_start("move", distance_m, speed_pct)

    def base_turn(self, angle_deg, speed_pct) -> bool:
        return self._base_start("turn", angle_deg, speed_pct)

    def _wheels(self):
        st = {j["id"]: j for j in self.brain.body.state()["joints"]}
        L, R = self.lib["base"]["left"], self.lib["base"]["right"]
        return st[L], st[R]

    def _base_start(self, kind, amount, speed_pct) -> bool:
        body, lb = self.brain.body, self.lib["base"]
        if self.base is not None:
            self._end_base(interrupted="nouveau déplacement")
        if not _num(amount) or amount == 0:
            return False
        jl, jr = self._wheels()
        vmax = min(body.cal[lb["left"]]["max_speed"], body.cal[lb["right"]]["max_speed"],
                   body.cal[lb["left"]]["max"], body.cal[lb["right"]]["max"])
        v = vmax * speed_fraction(speed_pct)
        sign = 1.0 if amount > 0 else -1.0
        if kind == "move":
            t, goal = {lb["left"]: sign * v, lb["right"]: sign * v}, abs(float(amount))
            expected = goal / v
        else:                              # + = left (counter-clockwise): right wheel forward
            t, goal = {lb["left"]: -sign * v, lb["right"]: sign * v}, math.radians(abs(float(amount)))
            expected = goal * lb["track_m"] / (2 * v)
        r = self._command(t, None, "graph", owned=True)
        if not r.get("ok"):
            log.info("base %s refused: %s", kind, r.get("error") or r.get("refused"))
            return False
        now = self.brain.now()
        self.base = {"kind": kind, "goal": goal, "sign": sign, "v": v, "l0": jl["position"], "r0": jr["position"],
                     "deadline": now + BASE_TIMEOUT_K * expected + BASE_TIMEOUT_EXTRA_S, "stopping": False,
                     "cmds": {r["cmd_id"]}, "amount": float(amount)}
        return True

    def _base_done_so_far(self, jl, jr) -> float:
        b = self.base
        dl, dr = jl["position"] - b["l0"], jr["position"] - b["r0"]
        if b["kind"] == "move":
            return b["sign"] * (dl + dr) / 2.0
        return b["sign"] * (dr - dl) / self.lib["base"]["track_m"]

    def _base_stop(self) -> None:
        lb = self.lib["base"]
        r = self._command({lb["left"]: 0.0, lb["right"]: 0.0}, None, "graph", owned=True)
        if r.get("cmd_id") is not None:
            self.base["cmds"].add(r["cmd_id"])
        self.base["stopping"] = True

    def _end_base(self, interrupted=None) -> None:
        """End the base move: completed (base_move_done + motion_done, `done` = signed distance m / angle deg really
        travelled) or interrupted (wheels commanded to 0 unless already stopping / latched, one motion_interrupted)."""
        b = self.base
        if b is None:
            return
        if interrupted:
            self.base = None
            lb = self.lib["base"]
            if not b["stopping"] and not self.brain.body.estop["active"]:
                self._command({lb["left"]: 0.0, lb["right"]: 0.0}, None, "graph", owned=True)
            self.brain.post("motion_interrupted", cmd_id=None, reason=interrupted, base=b["kind"])
            return
        jl, jr = self._wheels()
        done = self._base_done_so_far(jl, jr)
        self.base = None
        done = round(done if b["kind"] == "move" else math.degrees(done), 3)
        self.brain.post("base_move_done", move=b["kind"], requested=b["amount"], done=b["sign"] * done)
        self.brain.post("motion_done", cmd_id=None, what="base")

    def stop(self) -> None:
        """Soft stop of everything (no latch): gestures / base moves end as interrupted, joints hold."""
        if self.seq is not None:
            self._end_seq(interrupted="stop")
        if self.base is not None:
            self.base["stopping"] = True   # body.stop() below halts the wheels itself
            self._end_base(interrupted="stop")
        self.brain.body.stop(source="graph")

    def emergency_stop(self) -> dict:
        """Latched emergency stop from the graph; only « Réarmer » (dashboard / API) releases it."""
        return self.brain.body.stop_all(reason="graphe", source="graph")

    def set_tracking(self, on: bool) -> None:
        on = bool(on)
        if on and self.face_source is None:
            log.info("face tracking on: no vision on this brain (simulator / tests): the head will not follow (no-op)")
        if on != self.tracking:
            self.tracking = on
            self.brain._changed("face_tracking_changed", value=on)

    # ------------------------------------------------------------------ heartbeat
    def tick(self, now) -> None:
        body = self.brain.body
        if body is not self._body:
            self.attach(body)
        notes, self._notes = self._notes, []
        for cid, reason in notes:
            if self.seq is not None and cid == self.seq["cmd"]:
                self._end_seq(interrupted=reason)
            elif self.base is not None and cid in self.base["cmds"]:
                self.base["stopping"] = True
                self._end_base(interrupted=reason)
        if self.seq is not None:
            self._tick_seq(now)
        if self.base is not None:
            self._tick_base(now)
        if self.tracking and self.face_source is not None and self.seq is None:
            self._tick_track(now)
        if body.moving() or self.seq is not None or self.base is not None:
            self._idle_since = None
        elif self._idle_since is None:
            self._idle_since = now

    def _tick_seq(self, now) -> None:
        s, body = self.seq, self.brain.body
        if body.estop["active"]:
            self._end_seq(interrupted="arrêt d'urgence")
            return
        if any(body.moving(j) for j in s["joints"]):
            return
        if s["hold_until"] is None:
            s["hold_until"] = now + s["steps"][s["i"]]["hold_s"]
        if now < s["hold_until"] - 1e-9:
            return
        s["i"] += 1
        if s["i"] >= len(s["steps"]):
            self._end_seq()
        else:
            self._step()

    def _tick_base(self, now) -> None:
        b, body, lb = self.base, self.brain.body, self.lib["base"]
        if body.estop["active"]:
            b["stopping"] = True
            self._end_base(interrupted="arrêt d'urgence")
            return
        jl, jr = self._wheels()
        if b["stopping"]:
            if abs(jl["velocity"]) < 1e-3 and abs(jr["velocity"]) < 1e-3:
                self._end_base()
            return
        if now > b["deadline"]:
            log.warning("base %s stopped: timeout (%.2f of %.2f done)", b["kind"], self._base_done_so_far(jl, jr), b["goal"])
            self._base_stop()
            self._end_base(interrupted="délai dépassé")
            return
        done = self._base_done_so_far(jl, jr)
        vel = (abs(jl["velocity"]) + abs(jr["velocity"])) / 2.0
        acc = min(body.cal[lb["left"]]["max_accel"], body.cal[lb["right"]]["max_accel"])
        brake = vel * vel / (2 * acc) + vel * 0.05          # braking distance + half a 10 Hz tick
        if b["kind"] == "turn":
            brake = 2 * brake / lb["track_m"]               # wheel distance -> body angle (rad)
        if done >= b["goal"] - brake:
            self._base_stop()

    def _tick_track(self, now) -> None:
        if now - self._track_at < TRACK_PERIOD_S or self.brain.body.estop["active"]:
            return
        self._track_at = now
        try:
            st = self.face_source() or {}
        except Exception:   # noqa: BLE001 - vision must never break the heartbeat
            return
        if not st.get("present"):
            return
        x, y = float(st.get("x") or 0.0), float(st.get("y") or 0.0)
        if abs(x) < TRACK_DEAD and abs(y) < TRACK_DEAD:
            return
        js = {j["id"]: j for j in self.brain.body.state()["joints"]}
        t = {}
        if "head_pan" in js and abs(x) >= TRACK_DEAD:      # face on the right (x > 0) -> turn right (pan decreases)
            t["head_pan"] = js["head_pan"]["position"] - x * CAM_HFOV_DEG / 2 * TRACK_GAIN
        if "head_tilt" in js and abs(y) >= TRACK_DEAD:     # face low (y > 0) -> look down (tilt decreases)
            t["head_tilt"] = js["head_tilt"]["position"] - y * CAM_VFOV_DEG / 2 * TRACK_GAIN
        if t:
            self._command(t, 0.6, "face", owned=True)

    # ------------------------------------------------------------------ conditions (read real state)
    def moving(self, group="all") -> bool:
        body = self.brain.body
        if group == "all":
            return body.moving() or self.seq is not None or self.base is not None
        js = body.joints_of(group)
        if any(body.moving(j) for j in js):
            return True
        if self.seq is not None and set(js) & set(self.seq["joints"]):
            return True
        return group == "base" and self.base is not None

    def positions(self) -> dict:
        return {j["id"]: j for j in self.brain.body.state()["joints"]}

    def at_pose(self, pose, tolerance) -> bool:
        p = self.lib["poses"].get(pose)
        if p is None:
            return False
        tol = max(0.0, float(tolerance)) if _num(tolerance) else 0.0
        js, body = self.positions(), self.brain.body
        return all(abs(js[k]["position"] - body.clamp(k, v)[0]) <= tol + 1e-6 for k, v in p["targets"].items() if k in js)

    def at_limit(self, group="all") -> bool:
        """« En butée »: a position joint of `group` whose LAST target was clamped to a calibration limit (clamp event)
        and that has reached it. A joint resting on a limit it was simply sent to (an elbow at 0 = its min) does not
        count; a later unclamped target forgets the record."""
        body, js = self.brain.body, self.positions()
        for jid, applied in list(self._clamped.items()):
            j = js.get(jid)
            if j is None or j["mode"] != "position" or applied is None or abs(j["target"] - applied) > 1e-6:
                self._clamped.pop(jid, None)          # stale: a newer target replaced the clamped one
                continue
            if group != "all" and j["group"] != group:
                continue
            if abs(j["position"] - applied) <= max(LIMIT_TOL, body.cal[jid]["deadband"]):
                return True
        return False

    def overcurrent(self) -> bool:
        return any(j["overcurrent"] for j in self.positions().values())

    def available(self) -> bool:
        body = self.brain.body
        return (not body.estop["active"] and body.backend_error is None
                and any(rec["enabled"] for rec in body.cal.values()))

    def idle_for(self, seconds) -> bool:
        if self._idle_since is None or self.moving():
            return False
        return self.brain.now() - self._idle_since >= float(seconds)

    def snapshot(self) -> dict:
        """Simulator / API view: positions (logical units), estop, gesture and base in progress, tracking."""
        js = self.positions()
        return {"joints": {k: j["position"] for k, j in js.items()}, "estop": bool(self.brain.body.estop["active"]),
                "moving": self.moving(), "gesture": self.seq["name"] if self.seq else None,
                "base": self.base["kind"] if self.base else None, "face_tracking": self.tracking,
                "backend": self.brain.body.backend.name}
