"""Condition `speaker_level_compare` (Comparer le niveau du haut-parleur) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Compare le niveau sonore joué en ce moment (0 à 100, comme la barre du tableau de bord ; 0 en silence) à un nombre.
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class SpeakerLevelCompare(Condition):
    id = 'speaker_level_compare'
    order = 560
    label = 'Comparer le niveau du haut-parleur'
    help = 'Compare le niveau sonore joué en ce moment (0 à 100, comme la barre du tableau de bord ; 0 en silence) à un nombre.'
    icon = 'volume'
    theme = 'parole'
    args = {'op': Arg('op', 'Opérateur'), 'percent': Arg('number', 'Niveau (0 à 100)')}

    def test(self, ctx, op, percent):
        b = ctx.brain
        level = min(100.0, float(b.out.level) * 100) if b.out.busy else 0.0
        return b._compare(level, op, percent, 'number')
