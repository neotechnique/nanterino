"""Trigger `mic_opened` (Le micro s'ouvre) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: mic_opened` react to it.
Producer: Brain.mic_set (mic_on action, Brain._mic_on, set_deaf), only on a real closed-to-open change.
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class MicOpened(Trigger):
    id = 'mic_opened'
    order = 390
    label = "Le micro s'ouvre"
    help = "Le micro vient de s'ouvrir (« Ouvrir le micro », fin du mode sourd, entrée dans un état qui écoute) ; à combiner avec « Le micro est ouvert ». Anti-boucle comme « Une variable change »."
    icon = 'microphone'
    theme = 'micro'
