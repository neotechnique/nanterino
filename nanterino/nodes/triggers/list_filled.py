"""Trigger `list_filled` (Une liste devient pleine) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: list_filled` (+ `var:`) react to it.
Producer: Brain.list_touched (list_add, remember_utterance), only for a listened name (subscribe()).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Trigger


class ListFilled(Trigger):
    id = 'list_filled'
    order = 610
    label = 'Une liste devient pleine'
    help = "Une liste qui a un nombre maximal d'éléments (réglage max) vient de l'atteindre ; à combiner avec « Une liste est pleine ». Anti-boucle comme « Une variable change »."
    icon = 'square'
    theme = 'listes'
    args = {'name': Arg('rlist_any', 'Liste')}   # the transition's `var:`

    def editor_args(self, g):
        return [{"name": "name", "type": "list", "list_types": list(g.LIST_TYPES), "list_kinds": ['list'], "writable": False,
                 "label": 'Liste', "help": 'Liste surveillée (avec un maximum) : la chaîne démarre quand elle devient pleine.'}]

    def subscribe(self, graph):
        """Names some enabled `list_filled` transition listens to (the brain posts only their changes)."""
        trs = list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]
        return frozenset(t.var for t in trs if t.enabled and t.on == self.id and t.var)

    def match(self, ctx, event, name):
        return name == ctx.kw.get("name")

    def check(self, parser, where, name, value):
        from nanterino.graph import NOVALUE
        li = parser.lists.get(name) if isinstance(name, str) else None
        if li is None or li.kind != 'list':
            parser.err(where, "`on: list_filled` needs `var:` = a declared list, got %r" % (name,))
        elif not li.maxlen:
            parser.err(where, "`on: list_filled` needs a list with `max:`, got %r" % (name,))
        if value is not NOVALUE:
            parser.err(where, "`on: list_filled` takes no `value:`")
