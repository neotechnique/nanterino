"""Condition `var_at_bound` (Une variable est à sa limite) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Une variable nombre vaut son minimum ou son maximum (réglages min / max) ; faux si elle n'en a pas.
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class VarAtBound(Condition):
    id = 'var_at_bound'
    order = 610
    label = 'Une variable est à sa limite'
    help = "Une variable nombre vaut son minimum ou son maximum (réglages min / max) ; faux si elle n'en a pas."
    icon = 'circle-dot'
    theme = 'variables'
    args = {'name': Arg('numvar', 'Variable')}

    def test(self, ctx, name):
        v = ctx.graph.variables.get(name)
        cur = ctx.brain.vars.get(name)
        if v is None or isinstance(cur, bool) or not isinstance(cur, (int, float)):
            return False
        return any(lim is not None and cur == lim for lim in (v.vmin, v.vmax))
