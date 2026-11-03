"""Trigger `speech_started` (Le robot commence à parler) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: speech_started` react to it.
Producer: Brain._audio_tick (heartbeat: rising edge of out.busy).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class SpeechStarted(Trigger):
    id = 'speech_started'
    order = 530
    label = 'Le robot commence à parler'
    help = 'Le haut-parleur se met à jouer : une phrase, une réponse, la chanson ou un son (vu par le battement du robot, à 0,1 s près) ; à combiner avec « Le robot ne parle pas ». Anti-boucle comme « Une variable change ».'
    icon = 'volume'
    theme = 'parole'
