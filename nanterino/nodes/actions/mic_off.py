"""Action `mic_off` (Couper le micro) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action


class MicOff(Action):
    id = 'mic_off'
    order = 30
    label = 'Couper le micro'
    help = "Le robot n'écoute plus."
    icon = 'microphone-off'
    theme = 'micro'
    args = {}

    def run(self, ctx):
        ctx.brain.mic_set(False)   # lot N2: mic_closed when it really closes
