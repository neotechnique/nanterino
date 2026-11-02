"""Condition `state_age` (Temps passé dans l'état) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Secondes passées dans l'état actuel, comparées à un nombre.
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class StateAge(Condition):
    id = 'state_age'
    order = 450
    label = "Temps passé dans l'état"
    help = "Secondes passées dans l'état actuel, comparées à un nombre."
    icon = 'clock'
    theme = 'systeme'
    args = {'op': Arg('op', 'Opérateur'), 'seconds': Arg('seconds0', 'Secondes')}

    def test(self, ctx, op, seconds):
        b = ctx.brain
        return b._compare(b.now() - b.since, op, seconds)
