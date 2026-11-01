"""Trigger `start` (Bouton Démarrer) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: start` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class Start(Trigger):
    id = 'start'
    order = 40
    label = 'Bouton Démarrer'
    help = "Le bouton Démarrer du tableau de bord, ou un appui sur le visage de l'écran."
    icon = 'player-play'
    theme = 'systeme'
