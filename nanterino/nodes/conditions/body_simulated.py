"""Condition `body_simulated` (Le corps est simulé) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: brain.body.backend.name == "sim".
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Condition


class BodySimulated(Condition):
    id = 'body_simulated'
    order = 750
    label = 'Le corps est simulé'
    help = "Les mouvements sont simulés (aucun moteur réel branché) : vrai aujourd'hui, faux avec MuJoCo ou le vrai matériel."
    icon = 'question-mark'
    theme = 'mouvement'

    def test(self, ctx):
        return ctx.brain.body.backend.name == "sim"
