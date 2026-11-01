"""List mode `history`: keeps the last `max` items (required); an addition beyond it drops the oldest."""
from nanterino.listmodes import ListMode


class History(ListMode):
    id = "history"
    order = 30
    label = "Historique"
    help = "Garde les N derniers éléments (`max`) : un ajout de trop retire le plus ancien."
    needs_max = True
    bound_ok = False      # a bound list is read-only: nothing is ever added to it
