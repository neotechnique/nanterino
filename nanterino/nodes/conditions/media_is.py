"""Condition `media_is` (Le son en cours est) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: « Jouer un son » joue ce fichier en ce moment.
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class MediaIs(Condition):
    id = 'media_is'
    order = 540
    label = 'Le son en cours est'
    help = '« Jouer un son » joue ce fichier en ce moment.'
    icon = 'music'
    theme = 'parole'
    args = {'file': Arg('media', 'Fichier son')}

    def test(self, ctx, file):
        return ctx.brain._media is not None and ctx.brain._media == file
