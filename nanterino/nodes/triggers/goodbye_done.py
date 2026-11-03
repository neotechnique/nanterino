"""Trigger `goodbye_done` (Au revoir terminé) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: goodbye_done` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class GoodbyeDone(Trigger):
    id = 'goodbye_done'
    order = 90
    label = 'Au revoir terminé'
    help = 'Le robot a fini de dire au revoir.'
    icon = 'door-exit'
    theme = 'conversation'
