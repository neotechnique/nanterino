"""Condition `robot_quiet_since` (Le robot se tait depuis) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Secondes depuis que le haut-parleur s'est tu (0 pendant qu'il joue ; depuis le démarrage s'il n'a encore rien joué), comparées à un nombre.
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class RobotQuietSince(Condition):
    id = 'robot_quiet_since'
    order = 530
    label = 'Le robot se tait depuis'
    help = "Secondes depuis que le haut-parleur s'est tu (0 pendant qu'il joue ; depuis le démarrage s'il n'a encore rien joué), comparées à un nombre."
    icon = 'hourglass'
    theme = 'parole'
    args = {'op': Arg('op', 'Opérateur'), 'seconds': Arg('seconds0', 'Secondes')}

    def test(self, ctx, op, seconds):
        b = ctx.brain
        now = b.now()
        quiet = 0.0 if b.out.busy else now - (b._spoke_at if b._spoke_at is not None else b.started_at)
        return b._compare(quiet, op, seconds)
