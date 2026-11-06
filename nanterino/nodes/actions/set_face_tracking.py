"""Action `set_face_tracking` (Suivre le visage) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Effect: brain.motion.set_tracking (MotionRuntime._tick_track reads brain.motion.face_source = vision.state).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Arg, Action


class SetFaceTracking(Action):
    id = 'set_face_tracking'
    order = 810
    label = 'Suivre le visage'
    help = 'Active ou coupe le suivi du visage : la tête suit le visage vu par la caméra (au plus 5 corrections par seconde, pas pendant un geste). Sans caméra (Testeur, simulation), rien ne bouge.'
    icon = 'scan-eye'
    theme = 'mouvement'
    args = {'state': Arg('onoff', 'Suivi')}

    def run(self, ctx, state):
        ctx.brain.motion.set_tracking(state == "on")
