"""Action `set_deaf` (Mode sourd) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Producer of deaf_changed: Brain.set_deaf (also used by the dashboard Sourd button).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Action, Arg


class SetDeaf(Action):
    id = 'set_deaf'
    order = 420
    label = 'Mode sourd'
    help = "Active ou coupe le mode sourd, comme le bouton Sourd du tableau de bord (gardé au redémarrage) : sourd, le micro reste fermé. « Le mode sourd change » s'il a changé."
    icon = 'microphone-off'
    theme = 'micro'
    args = {'mode': Arg('onoff', 'Sourd')}

    def run(self, ctx, mode):
        ctx.brain.set_deaf(mode == 'on', external=False, persist=True)
