"""Condition `date_compare` (Comparer une date) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Arg, Condition


class DateCompare(Condition):
    id = 'date_compare'
    order = 160
    label = 'Comparer une date'
    help = 'Compare une variable date et heure à une date (ou à « $heure », maintenant) : avant, après, égale.'
    icon = 'calendar-time'
    theme = 'temps'
    args = {'name': Arg('datevar_any', 'Date'), 'op': Arg('op', 'Opérateur'), 'value': Arg('value', 'Date (ou $heure)')}

    def test(self, ctx, name, op, value):
        b = ctx.brain
        return b._compare(b.var_value(name), op, b._resolve(value, ctx.kw), "datetime")
