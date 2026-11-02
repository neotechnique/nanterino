"""Condition `utterance_length` (Longueur de la phrase du visiteur) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Compare le nombre de mots de la phrase du visiteur à un nombre (0 si rien n'a été entendu).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class UtteranceLength(Condition):
    id = 'utterance_length'
    order = 390
    label = 'Longueur de la phrase du visiteur'
    help = "Compare le nombre de mots de la phrase du visiteur à un nombre (0 si rien n'a été entendu)."
    icon = 'text-caption'
    theme = 'conversation'
    args = {'op': Arg('op', 'Opérateur'), 'count': Arg('number', 'Nombre de mots')}

    def test(self, ctx, op, count):
        b = ctx.brain
        said = b._resolve('$utterance', ctx.kw)
        return b._compare(len(said.split()) if isinstance(said, str) else 0, op, count, 'number')
