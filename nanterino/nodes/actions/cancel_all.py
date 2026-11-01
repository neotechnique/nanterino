"""Action `cancel_all` (Se taire) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action


class CancelAll(Action):
    id = 'cancel_all'
    order = 10
    label = 'Se taire'
    help = 'Coupe immédiatement le son et annule toute réponse en cours.'
    icon = 'x'
    theme = 'parole'
    args = {}

    def run(self, ctx):
        ctx.brain._cancel_all()
