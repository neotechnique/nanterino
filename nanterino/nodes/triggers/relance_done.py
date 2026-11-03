"""Trigger `relance_done` (Relance terminée) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: relance_done` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class RelanceDone(Trigger):
    id = 'relance_done'
    order = 80
    label = 'Relance terminée'
    help = 'Le robot a fini de dire la phrase de relance (ou de demande de répétition).'
    icon = 'refresh'
    theme = 'conversation'
