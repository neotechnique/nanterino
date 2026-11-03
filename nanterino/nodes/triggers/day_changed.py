"""Trigger `day_changed` (Un nouveau jour commence) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: day_changed` react to it.
Producer: Brain._clock_tick (sensor period, wall clock).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class DayChanged(Trigger):
    id = 'day_changed'
    order = 660
    label = 'Un nouveau jour commence'
    help = 'Minuit est passé : un nouveau jour commence (kw value = le jour : lun, mar ... dim ; le nombre de visiteurs du jour repart de zéro).'
    icon = 'calendar-time'
    theme = 'temps'
