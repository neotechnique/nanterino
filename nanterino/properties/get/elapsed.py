"""Value source `elapsed` (Temps écoulé) - property module (lot M4, 2026-11-01).

Seconds since a datetime variable or since a timer's start (brain._elapsed: simulated wall clock in the simulator).
Fallback: an empty date or a stopped timer gives 0.
How to test: .venv/bin/python -m tests.test_properties
"""
from nanterino.nodes.base import Arg
from nanterino.properties import GetSource


class Elapsed(GetSource):
    id = "elapsed"
    order = 110
    label = "Temps écoulé"
    help = "Les secondes écoulées depuis une date ou depuis le départ d'un chrono (0 si vide ou arrêté)."
    icon = "hourglass"
    out = "duration"
    args = {"name": Arg("timeref", "Date ou chrono")}

    def get(self, ctx, name):
        e = ctx.brain._elapsed(name)
        return e if e is not None else 0
