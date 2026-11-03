"""Trigger `greeting_done` (Salutation terminée) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: greeting_done` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class GreetingDone(Trigger):
    id = 'greeting_done'
    order = 70
    label = 'Salutation terminée'
    help = "Le robot a fini de dire la phrase d'accueil."
    icon = 'hand-move'
    theme = 'conversation'
