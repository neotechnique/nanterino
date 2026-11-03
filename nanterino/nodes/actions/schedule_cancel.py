"""Action `schedule_cancel` (Annuler un événement programmé) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Action, Arg


class ScheduleCancel(Action):
    id = 'schedule_cancel'
    order = 590
    label = 'Annuler un événement programmé'
    help = "Retire les « Programmer un événement » de cet événement qui attendent encore ; « Un événement programmé est annulé » s'il y en avait."
    icon = 'x'
    theme = 'temps'
    args = {'event': Arg('event', 'Événement')}

    def run(self, ctx, event):
        b = ctx.brain
        with b._sched_lock:   # same list and lock as the schedule action / Brain._release_scheduled
            before = len(b._scheduled)
            b._scheduled = [x for x in b._scheduled if x[1] != event]
            removed = before - len(b._scheduled)
        if removed:
            b._changed("schedule_cancelled", value=event)
