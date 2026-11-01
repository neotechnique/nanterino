"""Trigger `stop` (Bouton Stop) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: stop` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class Stop(Trigger):
    id = 'stop'
    order = 10
    label = 'Bouton Stop'
    help = 'Le bouton Stop du tableau de bord est pressé : se taire et revenir en veille.'
    icon = 'hand-stop'
    theme = 'systeme'
