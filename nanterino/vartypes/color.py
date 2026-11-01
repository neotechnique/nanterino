"""Variable type `color`: #rrggbb text."""
from nanterino.vartypes import VarType


class Color(VarType):
    id = "color"
    order = 170
    label = "Couleur"
    control = "color"
    default = "#ffffff"
    textlike = True

    def validate(self, v, choices=()):
        from nanterino.graph import _COLOR
        return isinstance(v, str) and bool(_COLOR.match(v))
