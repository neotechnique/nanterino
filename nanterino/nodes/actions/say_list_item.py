"""Action `say_list_item` (Dire l'élément d'une liste) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Producer of list_item_said: Brain._speak_then (the done event of the phrase).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Action, Arg
from nanterino.nodes.helpers import list_index


class SayListItem(Action):
    id = 'say_list_item'
    order = 440
    label = "Dire l'élément d'une liste"
    help = "Dit l'élément d'une liste de textes à une position (1 = le premier, -1 = le dernier ; muet = reste muet), puis « Un élément de liste est dit ». Position absente : rien n'est dit (condition « La position existe dans une liste »)."
    icon = 'volume'
    theme = 'parole'
    args = {'list': Arg('rlist', 'Liste de phrases'), 'index': Arg('number', 'Position (1 = le premier)')}

    def run(self, ctx, list, index):  # noqa: A002 (argument names fixed by the graph vocabulary)
        b = ctx.brain
        items = b.list_items(list)
        i = list_index(items, index)
        item = items[i] if i is not None else None
        if not (isinstance(item, str) and item.strip()):
            # lot L27: list_item_said anyway (ok=False), else a chain waiting for it traps the robot
            b.complete_silently("say_list_item", "list_item_said", "list %s has no text at position %r" % (list, index))
            return
        b._speak_then(item, "list_item_said")
