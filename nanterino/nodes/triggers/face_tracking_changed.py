"""Trigger `face_tracking_changed` (Le suivi du visage change) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: face_tracking_changed` react to it.
Producer: MotionRuntime.set_tracking through Brain._changed (CHANGE_EVENTS).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Trigger


class FaceTrackingChanged(Trigger):
    id = 'face_tracking_changed'
    order = 810
    label = 'Le suivi du visage change'
    help = "Le suivi du visage vient d'être activé ou coupé ; à combiner avec la condition sur le suivi. Anti-boucle comme « Une variable change »."
    icon = 'scan-eye'
    theme = 'mouvement'
