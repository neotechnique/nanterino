"""Action `forget_last_exchange` (Oublier le dernier échange) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Action


class ForgetLastExchange(Action):
    id = 'forget_last_exchange'
    order = 520
    label = 'Oublier le dernier échange'
    help = "Retire de l'historique la dernière question du visiteur et la réponse du robot : les réponses suivantes ne s'en servent plus."
    icon = 'eraser'
    theme = 'conversation'
    args = {}

    def run(self, ctx):
        h = ctx.brain.history
        # history = [user, assistant, user, assistant, ...] (Brain._answer appends one pair per answer)
        if len(h) >= 2 and h[-1].get("role") == "assistant" and h[-2].get("role") == "user":
            del h[-2:]
