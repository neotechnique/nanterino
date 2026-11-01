"""Value source `list_item` (Élément d'une liste) - property module (lot M4, 2026-11-01).

pick: first / last / random (brain.rng: seeded by the simulator) / index (1 = first item). Output type = the list's
item type. Fallback: an empty list or an index out of range gives the item type's default.
How to test: .venv/bin/python -m tests.test_properties
"""
from nanterino.nodes.base import Arg
from nanterino.properties import GetSource, PropertyError, default_of, num


class ListItem(GetSource):
    id = "list_item"
    order = 40
    label = "Élément d'une liste"
    help = "Le premier, le dernier, un élément au hasard ou celui d'une position donnée (1 = le premier)."
    icon = "text-caption"
    out = ("of", "list")
    args = {"list": Arg("list", "Liste"), "pick": Arg("pick", "Lequel"), "index": Arg("number", "Position")}
    defaults = {"pick": "first", "index": 1}

    def check(self, parser, field_type, list, pick, index):  # noqa: A002 (argument names fixed by the vocabulary)
        if num(index) and not (isinstance(index, int) and index >= 1):
            raise PropertyError("index must be an integer >= 1 (1 = first item), got %r" % (index,))
        return parser.lists[list].type

    def get(self, ctx, list, pick, index):  # noqa: A002
        b = ctx.brain
        items = b.list_items(list)
        li = ctx.graph.lists.get(list)
        if not items:
            return default_of(li.type if li is not None else None)
        if pick == "last":
            return items[-1]
        if pick == "random":
            return b.rng.choice(items)
        if pick == "index":
            i = int(index) - 1 if num(index) else -1
            return items[i] if 0 <= i < len(items) else default_of(li.type if li is not None else None)
        return items[0]
