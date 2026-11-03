"""Trigger `dict_changed` (Un dictionnaire change) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by brain.py (see
the producer named below); transitions with `on: dict_changed` react to it.
Producer: Brain.list_touched (dict_set, dict_remove, dict_clear).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Arg, Trigger


class DictChanged(Trigger):
    id = 'dict_changed'
    order = 350
    label = 'Un dictionnaire change'
    help = "Une clé d'un dictionnaire vient d'être écrite ou retirée, ou il vient d'être vidé. Anti-boucle comme « Une variable change »."
    icon = 'square'
    theme = 'listes'
    args = {'name': Arg('rdict', 'Dictionnaire')}   # the transition's `var:`

    def editor_args(self, g):
        return [{"name": "name", "type": "list", "list_types": list(g.LIST_TYPES), "list_kinds": ["dict"], "writable": False,
                 "label": "Dictionnaire", "help": "Dictionnaire surveillé : la chaîne démarre quand son contenu change."}]

    def subscribe(self, graph):
        """Names some enabled `dict_changed` transition listens to (the brain posts only their changes)."""
        trs = list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]
        return frozenset(t.var for t in trs if t.enabled and t.on == self.id and t.var)

    def match(self, ctx, event, name):
        return name == ctx.kw.get("name")

    def check(self, parser, where, name, value):
        from nanterino.graph import NOVALUE
        li = parser.lists.get(name) if isinstance(name, str) else None
        if li is None or li.kind != "dict":
            parser.err(where, "`on: dict_changed` needs `var:` = a declared dictionary, got %r" % (name,))
        if value is not NOVALUE:
            parser.err(where, "`on: dict_changed` takes no `value:`")
