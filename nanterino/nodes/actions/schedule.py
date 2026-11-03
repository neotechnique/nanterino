"""Action `schedule` (Programmer un événement) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class Schedule(Action):
    id = 'schedule'
    order = 180
    label = 'Programmer un événement'
    help = 'Déclenche un événement après un délai (annulé si le robot est arrêté entre-temps).'
    icon = 'clock'
    theme = 'temps'
    args = {'event': Arg('event', 'Événement à déclencher'), 'delay': Arg('delay', 'Délai (secondes ou clé de configuration)')}

    def run(self, ctx, event, delay):
        b = ctx.brain
        d = float(delay if isinstance(delay, (int, float)) else ctx.cfg[delay])
        with b._sched_lock:  # gen captured now: stop/off before the due time drops the event
            b._scheduled.append((b.now() + d, event, b.gen))
