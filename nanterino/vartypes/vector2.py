"""Variable type `vector2`: a list of 2 numbers ('1, 2.5' typed in the editor)."""
from nanterino.vartypes import VarType, _num, coerce_vector


class Vector2(VarType):
    id = "vector2"
    order = 180
    label = "Vecteur 2D"
    control = "vector"
    default = [0, 0]
    size = 2

    def validate(self, v, choices=()):
        return isinstance(v, list) and len(v) == self.size and all(_num(x) for x in v)

    def coerce(self, v):
        return coerce_vector(v)

    def editor_extra(self):
        return {"size": self.size}
