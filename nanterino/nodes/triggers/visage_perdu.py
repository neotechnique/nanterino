"""Trigger `visage_perdu` (Le visage disparaît) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: visage_perdu` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class VisagePerdu(Trigger):
    id = 'visage_perdu'
    order = 60
    label = 'Le visage disparaît'
    help = "Plus aucun visage vu depuis lost_face_s (10 s). Le graphe par défaut n'en a qu'un exemple désactivé."
    icon = 'user-off'
    theme = 'vision'
