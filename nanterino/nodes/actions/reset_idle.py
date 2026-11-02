"""Action `reset_idle` (Redémarrer le chrono d'inactivité) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Action


class ResetIdle(Action):
    id = 'reset_idle'
    order = 600
    label = "Redémarrer le chrono d'inactivité"
    help = "L'activité est considérée comme étant maintenant : « Longue inactivité » attend de nouveau idle_long_s secondes sans visage ni parole."
    icon = 'hourglass'
    theme = 'temps'
    args = {}

    def run(self, ctx):
        ctx.brain._activity()   # last_activity = now, inactivite_longue re-armed
