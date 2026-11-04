"""Condition `face_tracking_on` (Le suivi du visage est actif) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: brain.motion.tracking.
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Condition


class FaceTrackingOn(Condition):
    id = 'face_tracking_on'
    order = 800
    label = 'Le suivi du visage est actif'
    help = 'Le suivi du visage par la tête est activé (même sans caméra, où il ne fait rien).'
    icon = 'scan-eye'
    theme = 'mouvement'

    def test(self, ctx):
        return bool(ctx.brain.motion.tracking)
