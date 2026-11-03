"""Condition `repairs_left` (Il reste des demandes de répétition) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Condition


class RepairsLeft(Condition):
    id = 'repairs_left'
    order = 60
    label = 'Il reste des demandes de répétition'
    help = 'Le robot a demandé de répéter moins de 2 fois de suite.'
    icon = 'refresh'
    theme = 'conversation'
    as_vars = 'reparations < max_reparations'   # shown as a variable comparison; the compiled guard does not change

    def test(self, ctx):
        from nanterino import brain as brain_mod   # looked up at call time (tests patch it)
        return ctx.brain.repairs < brain_mod.MAX_REPAIRS   # "pardon ?" at most twice in a row
