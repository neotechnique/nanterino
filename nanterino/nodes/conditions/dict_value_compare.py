"""Condition `dict_value_compare` (Comparer une valeur de dictionnaire) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.helpers import match_key
from nanterino.nodes.base import Arg, Condition


class DictValueCompare(Condition):
    id = 'dict_value_compare'
    order = 180
    label = 'Comparer une valeur de dictionnaire'
    help = "Compare la valeur d'une clé à une valeur (faux si la clé est absente)."
    icon = 'git-branch'
    theme = 'listes'
    args = {'dict': Arg('rdict', 'Dictionnaire'), 'key': Arg('dictkey', 'Clé (ou $utterance)'), 'op': Arg('op', 'Opérateur'), 'value': Arg('value', 'Valeur')}

    def test(self, ctx, dict, key, op, value):  # noqa: A002 (argument names are the graph's)
        b = ctx.brain
        k = match_key(b, ctx.kw, dict, key)
        if k is None:
            return False
        return b._compare(b.lists[dict][k], op, b._resolve(value, ctx.kw), ctx.graph.lists[dict].type)
