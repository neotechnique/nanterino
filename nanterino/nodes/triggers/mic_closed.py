"""Trigger `mic_closed` (Le micro se ferme) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: mic_closed` react to it.
Producer: Brain.mic_set (mic_off / mic_off_no_barge_in actions, set_deaf), only on a real open-to-closed change.
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class MicClosed(Trigger):
    id = 'mic_closed'
    order = 400
    label = 'Le micro se ferme'
    help = 'Le micro vient de se fermer (« Couper le micro », mode sourd) ; anti-boucle comme « Une variable change ».'
    icon = 'microphone-off'
    theme = 'micro'
