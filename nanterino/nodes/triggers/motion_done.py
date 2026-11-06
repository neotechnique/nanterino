"""Trigger `motion_done` (Un mouvement est terminé) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: motion_done` react to it.
Producer: MotionRuntime._hook (Body `arrived` of a non-owned command), _end_seq, _end_base.
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Trigger


class MotionDone(Trigger):
    id = 'motion_done'
    order = 700
    label = 'Un mouvement est terminé'
    help = 'Une commande de mouvement est arrivée au bout : tête, bras, pose, geste complet ou déplacement de la base (du graphe ou du tableau de bord). kw what = commande, pose, geste ou base.'
    icon = 'flag'
    theme = 'mouvement'
