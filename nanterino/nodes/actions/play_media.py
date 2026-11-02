"""Action `play_media` (Jouer un son) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Producer of media_started / media_finished: Brain.play_media (same audio output as speech).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Action, Arg


class PlayMedia(Action):
    id = 'play_media'
    order = 390
    label = 'Jouer un son'
    help = "Joue un fichier son (.wav) du dossier media/ par le haut-parleur, comme la chanson (muet = reste muet). « Un son commence » au départ, « Un son est fini » à la fin ; Stop, Chut ou Éteindre l'arrêtent."
    icon = 'music'
    theme = 'parole'
    args = {'file': Arg('media', 'Fichier son')}

    def run(self, ctx, file):
        ctx.brain.play_media(file)
