"""Condition `list_index_exists` (La position existe dans une liste) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: La liste a un élément à cette position (1 = le premier, -1 = le dernier).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Arg, Condition
from nanterino.nodes.helpers import list_index


class ListIndexExists(Condition):
    id = 'list_index_exists'
    order = 240
    label = 'La position existe dans une liste'
    help = 'La liste a un élément à cette position (1 = le premier, -1 = le dernier).'
    icon = 'square'
    theme = 'listes'
    args = {'list': Arg('rlist_any', 'Liste'), 'index': Arg('number', 'Position (1 = le premier)')}

    def test(self, ctx, list, index):  # noqa: A002 (argument names are the graph's)
        return list_index(ctx.brain.list_items(list), index) is not None
