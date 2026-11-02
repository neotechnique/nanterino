"""Action `start_sing` (Chanter) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action


class StartSing(Action):
    id = 'start_sing'
    order = 150
    label = 'Chanter'
    help = 'Lance la chanson de Nanterino.'
    icon = 'music'
    theme = 'parole'
    args = {}

    def run(self, ctx):
        # Lot N2: Brain.start_song posts song_started / song_finished (is_singing) and keeps the simulator path
        # (SIM_SONG_S virtual seconds, then answer_done as before).
        ctx.brain.start_song()
