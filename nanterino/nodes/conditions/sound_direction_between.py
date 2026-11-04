"""Condition `sound_direction_between` (La direction du son est entre deux angles) - graph node module (lot C2, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: brain.sound.direction() (fresh, confident, loud enough; None with the mono microphone of today -> false) and
nanterino.sound.angles.in_sector (counter-clockwise from `start` to `end`, wrap-around safe: 135 to -135 = behind).
How to test: .venv/bin/python -m tests.test_sound (behaviour, wrap-around mutation) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Arg, Condition
from nanterino.sound.angles import in_sector


class SoundDirectionBetween(Condition):
    id = 'sound_direction_between'
    order = 670
    label = 'La direction du son est entre deux angles'
    help = ("Le dernier son net vient d'une direction comprise entre deux angles en degrés, en tournant vers la gauche "
            "du premier au second (0 = devant, 90 = à gauche, -90 = à droite, 180 = derrière ; de 135 à -135 = derrière). "
            "Faux s'il n'y a pas de son net depuis 1 s ou si le micro ne donne pas de direction (micro mono).")
    icon = 'ear'
    theme = 'micro'
    args = {'start': Arg('number', 'De (degrés)'), 'end': Arg('number', 'À (degrés)')}

    def test(self, ctx, start, end):
        d = ctx.brain.sound.direction()
        return d is not None and in_sector(d["azimuth_deg"], start, end)
