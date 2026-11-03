"""Condition `notification_pending` (Une notification attend) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Une notification de « Prévenir le tableau de bord » n'a pas encore été cliquée.
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Condition


class NotificationPending(Condition):
    id = 'notification_pending'
    order = 300
    label = 'Une notification attend'
    help = "Une notification de « Prévenir le tableau de bord » n'a pas encore été cliquée."
    icon = 'bell'
    theme = 'systeme'

    def test(self, ctx):
        return bool(ctx.brain.notifications_view())
