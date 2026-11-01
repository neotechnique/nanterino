"""Action `timer_start` (Démarrer un chrono) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class TimerStart(Action):
    id = 'timer_start'
    order = 320
    label = 'Démarrer un chrono'
    help = 'Démarre (ou redémarre à zéro) un chronomètre ; ses déclencheurs « Un chrono atteint une durée » sont réarmés.'
    icon = 'player-play'
    theme = 'temps'
    args = {'name': Arg('timervar', 'Chrono')}

    def run(self, ctx, name):
        # The start is a WALL epoch, so a persisted timer keeps running across a restart.
        ctx.brain._set_var(name, round(ctx.brain.wall(), 3))
