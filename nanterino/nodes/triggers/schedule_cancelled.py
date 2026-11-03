"""Trigger `schedule_cancelled` (Un événement programmé est annulé) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: schedule_cancelled` react to it.
Producer: schedule_cancel action (Brain._changed).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class ScheduleCancelled(Trigger):
    id = 'schedule_cancelled'
    order = 670
    label = 'Un événement programmé est annulé'
    help = "« Annuler un événement programmé » vient de retirer un événement qui attendait (kw value = l'événement). Anti-boucle comme « Une variable change »."
    icon = 'clock'
    theme = 'temps'
