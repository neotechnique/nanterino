"""Trigger `motion_interrupted` (Un mouvement est interrompu) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: motion_interrupted` react to it.
Producer: MotionRuntime._hook (Body `interrupted`), _end_seq / _end_base (one per gesture / base move).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Trigger


class MotionInterrupted(Trigger):
    id = 'motion_interrupted'
    order = 710
    label = 'Un mouvement est interrompu'
    help = "Un mouvement n'est pas arrivé au bout : une commande plus récente, un arrêt, un arrêt d'urgence, une surintensité ou un délai dépassé l'a coupé. kw reason = la raison."
    icon = 'x'
    theme = 'mouvement'
