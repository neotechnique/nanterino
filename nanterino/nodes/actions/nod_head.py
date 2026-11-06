"""Action `nod_head` (Hocher la tête (oui)) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Effect: brain.motion.play("oui") (gesture library nanterino/body/gestures.yaml).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Action


class NodHead(Action):
    id = 'nod_head'
    order = 720
    label = 'Hocher la tête (oui)'
    help = 'Fait « oui » de la tête (geste « oui » de la bibliothèque des gestes : haut, bas, puis retour au centre). Un geste en cours est interrompu. À la fin, le geste « oui » compte comme un geste terminé.'
    icon = 'mood-smile'
    theme = 'mouvement'

    def run(self, ctx):
        ctx.brain.motion.play("oui")
