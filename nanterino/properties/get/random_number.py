"""Value source `random_number` (Nombre au hasard) - property module (lot M4, 2026-11-01).

Two integers give an integer in [min, max] (both included), otherwise a decimal number; drawn from brain.rng (the
simulator seeds it: deterministic traces). min > max is refused when both are literals, swapped at run time.
How to test: .venv/bin/python -m tests.test_properties
"""
from nanterino.nodes.base import Arg
from nanterino.properties import GetSource, PropertyError, num


class RandomNumber(GetSource):
    id = "random_number"
    order = 70
    label = "Nombre au hasard"
    help = "Un nombre tiré au hasard entre un minimum et un maximum (entier si les deux bornes sont entières)."
    icon = "question-mark"
    out = "number"
    args = {"min": Arg("number", "Minimum"), "max": Arg("number", "Maximum")}

    def check(self, parser, field_type, min, max):  # noqa: A002 (argument names fixed by the vocabulary)
        if num(min) and num(max) and min > max:
            raise PropertyError("min %r is above max %r" % (min, max))
        return "number"

    def get(self, ctx, min, max):  # noqa: A002
        lo, hi = (min if num(min) else 0), (max if num(max) else 0)
        if lo > hi:
            lo, hi = hi, lo
        rng = ctx.brain.rng
        if isinstance(lo, int) and isinstance(hi, int):
            return rng.randint(lo, hi)
        return round(rng.uniform(lo, hi), 3)
