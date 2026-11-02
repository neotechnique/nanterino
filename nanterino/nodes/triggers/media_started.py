"""Trigger `media_started` (Un son commence) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by brain.py (see
the producer named below); transitions with `on: media_started` react to it.
Producer: Brain.play_media.
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Trigger


class MediaStarted(Trigger):
    id = 'media_started'
    order = 260
    label = 'Un son commence'
    help = 'Un son lancé par « Jouer un son » commence (kw file = le fichier). Une chaîne lancée par ce déclencheur ne relance pas de déclencheur de changement (anti-boucle).'
    icon = 'music'
    theme = 'parole'
