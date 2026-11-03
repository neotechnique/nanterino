"""Condition `not_busy` (Aucune transcription en cours) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Condition


class NotBusy(Condition):
    id = 'not_busy'
    order = 30
    label = 'Aucune transcription en cours'
    help = "Le robot n'est pas en train de transcrire une phrase."
    icon = 'circle-dot'
    theme = 'micro'

    def test(self, ctx):
        return not ctx.brain._busy
