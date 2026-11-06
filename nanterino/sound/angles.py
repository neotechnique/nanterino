"""Angle helpers of the 360-degree sound layer (lot C2): wrapping, sectors with wrap-around, circular means.

logging: none (pure functions).

Purpose
    One convention for every sound module, node and the dashboard: azimuths in degrees in the ROBOT FRAME, seen from
    above, 0 = straight ahead, positive = towards the robot's LEFT (counter-clockwise), the same sign as the head pan
    joint of nanterino/body (head_pan +30 looks 30 degrees to the left). Values are kept in (-180, 180].
Boundary
    No I/O, no numpy: imported by graph node modules and by the Brain.
Invariants
    - wrap180() is the only normaliser (callers never use % 360 themselves);
    - in_sector(az, a, b) walks COUNTER-CLOCKWISE from a to b (increasing azimuth): (-45, 45) is the front,
      (135, -135) is the back through 180 degrees; a == b (mod 360) means the whole circle;
    - the four named sectors (SECTORS) tile the circle without overlap: the start bound is included, the end
      bound excluded (45 belongs to « gauche », -45 to « avant »).
How to test
    .venv/bin/python -m tests.test_sound   (angles section, plus a mutation run of the wrap-around)
"""
import math

# Named sectors of the trigger `sound_from_direction` (value:), in palette order: (start, end) counter-clockwise.
SECTORS = {"avant": (-45.0, 45.0), "gauche": (45.0, 135.0), "arriere": (135.0, -135.0), "droite": (-135.0, -45.0)}
SECTOR_LABELS = {"avant": "Devant", "gauche": "À gauche", "arriere": "Derrière", "droite": "À droite"}


def wrap180(a: float) -> float:
    """Angle in degrees folded into (-180, 180]."""
    a = math.fmod(float(a), 360.0)
    if a <= -180.0:
        a += 360.0
    elif a > 180.0:
        a -= 360.0
    return a


def in_sector(az: float, a: float, b: float, *, include_end: bool = True) -> bool:
    """Is azimuth `az` inside the sector that goes counter-clockwise from `a` to `b` (degrees, wrap-around safe)?"""
    width = (float(b) - float(a)) % 360.0
    if width == 0.0:
        return True                      # a == b: the whole circle (documented choice, see module header)
    d = (float(az) - float(a)) % 360.0
    return d <= width + 1e-9 if include_end else d < width - 1e-9


def sector_of(az: float) -> str:
    """Named sector (SECTORS key) of an azimuth; start bound included, end bound excluded."""
    for name, (a, b) in SECTORS.items():
        if in_sector(az, a, b, include_end=False):
            return name
    return "avant"                       # unreachable: the sectors tile the circle


def circular_mean(angles, weights=None):
    """Weighted circular mean in degrees (None when the weights are all zero or the vectors cancel out)."""
    sx = sy = 0.0
    for i, a in enumerate(angles):
        w = 1.0 if weights is None else float(weights[i])
        sx += w * math.cos(math.radians(a))
        sy += w * math.sin(math.radians(a))
    if math.hypot(sx, sy) < 1e-9:
        return None
    return wrap180(math.degrees(math.atan2(sy, sx)))


def angle_diff(a: float, b: float) -> float:
    """Signed smallest difference a - b in degrees, in (-180, 180]."""
    return wrap180(float(a) - float(b))
