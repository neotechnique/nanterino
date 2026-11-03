"""Condition `expression_is` (L'expression du visage est) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Le visage montre cette expression en ce moment (« neutre » quand aucune n'est en cours).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class ExpressionIs(Condition):
    id = 'expression_is'
    order = 400
    label = "L'expression du visage est"
    help = "Le visage montre cette expression en ce moment (« neutre » quand aucune n'est en cours)."
    icon = 'mood-smile'
    theme = 'vision'
    args = {'name': Arg('expression', 'Expression')}

    def test(self, ctx, name):
        return ctx.brain.var_value('expression') == name
