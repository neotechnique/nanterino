"""Action `arm_to` (Bouger un bras) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Effect: brain.motion.arm_to -> Body.command({arm_*_shoulder, arm_*_elbow}).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.log import log
from nanterino.nodes.base import Arg, Action


class ArmTo(Action):
    id = 'arm_to'
    order = 760
    label = 'Bouger un bras'
    help = "Amène l'épaule et le coude d'un bras (ou des deux) à des angles en degrés (épaule 0 = bras baissé, coude 0 = bras tendu), à une vitesse en %. Les limites de calibration s'appliquent."
    icon = 'hand-move'
    theme = 'mouvement'
    args = {'arm': Arg('arm', 'Bras'), 'shoulder': Arg('number', 'Épaule (degrés)'), 'elbow': Arg('number', 'Coude (degrés)'), 'speed': Arg('number', 'Vitesse (%)')}

    def run(self, ctx, arm, shoulder, elbow, speed):
        r = ctx.brain.motion.arm_to(arm, shoulder, elbow, speed)
        if not r.get("ok"):
            log.info("arm_to %s: not moved (%s)", arm, r.get("error") or r.get("refused") or "already there")
