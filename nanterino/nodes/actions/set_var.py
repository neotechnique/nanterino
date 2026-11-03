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
        from nanterino import properties   # lazy: graph.py imports the node packages
        # lot M4: the value (constant, `$x` or a value source) is written through the `variable` set target
        # (type clamp + variable bounds = the former graph.fit_value, then Brain._set_var).
        properties.write("variable", ctx, ctx.brain._resolve(value, ctx.kw), name=name)
