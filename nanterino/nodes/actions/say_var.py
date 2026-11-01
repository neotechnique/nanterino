"""Action `say_var` (Dire une variable phrase) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.log import log
from nanterino.nodes.base import Action, Arg


class SayVar(Action):
    id = 'say_var'
    order = 340
    label = 'Dire une variable phrase'
    help = "Dit le texte d'une variable phrase ou texte (voix calculée à l'avance pour les phrases écrites dans le graphe ; muet = reste muet), puis say_done. Variable vide : rien n'est dit."
    icon = 'text-caption'
    theme = 'parole'
    args = {'name': Arg('textvar', 'Variable')}

    def run(self, ctx, name):
        b = ctx.brain
        text = b.var_value(name)
        if isinstance(text, str) and text.strip():
            b._speak_then(text, "say_done")
        else:
            log.info("say_var: %s is empty, nothing said", name)
