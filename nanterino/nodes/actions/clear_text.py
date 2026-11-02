"""Action `clear_text` (Effacer le texte affiché) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Action


class ClearText(Action):
    id = 'clear_text'
    order = 540
    label = 'Effacer le texte affiché'
    help = "Retire tout de suite le texte sous le visage (sous-titre) ; « Le texte affiché disparaît » suit s'il venait de « Afficher un texte »."
    icon = 'eraser'
    theme = 'vision'
    args = {}

    def run(self, ctx):
        # Brain._text_tick posts text_cleared on the next beat when a show_text text was on screen
        ctx.brain.subtitle = ""
