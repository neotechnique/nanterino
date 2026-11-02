"""Condition `face_count_compare` (Comparer le nombre de visages) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Compare le nombre de visages que la caméra voit en ce moment à un nombre.
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class FaceCountCompare(Condition):
    id = 'face_count_compare'
    order = 430
    label = 'Comparer le nombre de visages'
    help = 'Compare le nombre de visages que la caméra voit en ce moment à un nombre.'
    icon = 'users'
    theme = 'vision'
    args = {'op': Arg('op', 'Opérateur'), 'count': Arg('number', 'Nombre de visages')}

    def test(self, ctx, op, count):
        b = ctx.brain
        return b._compare(b.faces, op, count, 'number')
