"""Trigger `gaze_changed` (Le regard change) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: gaze_changed` react to it.
Producer: Brain.set_gaze (gaze action, return to suivre in Brain._go).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class GazeChanged(Trigger):
    id = 'gaze_changed'
    order = 420
    label = 'Le regard change'
    help = 'Le mode du regard change (« Régler le regard », ou retour à « suivre » en veille) ; lire la variable système regard. Anti-boucle comme « Une variable change ».'
    icon = 'eye'
    theme = 'vision'
