"""Action `base_turn` (Tourner sur place) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Effect: brain.motion.base_turn: opposite wheel velocities, stop on odometry (gestures.yaml base.track_m).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.log import log
from nanterino.nodes.base import Arg, Action


class BaseTurn(Action):
    id = 'base_turn'
    order = 780
    label = 'Tourner sur place'
    help = "Fait tourner la base sur place d'un angle en degrés (+ = vers la gauche, - = vers la droite), à une vitesse en % : les roues tournent en sens opposés et s'arrêtent d'après leur odométrie. Sa fin est signalée comme un déplacement terminé."
    icon = 'refresh'
    theme = 'mouvement'
    args = {'angle': Arg('number', 'Angle (degrés, + = gauche)'), 'speed': Arg('number', 'Vitesse (%)')}

    def run(self, ctx, angle, speed):
        if not ctx.brain.motion.base_turn(angle, speed):
            log.info("base_turn %s deg: base not moved", angle)
