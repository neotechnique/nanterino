"""Condition `auto_greet_on_face` (L'accueil automatique est activé) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Condition


class AutoGreetOnFace(Condition):
    id = 'auto_greet_on_face'
    order = 10
    label = "L'accueil automatique est activé"
    help = 'Réglage « accueil automatique » de la configuration.'
    icon = 'scan-eye'
    theme = 'vision'

    def test(self, ctx):
        return bool(ctx.cfg.get("auto_greet_on_face"))
