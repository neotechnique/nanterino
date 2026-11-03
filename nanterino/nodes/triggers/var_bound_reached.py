"""Trigger `var_bound_reached` (Une variable atteint sa limite) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: var_bound_reached` (+ `var:`) react to it.
Producer: Brain._set_var (every variable write: set_var, add_var, value targets), only for a listened variable (subscribe()).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Trigger


class VarBoundReached(Trigger):
    id = 'var_bound_reached'
    order = 570
    label = 'Une variable atteint sa limite'
    help = "Une variable nombre qui a un minimum ou un maximum (réglages min / max) vient de l'atteindre, par exemple « Ajouter à une variable » bloqué à la limite (kw value = la limite). Anti-boucle comme « Une variable change »."
    icon = 'circle-dot'
    theme = 'variables'
    args = {'name': Arg('anyvar', 'Variable')}   # the transition's `var:`

    def editor_args(self, g):
        return [{"name": "name", "type": "var", "var_types": [t for t in g.VAR_TYPES if t in g.NUMERIC_TYPES and t != "timer"], "writable": False, "label": "Variable",
                 "help": 'Variable nombre surveillée (avec min ou max) : la chaîne démarre quand elle atteint une limite.'}]

    def subscribe(self, graph):
        """Variables some enabled `var_bound_reached` transition listens to (the brain posts only those)."""
        trs = list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]
        return frozenset(t.var for t in trs if t.enabled and t.on == self.id and t.var)

    def match(self, ctx, event, name):
        return name == ctx.kw.get("name")

    def check(self, parser, where, name, value):
        from nanterino.graph import NOVALUE
        var = parser.vars.get(name) if isinstance(name, str) else None
        if var is None:
            parser.err(where, "`on: var_bound_reached` needs `var:` = a declared variable, got %r" % (name,))
        elif var.vmin is None and var.vmax is None:
            parser.err(where, "`on: var_bound_reached`: variable %r has no min / max" % (name,))
        if value is not NOVALUE:
            parser.err(where, "`on: var_bound_reached` takes no `value:`")
