"""Condition `elapsed_since` (Temps écoulé depuis) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Arg, Condition


class ElapsedSince(Condition):
    id = 'elapsed_since'
    order = 130
    label = 'Temps écoulé depuis'
    help = "Secondes écoulées depuis une date ou depuis le départ d'un chrono, comparées à un nombre (faux si la date est vide ou le chrono arrêté)."
    icon = 'hourglass'
    theme = 'temps'
    args = {'name': Arg('timeref', 'Date ou chrono'), 'op': Arg('op', 'Opérateur'), 'seconds': Arg('seconds0', 'Secondes')}

    def test(self, ctx, name, op, seconds):
        b = ctx.brain
        e = b._elapsed(name)
        return e is not None and b._compare(e, op, seconds)
