"""Opening hours parser (config `opening_hours`) used by the `dans_les_horaires` guard and the
ouverture/fermeture events (logging: robotlog via nanterino.log).

Purpose
    `opening_hours` is a small French-keyed mapping, e.g. {"lun-ven": "09:00-18:00",
    "sam": ["10:00-12:00", "14:00-17:00"]}. `parse()` turns it into a table weekday -> ranges (minutes of
    the day); `is_open()` answers for one local date-time. An EMPTY mapping means "always open": no guard
    ever fails and no ouverture/fermeture event is ever posted.

Boundary
    Pure functions, no clock access: the caller passes a `datetime` (the brain passes its wall clock, the
    simulator passes simulated time), so tests never depend on the real time of day.

Invariants
    - Weekdays are 0=lun .. 6=dim. A day key is `lun`, a range `lun-ven` (may wrap: `sam-lun`) or a list
      `lun,mer`; case-insensitive, French 3-letter names only.
    - A time range is `HH:MM-HH:MM`. An end <= start means "past midnight": it belongs to the day it starts on
      and continues into the next morning.
    - A malformed value raises ValueError (message in French for the config author); `safe_parse()` logs it and
      returns None, which callers treat as "always open" so a typo never locks the robot out.

How to test
    python -m tests.test_graph_features   (hours cases)
"""
import re

from .log import log

DAYS = ("lun", "mar", "mer", "jeu", "ven", "sam", "dim")
_RANGE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")


def _minutes(h: str, m: str) -> int:
    hh, mm = int(h), int(m)
    if not (0 <= hh <= 24 and 0 <= mm < 60) or (hh == 24 and mm):
        raise ValueError("heure invalide : %s:%s" % (h, m))
    return hh * 60 + mm


def _days(key: str) -> list:
    out = []
    for part in str(key).lower().replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            if a not in DAYS or b not in DAYS:
                raise ValueError("jours inconnus : %r (attendu : %s)" % (part, " ".join(DAYS)))
            i, j = DAYS.index(a), DAYS.index(b)
            out += [d % 7 for d in range(i, j + 1 if j >= i else j + 8)]
        elif part in DAYS:
            out.append(DAYS.index(part))
        else:
            raise ValueError("jour inconnu : %r (attendu : %s)" % (part, " ".join(DAYS)))
    if not out:
        raise ValueError("clé de jours vide")
    return out


def parse(hours) -> dict | None:
    """Table {weekday: [(start_min, end_min), ...]} or None when `hours` is empty (always open)."""
    if not hours:
        return None
    if not isinstance(hours, dict):
        raise ValueError("opening_hours doit être un dictionnaire {jours: plage}")
    table = {d: [] for d in range(7)}
    for key, val in hours.items():
        ranges = val if isinstance(val, (list, tuple)) else [val]
        parsed = []
        for r in ranges:
            m = _RANGE.match(str(r))
            if not m:
                raise ValueError("plage invalide : %r (attendu HH:MM-HH:MM)" % (r,))
            parsed.append((_minutes(m.group(1), m.group(2)), _minutes(m.group(3), m.group(4))))
        for d in _days(key):
            table[d] += parsed
    return table


def safe_parse(hours) -> dict | None:
    try:
        return parse(hours)
    except ValueError as e:
        log.warning("opening_hours ignored (always open): %s", e)
        return None


def is_open(table: dict | None, when) -> bool:
    """Open at `when` (a datetime)? `None` table = always open."""
    if table is None:
        return True
    minute, day = when.hour * 60 + when.minute, when.weekday()
    for start, end in table[day]:
        if start < end:
            if start <= minute < end:
                return True
        elif minute >= start:        # range past midnight, evening part
            return True
    for start, end in table[(day - 1) % 7]:
        if end <= start and minute < end:   # morning part of yesterday's range
            return True
    return False
