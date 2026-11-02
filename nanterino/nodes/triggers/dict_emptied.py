"""Trigger `dict_emptied` (Un dictionnaire devient vide) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: dict_emptied` (+ `var:`) react to it.
Producer: Brain.list_touched (dict_clear, dict_remove), only for a listened name (subscribe()).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Trigger


class DictEmptied(Trigger):
    id = 'dict_emptied'
    order = 640
    label = 'Un dictionnaire devient vide'
    help = "La dernière clé d'un dictionnaire vient de partir (« Vider un dictionnaire », « Retirer une clé d'un dictionnaire ») ; à combiner avec « Un dictionnaire est vide ». Anti-boucle comme « Une variable change »."
    icon = 'eraser'
    theme = 'listes'
    args = {'name': Arg('rdict', 'Dictionnaire')}   # the transition's `var:`

    def editor_args(self, g):
        return [{"name": "name", "type": "list", "list_types": list(g.LIST_TYPES), "list_kinds": ['dict'], "writable": False,
                 "label": 'Dictionnaire', "help": 'Dictionnaire surveillé : la chaîne démarre quand il devient vide.'}]

    def subscribe(self, graph):
        """Names some enabled `dict_emptied` transition listens to (the brain posts only their changes)."""
        trs = list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]
        return frozenset(t.var for t in trs if t.enabled and t.on == self.id and t.var)

    def match(self, ctx, event, name):
        return name == ctx.kw.get("name")

    def check(self, parser, where, name, value):
        from nanterino.graph import NOVALUE
        li = parser.lists.get(name) if isinstance(name, str) else None
        if li is None or li.kind != 'dict':
            parser.err(where, "`on: dict_emptied` needs `var:` = a declared dictionary, got %r" % (name,))
        if value is not NOVALUE:
            parser.err(where, "`on: dict_emptied` takes no `value:`")
