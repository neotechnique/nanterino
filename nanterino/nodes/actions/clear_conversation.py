"""Action `clear_conversation` (Oublier la conversation) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action


class ClearConversation(Action):
    id = 'clear_conversation'
    order = 50
    label = 'Oublier la conversation'
    help = "Efface l'historique, le compteur de tours et le sous-titre."
    icon = 'eraser'
    theme = 'conversation'
    args = {}

    def run(self, ctx):
        b = ctx.brain
        b.history.clear()
        b.turns = 0
        b.subtitle = ""
        b._reset_scope(ctx.graph, "conversation")   # lot L11: conversation-scoped variables and lists
