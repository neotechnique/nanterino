"""Action `speak_phrase` (Dire une phrase fixe) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
from nanterino.nodes.base import Action, Arg


class SpeakPhrase(Action):
    id = 'speak_phrase'
    order = 170
    label = 'Dire une phrase fixe'
    help = "Dit une phrase de la configuration, puis déclenche l'événement indiqué."
    icon = 'volume'
    theme = 'parole'
    args = {'text': Arg('cfgkey', 'Phrase à dire'), 'done': Arg('event', 'Événement à la fin')}

    def run(self, ctx, text, done):
        phrase = ctx.cfg.get(text)
        if not (isinstance(phrase, str) and phrase.strip()):   # lot L27: a missing / emptied config phrase still ends
            ctx.brain.complete_silently("speak_phrase", done, "config phrase %s is empty" % text)
            return
        ctx.brain._speak_then(phrase, done)
