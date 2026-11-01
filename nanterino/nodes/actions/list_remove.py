"""Action `list_remove` (Retirer d'une liste) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class ListRemove(Action):
    id = 'list_remove'
    order = 280
    label = "Retirer d'une liste"
    help = "Retire un élément d'une liste (toutes ses occurrences)."
    icon = 'x'
    theme = 'listes'
    args = {'list': Arg('wlist', 'Liste'), 'value': Arg('value', 'Élément')}

    def run(self, ctx, list, value):  # noqa: A002 (argument names fixed by the graph vocabulary)
        b = ctx.brain
        v = b._resolve(value, ctx.kw)
        b.lists[list] = [x for x in b.lists.get(list, []) if x != v]
