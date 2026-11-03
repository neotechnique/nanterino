"""Condition `list_sorted` (Une liste est triée) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Les éléments de la liste sont dans l'ordre croissant (comme après « Trier une liste »).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Arg, Condition
from nanterino.nodes.helpers import sort_key

list_ = list   # the argument `list` shadows the builtin inside test()


class ListSorted(Condition):
    id = 'list_sorted'
    order = 250
    label = 'Une liste est triée'
    help = "Les éléments de la liste sont dans l'ordre croissant (comme après « Trier une liste »)."
    icon = 'square'
    theme = 'listes'
    args = {'list': Arg('rlist_any', 'Liste')}

    def test(self, ctx, list):  # noqa: A002 (argument names are the graph's)
        items = list_(ctx.brain.list_items(list))
        return items == sorted(items, key=sort_key)
