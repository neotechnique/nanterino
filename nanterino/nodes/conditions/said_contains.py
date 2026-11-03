"""Condition `said_contains` (La phrase du robot contient) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: La dernière phrase dite par le robot (ou sa réponse) contient ce texte, sans tenir compte des majuscules ; faux si le texte est vide.
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class SaidContains(Condition):
    id = 'said_contains'
    order = 520
    label = 'La phrase du robot contient'
    help = 'La dernière phrase dite par le robot (ou sa réponse) contient ce texte, sans tenir compte des majuscules ; faux si le texte est vide.'
    icon = 'message'
    theme = 'parole'
    args = {'text': Arg('optext', 'Texte cherché')}

    def test(self, ctx, text):
        t = str(ctx.brain._resolve(text, ctx.kw) or "").strip().lower()
        return bool(t) and t in (ctx.brain.last_said or "").lower()
