"""Action `count_turn` (Compter un tour de parole) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action


class CountTurn(Action):
    id = 'count_turn'
    order = 100
    label = 'Compter un tour de parole'
    help = 'Ajoute un échange au compteur de la conversation.'
    icon = 'plus'
    theme = 'conversation'
    args = {}

    def run(self, ctx):
        ctx.brain.turns += 1
