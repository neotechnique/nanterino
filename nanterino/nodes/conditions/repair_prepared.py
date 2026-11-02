"""Condition `repair_prepared` (La phrase « répétez » est préparée) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: « Préparer la phrase « répétez » » a été fait et la prochaine relance ne l'a pas encore dite.
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Condition


class RepairPrepared(Condition):
    id = 'repair_prepared'
    order = 510
    label = 'La phrase « répétez » est préparée'
    help = "« Préparer la phrase « répétez » » a été fait et la prochaine relance ne l'a pas encore dite."
    icon = 'message'
    theme = 'conversation'
    args = {}

    def test(self, ctx):
        return ctx.brain._relance_text is not None
