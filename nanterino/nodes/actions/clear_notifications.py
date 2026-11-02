"""Action `clear_notifications` (Effacer les notifications) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Action


class ClearNotifications(Action):
    id = 'clear_notifications'
    order = 620
    label = 'Effacer les notifications'
    help = 'Retire toutes les notifications du tableau de bord qui attendent un clic (sans « Une notification est cliquée »).'
    icon = 'bell'
    theme = 'systeme'
    args = {}

    def run(self, ctx):
        b = ctx.brain
        with b._notif_lock:
            b.notifications.clear()
