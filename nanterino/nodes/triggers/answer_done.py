"""Trigger `answer_done` (Réponse terminée) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: answer_done` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class AnswerDone(Trigger):
    id = 'answer_done'
    order = 110
    label = 'Réponse terminée'
    help = 'Le robot a fini de répondre (ou de chanter).'
    icon = 'message'
    theme = 'conversation'
