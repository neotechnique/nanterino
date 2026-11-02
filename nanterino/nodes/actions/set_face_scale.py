"""Action `set_face_scale` (Taille du visage) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Action, Arg


class SetFaceScale(Action):
    id = 'set_face_scale'
    order = 570
    label = 'Taille du visage'
    help = "Règle la taille du visage à l'écran, de 50 à 160 %, comme le réglage du tableau de bord (jusqu'au prochain redémarrage)."
    icon = 'eye'
    theme = 'vision'
    args = {'percent': Arg('number', 'Taille (50 à 160 %)')}

    def run(self, ctx, percent):
        # /api/live hands cfg["face_scale"] to the face page; same bounds as the dashboard control (server.py)
        p = percent if isinstance(percent, (int, float)) and not isinstance(percent, bool) else 100
        ctx.cfg["face_scale"] = max(0.5, min(1.6, float(p) / 100.0))
