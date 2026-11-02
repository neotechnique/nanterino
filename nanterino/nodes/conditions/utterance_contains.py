"""Condition `utterance_contains` (La phrase du visiteur contient) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: La phrase du visiteur (celle traitée, sinon la dernière entendue) contient ce texte, sans tenir compte des majuscules ; faux si le texte est vide.
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class UtteranceContains(Condition):
    id = 'utterance_contains'
    order = 370
    label = 'La phrase du visiteur contient'
    help = 'La phrase du visiteur (celle traitée, sinon la dernière entendue) contient ce texte, sans tenir compte des majuscules ; faux si le texte est vide.'
    icon = 'message'
    theme = 'conversation'
    args = {'text': Arg('optext', 'Texte cherché')}

    def test(self, ctx, text):
        said = ctx.brain._resolve('$utterance', ctx.kw)
        want = str(text or '').strip().lower()
        return bool(want) and isinstance(said, str) and want in said.lower()
