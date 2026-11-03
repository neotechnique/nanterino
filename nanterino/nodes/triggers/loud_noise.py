"""Trigger `loud_noise` (Un bruit fort) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: loud_noise` react to it.
Producer: Brain._audio_tick (heartbeat: mic level crosses brain.LOUD_LEVEL).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class LoudNoise(Trigger):
    id = 'loud_noise'
    order = 550
    label = 'Un bruit fort'
    help = 'Le niveau du micro ouvert atteint 60 (sur 100, comme la barre du tableau de bord) ; posté une fois, ré-armé quand il redescend sous 30 (kw value = le niveau). Anti-boucle comme « Une variable change ».'
    icon = 'microphone'
    theme = 'micro'
