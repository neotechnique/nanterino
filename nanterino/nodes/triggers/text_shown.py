"""Trigger `text_shown` (Un texte s'affiche) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by brain.py (see
the producer named below); transitions with `on: text_shown` react to it.
Producer: Brain.show_text.
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Trigger


class TextShown(Trigger):
    id = 'text_shown'
    order = 310
    label = "Un texte s'affiche"
    help = '« Afficher un texte » vient de mettre un texte sous le visage.'
    icon = 'text-caption'
    theme = 'vision'
