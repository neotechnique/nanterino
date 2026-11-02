"""Condition `graph_update_waiting` (Un graphe enregistré attend) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Un graphe enregistré depuis l'éditeur attend le retour en veille (ou l'arrêt) pour s'appliquer.
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Condition


class GraphUpdateWaiting(Condition):
    id = 'graph_update_waiting'
    order = 630
    label = 'Un graphe enregistré attend'
    help = "Un graphe enregistré depuis l'éditeur attend le retour en veille (ou l'arrêt) pour s'appliquer."
    icon = 'git-branch'
    theme = 'systeme'
    args = {}

    def test(self, ctx):
        return bool(ctx.brain.graph_pending)
