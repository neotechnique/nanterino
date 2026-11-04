"""Condition `gesture_playing` (Un geste est en cours) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: brain.motion.seq.
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Condition


class GesturePlaying(Condition):
    id = 'gesture_playing'
    order = 720
    label = 'Un geste est en cours'
    help = "Un geste de la bibliothèque est en train d'être joué (hocher, secouer ou un geste nommé)."
    icon = 'hand-move'
    theme = 'mouvement'

    def test(self, ctx):
        return ctx.brain.motion.seq is not None
