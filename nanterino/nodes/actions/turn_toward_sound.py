"""Action `turn_toward_sound` (Tourner la tête vers le son) - graph node module (lot C2, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Effect: nanterino.sound.turn.turn_head_toward(brain.body, direction): Body.look(pan=..., source="sound"), bounded by
the head_pan calibration (beyond it: saturated at the limit and logged); the wheels never move. Without a direction
(mono microphone, silence) nothing moves (INFO record).
How to test: .venv/bin/python -m tests.test_sound (sim sound + sim body) + tests.test_nodes_registry.
"""
from nanterino.log import log
from nanterino.nodes.base import Action
from nanterino.sound.turn import turn_head_toward


class TurnTowardSound(Action):
    id = 'turn_toward_sound'
    order = 670
    label = 'Tourner la tête vers le son'
    help = ("Tourne la tête (rotation pan) vers la direction du dernier son net, dans les limites de calibration de la "
            "tête (au-delà, la tête s'arrête à sa limite) ; les roues ne bougent jamais. Sans direction connue (micro "
            "mono, silence), rien ne bouge.")
    icon = 'scan-eye'
    theme = 'micro'

    def run(self, ctx):
        b = ctx.brain
        d = b.sound.direction()
        if d is None:
            log.info("turn_toward_sound: no sound direction (backend=%s), head not moved", b.sound.source.name)
            return
        res = turn_head_toward(b.body, d["azimuth_deg"])
        if not res["ok"]:
            log.info("turn_toward_sound: head not moved (%s)", res["error"])
