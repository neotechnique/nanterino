"""Trigger `var_changed` (Une variable change) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: var_changed` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import ANY, Arg, Trigger


class VarChanged(Trigger):
    id = 'var_changed'
    order = 220
    label = 'Une variable change'
    help = "La valeur d'une variable vient de changer (valeur précise facultative). Une chaîne lancée par ce déclencheur qui change encore une variable ne relance pas de déclencheur (anti-boucle)."
    icon = 'circle-dot'
    theme = 'variables'
    args = {'name': Arg('anyvar', 'Variable'), 'value': Arg('value', 'Valeur (facultative)')}   # the transition's `var:` / `value:`

    def editor_args(self, g):
        """Inspector schema of the transition's `var:` / `value:` (GET /api/graph/vocab, events[].args)."""
        return [{"name": "name", "type": "var", "var_types": list(g.VAR_TYPES), "writable": False, "label": "Variable",
                 "help": "Variable surveillée : la chaîne démarre quand sa valeur change."},
                {"name": "value", "type": "value", "of": "name", "optional": True, "label": "Valeur (facultative)",
                 "help": "Seulement quand la variable prend cette valeur ; vide = à chaque changement."}]

    def subscribe(self, graph):
        """Variables some enabled `var_changed` transition listens to (the brain posts only those changes)."""
        trs = list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]
        return frozenset(t.var for t in trs if t.enabled and t.on == self.id and t.var)

    def match(self, ctx, event, name, value=ANY):
        """Only the watched variable (and, when `value:` is set, only that new value)."""
        return name == ctx.kw.get("name") and (value is ANY or value == ctx.kw.get("value"))

    def check(self, parser, where, name, value):
        """Parser check of `var:` / `value:` (value is graph.NOVALUE when the YAML has no `value:`)."""
        from nanterino.graph import NOVALUE
        info = parser.var_info(name) if isinstance(name, str) else None
        if name == "etat":
            parser.err(where, "var_changed on etat: use the state's on_enter")
        elif info is None:
            parser.err(where, "`on: var_changed` needs `var:` = a declared variable, got %r" % (name,))
        elif value is not NOVALUE:
            parser.check_value(where, "value", info[0], info[1], value)
