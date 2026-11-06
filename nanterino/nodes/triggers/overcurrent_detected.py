"""Trigger `overcurrent_detected` (Un moteur force (surintensité)) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: overcurrent_detected` react to it.
Producer: MotionRuntime._hook (Body `overcurrent`, anti-burst OVERCURRENT_GAP_S per joint).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Trigger


class OvercurrentDetected(Trigger):
    id = 'overcurrent_detected'
    order = 750
    label = 'Un moteur force (surintensité)'
    help = "Le courant d'un moteur dépasse son maximum (blocage, choc) : l'articulation est tenue sur place. Au plus une fois toutes les 2 s par articulation. kw joint."
    icon = 'power'
    theme = 'mouvement'
