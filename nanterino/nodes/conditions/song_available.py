"""Condition `song_available` (La chanson est apprise) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Le fichier de la chanson existe : « Chanter » la jouera (sinon le robot dit qu'il ne l'a pas encore apprise).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
import os

from nanterino.nodes.base import Condition


class SongAvailable(Condition):
    id = 'song_available'
    order = 550
    label = 'La chanson est apprise'
    help = "Le fichier de la chanson existe : « Chanter » la jouera (sinon le robot dit qu'il ne l'a pas encore apprise)."
    icon = 'music'
    theme = 'parole'
    args = {}

    def test(self, ctx):
        return os.path.isfile(ctx.brain.song_path())
