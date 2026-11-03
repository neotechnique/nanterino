"""Value source `system` (Valeur du robot) - property module (lot M4, 2026-11-01).

The read-only system views (graph.SYSTEM_VARS: heure, jour, volume, visage_vu, tours ...), read through
brain.var_value. Output type = the system variable's type.
How to test: .venv/bin/python -m tests.test_properties
"""
from nanterino.nodes.base import Arg
from nanterino.properties import GetSource


class System(GetSource):
    id = "system"
    order = 60
    label = "Valeur du robot"
    help = "Une information du robot : heure, jour, volume, visage vu, tours de parole..."
    icon = "eye"
    out = ("of", "name")
    args = {"name": Arg("sysvar", "Information")}

    def check(self, parser, field_type, name):
        from nanterino import graph as G
        return G.SYSTEM_VARS[name][0]

    def get(self, ctx, name):
        return ctx.brain.var_value(name)
