"""Action `set_now` (Noter la date et l'heure) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class SetNow(Action):
    id = 'set_now'
    order = 310
    label = "Noter la date et l'heure"
    help = 'Met une variable date et heure à maintenant.'
    icon = 'calendar-time'
    theme = 'temps'
    args = {'name': Arg('datetimevar', 'Variable date')}

    def run(self, ctx, name):
        ctx.brain._set_var(name, ctx.brain._now_iso())
