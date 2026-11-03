"""Action `add_var` (Ajouter à une variable) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class AddVar(Action):
    id = 'add_var'
    order = 250
    label = 'Ajouter à une variable'
    help = 'Ajoute un nombre (négatif pour retirer) à une variable nombre ou durée.'
    icon = 'plus'
    theme = 'variables'
    args = {'name': Arg('numvar', 'Variable'), 'delta': Arg('number', 'Quantité')}

    def run(self, ctx, name, delta):
        from nanterino import graph as G   # lazy: graph.py imports this package
        b = ctx.brain
        v = b.vars.get(name, 0) + delta
        if ctx.graph.variables[name].type == "duration":
            v = max(0, v)   # a duration never goes negative
        b._set_var(name, G.fit_value(ctx.graph.variables[name], v))   # integer / percent / min / max
