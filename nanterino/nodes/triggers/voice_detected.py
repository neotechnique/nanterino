"""Trigger `voice_detected` (Le visiteur commence à parler) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: voice_detected` react to it.
Producer: Brain._on_speech_start (AudioIn's voice-activity start, mic thread).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class VoiceDetected(Trigger):
    id = 'voice_detected'
    order = 540
    label = 'Le visiteur commence à parler'
    help = 'Le micro entend une voix commencer (détection de parole, avant la transcription) ; posté à chaque début de phrase du visiteur. Anti-boucle comme « Une variable change ».'
    icon = 'ear'
    theme = 'micro'
