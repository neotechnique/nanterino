"""Variable type `bool` (true / false): checkbox, = and != only."""
from nanterino.vartypes import VarType


class Bool(VarType):
    id = "bool"
    order = 10
    label = "Vrai / faux"
    control = "checkbox"
    default = False
    item_order = 3        # third item type of the list menus (after texts and numbers)

    def validate(self, v, choices=()):
        return isinstance(v, bool)

    def coerce(self, v):
        s = v.strip()
        if s.lower() in ("true", "false", "vrai", "faux"):
            return s.lower() in ("true", "vrai")
        return v
