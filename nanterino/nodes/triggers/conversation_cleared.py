"""Trigger `conversation_cleared` (La conversation est oubliée) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: conversation_cleared` react to it.
Producer: clear_conversation action (Brain._changed).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class ConversationCleared(Trigger):
    id = 'conversation_cleared'
    order = 460
    label = 'La conversation est oubliée'
    help = "Le robot vient d'oublier la conversation (« Oublier la conversation ») : historique, tours et variables de conversation remis à zéro. Anti-boucle comme « Une variable change »."
    icon = 'eraser'
    theme = 'conversation'
