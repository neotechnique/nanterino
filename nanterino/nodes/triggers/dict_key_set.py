"""Trigger `dict_key_set` (Une clé est écrite) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: dict_key_set` (+ `var:`) react to it.
Producer: Brain.dict_key_events (dict_set), only for a listened name (subscribe()).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Trigger


class DictKeySet(Trigger):
    id = 'dict_key_set'
    order = 620
    label = 'Une clé est écrite'
    help = "« Écrire dans un dictionnaire » vient d'ajouter une clé ou de changer sa valeur (kw value = la clé). Anti-boucle comme « Une variable change »."
    icon = 'plus'
    theme = 'listes'
    args = {'name': Arg('rdict', 'Dictionnaire')}   # the transition's `var:`

    def editor_args(self, g):
        return [{"name": "name", "type": "list", "list_types": list(g.LIST_TYPES), "list_kinds": ['dict'], "writable": False,
                 "label": 'Dictionnaire', "help": 'Dictionnaire surveillé : la chaîne démarre quand une clé y est écrite.'}]

    def subscribe(self, graph):
        """Names some enabled `dict_key_set` transition listens to (the brain posts only their changes)."""
        trs = list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]
        return frozenset(t.var for t in trs if t.enabled and t.on == self.id and t.var)

    def match(self, ctx, event, name):
        return name == ctx.kw.get("name")

    def check(self, parser, where, name, value):
        from nanterino.graph import NOVALUE
        li = parser.lists.get(name) if isinstance(name, str) else None
        if li is None or li.kind != 'dict':
            parser.err(where, "`on: dict_key_set` needs `var:` = a declared dictionary, got %r" % (name,))
        if value is not NOVALUE:
            parser.err(where, "`on: dict_key_set` takes no `value:`")
