"""Action `reset_silence` (Redémarrer le chrono de silence) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action


class ResetSilence(Action):
    id = 'reset_silence'
    order = 80
    label = 'Redémarrer le chrono de silence'
    help = 'La dernière parole est considérée comme étant maintenant.'
    icon = 'clock'
    theme = 'micro'
    args = {}

    def run(self, ctx):
        ctx.brain.last_speech = ctx.brain.now()
