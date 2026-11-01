"""Action `wait` (Attendre) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class Wait(Action):
    id = 'wait'
    order = 220
    label = 'Attendre'
    help = "Pause sans bloquer le robot : la suite de la chaîne reprend après le délai, les autres événements continuent d'être traités."
    icon = 'hourglass'
    theme = 'temps'
    args = {'seconds': Arg('delay', 'Durée (secondes ou clé de configuration)')}

    def run(self, ctx, seconds):
        # Never called for real: GraphEngine._exec handles `wait` itself (it needs the rest of the chain and
        # hands it to brain.defer). Kept so the registry stays complete and a direct call is a harmless no-op.
        return None
