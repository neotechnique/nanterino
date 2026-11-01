"""Action `mic_on` (Ouvrir le micro) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action


class MicOn(Action):
    id = 'mic_on'
    order = 20
    label = 'Ouvrir le micro'
    help = 'Le robot se remet à écouter (sauf mode sourd).'
    icon = 'microphone'
    theme = 'micro'
    args = {}

    def run(self, ctx):
        ctx.brain._mic_on()
