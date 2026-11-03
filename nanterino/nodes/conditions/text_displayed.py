"""Condition `text_displayed` (Un texte est affiché) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Le texte de « Afficher un texte » est encore sous le visage.
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Condition


class TextDisplayed(Condition):
    id = 'text_displayed'
    order = 230
    label = 'Un texte est affiché'
    help = 'Le texte de « Afficher un texte » est encore sous le visage.'
    icon = 'text-caption'
    theme = 'vision'

    def test(self, ctx):
        return ctx.brain.text_displayed()
