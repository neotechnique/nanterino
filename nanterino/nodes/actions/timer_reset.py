"""Action `timer_reset` (Arrêter un chrono) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class TimerReset(Action):
    id = 'timer_reset'
    order = 330
    label = 'Arrêter un chrono'
    help = "Arrête et remet à zéro un chronomètre : il ne déclenche plus rien jusqu'au prochain départ."
    icon = 'refresh'
    theme = 'temps'
    args = {'name': Arg('timervar', 'Chrono')}

    def run(self, ctx, name):
        ctx.brain._set_var(name, None)
