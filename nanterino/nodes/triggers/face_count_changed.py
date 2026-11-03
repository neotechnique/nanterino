"""Trigger `face_count_changed` (Le nombre de visages change) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: face_count_changed` react to it.
Producer: Brain.set_faces (vision thread on the live robot, simulator steps `faces`), external change.
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class FaceCountChanged(Trigger):
    id = 'face_count_changed'
    order = 520
    label = 'Le nombre de visages change'
    help = 'La caméra voit un nombre différent de visages (0, 1, 2 ...) ; à combiner avec « Comparer le nombre de visages ».'
    icon = 'scan-eye'
    theme = 'vision'
