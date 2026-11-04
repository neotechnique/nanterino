"""Trigger `motion_clamped` (Une limite de mouvement est atteinte) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: motion_clamped` react to it.
Producer: MotionRuntime._hook (Body `clamp`, anti-burst CLAMP_GAP_S per joint).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Trigger


class MotionClamped(Trigger):
    id = 'motion_clamped'
    order = 740
    label = 'Une limite de mouvement est atteinte'
    help = "Une consigne dépassait la calibration d'une articulation : elle a été ramenée à la limite. Au plus une fois par seconde et par articulation. kw joint, requested, applied."
    icon = 'bolt'
    theme = 'mouvement'
