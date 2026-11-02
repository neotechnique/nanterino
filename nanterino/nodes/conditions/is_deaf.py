"""Condition `is_deaf` (Le robot est sourd) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Le mode sourd est activé (bouton Sourd ou « Mode sourd ») : le micro reste fermé.
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Condition


class IsDeaf(Condition):
    id = 'is_deaf'
    order = 220
    label = 'Le robot est sourd'
    help = 'Le mode sourd est activé (bouton Sourd ou « Mode sourd ») : le micro reste fermé.'
    icon = 'microphone-off'
    theme = 'micro'

    def test(self, ctx):
        return bool(ctx.brain.deaf)
