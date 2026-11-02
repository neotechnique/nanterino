"""Action `dict_remove` (Retirer une clé d'un dictionnaire) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class DictRemove(Action):
    id = 'dict_remove'
    order = 370
    label = "Retirer une clé d'un dictionnaire"
    help = "Retire une clé (et sa valeur) d'un dictionnaire."
    icon = 'x'
    theme = 'listes'
    args = {'dict': Arg('wdict', 'Dictionnaire'), 'key': Arg('dictkey', 'Clé')}

    def run(self, ctx, dict, key):  # noqa: A002 (argument names fixed by the graph vocabulary)
        b = ctx.brain
        k = b._resolve(key, ctx.kw)
        before = b.list_copy(dict)   # lot N1: dict_changed when a key was removed (listened dicts only)
        (b.lists.get(dict) or {}).pop(k, None)
        b.list_touched(dict, before)
