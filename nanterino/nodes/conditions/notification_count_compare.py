"""Condition `notification_count_compare` (Compter les notifications) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Compare le nombre de notifications du tableau de bord qui attendent un clic à un nombre.
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class NotificationCountCompare(Condition):
    id = 'notification_count_compare'
    order = 650
    label = 'Compter les notifications'
    help = 'Compare le nombre de notifications du tableau de bord qui attendent un clic à un nombre.'
    icon = 'bell'
    theme = 'systeme'
    args = {'op': Arg('op', 'Opérateur'), 'count': Arg('number', 'Nombre')}

    def test(self, ctx, op, count):
        return ctx.brain._compare(len(ctx.brain.notifications_view()), op, count, 'number')
