"""Action `set_expression` (Changer l'expression du visage) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class SetExpression(Action):
    id = 'set_expression'
    order = 210
    label = "Changer l'expression du visage"
    help = "Affiche une expression (content, surpris, réfléchit, triste, neutre) pendant un nombre de secondes, puis revient à l'expression de l'état."
    icon = 'mood-smile'
    theme = 'vision'
    args = {'name': Arg('expression', 'Expression'), 'seconds': Arg('seconds', 'Durée (secondes)')}

    def run(self, ctx, name, seconds):
        ctx.brain._expression = (name, ctx.brain.now() + float(seconds))
