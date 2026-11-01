"""Value source `utterance` (Phrase entendue) - property module (lot M4, 2026-11-01).

`$utterance` is its shorthand: in the fields that always accepted it, both compile to "$utterance" (a list search /
dictionary key keeps its "contained in the sentence" meaning). Run time: the sentence being handled, else the last
one heard, "" when none.
How to test: .venv/bin/python -m tests.test_properties
"""
from nanterino.properties import GetSource


class Utterance(GetSource):
    id = "utterance"
    order = 30
    label = "Phrase entendue"
    help = "La phrase que le visiteur vient de dire (sinon la dernière entendue)."
    icon = "ear"
    out = "phrase"
    shorthand = "utterance"
    args = {}

    def check(self, parser, field_type):
        if not parser.value_ok(field_type, "$utterance"):   # the pre-M4 `$utterance` check and message
            return None
        return "phrase"

    def get(self, ctx):
        v = ctx.brain._resolve("$utterance", ctx.kw)
        return v if isinstance(v, str) else ""
