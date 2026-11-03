"""Value source `calc` (Calcul) - property module (lot M4, 2026-11-01).

A op B with op in properties.CALC_OPS (+ - * / min max); A and B are numbers, `$x` or other sources (calc of calc,
at most properties.MAX_DEPTH levels). No text expression, no eval. Run time: a non-number operand counts as 0; a
division by zero gives 0 (the parser adds a `division_by_zero` diagnostic when the divisor is a literal 0). Two
integers give an integer except for `/`, whose exact integer results are returned as integers too.
How to test: .venv/bin/python -m tests.test_properties
"""
from nanterino.nodes.base import Arg
from nanterino.properties import GetSource, num


class Calc(GetSource):
    id = "calc"
    order = 120
    label = "Calcul"
    help = "Valeur A, opérateur (+ − × ÷ min max), valeur B ; A et B peuvent être d'autres sources."
    icon = "plus"
    out = "number"
    args = {"a": Arg("number", "Valeur A"), "op": Arg("calcop", "Opérateur"), "b": Arg("number", "Valeur B")}

    def check(self, parser, field_type, a, op, b):
        if op == "/" and num(b) and b == 0:
            parser.warn("division by zero (the result is 0 at run time)", "division_by_zero")
        return "number"

    def get(self, ctx, a, op, b):
        x, y = (a if num(a) else 0), (b if num(b) else 0)
        if op == "+":
            r = x + y
        elif op == "-":
            r = x - y
        elif op == "*":
            r = x * y
        elif op == "/":
            if y == 0:
                return 0
            r = x / y
            return int(r) if isinstance(x, int) and isinstance(y, int) and r == int(r) else r
        elif op == "min":
            r = min(x, y)
        elif op == "max":
            r = max(x, y)
        else:
            return 0
        return r
