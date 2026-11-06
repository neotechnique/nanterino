"""Action `look_at` (Regarder (angles)) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Effect: brain.motion.look -> Body.look(pan, tilt, speed, source="graph") (clamped by the Body, clamp event).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.log import log
from nanterino.nodes.base import Arg, Action


class LookAt(Action):
    id = 'look_at'
    order = 700
    label = 'Regarder (angles)'
    help = "Tourne la tête vers deux angles en degrés : rotation (0 = devant, + = vers la gauche du robot) et inclinaison (+ = vers le haut), à une vitesse en % de la vitesse maxi. Les limites de calibration s'appliquent (au-delà, la tête s'arrête à sa limite). Refusé pendant un arrêt d'urgence."
    icon = 'eye'
    theme = 'mouvement'
    args = {'pan': Arg('number', 'Rotation (degrés, + = gauche)'), 'tilt': Arg('number', 'Inclinaison (degrés, + = haut)'), 'speed': Arg('number', 'Vitesse (%)')}

    def run(self, ctx, pan, tilt, speed):
        r = ctx.brain.motion.look(pan, tilt, speed)
        if not r.get("ok"):
            log.info("look_at: head not moved (%s)", r.get("error") or r.get("refused") or "already there")
