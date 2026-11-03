"""Trigger `turn_counted` (Un tour de parole est compté) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: turn_counted` react to it.
Producer: count_turn action (Brain._changed, value = the new count).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class TurnCounted(Trigger):
    id = 'turn_counted'
    order = 490
    label = 'Un tour de parole est compté'
    help = "« Compter un tour de parole » vient d'ajouter un échange ; lire la variable système tours ou « Comparer les tours de parole ». Anti-boucle comme « Une variable change »."
    icon = 'plus'
    theme = 'conversation'
