"""Trigger `not_understood` (Parole non comprise) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: not_understood` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class NotUnderstood(Trigger):
    id = 'not_understood'
    order = 150
    label = 'Parole non comprise'
    help = 'Du bruit ou une parole inexploitable a été entendu.'
    icon = 'question-mark'
    theme = 'conversation'
