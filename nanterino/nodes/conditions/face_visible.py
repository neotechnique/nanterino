"""Condition `face_visible` (Un visage est visible) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: La caméra voit au moins un visage en ce moment.
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Condition


class FaceVisible(Condition):
    id = 'face_visible'
    order = 420
    label = 'Un visage est visible'
    help = 'La caméra voit au moins un visage en ce moment.'
    icon = 'scan-eye'
    theme = 'vision'

    def test(self, ctx):
        return ctx.brain.faces > 0
