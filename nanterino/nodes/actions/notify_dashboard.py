"""Action `notify_dashboard` (Prévenir le tableau de bord) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Producer of the pending list read by GET /api/notifications; the click posts notification_clicked.
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Action, Arg


class NotifyDashboard(Action):
    id = 'notify_dashboard'
    order = 490
    label = 'Prévenir le tableau de bord'
    help = "Ajoute une notification au tableau de bord (et à l'application) ; elle reste en attente jusqu'au clic, qui lance « Une notification est cliquée »."
    icon = 'bell'
    theme = 'systeme'
    args = {'text': Arg('text', 'Message'), 'level': Arg('loglevel', 'Niveau')}

    def run(self, ctx, text, level):
        ctx.brain.notify(text, level)
