"""Condition `var_true` (Une variable est vraie) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Arg, Condition


class VarTrue(Condition):
    id = 'var_true'
    order = 100
    label = 'Une variable est vraie'
    help = 'Une variable vrai/faux vaut vrai.'
    icon = 'circle-dot'
    theme = 'variables'
    args = {'name': Arg('anyboolvar', 'Variable')}

    def test(self, ctx, name):
        return ctx.brain.var_value(name) is True
