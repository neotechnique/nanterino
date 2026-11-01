"""Action `speak_relance` (Dire la relance) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action


class SpeakRelance(Action):
    id = 'speak_relance'
    order = 130
    label = 'Dire la relance'
    help = 'Dit la phrase de relance (ou de répétition si elle est préparée), puis relance_done.'
    icon = 'volume'
    theme = 'parole'
    args = {}

    def run(self, ctx):
        b = ctx.brain
        text, b._relance_text = b._relance_text or ctx.cfg["relance"], None   # one-shot repair text
        b._speak_then(text, "relance_done")
