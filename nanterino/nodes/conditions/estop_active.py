"""Condition `estop_active` (L'arrêt d'urgence est actif) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: brain.body.estop["active"].
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Condition


class EstopActive(Condition):
    id = 'estop_active'
    order = 730
    label = "L'arrêt d'urgence est actif"
    help = "L'arrêt d'urgence est verrouillé : toute commande de mouvement est refusée jusqu'au réarmement."
    icon = 'lock'
    theme = 'mouvement'

    def test(self, ctx):
        return bool(ctx.brain.body.estop["active"])
