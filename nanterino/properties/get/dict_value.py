"""Value source `dict_value` (Valeur d'un dictionnaire) - property module (lot M4, 2026-11-01).

The key is matched like the dictionary conditions (nodes.helpers.match_key): a literal / `$x` key must exist,
`$utterance` = the first key contained in the sentence. Output type = the dictionary's value type; a missing key
gives that type's default.
How to test: .venv/bin/python -m tests.test_properties
"""
from nanterino.nodes.base import Arg
from nanterino.nodes.helpers import match_key
from nanterino.properties import GetSource, default_of


class DictValue(GetSource):
    id = "dict_value"
    order = 50
    label = "Valeur d'un dictionnaire"
    help = "La valeur associée à une clé d'un dictionnaire (valeur par défaut du type si la clé manque)."
    icon = "keyboard"
    out = ("of", "dict")
    args = {"dict": Arg("dict", "Dictionnaire"), "key": Arg("key", "Clé")}

    def check(self, parser, field_type, dict, key):  # noqa: A002 (argument names fixed by the vocabulary)
        return parser.lists[dict].type

    def get(self, ctx, dict, key):  # noqa: A002
        b = ctx.brain
        k = match_key(b, ctx.kw, dict, key)
        li = ctx.graph.lists.get(dict)
        if k is None:
            return default_of(li.type if li is not None else None)
        return (b.lists.get(dict) or {})[k]
