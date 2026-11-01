"""Condition `weekday_in` (Jour de la semaine) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Arg, Condition


class WeekdayIn(Condition):
    id = 'weekday_in'
    order = 150
    label = 'Jour de la semaine'
    help = "Aujourd'hui est l'un des jours choisis."
    icon = 'calendar-time'
    theme = 'temps'
    args = {'days': Arg('weekdays', 'Jours')}

    def test(self, ctx, days):
        return ctx.brain._weekday() in days
