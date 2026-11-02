"""Action `dict_clear` (Vider un dictionnaire) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Producer of dict_changed: Brain.list_touched (only for a listened dictionary).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Action, Arg


class DictClear(Action):
    id = 'dict_clear'
    order = 470
    label = 'Vider un dictionnaire'
    help = "Retire toutes les clés d'un dictionnaire ; « Un dictionnaire change » s'il n'était pas vide."
    icon = 'eraser'
    theme = 'listes'
    args = {'dict': Arg('wdict', 'Dictionnaire')}

    def run(self, ctx, dict):  # noqa: A002 (argument names fixed by the graph vocabulary)
        b = ctx.brain
        before = b.list_copy(dict)
        b.lists[dict] = {}
        b.list_touched(dict, before)
