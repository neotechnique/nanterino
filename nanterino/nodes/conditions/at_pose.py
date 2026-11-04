"""Condition `at_pose` (Le robot est dans une pose) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: brain.motion.at_pose (live logical positions of Body.state).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Arg, Condition


class AtPose(Condition):
    id = 'at_pose'
    order = 710
    label = 'Le robot est dans une pose'
    help = 'Chaque articulation de la pose est à moins de la tolérance (en degrés) de sa valeur ; une valeur hors calibration compte à sa limite.'
    icon = 'flag'
    theme = 'mouvement'
    args = {'pose': Arg('pose', 'Pose'), 'tolerance': Arg('number', 'Tolérance (degrés)')}

    def test(self, ctx, pose, tolerance):
        return ctx.brain.motion.at_pose(pose, tolerance)
