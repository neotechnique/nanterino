"""Trigger `hour_changed` (Une nouvelle heure commence) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: hour_changed` react to it.
Producer: Brain._clock_tick (sensor period, wall clock).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class HourChanged(Trigger):
    id = 'hour_changed'
    order = 650
    label = 'Une nouvelle heure commence'
    help = "L'horloge du robot passe à l'heure suivante (10:00, 11:00 ...) ; kw value = l'heure (0 à 23). Vérifié chaque seconde."
    icon = 'clock'
    theme = 'temps'
