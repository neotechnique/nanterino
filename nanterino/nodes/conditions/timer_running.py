"""Condition `timer_running` (Un chrono tourne) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Le chronomètre a été démarré et n'est pas arrêté.
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Arg, Condition


class TimerRunning(Condition):
    id = 'timer_running'
    order = 280
    label = 'Un chrono tourne'
    help = "Le chronomètre a été démarré et n'est pas arrêté."
    icon = 'hourglass'
    theme = 'temps'
    args = {'name': Arg('timervar', 'Chrono')}

    def test(self, ctx, name):
        return ctx.brain._elapsed(name) is not None
