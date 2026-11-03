"""Condition `month_compare` (Comparer le mois) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Compare le mois en cours (1 = janvier ... 12 = décembre) à un nombre.
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class MonthCompare(Condition):
    id = 'month_compare'
    order = 470
    label = 'Comparer le mois'
    help = 'Compare le mois en cours (1 = janvier ... 12 = décembre) à un nombre.'
    icon = 'calendar-time'
    theme = 'temps'
    args = {'op': Arg('op', 'Opérateur'), 'count': Arg('number', 'Mois (1 à 12)')}

    def test(self, ctx, op, count):
        b = ctx.brain
        return b._compare(b._wall_dt().month, op, count, 'number')
