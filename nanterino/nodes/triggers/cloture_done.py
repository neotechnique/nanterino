"""Trigger `cloture_done` (Pause de clôture terminée) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: cloture_done` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class ClotureDone(Trigger):
    id = 'cloture_done'
    order = 100
    label = 'Pause de clôture terminée'
    help = "Le délai programmé après l'au revoir est écoulé (action « Programmer un événement »)."
    icon = 'clock'
    theme = 'evenements'
