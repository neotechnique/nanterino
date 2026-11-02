"""Trigger `timer_stopped` (Un chrono s'arrête) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by brain.py (see
the producer named below); transitions with `on: timer_stopped` react to it.
Producer: the timer_reset action (a running timer stopped).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Arg, Trigger


class TimerStopped(Trigger):
    id = 'timer_stopped'
    order = 360
    label = "Un chrono s'arrête"
    help = "« Arrêter un chrono » vient d'arrêter un chronomètre qui tournait. Anti-boucle comme « Une variable change »."
    icon = 'hourglass'
    theme = 'temps'
    args = {'name': Arg('timervar', 'Chrono')}   # the transition's `var:`

    def editor_args(self, g):
        return [{"name": "name", "type": "var", "var_types": ["timer"], "writable": False, "label": "Chrono",
                 "help": "Chrono surveillé (variable de type chrono)."}]

    def subscribe(self, graph):
        """Names some enabled `timer_stopped` transition listens to (the brain posts only their changes)."""
        trs = list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]
        return frozenset(t.var for t in trs if t.enabled and t.on == self.id and t.var)

    def match(self, ctx, event, name):
        return name == ctx.kw.get("name")

    def check(self, parser, where, name, value):
        from nanterino.graph import NOVALUE, SYSTEM_VARS
        info = parser.var_info(name) if isinstance(name, str) else None
        if info is None or info[0] != "timer" or name in SYSTEM_VARS:
            parser.err(where, "`on: timer_stopped` needs `var:` = a timer variable, got %r" % (name,))
        if value is not NOVALUE:
            parser.err(where, "`on: timer_stopped` takes no `value:`")
