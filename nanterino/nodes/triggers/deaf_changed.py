"""Trigger `deaf_changed` (Le mode sourd change) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by brain.py (see
the producer named below); transitions with `on: deaf_changed` react to it.
Producer: Brain.set_deaf.
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Trigger


class DeafChanged(Trigger):
    id = 'deaf_changed'
    order = 300
    label = 'Le mode sourd change'
    help = "Le mode sourd vient d'être activé ou coupé (tableau de bord ou « Mode sourd ») ; à combiner avec la condition « Le robot est sourd ». Anti-boucle comme « Une variable change »."
    icon = 'microphone-off'
    theme = 'micro'
