"""Condition `turns_left` (Il reste des tours de parole) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Condition


class TurnsLeft(Condition):
    id = 'turns_left'
    order = 70
    label = 'Il reste des tours de parole'
    help = "La conversation n'a pas atteint le nombre maximal d'échanges."
    icon = 'message'
    theme = 'conversation'
    as_vars = 'tours < max_tours'   # shown as a variable comparison; the compiled guard does not change

    def test(self, ctx):
        from nanterino import brain as brain_mod   # looked up at call time (tests patch it)
        return ctx.brain.turns < brain_mod.MAX_TURNS
