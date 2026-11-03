"""Action `shift_date` (Décaler une date) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
import datetime
from nanterino.nodes.base import Action, Arg


class ShiftDate(Action):
    id = 'shift_date'
    order = 610
    label = 'Décaler une date'
    help = 'Ajoute un nombre de secondes (négatif pour reculer) à une variable date et heure ; une date vide reste vide.'
    icon = 'calendar-time'
    theme = 'temps'
    args = {'name': Arg('datetimevar', 'Variable date'), 'seconds': Arg('number', 'Secondes (négatif = avant)')}

    def run(self, ctx, name, seconds):
        from nanterino import graph as graph_mod   # lazy: graph.py imports the node packages
        b = ctx.brain
        dt = graph_mod.parse_iso(b.var_value(name))
        if dt is None or not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
            return
        b._set_var(name, (dt + datetime.timedelta(seconds=seconds)).replace(microsecond=0).isoformat())
