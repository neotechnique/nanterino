"""Action `list_clear` (Vider une liste) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class ListClear(Action):
    id = 'list_clear'
    order = 290
    label = 'Vider une liste'
    help = "Retire tous les éléments d'une liste."
    icon = 'eraser'
    theme = 'listes'
    args = {'list': Arg('wlist', 'Liste')}

    def run(self, ctx, list):  # noqa: A002 (argument names fixed by the graph vocabulary)
        ctx.brain.lists[list] = []
