"""Write target `dict_key` (Clé de dictionnaire) - property module (lot M4, 2026-11-01).

Used by dict_set: key resolved like before (a literal, `$x`, `$utterance` = the whole sentence, or a source),
stripped and cut to graph.KEY_MAX; an empty key writes nothing. The value goes through the dictionary value type's
clamp; a dictionary missing from the brain gets a fresh container from its list kind (LISTKINDS).
How to test: .venv/bin/python -m tests.test_properties
"""
from nanterino.nodes.base import Arg
from nanterino.properties import SetTarget


class DictKey(SetTarget):
    id = "dict_key"
    order = 30
    label = "Clé de dictionnaire"
    help = "Associe la valeur à une clé d'un dictionnaire (remplace l'ancienne valeur)."
    icon = "keyboard"
    args = {"dict": Arg("wdict", "Dictionnaire"), "key": Arg("key", "Clé")}

    def check(self, parser, dict, key):  # noqa: A002 (argument names fixed by the vocabulary)
        return parser.lists[dict].type

    def write(self, ctx, value, dict, key):  # noqa: A002
        from nanterino import graph as G
        from nanterino.listkinds import LISTKINDS
        from nanterino.vartypes import VARTYPES
        b = ctx.brain
        k = b._resolve(key, ctx.kw)
        if not (isinstance(k, str) and k.strip()):
            return
        li = ctx.graph.lists.get(dict)
        if dict not in b.lists:
            b.lists[dict] = LISTKINDS[li.kind].fresh({}) if li is not None else {}
        b.lists[dict][k.strip()[:G.KEY_MAX]] = VARTYPES[li.type].clamp(value) if li is not None else value
