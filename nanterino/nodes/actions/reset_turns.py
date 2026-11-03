"""Action `reset_turns` (Remettre à zéro les tours de parole) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Action


class ResetTurns(Action):
    id = 'reset_turns'
    order = 510
    label = 'Remettre à zéro les tours de parole'
    help = "Le compteur de tours de parole de la conversation repart de zéro (l'historique est gardé)."
    icon = 'refresh'
    theme = 'conversation'
    args = {}

    def run(self, ctx):
        ctx.brain.turns = 0
