"""Trigger `text_cleared` (Le texte affiché disparaît) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by brain.py (see
the producer named below); transitions with `on: text_cleared` react to it.
Producer: Brain._text_tick (heartbeat).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Trigger


class TextCleared(Trigger):
    id = 'text_cleared'
    order = 320
    label = 'Le texte affiché disparaît'
    help = "Le texte de « Afficher un texte » n'est plus affiché (durée écoulée ou remplacé par une parole)."
    icon = 'text-caption'
    theme = 'vision'
