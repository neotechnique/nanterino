"""Action `set_volume` (Régler le volume) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Producer of volume_changed: Brain.set_volume (also used by the dashboard slider).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Action, Arg


class SetVolume(Action):
    id = 'set_volume'
    order = 400
    label = 'Régler le volume'
    help = "Règle le volume du haut-parleur de 0 à 100, comme le curseur du tableau de bord ; « Le volume change » s'il a changé."
    icon = 'volume'
    theme = 'parole'
    args = {'percent': Arg('number', 'Volume (0 à 100)')}

    def run(self, ctx, percent):
        if isinstance(percent, bool) or not isinstance(percent, (int, float)):
            return   # a value source that gave nothing usable: the volume stays
        ctx.brain.set_volume(min(100.0, max(0.0, float(percent))) / 100.0)
