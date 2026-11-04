"""Action `look_center` (Regarder droit devant) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Effect: brain.motion.look(0, 0, 50 %).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.log import log
from nanterino.nodes.base import Action


class LookCenter(Action):
    id = 'look_center'
    order = 710
    label = 'Regarder droit devant'
    help = "Ramène la tête au centre (rotation 0, inclinaison 0) à mi-vitesse. Refusé pendant un arrêt d'urgence."
    icon = 'eye'
    theme = 'mouvement'

    def run(self, ctx):
        r = ctx.brain.motion.look(0, 0, 50)
        if not r.get("ok"):
            log.info("look_center: head not moved (%s)", r.get("error") or r.get("refused") or "already there")
