"""Variable type `duration` (seconds >= 0)."""
from nanterino.vartypes import VarType, _num, coerce_number


class Duration(VarType):
    id = "duration"
    order = 50
    label = "Durée (s)"
    control = "number"
    default = 0
    numeric = ordered = True

    def validate(self, v, choices=()):
        return _num(v) and v >= 0

    def coerce(self, v):
        return coerce_number(v)
