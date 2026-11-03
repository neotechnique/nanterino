"""Trigger `fermeture` (Fermeture) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: fermeture` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class Fermeture(Trigger):
    id = 'fermeture'
    order = 190
    label = 'Fermeture'
    help = "L'heure de fermeture de la configuration `opening_hours` vient de passer (jamais si les horaires sont vides)."
    icon = 'lock'
    theme = 'temps'
