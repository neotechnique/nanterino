"""Trigger `expression_changed` (L'expression du visage change) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: expression_changed` react to it.
Producer: Brain.set_expression (set_expression action) and Brain._expr_tick (heartbeat: expiry back to neutre).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class ExpressionChanged(Trigger):
    id = 'expression_changed'
    order = 410
    label = "L'expression du visage change"
    help = "Le visage change d'expression (« Changer l'expression du visage », ou retour à « neutre » quand la durée est finie) ; lire la variable système expression. Anti-boucle comme « Une variable change »."
    icon = 'mood-smile'
    theme = 'vision'
