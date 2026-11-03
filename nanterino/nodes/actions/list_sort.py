"""Action `list_sort` (Trier une liste) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Producer of list_changed: Brain.list_touched (only for a listened list).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Action, Arg
from nanterino.nodes.helpers import sort_key


class ListSort(Action):
    id = 'list_sort'
    order = 460
    label = 'Trier une liste'
    help = "Range les éléments d'une liste dans l'ordre croissant (nombres, dates, textes sans tenir compte des majuscules) ; « Une liste change » si l'ordre a changé."
    icon = 'arrow-right'
    theme = 'listes'
    args = {'list': Arg('wlist', 'Liste')}

    def run(self, ctx, list):  # noqa: A002 (argument names fixed by the graph vocabulary)
        b = ctx.brain
        before = b.list_copy(list)
        b.lists[list] = sorted(before or [], key=sort_key)
        b.list_touched(list, before)
