"""Action `subtitle_listening` (Afficher « Je vous écoute ») - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action


class SubtitleListening(Action):
    id = 'subtitle_listening'
    order = 90
    label = 'Afficher « Je vous écoute »'
    help = "Met le sous-titre de l'écran sur « Je vous écoute »."
    icon = 'ear'
    theme = 'micro'
    args = {}

    def run(self, ctx):
        ctx.brain.subtitle = "Je vous écoute"
