"""Action `clear_history` (Effacer l'historique) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action


class ClearHistory(Action):
    id = 'clear_history'
    order = 60
    label = "Effacer l'historique"
    help = "Efface seulement l'historique des échanges."
    icon = 'eraser'
    theme = 'conversation'
    args = {}

    def run(self, ctx):
        ctx.brain.history.clear()
