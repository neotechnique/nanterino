"""Condition `not_speaking` (Le robot ne parle pas) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Condition


class NotSpeaking(Condition):
    id = 'not_speaking'
    order = 50
    label = 'Le robot ne parle pas'
    help = "Aucun son n'est en cours de lecture."
    icon = 'volume-off'
    theme = 'parole'

    def test(self, ctx):
        return not ctx.brain.out.busy
