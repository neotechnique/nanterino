"""Condition `media_playing` (Un son est en cours) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Un son lancé par « Jouer un son » est en train de jouer.
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Condition


class MediaPlaying(Condition):
    id = 'media_playing'
    order = 190
    label = 'Un son est en cours'
    help = 'Un son lancé par « Jouer un son » est en train de jouer.'
    icon = 'music'
    theme = 'parole'

    def test(self, ctx):
        b = ctx.brain
        return b._media is not None and bool(b.out.busy)
