"""Variable type `number` (int or float): optional min / max / step, clamped at run time."""
from nanterino.vartypes import VarType, _num, coerce_number


class Number(VarType):
    id = "number"
    order = 20
    label = "Nombre"
    control = "number"
    default = 0
    numeric = ordered = bounded = True
    item_label = "Nombres"
    item_order = 2

    def validate(self, v, choices=()):
        return _num(v)

    def coerce(self, v):
        return coerce_number(v)
