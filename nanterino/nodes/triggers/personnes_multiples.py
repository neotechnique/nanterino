"""Trigger `personnes_multiples` (Plusieurs personnes) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: personnes_multiples` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class PersonnesMultiples(Trigger):
    id = 'personnes_multiples'
    order = 170
    label = 'Plusieurs personnes'
    help = 'Au moins 2 visages restent visibles pendant 1 s (posté une fois, ré-armé quand il y en a moins de 2).'
    icon = 'users'
    theme = 'vision'
