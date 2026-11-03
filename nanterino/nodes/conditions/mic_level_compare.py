"""Condition `mic_level_compare` (Comparer le niveau du micro) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Compare le niveau sonore entendu par le micro (0 à 100, comme la barre du tableau de bord ; 0 micro fermé) à un nombre.
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class MicLevelCompare(Condition):
    id = 'mic_level_compare'
    order = 490
    label = 'Comparer le niveau du micro'
    help = 'Compare le niveau sonore entendu par le micro (0 à 100, comme la barre du tableau de bord ; 0 micro fermé) à un nombre.'
    icon = 'microphone'
    theme = 'micro'
    args = {'op': Arg('op', 'Opérateur'), 'percent': Arg('number', 'Niveau (0 à 100)')}

    def test(self, ctx, op, percent):
        b = ctx.brain
        level = min(100.0, float(b.mic.level) * 100) if b.mic.active else 0.0
        return b._compare(level, op, percent, 'number')
