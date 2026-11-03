"""Trigger `random_drawn` (Un tirage au hasard est fait) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: random_drawn` react to it.
Producer: random_choice action (Brain._changed).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class RandomDrawn(Trigger):
    id = 'random_drawn'
    order = 580
    label = 'Un tirage au hasard est fait'
    help = "« Choisir au hasard » vient de tirer un nombre (kw value = le nombre tiré) ; lire la variable qui l'a reçu. Anti-boucle comme « Une variable change »."
    icon = 'question-mark'
    theme = 'variables'
