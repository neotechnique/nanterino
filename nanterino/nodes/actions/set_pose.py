"""Action `set_pose` (Prendre une pose) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Effect: brain.motion.set_pose(pose, speed): one bounded Body.command.
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.log import log
from nanterino.nodes.base import Arg, Action


class SetPose(Action):
    id = 'set_pose'
    order = 750
    label = 'Prendre une pose'
    help = "Amène la tête et les bras dans une pose nommée de la bibliothèque (repos, accueil, bras levés, pensif) en une seule commande, à une vitesse en %. Son arrivée est signalée comme une pose atteinte."
    icon = 'flag'
    theme = 'mouvement'
    args = {'pose': Arg('pose', 'Pose'), 'speed': Arg('number', 'Vitesse (%)')}

    def run(self, ctx, pose, speed):
        r = ctx.brain.motion.set_pose(pose, speed)
        if not r.get("ok"):
            log.info("set_pose %s: not moved (%s)", pose, r.get("error") or r.get("refused"))
