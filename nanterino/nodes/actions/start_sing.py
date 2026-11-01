"""Action `start_sing` (Chanter) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
import threading
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
        b = ctx.brain
        if not b._threaded:   # simulator: the song "lasts" SIM_SONG_S virtual seconds
            from nanterino import brain as brain_mod   # lazy: see start_answer
            b._schedule_at(b.now() + brain_mod.SIM_SONG_S, "answer_done")
            return
        threading.Thread(target=b._sing, args=(b.gen,), daemon=True).start()
