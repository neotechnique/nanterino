"""Trigger `utterance` (Phrase du visiteur) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain posts this event (engine-internal:
never offered by the editor).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Trigger


class Utterance(Trigger):
    id = 'utterance'
    order = 240
    label = 'Phrase du visiteur'
    help = 'Interne : une phrase transcrite, classée en événement intent.*.'
    icon = 'microphone'
    theme = 'micro'
    internal = True
