"""Action `reset_repairs` (Remettre à zéro les demandes de répétition) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action


class ResetRepairs(Action):
    id = 'reset_repairs'
    order = 70
    label = 'Remettre à zéro les demandes de répétition'
    help = 'Le compteur de « pardon ? » repart de zéro.'
    icon = 'refresh'
    theme = 'conversation'
    args = {}

    def run(self, ctx):
        ctx.brain.repairs = 0
