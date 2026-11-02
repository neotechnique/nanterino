"""Action `reset_expression` (Revenir à l'expression neutre) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Action


class ResetExpression(Action):
    id = 'reset_expression'
    order = 550
    label = "Revenir à l'expression neutre"
    help = "Arrête l'expression en cours (« Changer l'expression du visage ») : le visage revient tout de suite à neutre ; « L'expression du visage change » si elle a changé."
    icon = 'mood-smile'
    theme = 'vision'
    args = {}

    def run(self, ctx):
        b = ctx.brain
        b._expression = None
        b._expr_tick()   # expression_changed when the visible expression changed
