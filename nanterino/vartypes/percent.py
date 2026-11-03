"""Variable type `percent` (0..100, kept in range at run time): slider."""
from nanterino.vartypes import VarType, _num, coerce_number


class Percent(VarType):
    id = "percent"
    order = 70
    label = "Pourcentage"
    control = "slider"
    default = 0
    numeric = ordered = True

    def validate(self, v, choices=()):
        return _num(v) and 0 <= v <= 100

    def coerce(self, v):
        return coerce_number(v)

    def fit(self, v):
        return min(100, max(0, v))

    def editor_extra(self):
        return {"range": [0, 100]}
