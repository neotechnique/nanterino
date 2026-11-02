"""Action `list_add` (Ajouter à une liste) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
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
        # lot M4: through the `list_item` set target (item type clamp, then the list mode's push like list_push)
        from nanterino import properties
        before = ctx.brain.list_copy(list)   # lot N1: list_changed when the content changed (listened lists only)
        v = ctx.brain._resolve(value, ctx.kw)
        properties.write("list_item", ctx, v, list=list)
        ctx.brain.list_touched(list, before)
        items = ctx.brain.lists.get(list)
        ctx.brain.list_item_event("list_item_added", list, before, items[-1] if items else v)   # lot N2: the stored item
