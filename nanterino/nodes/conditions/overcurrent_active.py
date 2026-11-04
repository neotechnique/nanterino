"""Condition `overcurrent_active` (Un moteur est en surintensité) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Body.state() joints[].overcurrent.
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Condition


class OvercurrentActive(Condition):
    id = 'overcurrent_active'
    order = 790
    label = 'Un moteur est en surintensité'
    help = "Le courant d'au moins un moteur est encore au-dessus de son maximum (l'articulation est tenue sur place)."
    icon = 'power'
    theme = 'mouvement'

    def test(self, ctx):
        return ctx.brain.motion.overcurrent()
