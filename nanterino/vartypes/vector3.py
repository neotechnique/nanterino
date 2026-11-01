"""Variable type `vector3`: a list of 3 numbers ('1, 2.5' typed in the editor)."""
from nanterino.vartypes import VarType, _num, coerce_vector


class Vector3(VarType):
    id = "vector3"
    order = 190
    label = "Vecteur 3D"
    control = "vector"
    default = [0, 0, 0]
    size = 3

    def validate(self, v, choices=()):
        return isinstance(v, list) and len(v) == self.size and all(_num(x) for x in v)

    def coerce(self, v):
        return coerce_vector(v)

    def editor_extra(self):
        return {"size": self.size}
