"""Condition `list_empty` (Une liste est vide) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Arg, Condition


class ListEmpty(Condition):
    id = 'list_empty'
    order = 120
    label = 'Une liste est vide'
    help = "La liste n'a aucun élément."
    icon = 'square'
    theme = 'listes'
    args = {'list': Arg('rlist_any', 'Liste')}

    def test(self, ctx, list):  # noqa: A002 (argument names are the graph's)
        return not ctx.brain.list_items(list)
