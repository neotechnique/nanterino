"""Trigger `media_finished` (Un son est fini) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by brain.py (see
the producer named below); transitions with `on: media_finished` react to it.
Producer: Brain.play_media (end of playback) / Brain._schedule_at in the simulator.
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Trigger


class MediaFinished(Trigger):
    id = 'media_finished'
    order = 270
    label = 'Un son est fini'
    help = 'Le son lancé par « Jouer un son » est fini (aussitôt si le fichier ne peut pas être lu) ; pas après Stop, Chut ou Éteindre.'
    icon = 'music'
    theme = 'parole'
