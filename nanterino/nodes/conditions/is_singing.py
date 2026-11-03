"""Condition `is_singing` (Le robot chante) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: La chanson est en cours (« Chanter », pas encore finie ni arrêtée).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Condition


class IsSinging(Condition):
    id = 'is_singing'
    order = 320
    label = 'Le robot chante'
    help = 'La chanson est en cours (« Chanter », pas encore finie ni arrêtée).'
    icon = 'music'
    theme = 'parole'

    def test(self, ctx):
        return ctx.brain.is_singing()
