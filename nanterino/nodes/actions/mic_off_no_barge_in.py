"""Action `mic_off_no_barge_in` (Couper le micro (sauf interruption)) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action


class MicOffNoBargeIn(Action):
    id = 'mic_off_no_barge_in'
    order = 40
    label = 'Couper le micro (sauf interruption)'
    help = "Coupe le micro, sauf si l'interruption est activée dans la configuration."
    icon = 'microphone-off'
    theme = 'micro'
    args = {}

    def run(self, ctx):
        # Without echo cancellation the robot would hear itself, unless barge-in is wanted.
        if not ctx.cfg["barge_in"]:
            ctx.brain.mic.stop()
