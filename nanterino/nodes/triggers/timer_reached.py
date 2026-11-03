"""Trigger `timer_reached` (Un chrono atteint une durée) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the brain (or a graph action) posts this
event; transitions with `on: timer_reached` react to it.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import ANY, Arg, Trigger


class TimerReached(Trigger):
    id = 'timer_reached'
    order = 230
    label = 'Un chrono atteint une durée'
    help = 'Un chronomètre (variable de type chrono) atteint le nombre de secondes indiqué depuis son départ ; une seule fois par départ (« Démarrer un chrono » le réarme). Une chaîne lancée par ce déclencheur qui change une variable ne relance pas de déclencheur (anti-boucle).'
    icon = 'hourglass'
    theme = 'temps'
    args = {'name': Arg('timeref', 'Chrono'), 'value': Arg('seconds0', 'Secondes')}   # the transition's `var:` / `value:`

    def editor_args(self, g):
        """Inspector schema of the transition's `var:` (a timer) / `value:` (seconds), lot L11."""
        return [{"name": "name", "type": "var", "var_types": ["timer"], "writable": False, "label": "Chrono",
                 "help": "Chrono surveillé (variable de type chrono)."},
                {"name": "value", "type": "number", "options": [], "min": 0, "label": "Secondes",
                 "help": "Secondes écoulées depuis le départ du chrono ; la chaîne démarre une fois par départ."}]

    def subscribe(self, graph):
        """(timer variable, seconds) pairs some enabled `timer_reached` transition waits for (polled by the heartbeat)."""
        trs = list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]
        return tuple(dict.fromkeys((t.var, t.value) for t in trs if t.enabled and t.on == self.id and t.var))

    def match(self, ctx, event, name, value=ANY):
        """Only the watched timer and the seconds of this transition (the heartbeat posts both)."""
        return name == ctx.kw.get("name") and (value is ANY or value == ctx.kw.get("value"))

    def check(self, parser, where, name, value):
        """Parser check: `var:` = a user timer, `value:` = seconds since its start (> 0)."""
        from nanterino.graph import SYSTEM_VARS, _num
        info = parser.var_info(name) if isinstance(name, str) else None
        if info is None or info[0] != "timer" or name in SYSTEM_VARS:
            parser.err(where, "`on: timer_reached` needs `var:` = a timer variable, got %r" % (name,))
        elif not (_num(value) and 0 < value <= 10 ** 7):
            parser.err(where, "`on: timer_reached` needs `value:` = a number of seconds > 0")
