"""Trigger `mute_changed` (Le mode muet change) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by brain.py (see
the producer named below); transitions with `on: mute_changed` react to it.
Producer: Brain.set_muted.
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Trigger


class MuteChanged(Trigger):
    id = 'mute_changed'
    order = 290
    label = 'Le mode muet change'
    help = "Le mode muet vient d'être activé ou coupé (tableau de bord ou « Mode muet ») ; à combiner avec la condition « Le robot est muet ». Anti-boucle comme « Une variable change »."
    icon = 'volume-off'
    theme = 'parole'
