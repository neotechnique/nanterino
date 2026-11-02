"""Condition `conversation_duration` (Durée de la conversation) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Secondes écoulées depuis le début de la conversation, comparées à un nombre (faux hors conversation).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class ConversationDuration(Condition):
    id = 'conversation_duration'
    order = 340
    label = 'Durée de la conversation'
    help = 'Secondes écoulées depuis le début de la conversation, comparées à un nombre (faux hors conversation).'
    icon = 'hourglass'
    theme = 'conversation'
    args = {'op': Arg('op', 'Opérateur'), 'seconds': Arg('seconds0', 'Secondes')}

    def test(self, ctx, op, seconds):
        b = ctx.brain
        age = b.conversation_age()
        return age is not None and b._compare(age, op, seconds)
