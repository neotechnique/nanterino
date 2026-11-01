"""List mode `plain`: the usual behaviour (say_random draws at random, `max` optional)."""
from nanterino.listmodes import ListMode


class Plain(ListMode):
    id = "plain"
    order = 10
    label = "Simple"
    help = "Comportement habituel."
