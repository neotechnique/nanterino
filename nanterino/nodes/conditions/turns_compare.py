"""Condition `turns_compare` (Comparer les tours de parole) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Compare le nombre de tours de parole de la conversation (« Compter un tour de parole ») à un nombre.
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class TurnsCompare(Condition):
    id = 'turns_compare'
    order = 360
    label = 'Comparer les tours de parole'
    help = 'Compare le nombre de tours de parole de la conversation (« Compter un tour de parole ») à un nombre.'
    icon = 'refresh'
    theme = 'conversation'
    args = {'op': Arg('op', 'Opérateur'), 'count': Arg('number', 'Nombre de tours')}

    def test(self, ctx, op, count):
        b = ctx.brain
        return b._compare(b.turns, op, count, 'number')
