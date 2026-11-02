"""Trigger `conversation_started` (Une conversation commence) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: conversation_started` react to it.
Producer: Brain._go (exit from veille / eteint into a conversation state).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class ConversationStarted(Trigger):
    id = 'conversation_started'
    order = 470
    label = 'Une conversation commence'
    help = "Le robot quitte la veille (ou l'arrêt) pour un état de conversation : un nouveau visiteur commence."
    icon = 'users'
    theme = 'conversation'
