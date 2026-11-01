"""Trigger `tick` (Battement de coeur) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain posts this event (engine-internal:
never offered by the editor).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class Tick(Trigger):
    id = 'tick'
    order = 250
    label = 'Battement de coeur'
    help = 'Interne : le battement de coeur (10 Hz) qui fait avancer les délais.'
    icon = 'clock'
    theme = 'temps'
    internal = True
