"""Per-joint calibration of the robot body (lot C3): validation and the versioned state/body-calibration.json store.

logging: robotlog via nanterino.log (unreadable / corrupt file = warning, then defaults).

Purpose
    Each joint has one calibration record (FIELDS): min / max (logical limits, joint unit), zero (hardware offset: the
    hardware position that reads as logical 0), direction (+1 / -1), max_speed (unit/s), max_accel (unit/s^2),
    max_current (A, the torque limit of a servo), deadband (unit: smaller target changes are ignored), enabled.
    `validate()` is the ONE rule set (API PUT, import, set_min / set_max / set_zero); the store persists it.
Boundary
    Knows joints only through joints.Joint (defaults); never talks to a backend. Body (core.py) applies the records.
    Only server.py gives the live path (state/body-calibration.json, git-ignored); tests use temporary paths, the
    simulator and test brains use no store at all (in-memory calibration).
Invariants
    - logical = direction * (hardware - zero); hardware = zero + direction * logical;
    - a valid record has finite numbers (bool refused), min < max, 0 within [min, max] ("zero in range"),
      direction in {+1, -1}, max_speed / max_accel / max_current > 0, 0 <= deadband < max - min, enabled bool;
    - file = {"schema": SCHEMA, "version": VERSION, "revision": n, "updated_at": ISO-8601 UTC, "joints": {id: record}};
      written atomically (temp file in the same folder, fsync, os.replace) after copying the previous file to
      `<path>.bak` (one previous version kept);
    - a record of an unknown joint in the file is ignored (logged); a joint missing from the file uses its defaults.
How to test
    .venv/bin/python -m tests.test_body   (calibration section: validate, persist, backup, atomic write, import)
"""
import json
import math
import os
import shutil
import tempfile
import threading
import time

from ..log import log

SCHEMA = "nanterino.body-calibration"
VERSION = 1
DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            "state", "body-calibration.json")
FIELDS = ("min", "max", "zero", "direction", "max_speed", "max_accel", "max_current", "deadband", "enabled")
# Used for every key a joint's body.yaml `defaults` leaves out.
BASE_DEFAULTS = {"min": -90.0, "max": 90.0, "zero": 0.0, "direction": 1, "max_speed": 60.0, "max_accel": 180.0,
                 "max_current": 1.0, "deadband": 0.0, "enabled": True}


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def defaults_for(joint) -> dict:
    rec = dict(BASE_DEFAULTS)
    rec.update(joint.defaults)
    return normalise(rec)


def normalise(rec: dict) -> dict:
    """Canonical types (floats, int direction, bool enabled) of an already VALID record."""
    out = {k: float(rec[k]) for k in ("min", "max", "zero", "max_speed", "max_accel", "max_current", "deadband")}
    out["direction"] = int(rec["direction"])
    out["enabled"] = bool(rec["enabled"])
    return out


def validate(rec, joint_id: str = "?") -> list:
    """French error messages for one calibration record ([] = valid). Every key of FIELDS is required."""
    if not isinstance(rec, dict):
        return ["%s : la calibration doit être un objet." % joint_id]
    errs = []
    unknown = sorted(set(rec) - set(FIELDS))
    if unknown:
        errs.append("%s : champs inconnus %s." % (joint_id, ", ".join(unknown)))
    missing = [k for k in FIELDS if k not in rec]
    if missing:
        errs.append("%s : champs manquants %s." % (joint_id, ", ".join(missing)))
        return errs
    for k in ("min", "max", "zero", "max_speed", "max_accel", "max_current", "deadband"):
        if not _num(rec[k]):
            errs.append("%s.%s : nombre fini attendu." % (joint_id, k))
    if rec["direction"] not in (1, -1) or isinstance(rec["direction"], bool):
        errs.append("%s.direction : 1 ou -1." % joint_id)
    if not isinstance(rec["enabled"], bool):
        errs.append("%s.enabled : vrai ou faux." % joint_id)
    if errs:
        return errs
    if not rec["min"] < rec["max"]:
        errs.append("%s : le mini (%g) doit être inférieur au maxi (%g)." % (joint_id, rec["min"], rec["max"]))
    elif not rec["min"] <= 0.0 <= rec["max"]:
        errs.append("%s : le zéro doit rester entre le mini et le maxi (mini %g, maxi %g)." % (
            joint_id, rec["min"], rec["max"]))
    for k in ("max_speed", "max_accel", "max_current"):
        if rec[k] <= 0:
            errs.append("%s.%s : valeur positive attendue." % (joint_id, k))
    if rec["deadband"] < 0 or (rec["min"] < rec["max"] and rec["deadband"] >= rec["max"] - rec["min"]):
        errs.append("%s.deadband : entre 0 et l'amplitude (maxi - mini)." % joint_id)
    return errs


def to_logical(rec: dict, hw: float) -> float:
    return rec["direction"] * (hw - rec["zero"])


def to_hardware(rec: dict, logical: float) -> float:
    return rec["zero"] + rec["direction"] * logical


def make_doc(records: dict, revision: int) -> dict:
    return {"schema": SCHEMA, "version": VERSION, "revision": int(revision),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "joints": records}


def parse_doc(doc, joint_ids) -> tuple:
    """(records {id: record}, errors) of an imported / read calibration document. Every record must be complete and
    valid and name a known joint; joints the document leaves out are simply not in `records`."""
    if not isinstance(doc, dict):
        return {}, ["Document de calibration : objet JSON attendu."]
    if doc.get("schema") != SCHEMA:
        return {}, ["Document de calibration : `schema` doit valoir %s." % SCHEMA]
    if doc.get("version") != VERSION:
        return {}, ["Document de calibration : version %r non prise en charge (attendu %d)." % (doc.get("version"), VERSION)]
    joints = doc.get("joints")
    if not isinstance(joints, dict) or not joints:
        return {}, ["Document de calibration : `joints` doit être un objet non vide."]
    errs, out = [], {}
    for jid, rec in joints.items():
        if jid not in joint_ids:
            errs.append("Articulation inconnue : %s." % jid)
            continue
        e = validate(rec, jid)
        if e:
            errs += e
        else:
            out[jid] = normalise(rec)
    return out, errs


class CalibrationStore:
    """The live calibration file. load() never raises; save() raises OSError only when the disk refuses the write."""

    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        self.revision = 0
        self.updated_at = None
        self.writes = 0
        self.last_error = None
        self._lock = threading.Lock()

    @property
    def backup_path(self) -> str:
        return self.path + ".bak"

    def load(self, joint_ids) -> dict:
        """Valid records of the file ({} when missing / unreadable / invalid; problems are logged as warnings)."""
        try:
            with open(self.path, encoding="utf-8") as f:
                doc = json.load(f)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            self.last_error = "fichier illisible : %s" % e
            log.warning("body calibration %s unreadable, defaults used: %s", self.path, e)
            return {}
        if not (isinstance(doc, dict) and doc.get("schema") == SCHEMA and isinstance(doc.get("joints"), dict)):
            self.last_error = "document sans schéma %s" % SCHEMA
            log.warning("body calibration %s has no %s document, defaults used", self.path, SCHEMA)
            return {}
        self.revision = int(doc["revision"]) if _num(doc.get("revision")) else 0
        self.updated_at = doc.get("updated_at")
        records, errs = {}, []
        for jid, rec in doc["joints"].items():
            if jid not in joint_ids:
                # a layout change must not crash the robot nor lose the file: the record is kept on disk until a save
                errs.append("articulation inconnue %s" % jid)
                continue
            e = validate(rec, jid)
            if e:
                errs += e
            else:
                records[jid] = normalise(rec)
        if errs:
            self.last_error = "; ".join(errs)
            log.warning("body calibration %s: %d record(s) ignored, defaults used for them", self.path, len(errs))
        return records

    def save(self, records: dict) -> dict:
        """Write every record atomically (previous file copied to .bak first); returns the written document."""
        with self._lock:
            doc = make_doc(records, self.revision + 1)
            folder = os.path.dirname(self.path) or "."
            os.makedirs(folder, exist_ok=True)
            if os.path.exists(self.path):
                shutil.copy2(self.path, self.backup_path)   # the previous version survives a bad calibration
            fd, tmp = tempfile.mkstemp(prefix=".body-calibration.", suffix=".tmp", dir=folder)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(doc, f, ensure_ascii=False, indent=2, sort_keys=True)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            self.revision, self.updated_at = doc["revision"], doc["updated_at"]
            self.writes += 1
            self.last_error = None
            return doc

    def info(self) -> dict:
        return {"path": self.path, "revision": self.revision, "updated_at": self.updated_at,
                "backup": os.path.exists(self.backup_path), "error": self.last_error}
