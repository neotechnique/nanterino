"""Trigger `sound_from_direction` (Un son vient d'une direction) - graph node module (lot C2, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: sound_from_direction` (optional `value:` = a sector) react to it.
Producer: Brain._sound_tick (heartbeat: brain.sound gives a confident direction; once per sound onset or sector change,
at most one per second). The mono microphone of today never gives a direction, so it never fires on the live robot
until a microphone array (nanterino/sound, Notes/HOWTO-sound360.md) is plugged in.
How to test: .venv/bin/python -m tests.test_sound (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import ANY, Arg, Trigger
from nanterino.sound.angles import SECTOR_LABELS, SECTORS


class SoundFromDirection(Trigger):
    id = 'sound_from_direction'
    order = 690
    label = "Un son vient d'une direction"
    help = ("Un son net arrive d'un côté du robot : devant, à gauche, derrière ou à droite (direction facultative ; "
            "vide = n'importe où). Une fois par son ou par changement de côté, au plus une fois par seconde ; il faut une "
            "barrette de micros (le micro mono actuel ne donne pas de direction). kw azimuth = l'angle (0 devant, + à "
            "gauche), level_db, confidence.")
    icon = 'ear'
    theme = 'micro'
    args = {'value': Arg('text', 'Direction (facultative)')}   # the transition's `value:` (no `var:`)

    def editor_args(self, g):
        return [{"name": "value", "type": "enum", "options": list(SECTORS), "labels": dict(SECTOR_LABELS),
                 "optional": True, "label": "Direction (facultative)",
                 "help": "Seulement les sons de ce côté (devant = -45 à 45 degrés) ; vide = de n'importe où."}]

    def subscribe(self, graph):
        """Sectors listened to ("*" = any): the brain posts sound_from_direction only when this is not empty."""
        from nanterino.graph import NOVALUE
        trs = list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]
        return frozenset("*" if t.value is NOVALUE else t.value for t in trs if t.enabled and t.on == self.id)

    def match(self, ctx, event, value=ANY):
        return value is ANY or value == ctx.kw.get("value")

    def check(self, parser, where, name, value):
        from nanterino.graph import NOVALUE
        if name is not None:
            parser.err(where, "`on: sound_from_direction` takes no `var:`")
        if value is not NOVALUE and value not in SECTORS:
            parser.err(where, "`on: sound_from_direction` `value:` must be one of %s, got %r" % (", ".join(SECTORS), value))
