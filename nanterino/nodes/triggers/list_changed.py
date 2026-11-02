"""Trigger `list_changed` (Une liste change) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by brain.py (see
the producer named below); transitions with `on: list_changed` react to it.
Producer: Brain.list_touched (list actions: add, remove, clear, shuffle, sort, remember).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Arg, Trigger


class ListChanged(Trigger):
    id = 'list_changed'
    order = 340
    label = 'Une liste change'
    help = "Le contenu d'une liste vient de changer (ajout, retrait, vidage, mélange, tri). Anti-boucle comme « Une variable change »."
    icon = 'square'
    theme = 'listes'
    args = {'name': Arg('rlist_any', 'Liste')}   # the transition's `var:`

    def editor_args(self, g):
        return [{"name": "name", "type": "list", "list_types": list(g.LIST_TYPES), "list_kinds": ["list"], "writable": False,
                 "label": "Liste", "help": "Liste surveillée : la chaîne démarre quand son contenu change."}]

    def subscribe(self, graph):
        """Names some enabled `list_changed` transition listens to (the brain posts only their changes)."""
        trs = list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]
        return frozenset(t.var for t in trs if t.enabled and t.on == self.id and t.var)

    def match(self, ctx, event, name):
        return name == ctx.kw.get("name")

    def check(self, parser, where, name, value):
        from nanterino.graph import NOVALUE
        li = parser.lists.get(name) if isinstance(name, str) else None
        if li is None or li.kind != "list":
            parser.err(where, "`on: list_changed` needs `var:` = a declared list, got %r" % (name,))
        if value is not NOVALUE:
            parser.err(where, "`on: list_changed` takes no `value:`")
