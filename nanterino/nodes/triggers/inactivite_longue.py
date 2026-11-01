"""Trigger `inactivite_longue` (Longue inactivité) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: inactivite_longue` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class InactiviteLongue(Trigger):
    id = 'inactivite_longue'
    order = 200
    label = 'Longue inactivité'
    help = "Aucun visage ni parole depuis idle_long_s (300 s) ; posté une seule fois jusqu'à la prochaine activité."
    icon = 'hourglass'
    theme = 'temps'
