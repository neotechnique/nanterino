"""Action `base_move` (Avancer / reculer) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Effect: brain.motion.base_move: wheel velocities, stop on odometry (MotionRuntime._tick_base).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.log import log
from nanterino.nodes.base import Arg, Action


class BaseMove(Action):
    id = 'base_move'
    order = 770
    label = 'Avancer / reculer'
    help = "Fait avancer la base d'une distance en mètres (négative = reculer), à une vitesse en % : les deux roues tournent ensemble et s'arrêtent d'après leur odométrie (freinage compris). Un déplacement en cours est interrompu ; trop long, il est arrêté. Sa fin est signalée comme un déplacement terminé."
    icon = 'arrow-right'
    theme = 'mouvement'
    args = {'distance': Arg('number', 'Distance (m, négatif = reculer)'), 'speed': Arg('number', 'Vitesse (%)')}

    def run(self, ctx, distance, speed):
        if not ctx.brain.motion.base_move(distance, speed):
            log.info("base_move %s m: base not moved", distance)
