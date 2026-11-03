"""Value source `random_from_list` (Au hasard dans une liste) - property module (lot M4, 2026-11-01).

One item drawn with brain.rng (independent of the list mode's shuffle bag, which only say_random uses). Output
type = the list's item type; an empty list gives that type's default.
How to test: .venv/bin/python -m tests.test_properties
"""
from nanterino.nodes.base import Arg
from nanterino.properties import GetSource, default_of


class RandomFromList(GetSource):
    id = "random_from_list"
    order = 80
    label = "Au hasard dans une liste"
    help = "Un élément d'une liste tiré au hasard."
    icon = "refresh"
    out = ("of", "list")
    args = {"list": Arg("list", "Liste")}

    def check(self, parser, field_type, list):  # noqa: A002 (argument names fixed by the vocabulary)
        return parser.lists[list].type

    def get(self, ctx, list):  # noqa: A002
        items = ctx.brain.list_items(list)
        if not items:
            li = ctx.graph.lists.get(list)
            return default_of(li.type if li is not None else None)
        return ctx.brain.rng.choice(items)
