"""Trigger `var_reset` (Une variable revient à sa valeur de départ) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: var_reset` (+ `var:`) react to it.
Producer: Brain.reset_var (reset_var action, dashboard variable manager) and Brain._reset_scope (clear_conversation), only for a listened variable (subscribe()).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Trigger


class VarReset(Trigger):
    id = 'var_reset'
    order = 560
    label = 'Une variable revient à sa valeur de départ'
    help = 'La variable reprend la valeur écrite dans le graphe : « Remettre une variable à sa valeur de départ », le bouton du gestionnaire de variables, ou « Oublier la conversation » pour une variable de conversation. Anti-boucle comme « Une variable change ».'
    icon = 'refresh'
    theme = 'variables'
    args = {'name': Arg('anyvar', 'Variable')}   # the transition's `var:`

    def editor_args(self, g):
        return [{"name": "name", "type": "var", "var_types": list(g.VAR_TYPES), "writable": False, "label": "Variable",
                 "help": 'Variable surveillée : la chaîne démarre quand elle revient à sa valeur de départ.'}]

    def subscribe(self, graph):
        """Variables some enabled `var_reset` transition listens to (the brain posts only those)."""
        trs = list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]
        return frozenset(t.var for t in trs if t.enabled and t.on == self.id and t.var)

    def match(self, ctx, event, name):
        return name == ctx.kw.get("name")

    def check(self, parser, where, name, value):
        from nanterino.graph import NOVALUE
        if not isinstance(name, str) or name not in parser.vars:
            parser.err(where, "`on: var_reset` needs `var:` = a declared variable, got %r" % (name,))
        if value is not NOVALUE:
            parser.err(where, "`on: var_reset` takes no `value:`")
