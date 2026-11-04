"""Trigger `gesture_done` (Un geste est terminé) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: gesture_done` react to it.
Producer: MotionRuntime._end_seq (posted only when a transition listens).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import ANY, Arg, Trigger


class GestureDone(Trigger):
    id = 'gesture_done'
    order = 780
    label = 'Un geste est terminé'
    help = "Un geste de la bibliothèque est allé jusqu'au bout (geste facultatif ; vide = n'importe lequel). Un geste interrompu ne compte pas."
    icon = 'hand-move'
    theme = 'mouvement'
    args = {'value': Arg('text', 'Geste (facultatif)')}   # the transition's `value:` (no `var:`)

    def editor_args(self, g):
        return [{"name": "value", "type": "enum", "options": list(g.MOTION_ENUMS["gesture"]),
                 "labels": dict(g.MOTION_ENUMS["gesture"]), "optional": True, "label": "Geste (facultatif)",
                 "help": "Seulement ce geste ; vide = n'importe lequel."}]

    def subscribe(self, graph):
        """Names listened to ("*" = any): MotionRuntime posts gesture_done only when this is not empty."""
        from nanterino.graph import NOVALUE
        trs = list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]
        return frozenset("*" if t.value is NOVALUE else t.value for t in trs if t.enabled and t.on == self.id)

    def match(self, ctx, event, value=ANY):
        return value is ANY or value == ctx.kw.get("value")

    def check(self, parser, where, name, value):
        from nanterino.graph import MOTION_ENUMS, NOVALUE
        if name is not None:
            parser.err(where, "`on: gesture_done` takes no `var:`")
        if value is not NOVALUE and value not in MOTION_ENUMS["gesture"]:
            parser.err(where, "`on: gesture_done` `value:` must be one of %s, got %r" % (", ".join(MOTION_ENUMS["gesture"]), value))
