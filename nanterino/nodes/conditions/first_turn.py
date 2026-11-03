"""Condition `first_turn` (C'est le premier tour de parole) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Aucun tour n'a encore été compté dans cette conversation (variable système tours = 0).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Condition


class FirstTurn(Condition):
    id = 'first_turn'
    order = 350
    label = "C'est le premier tour de parole"
    help = "Aucun tour n'a encore été compté dans cette conversation (variable système tours = 0)."
    icon = 'flag'
    theme = 'conversation'

    def test(self, ctx):
        return ctx.brain.turns == 0
