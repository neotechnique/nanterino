"""Action `set_mute` (Mode muet) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Producer of mute_changed: Brain.set_muted (also used by the dashboard Muet button).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Action, Arg


class SetMute(Action):
    id = 'set_mute'
    order = 410
    label = 'Mode muet'
    help = "Active ou coupe le mode muet, comme le bouton Muet du tableau de bord (gardé au redémarrage) : muet, le robot continue mais on ne l'entend plus. « Le mode muet change » s'il a changé."
    icon = 'volume-off'
    theme = 'parole'
    args = {'mode': Arg('onoff', 'Muet')}

    def run(self, ctx, mode):
        ctx.brain.set_muted(mode == 'on', persist=True)
