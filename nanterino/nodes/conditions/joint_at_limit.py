"""Condition `joint_at_limit` (Une articulation est en butée) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: brain.motion.at_limit(group) (clamp events of the Body + live positions / targets).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Arg, Condition


class JointAtLimit(Condition):
    id = 'joint_at_limit'
    order = 780
    label = 'Une articulation est en butée'
    help = 'Une articulation de la partie choisie a reçu une consigne au-delà de sa calibration et se trouve à cette limite, mini ou maxi (à 0,5 degré près ou à sa zone morte). Une articulation simplement envoyée à sa limite (un coude tendu à 0) ne compte pas.'
    icon = 'square'
    theme = 'mouvement'
    args = {'group': Arg('bodygroup', 'Partie du corps')}

    def test(self, ctx, group):
        return ctx.brain.motion.at_limit(group)
