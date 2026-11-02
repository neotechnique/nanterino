"""Condition `is_muted` (Le robot est muet) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Le mode muet est activé (bouton Muet ou « Mode muet »).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Condition


class IsMuted(Condition):
    id = 'is_muted'
    order = 210
    label = 'Le robot est muet'
    help = 'Le mode muet est activé (bouton Muet ou « Mode muet »).'
    icon = 'volume-off'
    theme = 'parole'

    def test(self, ctx):
        return bool(ctx.brain.out.muted)
