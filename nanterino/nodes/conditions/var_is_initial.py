"""Condition `var_is_initial` (Une variable a sa valeur de départ) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: La variable a encore la valeur écrite dans le graphe (jamais changée, ou remise à sa valeur de départ).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class VarIsInitial(Condition):
    id = 'var_is_initial'
    order = 600
    label = 'Une variable a sa valeur de départ'
    help = 'La variable a encore la valeur écrite dans le graphe (jamais changée, ou remise à sa valeur de départ).'
    icon = 'circle-dot'
    theme = 'variables'
    args = {'name': Arg('var', 'Variable')}

    def test(self, ctx, name):
        v = ctx.graph.variables.get(name)
        cur = ctx.brain.vars.get(name)
        return v is not None and cur == v.value and type(cur) is type(v.value)
