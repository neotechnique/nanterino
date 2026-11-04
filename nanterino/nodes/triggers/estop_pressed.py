"""Trigger `estop_pressed` (L'arrêt d'urgence est déclenché) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: estop_pressed` react to it.
Producer: MotionRuntime._hook (Body `estop`).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Trigger


class EstopPressed(Trigger):
    id = 'estop_pressed'
    order = 760
    label = "L'arrêt d'urgence est déclenché"
    help = "L'arrêt d'urgence vient d'être déclenché (tableau de bord, API ou graphe) : tout est arrêté et verrouillé. kw source."
    icon = 'lock'
    theme = 'mouvement'
