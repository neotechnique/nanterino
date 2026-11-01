"""Trigger `on` (Bouton Allumer) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: on` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class On(Trigger):
    id = 'on'
    order = 30
    label = 'Bouton Allumer'
    help = "Le bouton Allumer est pressé : le robot sort de l'état éteint."
    icon = 'power'
    theme = 'systeme'
