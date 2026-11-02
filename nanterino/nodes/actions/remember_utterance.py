"""Action `remember_utterance` (Retenir la phrase du visiteur) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.helpers import list_push
from nanterino.nodes.base import Action, Arg


class RememberUtterance(Action):
    id = 'remember_utterance'
    order = 350
    label = 'Retenir la phrase du visiteur'
    help = 'Ajoute la dernière phrase du visiteur à une liste de textes (en mode historique, seules les N dernières restent).'
    icon = 'microphone'
    theme = 'listes'
    args = {'list': Arg('wtextlist', 'Liste')}

    def run(self, ctx, list):  # noqa: A002 (argument names fixed by the graph vocabulary)
        text = ctx.brain._resolve("$utterance", ctx.kw)
        if isinstance(text, str) and text.strip():
            before = ctx.brain.list_copy(list)   # lot N1: list_changed (listened lists only)
            list_push(ctx, list, text.strip())
            ctx.brain.list_touched(list, before)
            ctx.brain.list_item_event("list_item_added", list, before, text.strip())   # lot N2 (listened lists only)
