"""Trigger `pose_reached` (Une pose est atteinte) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: pose_reached` react to it.
Producer: MotionRuntime._hook (arrival of a pose command) / set_pose (already there).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import ANY, Arg, Trigger


class PoseReached(Trigger):
    id = 'pose_reached'
    order = 790
    label = 'Une pose est atteinte'
    help = "La tête et les bras sont arrivés dans une pose de la bibliothèque (pose facultative ; vide = n'importe laquelle)."
    icon = 'flag'
    theme = 'mouvement'
    args = {'value': Arg('text', 'Pose (facultative)')}   # the transition's `value:` (no `var:`)

    def editor_args(self, g):
        return [{"name": "value", "type": "enum", "options": list(g.MOTION_ENUMS["pose"]),
                 "labels": dict(g.MOTION_ENUMS["pose"]), "optional": True, "label": "Pose (facultative)",
                 "help": "Seulement cette pose ; vide = n'importe laquelle."}]

    def subscribe(self, graph):
        """Names listened to ("*" = any): MotionRuntime posts pose_reached only when this is not empty."""
        from nanterino.graph import NOVALUE
        trs = list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]
        return frozenset("*" if t.value is NOVALUE else t.value for t in trs if t.enabled and t.on == self.id)

    def match(self, ctx, event, value=ANY):
        return value is ANY or value == ctx.kw.get("value")

    def check(self, parser, where, name, value):
        from nanterino.graph import MOTION_ENUMS, NOVALUE
        if name is not None:
            parser.err(where, "`on: pose_reached` takes no `var:`")
        if value is not NOVALUE and value not in MOTION_ENUMS["pose"]:
            parser.err(where, "`on: pose_reached` `value:` must be one of %s, got %r" % (", ".join(MOTION_ENUMS["pose"]), value))
