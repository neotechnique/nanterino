"""Action `shake_head` (Secouer la tête (non)) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Effect: brain.motion.play("non").
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Action


class ShakeHead(Action):
    id = 'shake_head'
    order = 730
    label = 'Secouer la tête (non)'
    help = 'Fait « non » de la tête (geste « non » de la bibliothèque des gestes : gauche, droite, puis retour au centre). Un geste en cours est interrompu. À la fin, le geste « non » compte comme un geste terminé.'
    icon = 'x'
    theme = 'mouvement'

    def run(self, ctx):
        ctx.brain.motion.play("non")
