"""Condition `var_compare` (Comparer une variable) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Arg, Condition


class VarCompare(Condition):
    id = 'var_compare'
    order = 90
    label = 'Comparer une variable'
    help = 'Compare une variable à une valeur (=, ≠ ; <, ≤, >, ≥ pour les nombres et durées).'
    icon = 'git-branch'
    theme = 'variables'
    args = {'name': Arg('anyvar', 'Variable'), 'op': Arg('op', 'Opérateur'), 'value': Arg('value', 'Valeur')}

    def test(self, ctx, name, op, value):
        b = ctx.brain
        return b._compare(b.var_value(name), op, b._resolve(value, ctx.kw), b._var_type(name))
