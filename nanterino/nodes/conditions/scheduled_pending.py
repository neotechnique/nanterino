"""Condition `scheduled_pending` (Un événement programmé attend) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: « Programmer un événement » a programmé cet événement et il n'a pas encore eu lieu (un arrêt l'annule).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class ScheduledPending(Condition):
    id = 'scheduled_pending'
    order = 460
    label = 'Un événement programmé attend'
    help = "« Programmer un événement » a programmé cet événement et il n'a pas encore eu lieu (un arrêt l'annule)."
    icon = 'calendar-time'
    theme = 'temps'
    args = {'event': Arg('event', 'Événement')}

    def test(self, ctx, event):
        return ctx.brain.scheduled_pending(event)
