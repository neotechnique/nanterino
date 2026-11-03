"""Trigger `visage` (Un visage apparaît) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: visage` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class Visage(Trigger):
    id = 'visage'
    order = 50
    label = 'Un visage apparaît'
    help = "La caméra voit un visage alors qu'il n'y en avait plus."
    icon = 'scan-eye'
    theme = 'vision'
