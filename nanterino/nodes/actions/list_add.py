"""Action `list_add` (Ajouter à une liste) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.helpers import list_push
from nanterino.nodes.base import Action, Arg


class ListAdd(Action):
    id = 'list_add'
    order = 270
    label = 'Ajouter à une liste'
    help = "Ajoute un élément à la fin d'une liste."
    icon = 'plus'
    theme = 'listes'
    args = {'list': Arg('wlist', 'Liste'), 'value': Arg('value', 'Élément')}

    def run(self, ctx, list, value):  # noqa: A002 (argument names fixed by the graph vocabulary)
        list_push(ctx, list, ctx.brain._resolve(value, ctx.kw))
