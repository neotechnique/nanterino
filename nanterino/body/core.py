"""The robot body (lot C3): hardware-agnostic joints, calibration, limits, emergency stop, trace.

logging: robotlog via nanterino.log (estop, clamps, overcurrent and refused calibrations are WARNING records; on the
live robot nanterino/journal.py turns them into robot journal entries).

Purpose
    `Body` is the single door to the motors for every command source: the HTTP API (server.py through body/api.py),
    the graph (future Mouvement nodes, lot B1), the 360-degree sound turn-to (C2). It converts logical values
    (calibrated joint units) to hardware values, enforces the calibration limits, latches the emergency stop, tracks
    command completion (arrived / interrupted events), runs the slow test sweep, and keeps a ring buffer of recent
    states for the later MuJoCo comparison.
Boundary
    Talks to one backends.Backend (hardware units) and an optional calibration.CalibrationStore (None = in-memory, used
    by the simulator, the tests and every test Brain). Knows nothing about HTTP, the graph or the Brain: the Brain only
    calls tick(now) from its heartbeat and may subscribe with add_event_hook().
Invariants
    - LIMITS IN ONE PLACE: every target reaches the backend through Body.clamp() (commands, sweep points, holds after a
      calibration change); an out-of-range value is clamped to [min, max] and reported (`clamped`, WARNING record,
      at most one per joint per CLAMP_LOG_GAP_S);
    - a disabled joint refuses commands (`refused`), the backend holds it;
    - the emergency stop LATCHES: stop_all() halts every motor, cancels sweeps, interrupts pending commands, and every
      later command / sweep is refused until reset_estop() (explicit, never automatic);
    - a target change smaller than the joint's deadband is not sent (reported in `deadband`);
    - the store is written only with fully validated records (calibration.validate), previous file kept as .bak;
    - all public methods hold one re-entrant lock (HTTP threads and the brain loop call them concurrently); event
      hooks run under that lock and must not block (Brain.post is fine).
How to test
    .venv/bin/python -m tests.test_body   (prints `body tests: n/n passed`; part of tests/run_graph_tests.sh)
"""
import collections
import itertools
import math
import threading
import time

from ..log import log
from . import calibration as C
from .backends import Target
from .joints import GROUPS

CLAMP_LOG_GAP_S = 5.0      # at most one clamp WARNING per joint per 5 s (a slider dragged at a limit must not flood)
EVENTS_MAX = 50            # recent body events shown by the dashboard (state()["events"])
TRACE_S, TRACE_HZ = 120.0, 20.0
MAX_DT_S = 0.25            # a late tick never integrates more than this (a stalled loop must not teleport joints)
ARRIVE_POS_TOL, ARRIVE_VEL_TOL = 0.05, 0.5    # logical units: position within tol (or the deadband) and slow
SWEEP_SPEED = 0.25         # "Balayage lent": fraction of max_speed


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


class Body:
    def __init__(self, joints, backend, store=None, *, clock=time.monotonic, wall=time.time, backend_error=None,
                 backend_requested=None):
        self.joints = collections.OrderedDict((j.id, j) for j in joints)
        self.backend, self.store = backend, store
        self.backend_error = backend_error      # why the configured backend was replaced by the simulator (or None)
        self.backend_requested = backend_requested or backend.name   # name asked in the config (sim | mujoco | real)
        self.clock, self.wall = clock, wall
        self._lock = threading.RLock()
        stored = store.load(set(self.joints)) if store else {}
        self.cal = {jid: dict(stored.get(jid) or C.defaults_for(j)) for jid, j in self.joints.items()}
        self.backend.configure(list(self.joints.values()))
        self._targets = {}                     # logical target last sent per joint
        self._speed = {jid: 1.0 for jid in self.joints}   # speed fraction of the motion in progress
        for jid, j in self.joints.items():
            if not self.cal[jid]["enabled"]:
                self.backend.disable(jid)
            self._targets[jid] = 0.0 if j.mode == "velocity" else self.clamp(jid, self._logical_pos(jid))[0]
        self.estop = {"active": False, "since": None, "reason": None, "source": None}
        self._seq = itertools.count(1)
        self._pending = {}                     # cmd_id -> set of joint ids still moving to their target
        self._sweeps = {}                      # joint id -> {"points": [...], "i": n, "speed": f}
        self.events = collections.deque(maxlen=EVENTS_MAX)
        self._hooks = []
        self._clamp_log_at = {}
        self._trace = collections.deque(maxlen=int(TRACE_S * TRACE_HZ))
        self._last_tick = None
        self._last_sample = -1e9
        self._overcurrent = set()

    # ------------------------------------------------------------------ helpers
    def _raw(self, jid) -> dict:
        return self.backend.read_state()[jid]

    def _logical_pos(self, jid) -> float:
        hw = self._raw(jid)["position"]
        if self.joints[jid].mode == "velocity":
            return self.cal[jid]["direction"] * hw     # odometer (m); `zero` is not used by wheels
        return C.to_logical(self.cal[jid], hw)

    def _logical_vel(self, jid, raw=None) -> float:
        return self.cal[jid]["direction"] * (raw or self._raw(jid))["velocity"]

    def _to_hw(self, jid, logical: float) -> float:
        rec = self.cal[jid]
        if self.joints[jid].mode == "velocity":
            return rec["direction"] * logical
        return C.to_hardware(rec, logical)

    def add_event_hook(self, fn) -> None:
        """fn(event dict) on every body event (kinds: arrived, interrupted, clamp, refused, estop, estop_reset, stop,
        overcurrent, calibration, sweep_done, collision). Runs under the body lock: must not block (lot B1 posts graph events)."""
        self._hooks.append(fn)

    def _event(self, kind, level="info", joint=None, message="", **extra):
        ev = {"t": round(self.wall(), 3), "kind": kind, "level": level, "joint": joint, "message": message, **extra}
        self.events.append(ev)
        for fn in list(self._hooks):
            try:
                fn(ev)
            except Exception:   # noqa: BLE001 - a subscriber must never break the motor path
                log.exception("body event hook failed kind=%s", kind)
        return ev

    # ------------------------------------------------------------------ THE limit
    def clamp(self, jid: str, value: float) -> tuple:
        """(applied, clamped?) of a logical target: the ONE place where calibration limits are enforced."""
        rec = self.cal[jid]
        applied = min(rec["max"], max(rec["min"], float(value)))
        return applied, applied != float(value)

    def _send(self, jid: str, logical: float, speed: float) -> None:
        """Send an ALREADY CLAMPED logical target to the backend (callers: command, sweep, hold)."""
        rec = self.cal[jid]
        self._targets[jid], self._speed[jid] = logical, speed
        self.backend.command({jid: Target(self._to_hw(jid, logical), rec["max_speed"] * speed, rec["max_accel"])})

    def _note_clamp(self, jid, requested, applied, source):
        now = self.clock()
        if now - self._clamp_log_at.get(jid, -1e9) >= CLAMP_LOG_GAP_S:
            self._clamp_log_at[jid] = now
            log.warning("body clamp joint=%s requested=%.3f applied=%.3f source=%s", jid, requested, applied, source)
        self._event("clamp", "warning", jid, "Consigne bornée : %g → %g" % (round(requested, 3), round(applied, 3)),
                    requested=requested, applied=applied, source=source)

    def _interrupt(self, joints, reason):
        """Pending commands that move one of `joints` are interrupted (a newer command / stop / estop took over)."""
        for cid, left in list(self._pending.items()):
            if left & set(joints):
                del self._pending[cid]
                self._event("interrupted", "info", None, "Mouvement interrompu (%s)" % reason, cmd_id=cid, reason=reason)

    # ------------------------------------------------------------------ commands
    def command(self, targets, speed=None, source="api") -> dict:
        """Move joints to logical targets. Returns {ok, cmd_id, applied, clamped, refused, deadband, estop, error}.
        `speed` (optional) = fraction (0, 1] of each joint's max_speed. Never raises on bad input."""
        with self._lock:
            res = {"ok": False, "cmd_id": None, "applied": {}, "clamped": {}, "refused": {}, "deadband": [],
                   "estop": self.estop["active"], "error": None}
            if self.estop["active"]:   # checked first: a latched stop refuses everything, even a malformed command
                res["error"] = "Arrêt d'urgence actif : réarmez avant toute commande."
                res["refused"] = {k: "arrêt d'urgence" for k in (targets if isinstance(targets, dict) else {})}
                self._event("refused", "warning", None, "Commande refusée : arrêt d'urgence actif", source=source)
                return res
            if not isinstance(targets, dict) or not targets:
                res["error"] = "`targets` doit être un objet {articulation: valeur} non vide."
                return res
            if speed is None:
                speed = 1.0
            if not _num(speed) or not 0 < speed <= 1:
                res["error"] = "`speed` : fraction de la vitesse maxi, entre 0 (exclu) et 1."
                return res
            moved = []
            for jid, value in targets.items():
                if jid not in self.joints:
                    res["refused"][jid] = "articulation inconnue"
                    continue
                if not _num(value):
                    res["refused"][jid] = "valeur invalide (nombre fini attendu)"
                    continue
                if not self.cal[jid]["enabled"]:
                    res["refused"][jid] = "articulation désactivée"
                    continue
                applied, clamped = self.clamp(jid, value)
                if clamped:
                    res["clamped"][jid] = {"requested": float(value), "applied": applied}
                    self._note_clamp(jid, float(value), applied, source)
                if source != "sweep" and jid in self._sweeps:
                    del self._sweeps[jid]          # a manual command takes the joint back from the sweep
                if abs(applied - self._targets.get(jid, applied)) < self.cal[jid]["deadband"] and not clamped:
                    res["deadband"].append(jid)
                    res["applied"][jid] = self._targets[jid]
                    continue
                res["applied"][jid] = applied
                moved.append((jid, applied))
            if moved:
                ids = [j for j, _ in moved]
                self._interrupt(ids, "nouvelle commande")
                for jid, applied in moved:
                    self._send(jid, applied, float(speed))
                cid = next(self._seq)
                self._pending[cid] = set(ids)
                res["cmd_id"] = cid
            res["ok"] = bool(res["applied"]) and not res["refused"]
            return res

    def look(self, pan=None, tilt=None, speed=None, source="api") -> dict:
        """Convenience for gaze / sound turn-to (B1, C2): head_pan / head_tilt in degrees (limits still apply)."""
        t = {k: v for k, v in (("head_pan", pan), ("head_tilt", tilt)) if v is not None and k in self.joints}
        return self.command(t, speed, source)

    def stop(self, source="api") -> None:
        """Soft stop (no latch): every joint holds where it is, sweeps cancelled, pending commands interrupted."""
        with self._lock:
            self._sweeps.clear()
            self._interrupt(list(self.joints), "stop")
            self.backend.stop_all()
            for jid, j in self.joints.items():
                self._targets[jid] = 0.0 if j.mode == "velocity" else self.clamp(jid, self._logical_pos(jid))[0]
            self._event("stop", "info", None, "Arrêt des mouvements", source=source)

    def stop_all(self, reason="arrêt d'urgence", source="api") -> dict:
        """EMERGENCY STOP: halt every motor now and latch; commands are refused until reset_estop()."""
        with self._lock:
            self.backend.stop_all()
            self._sweeps.clear()
            self._interrupt(list(self.joints), "arrêt d'urgence")
            for jid, j in self.joints.items():
                self._targets[jid] = 0.0 if j.mode == "velocity" else self.clamp(jid, self._logical_pos(jid))[0]
            if not self.estop["active"]:
                self.estop = {"active": True, "since": round(self.wall(), 3), "reason": str(reason)[:120],
                              "source": source}
                log.warning("body EMERGENCY STOP source=%s", source)
                self._event("estop", "error", None, "ARRÊT D'URGENCE (%s)" % reason, source=source)
            return dict(self.estop)

    def reset_estop(self, source="api") -> dict:
        """Explicit re-arm after an emergency stop (joints stay where they stopped)."""
        with self._lock:
            if self.estop["active"]:
                log.warning("body emergency stop reset source=%s", source)
                self._event("estop_reset", "warning", None, "Arrêt d'urgence réarmé", source=source)
            self.estop = {"active": False, "since": None, "reason": None, "source": None}
            return dict(self.estop)

    def sweep(self, jid, speed=SWEEP_SPEED, source="api") -> tuple:
        """Slow test sweep of one position joint: min, then max, then back to where it was. (ok, error)."""
        with self._lock:
            if jid not in self.joints:
                return False, "Articulation inconnue : %s." % jid
            if self.joints[jid].mode != "position":
                return False, "Balayage réservé aux articulations en position (pas aux roues)."
            if self.estop["active"]:
                return False, "Arrêt d'urgence actif : réarmez avant le balayage."
            if not self.cal[jid]["enabled"]:
                return False, "Articulation désactivée."
            if not (_num(speed) and 0 < speed <= 1):
                return False, "`speed` : entre 0 (exclu) et 1."
            rec, back = self.cal[jid], self._targets[jid]
            self._sweeps[jid] = {"points": [rec["min"], rec["max"], back], "i": 0, "speed": float(speed),
                                 "cmd": None}
            self._sweep_next(jid, source)
            return True, None

    def _sweep_next(self, jid, source="sweep"):
        sw = self._sweeps[jid]
        if sw["i"] >= len(sw["points"]):
            del self._sweeps[jid]
            self._event("sweep_done", "info", jid, "Balayage terminé")
            return
        r = self.command({jid: sw["points"][sw["i"]]}, sw["speed"], "sweep")
        sw["i"] += 1
        sw["cmd"] = r["cmd_id"]
        if not r["ok"]:
            self._sweeps.pop(jid, None)
        elif r["cmd_id"] is None:     # already there (deadband): go on with the next point at the next tick
            sw["cmd"] = "now"

    # ------------------------------------------------------------------ calibration
    def calibration(self) -> dict:
        with self._lock:
            return {jid: dict(rec) for jid, rec in self.cal.items()}

    def export_calibration(self) -> dict:
        with self._lock:
            doc = C.make_doc(self.calibration(), self.store.revision if self.store else 0)
            if self.store and self.store.updated_at:
                doc["updated_at"] = self.store.updated_at
            return doc

    def _apply(self, new: dict, source: str, what: str) -> dict:
        """Install validated full records, persist them, re-clamp the held targets. Returns the store info."""
        changed = [jid for jid, rec in new.items() if rec != self.cal[jid]]
        for jid in changed:
            old = self.cal[jid]
            self.cal[jid] = dict(new[jid])
            if old["enabled"] and not new[jid]["enabled"]:
                self._sweeps.pop(jid, None)
                self._interrupt([jid], "articulation désactivée")
                self.backend.disable(jid)
            elif new[jid]["enabled"] and not old["enabled"]:
                self.backend.enable(jid)
            self._interrupt([jid], "calibration modifiée")
            if self.joints[jid].mode == "position":
                # hold where the joint physically is, inside the NEW limits (a narrower range pulls it back in)
                applied, clamped = self.clamp(jid, self._logical_pos(jid))
                if self.cal[jid]["enabled"] and not self.estop["active"]:
                    self._send(jid, applied, self._speed[jid])
                else:
                    self._targets[jid] = applied
        info = None
        if self.store is not None:
            self.store.save(self.calibration())
            info = self.store.info()
        if changed:
            self._event("calibration", "info", changed[0] if len(changed) == 1 else None,
                        "Calibration modifiée (%s) : %s" % (what, ", ".join(changed)), joints=changed, source=source)
        return {"changed": changed, "store": info}

    def set_calibration(self, partial, source="api", what="modification") -> tuple:
        """Merge {joint: {field: value}} into the calibration, validate EVERY touched record, apply + persist.
        (ok, errors, result). Nothing is applied when one record is invalid."""
        with self._lock:
            if not isinstance(partial, dict) or not partial:
                return False, ["Objet {articulation: {champ: valeur}} attendu."], None
            errs, new = [], {}
            for jid, fields in partial.items():
                if jid not in self.joints:
                    errs.append("Articulation inconnue : %s." % jid)
                    continue
                if not isinstance(fields, dict):
                    errs.append("%s : objet de champs attendu." % jid)
                    continue
                rec = {**self.cal[jid], **fields}
                e = C.validate(rec, jid)
                if e:
                    errs += e
                else:
                    new[jid] = C.normalise(rec)
            if errs:
                log.warning("body calibration refused (%d error(s)) source=%s", len(errs), source)
                return False, errs, None
            return True, [], self._apply(new, source, what)

    def import_calibration(self, doc, source="api") -> tuple:
        """Replace the records a calibration document lists (schema / version / every record checked first)."""
        with self._lock:
            records, errs = C.parse_doc(doc, set(self.joints))
            if errs:
                log.warning("body calibration import refused (%d error(s))", len(errs))
                return False, errs, None
            return True, [], self._apply(records, source, "import")

    def set_from_position(self, jid, which, source="api") -> tuple:
        """Dashboard buttons « Définir mini / maxi / zéro »: the limit (or the zero) becomes the CURRENT position.
        set_zero keeps the physical limits: min / max shift by the current logical position. (ok, errors, result)."""
        with self._lock:
            if jid not in self.joints:
                return False, ["Articulation inconnue : %s." % jid], None
            if self.joints[jid].mode != "position":
                return False, ["%s : une roue n'a ni butée ni zéro de position." % jid], None
            if which not in ("set_min", "set_max", "set_zero"):
                return False, ["Action inconnue : %s (set_min | set_max | set_zero)." % which], None
            rec, p = self.cal[jid], round(self._logical_pos(jid), 3)
            if which == "set_min":
                fields = {"min": p}
            elif which == "set_max":
                fields = {"max": p}
            else:
                hw = self._raw(jid)["position"]
                fields = {"zero": round(hw, 4), "min": round(rec["min"] - p, 3), "max": round(rec["max"] - p, 3)}
            return self.set_calibration({jid: fields}, source, which)

    # ------------------------------------------------------------------ heartbeat
    def tick(self, now=None) -> None:
        """Advance the backend (Brain heartbeat, ~10 Hz; tests call it with a manual clock)."""
        with self._lock:
            now = self.clock() if now is None else now
            dt = 0.0 if self._last_tick is None else min(MAX_DT_S, max(0.0, now - self._last_tick))
            self._last_tick = now
            self.backend.step(dt)
            for ev in self.backend.poll_events():   # physical contacts (MuJoCo); informative, limits stay in clamp()
                self._event("collision", "warning", ev.get("joint"), ev.get("message", "Collision"))
            raw = self.backend.read_state()
            done = set()
            for jid, j in self.joints.items():
                r, rec = raw[jid], self.cal[jid]
                if r["current"] > rec["max_current"] and jid not in self._overcurrent:
                    # torque / current limit: hold the joint where it is (latched per joint until it falls back)
                    self._overcurrent.add(jid)
                    log.warning("body overcurrent joint=%s current=%.2f max=%.2f", jid, r["current"], rec["max_current"])
                    self._sweeps.pop(jid, None)
                    self._interrupt([jid], "surintensité")
                    hold = 0.0 if j.mode == "velocity" else self.clamp(jid, self._logical_pos(jid))[0]
                    self._send(jid, hold, self._speed[jid])
                    self._event("overcurrent", "warning", jid, "Surintensité : %.2f A > %.2f A" % (
                        r["current"], rec["max_current"]))
                elif r["current"] <= rec["max_current"]:
                    self._overcurrent.discard(jid)
                if self._arrived(jid, raw):
                    done.add(jid)
            for cid, left in list(self._pending.items()):
                left -= done
                if not left:
                    del self._pending[cid]
                    self._event("arrived", "info", None, "Mouvement terminé", cmd_id=cid)
            for jid, sw in list(self._sweeps.items()):
                if sw["cmd"] == "now" or sw["cmd"] not in self._pending:
                    self._sweep_next(jid)
            if now - self._last_sample >= 1.0 / TRACE_HZ - 1e-6:
                self._last_sample = now
                self._trace.append((now, round(self.wall(), 3), {
                    jid: [round(self._logical_pos(jid), 4), round(self._logical_vel(jid, raw[jid]), 4),
                          round(self._targets[jid], 4), round(raw[jid]["current"], 3)] for jid in self.joints}))
                while self._trace and self._trace[0][0] < now - TRACE_S - 1e-9:   # time-bounded ring (any tick rate)
                    self._trace.popleft()

    def _arrived(self, jid, raw) -> bool:
        j, rec = self.joints[jid], self.cal[jid]
        vel = self._logical_vel(jid, raw[jid])
        if j.mode == "velocity":
            return abs(vel - self._targets[jid]) <= 1e-3
        tol = max(ARRIVE_POS_TOL, rec["deadband"])
        return abs(self._logical_pos(jid) - self._targets[jid]) <= tol and abs(vel) <= ARRIVE_VEL_TOL

    # ------------------------------------------------------------------ reads (API, dashboard, B1 conditions)
    def moving(self, jid=None) -> bool:
        """True while a command / sweep is still running (on `jid`, or on any joint)."""
        with self._lock:
            if jid is None:
                return bool(self._pending or self._sweeps)
            return jid in self._sweeps or any(jid in left for left in self._pending.values())

    def joints_of(self, group) -> list:
        return [jid for jid, j in self.joints.items() if j.group == group]

    def state(self) -> dict:
        with self._lock:
            raw = self.backend.read_state()
            joints = []
            for jid, j in self.joints.items():
                r = raw[jid]
                joints.append({**j.public(), "calibration": dict(self.cal[jid]),
                               "position": round(self._logical_pos(jid), 4),
                               "velocity": round(self._logical_vel(jid, r), 4),
                               "target": round(self._targets[jid], 4),
                               "current": round(r["current"], 3), "temperature": round(r["temperature"], 2),
                               "enabled": self.cal[jid]["enabled"], "moving": self.moving(jid),
                               "sweeping": jid in self._sweeps, "overcurrent": jid in self._overcurrent})
            return {"backend": self.backend.name, "backend_requested": self.backend_requested,
                    "backend_available": self.backend_error is None, "backend_error": self.backend_error, "estop": dict(self.estop),
                    "joints": joints, "groups": [{"id": g, "label": lbl} for g, lbl in GROUPS.items()],
                    "pending": sorted(self._pending), "events": list(self.events)[-20:],
                    "calibration_store": self.store.info() if self.store else None, "t": round(self.wall(), 3)}

    def trace(self, seconds=10.0) -> dict:
        """Recent samples (oldest first): {"fields", "hz", "samples": [{"t": epoch, "joints": {id: [..]}}]}."""
        with self._lock:
            seconds = max(0.0, min(TRACE_S, float(seconds)))
            if not self._trace:
                return {"fields": ["position", "velocity", "target", "current"], "hz": TRACE_HZ, "samples": []}
            last = self._trace[-1][0]
            samples = [{"t": w, "joints": js} for m, w, js in self._trace if m >= last - seconds - 1e-9]
            return {"fields": ["position", "velocity", "target", "current"], "hz": TRACE_HZ, "seconds": seconds,
                    "samples": samples}
