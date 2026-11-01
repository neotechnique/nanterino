"""Variable type `integer`: rounded at run time, optional integer min / max / step."""
from nanterino.vartypes import VarType, coerce_number


class Integer(VarType):
    id = "integer"
    order = 60
    label = "Entier"
    control = "number"
    default = 0
    numeric = ordered = bounded = integral = True

    def validate(self, v, choices=()):
        return isinstance(v, int) and not isinstance(v, bool)

    def coerce(self, v):
        return coerce_number(v)

    def fit(self, v):
        return int(round(v))
