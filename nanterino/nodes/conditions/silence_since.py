"""Condition `silence_since` (Silence du visiteur depuis) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Secondes depuis la dernière parole entendue (ou depuis « Redémarrer le chrono de silence »), comparées à un nombre.
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class SilenceSince(Condition):
    id = 'silence_since'
    order = 500
    label = 'Silence du visiteur depuis'
    help = 'Secondes depuis la dernière parole entendue (ou depuis « Redémarrer le chrono de silence »), comparées à un nombre.'
    icon = 'hourglass'
    theme = 'micro'
    args = {'op': Arg('op', 'Opérateur'), 'seconds': Arg('seconds0', 'Secondes')}

    def test(self, ctx, op, seconds):
        b = ctx.brain
        return b._compare(b.now() - b.last_speech, op, seconds)
