"""Trigger `motion_refused` (Une commande de mouvement est refusée) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: motion_refused` react to it.
Producer: MotionRuntime._hook (Body `refused`, anti-burst REFUSED_GAP_S).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Trigger


class MotionRefused(Trigger):
    id = 'motion_refused'
    order = 730
    label = 'Une commande de mouvement est refusée'
    help = "Le corps a refusé une commande, par exemple pendant un arrêt d'urgence. Au plus une fois par seconde."
    icon = 'lock'
    theme = 'mouvement'
