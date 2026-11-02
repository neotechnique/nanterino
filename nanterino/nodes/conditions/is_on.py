"""Condition `is_on` (Le robot est allumé) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Le robot n'est pas éteint (bouton Éteindre / Allumer).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Condition


class IsOn(Condition):
    id = 'is_on'
    order = 440
    label = 'Le robot est allumé'
    help = "Le robot n'est pas éteint (bouton Éteindre / Allumer)."
    icon = 'power'
    theme = 'systeme'

    def test(self, ctx):
        from nanterino import brain as brain_mod   # lazy: see conversation_active
        return ctx.brain.state != brain_mod.ETEINT
