"""Action `set_var` (Changer une variable) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class SetVar(Action):
    id = 'set_var'
    order = 240
    label = 'Changer une variable'
    help = "Donne une nouvelle valeur à une variable (« etat » : change d'état)."
    icon = 'arrow-right'
    theme = 'variables'
    args = {'name': Arg('var', 'Variable'), 'value': Arg('value', 'Valeur')}

    def run(self, ctx, name, value):
        from nanterino import graph as G   # lazy: graph.py imports this package
        b = ctx.brain
        b._set_var(name, G.fit_value(ctx.graph.variables[name], b._resolve(value, ctx.kw)))
