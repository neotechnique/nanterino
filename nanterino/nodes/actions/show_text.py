"""Action `show_text` (Afficher un texte) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Producer of text_shown (now) and text_cleared (heartbeat): Brain.show_text / Brain._text_tick.
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.log import log
from nanterino.nodes.base import Action, Arg


class ShowText(Action):
    id = 'show_text'
    order = 430
    label = 'Afficher un texte'
    help = "Affiche un texte sous le visage (ligne des sous-titres) pendant la durée donnée, sans le dire. « Un texte s'affiche » tout de suite, « Le texte affiché disparaît » à la fin (ou quand une parole le remplace)."
    icon = 'text-caption'
    theme = 'vision'
    args = {'text': Arg('text', 'Texte'), 'seconds': Arg('seconds', 'Durée (secondes)')}

    def run(self, ctx, text, seconds):
        # lot L27: text_shown / text_cleared always follow, even for an empty text or a bad duration (journal warning)
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            seconds = 0.0
        if not (isinstance(text, str) and text.strip()):
            log.warning("show_text: text is empty, an empty line is shown", extra={"graph_note": True})
            ctx.brain.note_journal("warning", "graph")
            text = ""
        ctx.brain.show_text(text, seconds)
