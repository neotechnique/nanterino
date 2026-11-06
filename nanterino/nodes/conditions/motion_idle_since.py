"""Condition `motion_idle_since` (Le robot est immobile depuis) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: brain.motion.idle_for(seconds) (heartbeat bookkeeping).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Arg, Condition


class MotionIdleSince(Condition):
    id = 'motion_idle_since'
    order = 810
    label = 'Le robot est immobile depuis'
    help = 'Plus rien ne bouge (aucune commande, aucun geste, aucun déplacement) depuis au moins ce nombre de secondes.'
    icon = 'hourglass'
    theme = 'mouvement'
    args = {'seconds': Arg('seconds0', 'Secondes')}

    def test(self, ctx, seconds):
        return ctx.brain.motion.idle_for(seconds)
