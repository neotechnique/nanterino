"""Condition `conversation_active` (Une conversation est en cours) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Le robot est dans un état de conversation (ni en veille ni éteint).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Condition


class ConversationActive(Condition):
    id = 'conversation_active'
    order = 330
    label = 'Une conversation est en cours'
    help = 'Le robot est dans un état de conversation (ni en veille ni éteint).'
    icon = 'users'
    theme = 'conversation'

    def test(self, ctx):
        from nanterino import brain as brain_mod   # lazy: brain.py imports graph.py, which imports this package
        return ctx.brain.state not in (brain_mod.VEILLE, brain_mod.ETEINT)
