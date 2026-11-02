"""Condition `gaze_is` (Le regard est) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Le regard est réglé sur ce mode (« Régler le regard »).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class GazeIs(Condition):
    id = 'gaze_is'
    order = 410
    label = 'Le regard est'
    help = 'Le regard est réglé sur ce mode (« Régler le regard »).'
    icon = 'eye'
    theme = 'vision'
    args = {'mode': Arg('gazemode', 'Regard')}

    def test(self, ctx, mode):
        return ctx.brain.gaze_mode == mode
