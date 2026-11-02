"""Trigger `conversation_ended` (Une conversation se termine) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: conversation_ended` react to it.
Producer: Brain._go (entry into veille / eteint from a conversation state).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class ConversationEnded(Trigger):
    id = 'conversation_ended'
    order = 480
    label = 'Une conversation se termine'
    help = "Le robot revient en veille (ou s'éteint) après une conversation."
    icon = 'door-exit'
    theme = 'conversation'
