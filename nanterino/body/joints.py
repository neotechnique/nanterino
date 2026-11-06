"""Joint registry of the robot body (lot C3): the declarative layout read from body.yaml.

logging: robotlog via nanterino.log (this module only raises LayoutError; nothing is logged here).

Purpose
    One immutable `Joint` per motor / articulation (id, French label, kind, unit, group) plus the default calibration of
    each joint, loaded from nanterino/body/body.yaml (provisional layout until the hardware is chosen).
Boundary
    Pure data: knows nothing about backends, calibration files or HTTP. Body (core.py) owns the live state.
Invariants
    - ids are lowercase `[a-z][a-z0-9_]*`, unique, and keep the file order (dashboard order);
    - kind in KINDS, unit in UNITS, group in GROUPS; a wheel is velocity-controlled (unit m/s), every other kind is
      position-controlled (unit deg or rad);
    - `defaults` only holds calibration keys (calibration.FIELDS); missing keys get calibration.BASE_DEFAULTS.
How to test
    .venv/bin/python -m tests.test_body   (layout section: default file loads, bad layouts are refused)
"""
import os
import re
from dataclasses import dataclass, field

import yaml

DEFAULT_LAYOUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "body.yaml")
KINDS = ("servo", "wheel", "pan", "tilt")
UNITS = ("deg", "rad", "m/s")
# Dashboard groups, in display order, with their French titles (the Mecanique screen and B1 nodes use the ids).
GROUPS = {"head": "Tête", "arm_l": "Bras gauche", "arm_r": "Bras droit", "base": "Base"}
_ID = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class LayoutError(ValueError):
    """The body layout file is invalid (message in French for the dashboard / journal)."""


@dataclass(frozen=True)
class Joint:
    id: str
    label: str
    kind: str
    unit: str
    group: str
    defaults: dict = field(default_factory=dict, compare=False)

    @property
    def mode(self) -> str:
        """`velocity` for wheels (the command is a speed), `position` for every other kind."""
        return "velocity" if self.kind == "wheel" else "position"

    def public(self) -> dict:
        return {"id": self.id, "label": self.label, "kind": self.kind, "unit": self.unit, "group": self.group,
                "mode": self.mode}


def parse_layout(raw) -> list:
    """Validate a decoded layout document and return its joints in file order (LayoutError on any problem)."""
    from .calibration import FIELDS   # local import: calibration imports nothing from here at module level
    if not isinstance(raw, dict) or not isinstance(raw.get("joints"), dict) or not raw["joints"]:
        raise LayoutError("body.yaml : clé `joints` manquante ou vide.")
    out = []
    for jid, spec in raw["joints"].items():
        if not (isinstance(jid, str) and _ID.match(jid)):
            raise LayoutError("body.yaml : identifiant d'articulation invalide : %r." % (jid,))
        if not isinstance(spec, dict):
            raise LayoutError("body.yaml : %s doit être un objet." % jid)
        kind, unit, group = spec.get("kind"), spec.get("unit"), spec.get("group")
        if kind not in KINDS:
            raise LayoutError("body.yaml : %s.kind doit être %s." % (jid, " | ".join(KINDS)))
        if unit not in UNITS:
            raise LayoutError("body.yaml : %s.unit doit être %s." % (jid, " | ".join(UNITS)))
        if (kind == "wheel") != (unit == "m/s"):
            raise LayoutError("body.yaml : %s : une roue s'exprime en m/s, une articulation en deg ou rad." % jid)
        if group not in GROUPS:
            raise LayoutError("body.yaml : %s.group doit être %s." % (jid, " | ".join(GROUPS)))
        defaults = spec.get("defaults") or {}
        if not isinstance(defaults, dict) or set(defaults) - set(FIELDS):
            raise LayoutError("body.yaml : %s.defaults : clés inconnues %s." % (
                jid, sorted(set(defaults) - set(FIELDS)) if isinstance(defaults, dict) else "?"))
        out.append(Joint(jid, str(spec.get("label") or jid), kind, unit, group, dict(defaults)))
    return out


def load_layout(path: str = DEFAULT_LAYOUT) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise LayoutError("body.yaml illisible : %s" % e) from e
    return parse_layout(raw)
