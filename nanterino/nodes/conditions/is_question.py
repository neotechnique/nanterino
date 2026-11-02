"""Condition `is_question` (La phrase du visiteur est une question) - graph node module (lot N2, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); test() is bound to the Brain by
brain._build_engine and evaluated on the brain loop thread (fast, reads state only).
Reads: La phrase du visiteur finit par « ? » ou commence par un mot interrogatif (qui, quoi, où, quand, comment, pourquoi, combien, quel, est-ce que ...).
How to test: .venv/bin/python -m tests.test_nodes_n2 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.nodes.base import Condition


class IsQuestion(Condition):
    id = 'is_question'
    order = 380
    label = 'La phrase du visiteur est une question'
    help = 'La phrase du visiteur finit par « ? » ou commence par un mot interrogatif (qui, quoi, où, quand, comment, pourquoi, combien, quel, est-ce que ...).'
    icon = 'question-mark'
    theme = 'conversation'

    def test(self, ctx):
        said = ctx.brain._resolve('$utterance', ctx.kw)
        return isinstance(said, str) and _question(said)


# French question words at the start of a sentence (Whisper does not always write the final « ? »).
_QWORDS = ("qui", "que", "quoi", "où", "quand", "comment", "pourquoi", "combien", "quel", "quelle", "quels",
           "quelles", "lequel", "laquelle", "est-ce", "qu'est-ce", "est ce", "qu'est ce")


def _question(text: str) -> bool:
    low = text.strip().lower()
    if low.endswith("?"):
        return True
    return any(low == w or low.startswith(w + " ") or low.startswith(w + "-") or low.startswith(w + "'") for w in _QWORDS)
