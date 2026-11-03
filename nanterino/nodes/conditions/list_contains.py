"""Condition `list_contains` (Une liste contient) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Arg, Condition


class ListContains(Condition):
    id = 'list_contains'
    order = 110
    label = 'Une liste contient'
    help = 'La liste contient la valeur ; avec « $utterance », un élément de la liste est contenu dans la phrase entendue.'
    icon = 'eye'
    theme = 'listes'
    args = {'list': Arg('rlist_any', 'Liste'), 'value': Arg('listvalue', 'Valeur (ou $utterance)')}

    def test(self, ctx, list, value):  # noqa: A002 (argument names are the graph's)
        b = ctx.brain
        items = b.list_items(list)
        if value == "$utterance":   # an item of the list appears in the sentence (like the intent words)
            text = str(b._resolve(value, ctx.kw) or "").lower()
            return any(str(x).lower() in text for x in items if str(x).strip())
        return b._resolve(value, ctx.kw) in items
