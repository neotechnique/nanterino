"""Value source `intent_match` (La phrase correspond à un motif) - property module (lot M4, 2026-11-01).

True when the sentence (being handled, else the last one heard) matches the intent's words / words_from / regex,
the test GraphEngine.classify applies (without only_in: this asks about one intent, not the dispatch). The implicit
`question` intent is refused (it is "no other intent", not a pattern).
How to test: .venv/bin/python -m tests.test_properties
"""
from nanterino.nodes.base import Arg
from nanterino.properties import GetSource, PropertyError


class IntentMatch(GetSource):
    id = "intent_match"
    order = 90
    label = "La phrase correspond à un motif"
    help = "Vrai si la phrase du visiteur correspond au motif choisi (mots ou expression)."
    icon = "message"
    out = "bool"
    args = {"intent": Arg("intent", "Motif")}

    def check(self, parser, field_type, intent):
        if intent == "question":
            raise PropertyError("`question` is the fallback intent (no other match), not a pattern")
        return "bool"

    def get(self, ctx, intent):
        text = ctx.brain._resolve("$utterance", ctx.kw)
        low = text.lower() if isinstance(text, str) else ""
        it = next((i for i in ctx.graph.intents if i.name == intent), None)
        if it is None or not low:
            return False
        if it.words and any(w in low for w in it.words):
            return True
        if it.words_from and any(isinstance(w, str) and w in low for w in (ctx.cfg.get(it.words_from) or ())):
            return True
        return bool(it.regex is not None and it.regex.search(low))
