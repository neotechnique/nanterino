"""List kind `dict`: key -> value pairs (values of the declared item type); always a writable user dictionary."""
from nanterino.listkinds import ListKind


class Dictionary(ListKind):
    id = "dict"
    order = 20
    label = "Dictionnaire"
    help = "Des paires clé → valeur (valeurs du type choisi)."

    def parse(self, parser, where, name, spec, item_type, mode, maxlen, scope, persist, desc, intent_names):
        import types
        from nanterino.graph import KEY_MAX, LIST_MAX, VarList
        from nanterino.listmodes import DEFAULT
        w, lt = where, item_type
        if "items" not in spec:
            parser.err(w, "a dictionary needs `items:` (key: value pairs); it cannot be bound"); return None
        if mode != DEFAULT or maxlen is not None:
            parser.err(w, "`mode:` / `max:` only go with kind list"); return None
        raw = spec["items"] if spec["items"] is not None else {}
        if not isinstance(raw, dict) or len(raw) > LIST_MAX:
            parser.err(w, "`items:` of a dictionary must be a mapping of at most %d keys" % LIST_MAX); return None
        n_err = len(parser.errors)
        for key, it in raw.items():
            if not (isinstance(key, str) and key.strip() and len(key) <= KEY_MAX and not key.startswith("$")):
                parser.err(w, "key %r: expected a text of 1..%d characters (not starting with $)" % (key, KEY_MAX)); continue
            parser.check_value(w, "key %r" % key, lt, (), it)
            if isinstance(it, str) and it.startswith("$"):
                parser.err(w, "key %r: a value cannot be a reference" % key)
        if len(parser.errors) > n_err:
            return None
        return VarList(name, lt, types.MappingProxyType(dict(raw)), desc, None, self.id, DEFAULT, None, scope, persist)

    def fresh(self, items):
        return dict(items)

    def serialize(self, items, vtype):
        return {k: vtype.serialize(x) for k, x in (items or {}).items()}

    def restore(self, graph, li, items):
        from nanterino.graph import LIST_MAX, persisted_ok
        if not isinstance(items, dict):
            return None
        if len(items) > LIST_MAX or not all(persisted_ok(graph, li.type, x) for x in items.values()):
            return None
        if not all(isinstance(k, str) and k.strip() for k in items):
            return None
        from nanterino.vartypes import VARTYPES
        return {k: VARTYPES[li.type].deserialize(x) for k, x in items.items()}

    def editor_items(self, li, cfg):
        return dict(li.items)
