"""Condition `head_tilt_between` (La tête est inclinée entre deux angles) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Body.state() head_tilt position.
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Arg, Condition


class HeadTiltBetween(Condition):
    id = 'head_tilt_between'
    order = 770
    label = 'La tête est inclinée entre deux angles'
    help = "L'inclinaison actuelle de la tête (+ = haut) est comprise entre deux angles en degrés (dans n'importe quel ordre)."
    icon = 'eye'
    theme = 'mouvement'
    args = {'start': Arg('number', 'De (degrés)'), 'end': Arg('number', 'À (degrés)')}

    def test(self, ctx, start, end):
        j = ctx.brain.motion.positions().get("head_tilt")
        return j is not None and min(start, end) <= j["position"] <= max(start, end)
