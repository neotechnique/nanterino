"""Trigger `off` (Bouton Éteindre) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: off` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class Off(Trigger):
    id = 'off'
    order = 20
    label = 'Bouton Éteindre'
    help = "Le bouton Éteindre est pressé : le robot s'éteint (micro coupé)."
    icon = 'power'
    theme = 'systeme'
