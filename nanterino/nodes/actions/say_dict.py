"""Action `say_dict` (Dire la valeur d'une clé) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.log import log
from nanterino.nodes.helpers import match_key
from nanterino.nodes.base import Action, Arg


class SayDict(Action):
    id = 'say_dict'
    order = 380
    label = "Dire la valeur d'une clé"
    help = "Dit le texte associé à une clé d'un dictionnaire de textes ; avec « $utterance », la première clé contenue dans la phrase entendue. Clé absente : dit le texte de repli (rien s'il est vide), puis say_done."
    icon = 'volume'
    theme = 'parole'
    args = {'dict': Arg('rtextdict', 'Dictionnaire de textes'), 'key': Arg('dictkey', 'Clé (ou $utterance)'), 'fallback': Arg('optext', 'Texte de repli')}

    def run(self, ctx, dict, key, fallback):  # noqa: A002 (argument names fixed by the graph vocabulary)
        b = ctx.brain
        k = match_key(b, ctx.kw, dict, key)
        text = (b.lists.get(dict) or {}).get(k) if k is not None else None
        if not (isinstance(text, str) and text.strip()):
            text = fallback
        if isinstance(text, str) and text.strip():
            b._speak_then(text, "say_done")
        else:
            log.info("say_dict: no value for key %r in %s and no fallback, nothing said", key, dict)
