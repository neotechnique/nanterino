"""Action `gaze` (Régler le regard) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class Gaze(Action):
    id = 'gaze'
    order = 230
    label = 'Régler le regard'
    help = "Le regard du visage suit le visiteur, regarde devant lui, ou erre ; reste jusqu'au prochain réglage (retour à « suivre » en veille)."
    icon = 'eye'
    theme = 'vision'
    args = {'mode': Arg('gazemode', 'Regard')}

    def run(self, ctx, mode):
        ctx.brain.set_gaze(mode)   # lot N2: gaze_changed
