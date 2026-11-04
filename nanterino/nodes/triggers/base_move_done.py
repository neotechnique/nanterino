"""Trigger `base_move_done` (Le déplacement de la base est terminé) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: base_move_done` react to it.
Producer: MotionRuntime._end_base (completed move or turn).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Trigger


class BaseMoveDone(Trigger):
    id = 'base_move_done'
    order = 800
    label = 'Le déplacement de la base est terminé'
    help = "La base a fini d'avancer, de reculer ou de tourner (odométrie des roues). kw move = move ou turn, requested, done (distance en m ou angle en degrés réellement parcourus)."
    icon = 'arrow-right'
    theme = 'mouvement'
