"""Trigger `list_emptied` (Une liste devient vide) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: list_emptied` (+ `var:`) react to it.
Producer: Brain.list_touched (list_clear, list_remove), only for a listened name (subscribe()).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Trigger


class ListEmptied(Trigger):
    id = 'list_emptied'
    order = 600
    label = 'Une liste devient vide'
    help = "Le dernier élément d'une liste vient de partir (« Vider une liste », « Retirer d'une liste ») ; à combiner avec « Une liste est vide ». Anti-boucle comme « Une variable change »."
    icon = 'eraser'
    theme = 'listes'
    args = {'name': Arg('rlist_any', 'Liste')}   # the transition's `var:`

    def editor_args(self, g):
        return [{"name": "name", "type": "list", "list_types": list(g.LIST_TYPES), "list_kinds": ['list'], "writable": False,
                 "label": 'Liste', "help": 'Liste surveillée : la chaîne démarre quand elle devient vide.'}]

    def subscribe(self, graph):
        """Names some enabled `list_emptied` transition listens to (the brain posts only their changes)."""
        trs = list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]
        return frozenset(t.var for t in trs if t.enabled and t.on == self.id and t.var)

    def match(self, ctx, event, name):
        return name == ctx.kw.get("name")

    def check(self, parser, where, name, value):
        from nanterino.graph import NOVALUE
        li = parser.lists.get(name) if isinstance(name, str) else None
        if li is None or li.kind != 'list':
            parser.err(where, "`on: list_emptied` needs `var:` = a declared list, got %r" % (name,))
        if value is not NOVALUE:
            parser.err(where, "`on: list_emptied` takes no `value:`")
