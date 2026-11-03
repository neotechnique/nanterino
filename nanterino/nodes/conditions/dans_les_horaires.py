"""Condition `dans_les_horaires` (Dans les horaires d'ouverture) - graph node module (lot M2, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph); the engine
negates it for `{not: ...}`.
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino import hours as hours_mod
from nanterino.nodes.base import Condition


class DansLesHoraires(Condition):
    id = 'dans_les_horaires'
    order = 80
    label = "Dans les horaires d'ouverture"
    help = "Les horaires `opening_hours` de la configuration sont en cours (toujours vrai s'ils sont vides)."
    icon = 'calendar-time'
    theme = 'temps'

    def test(self, ctx):
        return hours_mod.is_open(hours_mod.safe_parse(ctx.cfg.get("opening_hours")), ctx.brain._wall_dt())
