"""Condition `time_between` (Entre deux heures) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Arg, Condition


class TimeBetween(Condition):
    id = 'time_between'
    order = 140
    label = 'Entre deux heures'
    help = "L'heure actuelle est entre le début (inclus) et la fin (exclue) ; une fin avant le début passe minuit (22:00 → 06:00)."
    icon = 'clock'
    theme = 'temps'
    args = {'start': Arg('hhmm', 'Début (hh:mm)'), 'end': Arg('hhmm', 'Fin (hh:mm)')}

    def test(self, ctx, start, end):
        now = ctx.brain._wall_dt()   # wall clock only through the brain (injectable)
        m, a, b = now.hour * 60 + now.minute, int(start[:2]) * 60 + int(start[3:]), int(end[:2]) * 60 + int(end[3:])
        return a <= m < b if a <= b else (m >= a or m < b)   # end before start: the range wraps past midnight
