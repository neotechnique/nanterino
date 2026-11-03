"""Condition `phrase_ready` (La voix d'un texte est prête) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: La voix de ce texte (« Dire un texte » du graphe, phrases de la configuration) est déjà calculée : il sera dit sans attente ; faux pendant le calcul au chargement du graphe.
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Arg, Condition


class PhraseReady(Condition):
    id = 'phrase_ready'
    order = 570
    label = "La voix d'un texte est prête"
    help = 'La voix de ce texte (« Dire un texte » du graphe, phrases de la configuration) est déjà calculée : il sera dit sans attente ; faux pendant le calcul au chargement du graphe.'
    icon = 'volume'
    theme = 'parole'
    args = {'text': Arg('optext', 'Texte')}

    def test(self, ctx, text):
        t = ctx.brain._resolve(text, ctx.kw)
        return isinstance(t, str) and bool(t.strip()) and t in ctx.brain._phrases
