"""Action `toggle_var` (Inverser une variable) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class ToggleVar(Action):
    id = 'toggle_var'
    order = 260
    label = 'Inverser une variable'
    help = "Une variable vrai/faux passe à l'autre valeur."
    icon = 'refresh'
    theme = 'variables'
    args = {'name': Arg('boolvar', 'Variable')}

    def run(self, ctx, name):
        ctx.brain._set_var(name, not ctx.brain.vars.get(name))
