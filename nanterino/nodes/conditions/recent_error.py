"""Condition `recent_error` (Une erreur récente) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Le journal du robot a reçu une erreur (du robot ou de « Écrire dans le journal ») depuis ce nombre de secondes.
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Arg, Condition


class RecentError(Condition):
    id = 'recent_error'
    order = 290
    label = 'Une erreur récente'
    help = 'Le journal du robot a reçu une erreur (du robot ou de « Écrire dans le journal ») depuis ce nombre de secondes.'
    icon = 'flag'
    theme = 'systeme'
    args = {'seconds': Arg('seconds0', 'Depuis (secondes)')}

    def test(self, ctx, seconds):
        return ctx.brain.recent_error(seconds)
