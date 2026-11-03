"""Action `reset_var` (Remettre une variable à sa valeur de départ) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Action, Arg


class ResetVar(Action):
    id = 'reset_var'
    order = 580
    label = 'Remettre une variable à sa valeur de départ'
    help = 'La variable reprend la valeur écrite dans le graphe (sa valeur enregistrée est oubliée), comme le bouton du gestionnaire de variables ; « Une variable revient à sa valeur de départ » si elle avait changé.'
    icon = 'refresh'
    theme = 'variables'
    args = {'name': Arg('var', 'Variable')}

    def run(self, ctx, name):
        ctx.brain.reset_var(name, external=False)   # the dashboard's own path (store entry dropped too)
