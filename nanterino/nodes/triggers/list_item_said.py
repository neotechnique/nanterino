"""Trigger `list_item_said` (Un élément de liste est dit) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by brain.py (see
the producer named below); transitions with `on: list_item_said` react to it.
Producer: Brain._speak_then (done event of say_list_item).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Trigger


class ListItemSaid(Trigger):
    id = 'list_item_said'
    order = 330
    label = 'Un élément de liste est dit'
    help = "Le robot a fini de dire l'élément de liste demandé par « Dire l'élément d'une liste »."
    icon = 'volume'
    theme = 'parole'
