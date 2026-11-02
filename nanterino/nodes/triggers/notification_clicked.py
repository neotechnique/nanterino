"""Trigger `notification_clicked` (Une notification est cliquée) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by brain.py (see
the producer named below); transitions with `on: notification_clicked` react to it.
Producer: Brain.click_notification (POST /api/notifications/click).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Trigger


class NotificationClicked(Trigger):
    id = 'notification_clicked'
    order = 370
    label = 'Une notification est cliquée'
    help = "Quelqu'un a cliqué une notification du tableau de bord (ou de l'application) envoyée par « Prévenir le tableau de bord »."
    icon = 'bell'
    theme = 'systeme'
