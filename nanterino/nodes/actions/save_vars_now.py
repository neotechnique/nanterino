"""Action `save_vars_now` (Enregistrer les variables maintenant) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Action


class SaveVarsNow(Action):
    id = 'save_vars_now'
    order = 650
    label = 'Enregistrer les variables maintenant'
    help = "Écrit tout de suite les variables et listes « gardées au redémarrage » dans le fichier du robot (state/vars.json), sans attendre l'écriture automatique (2 s au plus)."
    icon = 'lock'
    theme = 'systeme'
    args = {}

    def run(self, ctx):
        b = ctx.brain
        if b._store is None:   # simulator / no store: nothing is persisted
            return
        b._persist_tick(b.now())   # hand the changed values to the store (same code as the heartbeat)
        b._store.flush()
