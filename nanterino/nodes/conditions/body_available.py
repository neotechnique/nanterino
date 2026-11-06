"""Condition `body_available` (Le corps peut bouger) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: brain.motion.available() (estop, Body.backend_error, enabled joints).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Condition


class BodyAvailable(Condition):
    id = 'body_available'
    order = 740
    label = 'Le corps peut bouger'
    help = "Le corps accepte des commandes : pas d'arrêt d'urgence, son moteur (simulé ou réel) a démarré sans erreur et au moins une articulation est activée."
    icon = 'circle-dot'
    theme = 'mouvement'

    def test(self, ctx):
        return ctx.brain.motion.available()
