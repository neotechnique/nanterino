"""Action `set_relance_text` (Préparer la phrase « répétez ») - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action


class SetRelanceText(Action):
    id = 'set_relance_text'
    order = 120
    label = 'Préparer la phrase « répétez »'
    help = 'La prochaine relance dira la phrase de demande de répétition.'
    icon = 'message'
    theme = 'conversation'
    args = {}

    def run(self, ctx):
        ctx.brain._relance_text = ctx.cfg.get("repair_text") or ctx.cfg["relance"]
