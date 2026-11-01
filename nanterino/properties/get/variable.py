"""Value source `variable` (Variable) - property module (lot M4, 2026-11-01).

`$x` is the shorthand of {get: variable, name: x}: in the fields that always accepted `$x` both compile to "$x"
(same messages, same run time); elsewhere (numbers, optional texts) the long form stays a dict and runs here.
How to test: .venv/bin/python -m tests.test_properties
"""
from nanterino.nodes.base import Arg
from nanterino.properties import GetSource


class Variable(GetSource):
    id = "variable"
    order = 20
    label = "Variable"
    help = "La valeur actuelle d'une variable (variables système comprises)."
    icon = "circle-dot"
    out = ("of", "name")
    shorthand = "variable"
    args = {"name": Arg("var", "Variable")}

    def check(self, parser, field_type, name):
        if not parser.value_ok(field_type, "$" + name):   # the pre-M4 `$x` check and messages
            return None
        return parser.var_info(name)[0]

    def get(self, ctx, name):
        return ctx.brain.var_value(name)
