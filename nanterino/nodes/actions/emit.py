"""Action `emit` (Déclencher un événement) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class Emit(Action):
    id = 'emit'
    order = 190
    label = 'Déclencher un événement'
    help = 'Envoie tout de suite un événement au graphe.'
    icon = 'bolt'
    theme = 'evenements'
    args = {'event': Arg('event', 'Événement à déclencher')}

    def run(self, ctx, event):
        ctx.brain._event_at[event] = ctx.brain.now()   # lot N2: event_recent sees emitted events too
        ctx.brain.engine.dispatch(event, {})
