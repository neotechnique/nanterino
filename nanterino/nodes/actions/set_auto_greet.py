"""Action `set_auto_greet` (Accueil automatique) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Action, Arg


class SetAutoGreet(Action):
    id = 'set_auto_greet'
    order = 560
    label = 'Accueil automatique'
    help = "Active ou coupe l'accueil automatique : un visage vu par la caméra lance « Un visage apparaît » (réglage auto_greet_on_face, jusqu'au prochain redémarrage)."
    icon = 'scan-eye'
    theme = 'vision'
    args = {'mode': Arg('onoff', 'Accueil automatique')}

    def run(self, ctx, mode):
        # server.py's vision callback reads cfg["auto_greet_on_face"] (same dict) before posting `visage`
        ctx.cfg["auto_greet_on_face"] = mode == "on"
