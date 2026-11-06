"""Action `play_gesture` (Faire un geste) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Effect: brain.motion.play(gesture): one Body.command per step.
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Arg, Action


class PlayGesture(Action):
    id = 'play_gesture'
    order = 740
    label = 'Faire un geste'
    help = "Joue un geste nommé de la bibliothèque (nanterino/body/gestures.yaml) : saluer, montrer à gauche ou à droite, hausser les épaules… pas à pas, chaque pas attend que les articulations soient arrivées. Un geste en cours est interrompu. Refusé pendant un arrêt d'urgence."
    icon = 'hand-move'
    theme = 'mouvement'
    args = {'gesture': Arg('gesture', 'Geste')}

    def run(self, ctx, gesture):
        ctx.brain.motion.play(gesture)
