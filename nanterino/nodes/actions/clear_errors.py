"""Action `clear_errors` (Oublier les erreurs récentes) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Action


class ClearErrors(Action):
    id = 'clear_errors'
    order = 630
    label = 'Oublier les erreurs récentes'
    help = 'Les erreurs déjà reçues par le journal du robot ne comptent plus pour « Une erreur récente » (le fichier errors.log garde tout).'
    icon = 'eraser'
    theme = 'systeme'
    args = {}

    def run(self, ctx):
        notes = ctx.brain.journal_notes   # (wall epoch, level, source); the log tap may append from another thread
        keep = [x for x in list(notes) if x[1] != "error"]
        notes.clear()
        notes.extend(keep)
