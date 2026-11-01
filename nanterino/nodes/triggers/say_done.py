"""Trigger `say_done` (Phrase libre terminée) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: say_done` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class SayDone(Trigger):
    id = 'say_done'
    order = 210
    label = 'Phrase libre terminée'
    help = "Le robot a fini de dire la phrase de l'action « Dire un texte » (ou « Dire une phrase au hasard »)."
    icon = 'text-caption'
    theme = 'parole'
