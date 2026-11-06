"""Trigger `motion_stopped` (Les mouvements sont arrêtés) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: motion_stopped` react to it.
Producer: MotionRuntime._hook (Body `stop`).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Trigger


class MotionStopped(Trigger):
    id = 'motion_stopped'
    order = 720
    label = 'Les mouvements sont arrêtés'
    help = "Un arrêt simple vient d'avoir lieu (graphe ou tableau de bord) : les articulations tiennent leur position. kw source."
    icon = 'hand-stop'
    theme = 'mouvement'
