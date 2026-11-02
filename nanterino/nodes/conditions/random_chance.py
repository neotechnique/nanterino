"""Condition `random_chance` (Au hasard (pourcentage)) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Vrai avec la chance indiquée : 25 = une fois sur quatre en moyenne (tirage du robot, rejouable dans le simulateur).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Arg, Condition


class RandomChance(Condition):
    id = 'random_chance'
    order = 310
    label = 'Au hasard (pourcentage)'
    help = 'Vrai avec la chance indiquée : 25 = une fois sur quatre en moyenne (tirage du robot, rejouable dans le simulateur).'
    icon = 'question-mark'
    theme = 'variables'
    args = {'percent': Arg('number', 'Chance (%)')}

    def test(self, ctx, percent):
        # draws from the brain's Random (seeded by the simulator): the only state it touches
        return ctx.brain.rng.random() * 100 < percent
