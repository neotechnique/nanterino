"""Condition `list_count_compare` (Compter les éléments d'une liste) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Compare le nombre d'éléments d'une liste à un nombre (=, ≠, <, ≤, >, ≥).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Arg, Condition


class ListCountCompare(Condition):
    id = 'list_count_compare'
    order = 260
    label = "Compter les éléments d'une liste"
    help = "Compare le nombre d'éléments d'une liste à un nombre (=, ≠, <, ≤, >, ≥)."
    icon = 'square'
    theme = 'listes'
    args = {'items': Arg('rlist_any', 'Liste'), 'op': Arg('op', 'Opérateur'), 'count': Arg('number', "Nombre d'éléments")}

    def test(self, ctx, items, op, count):
        b = ctx.brain
        return b._compare(len(b.list_items(items)), op, count, 'number')
