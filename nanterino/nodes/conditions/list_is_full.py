"""Condition `list_is_full` (Une liste est pleine) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: La liste a atteint son nombre maximal d'éléments (réglage max) ; faux si elle n'a pas de maximum.
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class ListIsFull(Condition):
    id = 'list_is_full'
    order = 620
    label = 'Une liste est pleine'
    help = "La liste a atteint son nombre maximal d'éléments (réglage max) ; faux si elle n'a pas de maximum."
    icon = 'square'
    theme = 'listes'
    args = {'list': Arg('rlist_any', 'Liste')}

    def test(self, ctx, list):  # noqa: A002 (argument names are the graph's)
        li = ctx.graph.lists.get(list)
        return li is not None and bool(li.maxlen) and len(ctx.brain.list_items(list)) >= li.maxlen
