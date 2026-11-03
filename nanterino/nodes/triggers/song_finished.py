"""Trigger `song_finished` (La chanson est finie) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: song_finished` react to it.
Producer: Brain._sing at the normal end (or at once when the song file is missing); simulator: Brain.start_song.
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class SongFinished(Trigger):
    id = 'song_finished'
    order = 440
    label = 'La chanson est finie'
    help = "La chanson est allée jusqu'au bout (juste avant « Réponse terminée ») ; un arrêt, « Tais-toi » ou Éteindre l'annulent sans cet événement."
    icon = 'music'
    theme = 'parole'
