"""Write target `list_item` (Nouvel élément de liste) - property module (lot M4, 2026-11-01).

Used by list_add: the item goes through the item type's clamp (integer rounding, percent range; texts unchanged),
then the list mode's push (LISTMODES: plain appends, history / max drop the oldest items).
How to test: .venv/bin/python -m tests.test_properties
"""
from nanterino.nodes.base import Arg
from nanterino.properties import SetTarget


class ListItem(SetTarget):
    id = "list_item"
    order = 20
    label = "Nouvel élément de liste"
    help = "Ajoute la valeur à la fin d'une liste (le mode de la liste garde ou retire les anciens éléments)."
    icon = "plus"
    args = {"list": Arg("wlist", "Liste")}

    def check(self, parser, list):  # noqa: A002 (argument names fixed by the vocabulary)
        return parser.lists[list].type

    def write(self, ctx, value, list):  # noqa: A002
        from nanterino.listmodes import LISTMODES
        from nanterino.vartypes import VARTYPES
        li = ctx.graph.lists[list]
        LISTMODES[li.mode].push(ctx.brain, li, VARTYPES[li.type].clamp(value))
