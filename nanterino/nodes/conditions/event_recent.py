"""Condition `event_recent` (Un événement a eu lieu récemment) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: Cet événement a eu lieu il y a au plus ce nombre de secondes (y compris celui qui lance la chaîne) ; faux s'il n'a pas eu lieu depuis le démarrage.
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class EventRecent(Condition):
    id = 'event_recent'
    order = 480
    label = 'Un événement a eu lieu récemment'
    help = "Cet événement a eu lieu il y a au plus ce nombre de secondes (y compris celui qui lance la chaîne) ; faux s'il n'a pas eu lieu depuis le démarrage."
    icon = 'bolt'
    theme = 'evenements'
    args = {'event': Arg('event', 'Événement'), 'seconds': Arg('seconds0', 'Secondes')}

    def test(self, ctx, event, seconds):
        age = ctx.brain.event_age(event)
        return age is not None and age <= seconds
