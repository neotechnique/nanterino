"""Condition `volume_compare` (Comparer le volume) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Compare le volume du haut-parleur (0 à 100) à un nombre.
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Arg, Condition


class VolumeCompare(Condition):
    id = 'volume_compare'
    order = 200
    label = 'Comparer le volume'
    help = 'Compare le volume du haut-parleur (0 à 100) à un nombre.'
    icon = 'volume'
    theme = 'parole'
    args = {'op': Arg('op', 'Opérateur'), 'percent': Arg('number', 'Volume (0 à 100)')}

    def test(self, ctx, op, percent):
        b = ctx.brain
        return b._compare(b.var_value('volume'), op, percent, 'percent')
