"""Condition `dict_empty` (Un dictionnaire est vide) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Le dictionnaire n'a aucune clé.
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Arg, Condition


class DictEmpty(Condition):
    id = 'dict_empty'
    order = 270
    label = 'Un dictionnaire est vide'
    help = "Le dictionnaire n'a aucune clé."
    icon = 'square'
    theme = 'listes'
    args = {'dict': Arg('rdict', 'Dictionnaire')}

    def test(self, ctx, dict):  # noqa: A002 (argument names are the graph's)
        return not ctx.brain.list_items(dict)
