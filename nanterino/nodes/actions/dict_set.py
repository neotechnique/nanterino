"""Action `dict_set` (Écrire dans un dictionnaire) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class DictSet(Action):
    id = 'dict_set'
    order = 360
    label = 'Écrire dans un dictionnaire'
    help = "Associe une valeur à une clé d'un dictionnaire (remplace l'ancienne valeur)."
    icon = 'plus'
    theme = 'listes'
    args = {'dict': Arg('wdict', 'Dictionnaire'), 'key': Arg('dictkey', 'Clé'), 'value': Arg('value', 'Valeur')}

    def run(self, ctx, dict, key, value):  # noqa: A002 (argument names fixed by the graph vocabulary)
        from nanterino import graph as G   # lazy: graph.py imports this package
        b = ctx.brain
        k = b._resolve(key, ctx.kw)
        if isinstance(k, str) and k.strip():
            b.lists.setdefault(dict, {})[k.strip()[:G.KEY_MAX]] = b._resolve(value, ctx.kw)
