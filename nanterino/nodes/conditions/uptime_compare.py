"""Condition `uptime_compare` (Temps depuis le démarrage) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Secondes depuis le démarrage du robot (du programme, pas de l'ordinateur), comparées à un nombre.
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class UptimeCompare(Condition):
    id = 'uptime_compare'
    order = 640
    label = 'Temps depuis le démarrage'
    help = "Secondes depuis le démarrage du robot (du programme, pas de l'ordinateur), comparées à un nombre."
    icon = 'power'
    theme = 'systeme'
    args = {'op': Arg('op', 'Opérateur'), 'seconds': Arg('seconds0', 'Secondes')}

    def test(self, ctx, op, seconds):
        return ctx.brain._compare(ctx.brain.now() - ctx.brain.started_at, op, seconds)
