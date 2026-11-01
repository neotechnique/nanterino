"""Condition `barge_in` (L'interruption est activée) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Condition


class BargeIn(Condition):
    id = 'barge_in'
    order = 20
    label = "L'interruption est activée"
    help = 'Réglage « barge_in » : le visiteur peut couper la parole du robot.'
    icon = 'hand-stop'
    theme = 'micro'

    def test(self, ctx):
        return bool(ctx.cfg.get("barge_in"))
