"""Value source `constant` (Valeur fixe) - property module (lot M4, 2026-11-01).

Boundary: metadata read by graph.py (validation, vocabulary); the compiled form is the plain value itself
(check_field collapses {get: constant, value: v} to v), so get() only runs when called directly.
How to test: .venv/bin/python -m tests.test_properties
"""
from nanterino.nodes.base import Arg
from nanterino.properties import GetSource


class Constant(GetSource):
    id = "constant"
    order = 10
    label = "Valeur fixe"
    help = "Une valeur écrite telle quelle (nombre, texte, vrai / faux...)."
    icon = "square"
    out = "same"
    shorthand = "constant"
    literal_args = ("value",)   # refused before the generic nested check (a `$x` here would be a variable source)
    args = {"value": Arg("value", "Valeur")}

    def check(self, parser, field_type, value):
        # literal_args already refused `$x` / sources; the generic check validated the literal against the field
        return field_type

    def get(self, ctx, value):
        return value
