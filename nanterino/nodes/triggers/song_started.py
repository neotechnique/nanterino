"""Trigger `song_started` (La chanson commence) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: song_started` react to it.
Producer: Brain.start_song (start_sing action).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class SongStarted(Trigger):
    id = 'song_started'
    order = 430
    label = 'La chanson commence'
    help = 'Le robot commence sa chanson (« Chanter ») ; à combiner avec « Le robot chante ». Anti-boucle comme « Une variable change ».'
    icon = 'music'
    theme = 'parole'
