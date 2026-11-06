"""Trigger `estop_released` (L'arrêt d'urgence est réarmé) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: estop_released` react to it.
Producer: MotionRuntime._hook (Body `estop_reset`).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Trigger


class EstopReleased(Trigger):
    id = 'estop_released'
    order = 770
    label = "L'arrêt d'urgence est réarmé"
    help = "Quelqu'un a réarmé l'arrêt d'urgence (bouton « Réarmer ») : les commandes sont de nouveau acceptées."
    icon = 'lock-open'
    theme = 'mouvement'
