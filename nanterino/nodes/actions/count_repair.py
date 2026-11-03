"""Action `count_repair` (Compter une demande de répétition) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action


class CountRepair(Action):
    id = 'count_repair'
    order = 110
    label = 'Compter une demande de répétition'
    help = 'Ajoute un « pardon ? » au compteur.'
    icon = 'plus'
    theme = 'conversation'
    args = {}

    def run(self, ctx):
        ctx.brain.repairs += 1
