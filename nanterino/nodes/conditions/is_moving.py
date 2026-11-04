"""Condition `is_moving` (Le robot bouge) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: brain.motion.moving(group) (Body.moving + gesture / base in progress).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Arg, Condition


class IsMoving(Condition):
    id = 'is_moving'
    order = 700
    label = 'Le robot bouge'
    help = 'Une partie du corps est en mouvement : une commande pas encore arrivée, un geste ou un déplacement de la base en cours.'
    icon = 'hand-move'
    theme = 'mouvement'
    args = {'group': Arg('bodygroup', 'Partie du corps')}

    def test(self, ctx, group):
        return ctx.brain.motion.moving(group)
