"""Condition `dict_has` (Un dictionnaire a la clé) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.helpers import match_key
from nanterino.nodes.base import Arg, Condition


class DictHas(Condition):
    id = 'dict_has'
    order = 170
    label = 'Un dictionnaire a la clé'
    help = 'Le dictionnaire contient la clé ; avec « $utterance », une de ses clés est contenue dans la phrase entendue.'
    icon = 'eye'
    theme = 'listes'
    args = {'dict': Arg('rdict', 'Dictionnaire'), 'key': Arg('dictkey', 'Clé (ou $utterance)')}

    def test(self, ctx, dict, key):  # noqa: A002 (argument names are the graph's)
        return match_key(ctx.brain, ctx.kw, dict, key) is not None
