"""Action `list_shuffle` (Mélanger une liste) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Producer of list_changed: Brain.list_touched (only for a listened list).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Action, Arg


class ListShuffle(Action):
    id = 'list_shuffle'
    order = 450
    label = 'Mélanger une liste'
    help = "Met les éléments d'une liste dans un ordre au hasard ; « Une liste change » si l'ordre a changé."
    icon = 'refresh'
    theme = 'listes'
    args = {'list': Arg('wlist', 'Liste')}

    def run(self, ctx, list):  # noqa: A002 (argument names fixed by the graph vocabulary)
        b = ctx.brain
        before = b.list_copy(list)
        items = [] if before is None else before[:]
        b.rng.shuffle(items)   # the brain's Random: the simulator seeds it (deterministic traces)
        b.lists[list] = items
        b.list_touched(list, before)
