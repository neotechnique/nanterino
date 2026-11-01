"""Trigger `hush` (« Tais-toi ») - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: hush` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class Hush(Trigger):
    id = 'hush'
    order = 120
    label = '« Tais-toi »'
    help = 'Le visiteur ou le bouton demande au robot de se taire.'
    icon = 'volume-off'
    theme = 'parole'
