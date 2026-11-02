"""Action `set_barge_in` (Interruption) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Action, Arg


class SetBargeIn(Action):
    id = 'set_barge_in'
    order = 530
    label = 'Interruption'
    help = "Active ou coupe l'interruption : le visiteur peut couper la parole du robot pendant une réponse (réglage barge_in, jusqu'au prochain redémarrage)."
    icon = 'hand-stop'
    theme = 'micro'
    args = {'mode': Arg('onoff', 'Interruption')}

    def run(self, ctx, mode):
        # The brain's cfg is the server's live config dict: Brain._on_speech_start and the barge_in condition read it.
        ctx.cfg["barge_in"] = mode == "on"
