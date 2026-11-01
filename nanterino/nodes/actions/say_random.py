"""Action `say_random` (Dire une phrase au hasard) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.log import log
from nanterino.nodes.base import Action, Arg


class SayRandom(Action):
    id = 'say_random'
    order = 300
    label = 'Dire une phrase au hasard'
    help = "Dit une phrase tirée au hasard dans une liste de textes (voix calculée à l'avance comme « Dire un texte » ; muet = reste muet), puis say_done."
    icon = 'volume'
    theme = 'parole'
    args = {'list': Arg('rlist', 'Liste de phrases')}

    def run(self, ctx, list):  # noqa: A002 (argument names fixed by the graph vocabulary)
        b = ctx.brain
        items = [x for x in b.list_items(list) if isinstance(x, str) and x.strip()]
        if not items:
            log.info("say_random: list %s is empty, nothing said", list)
            return
        li = ctx.graph.lists.get(list)
        pick = b._bag_pick(list, items) if li is not None and li.mode == "shuffle" else b.rng.choice(items)
        b._speak_then(pick, "say_done")
