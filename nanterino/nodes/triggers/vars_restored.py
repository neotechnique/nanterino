"""Trigger `vars_restored` (Les variables enregistrées sont relues) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by the real code path named
below; transitions with `on: vars_restored` react to it.
Producer: Brain._load_persisted (plain post after a store read).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Trigger


class VarsRestored(Trigger):
    id = 'vars_restored'
    order = 590
    label = 'Les variables enregistrées sont relues'
    help = "Au démarrage du robot ou au chargement d'un graphe, au moins une variable ou liste « gardée au redémarrage » a repris sa valeur enregistrée (kw value = combien)."
    icon = 'refresh'
    theme = 'variables'
