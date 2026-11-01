"""Action `say_text` (Dire un texte) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class SayText(Action):
    id = 'say_text'
    order = 200
    label = 'Dire un texte'
    help = "Dit une phrase libre (voix calculée à l'avance au chargement du graphe ; muet = reste muet), puis déclenche say_done."
    icon = 'text-caption'
    theme = 'parole'
    args = {'text': Arg('text', 'Phrase à dire')}

    def run(self, ctx, text):
        ctx.brain._speak_then(text, "say_done")
