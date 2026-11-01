"""Action `as_utterance` (Traiter la question tapée) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action


class AsUtterance(Action):
    id = 'as_utterance'
    order = 160
    label = 'Traiter la question tapée'
    help = "Traite le texte tapé comme s'il avait été dit."
    icon = 'keyboard'
    theme = 'systeme'
    args = {}

    def run(self, ctx):
        # Typed text (dashboard "ask") handled exactly like a spoken one.
        b = ctx.brain
        b.engine.dispatch("utterance", {"text": ctx.kw["text"], "t_end": ctx.kw.get("t_end") or b.now()})
