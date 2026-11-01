"""Variable type `timer`: stores its start epoch (null = stopped), reads as elapsed seconds; not a list item."""
from nanterino.vartypes import VarType, _num


class Timer(VarType):
    id = "timer"
    order = 90
    label = "Chrono"
    control = "timer"
    default = None
    numeric = ordered = nullable = True
    item_ok = False       # a start time is not an item

    def validate(self, v, choices=()):
        return v is None              # a timer starts stopped; timer_start writes the start time

    def stored_ok(self, v, choices=()):
        """state/vars.json keeps the start epoch, so a running timer survives a restart."""
        return v is None or _num(v)
