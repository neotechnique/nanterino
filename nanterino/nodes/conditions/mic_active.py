"""Condition `mic_active` (Le micro est ouvert) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Condition


class MicActive(Condition):
    id = 'mic_active'
    order = 40
    label = 'Le micro est ouvert'
    help = 'Le micro écoute en ce moment.'
    icon = 'microphone'
    theme = 'micro'

    def test(self, ctx):
        return bool(ctx.brain.mic.active)
