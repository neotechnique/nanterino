"""Trigger `volume_changed` (Le volume change) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by brain.py (see
the producer named below); transitions with `on: volume_changed` react to it.
Producer: Brain.set_volume.
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Trigger


class VolumeChanged(Trigger):
    id = 'volume_changed'
    order = 280
    label = 'Le volume change'
    help = 'Le volume du haut-parleur vient de changer (tableau de bord ou « Régler le volume ») ; lire la variable système volume. Anti-boucle comme « Une variable change ».'
    icon = 'volume'
    theme = 'parole'
