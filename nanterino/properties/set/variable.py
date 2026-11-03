"""Write target `variable` (Variable) - property module (lot M4, 2026-11-01).

Used by set_var: the value goes through the type module's clamp (integer rounding, percent range, the variable's
min / max: former graph.fit_value) and Brain._set_var (var_changed, anti-loop). System variables and timers are not
writable (the parser refuses them before).
How to test: .venv/bin/python -m tests.test_properties
"""
from nanterino.nodes.base import Arg
from nanterino.properties import SetTarget


class Variable(SetTarget):
    id = "variable"
    order = 10
    label = "Variable"
    help = "Donne la valeur à une variable (bornes et arrondis du type appliqués)."
    icon = "arrow-right"
    args = {"name": Arg("wvar", "Variable")}

    def check(self, parser, name):
        return parser.var_info(name)[0]

    def write(self, ctx, value, name):
        from nanterino.vartypes import VARTYPES
        var = ctx.graph.variables[name]
        ctx.brain._set_var(name, VARTYPES[var.type].clamp(value, var.vmin, var.vmax))
