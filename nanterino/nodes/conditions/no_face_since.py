"""Condition `no_face_since` (Aucun visage depuis) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Secondes depuis que la caméra ne voit plus de visage (0 quand un visage est visible ; depuis le démarrage si aucun n'a été vu), comparées à un nombre.
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class NoFaceSince(Condition):
    id = 'no_face_since'
    order = 590
    label = 'Aucun visage depuis'
    help = "Secondes depuis que la caméra ne voit plus de visage (0 quand un visage est visible ; depuis le démarrage si aucun n'a été vu), comparées à un nombre."
    icon = 'user-off'
    theme = 'vision'
    args = {'op': Arg('op', 'Opérateur'), 'seconds': Arg('seconds0', 'Secondes')}

    def test(self, ctx, op, seconds):
        b = ctx.brain
        since = b._faces_zero_since
        gone = 0.0 if b.faces > 0 or since is None else b.now() - since
        return b._compare(gone, op, seconds)
