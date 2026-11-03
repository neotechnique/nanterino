"""Trigger `answer_started` (Une réponse commence) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: answer_started` react to it.
Producer: start_answer action (Brain._changed).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class AnswerStarted(Trigger):
    id = 'answer_started'
    order = 450
    label = 'Une réponse commence'
    help = 'Le robot commence à chercher et dire sa réponse (« Répondre à la question ») ; la fin est « Réponse terminée ». Anti-boucle comme « Une variable change ».'
    icon = 'message'
    theme = 'conversation'
