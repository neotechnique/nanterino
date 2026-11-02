"""Trigger `list_item_added` (Un élément est ajouté à une liste) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: list_item_added` react to it.
Producer: Brain.list_item_event (list_add, remember_utterance), only for a listened list.
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Trigger


class ListItemAdded(Trigger):
    id = 'list_item_added'
    order = 500
    label = 'Un élément est ajouté à une liste'
    help = "Un élément vient d'entrer dans une liste (« Ajouter à une liste », « Retenir la phrase du visiteur »). Anti-boucle comme « Une variable change »."
    icon = 'plus'
    theme = 'listes'
    args = {'name': Arg('rlist_any', 'Liste')}   # the transition's `var:`

    def editor_args(self, g):
        return [{"name": "name", "type": "list", "list_types": list(g.LIST_TYPES), "list_kinds": ["list"], "writable": False,
                 "label": "Liste", "help": 'Liste surveillée : la chaîne démarre quand un élément y est ajouté.'}]

    def subscribe(self, graph):
        """Lists some enabled `list_item_added` transition listens to (the brain posts only their changes)."""
        trs = list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]
        return frozenset(t.var for t in trs if t.enabled and t.on == self.id and t.var)

    def match(self, ctx, event, name):
        return name == ctx.kw.get("name")

    def check(self, parser, where, name, value):
        from nanterino.graph import NOVALUE
        li = parser.lists.get(name) if isinstance(name, str) else None
        if li is None or li.kind != "list":
            parser.err(where, "`on: list_item_added` needs `var:` = a declared list, got %r" % (name,))
        if value is not NOVALUE:
            parser.err(where, "`on: list_item_added` takes no `value:`")
