"""Trigger `barge_in` (Le visiteur coupe la parole) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: barge_in` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class BargeIn(Trigger):
    id = 'barge_in'
    order = 130
    label = 'Le visiteur coupe la parole'
    help = 'Le visiteur parle pendant que le robot répond (interruption activée dans la configuration).'
    icon = 'microphone'
    theme = 'micro'
