"""List kind `list`: items in order; user list (`items:`) or read-only list bound to a config key / an intent."""
from nanterino.listkinds import ListKind


class ListOfItems(ListKind):
    id = "list"
    order = 10
    label = "Liste"
    help = "Des éléments dans l'ordre."

    def parse(self, parser, where, name, spec, item_type, mode, maxlen, scope, persist, desc, intent_names):
        from nanterino.graph import LIST_MAX, VarList
        from nanterino.listmodes import LISTMODES
        w, lt = where, item_type
        source, items = None, ()
        if "from" in spec:
            if not isinstance(parser.cfg.get(spec["from"]), (list, tuple)):
                parser.err(w, "from: %r is not a config key holding a list" % (spec["from"],)); return None
            source, items = ("cfg", spec["from"]), tuple(parser.cfg[spec["from"]])
        elif "intent" in spec:
            if spec["intent"] not in intent_names:
                parser.err(w, "intent: unknown intent %r (words or words_from only)" % (spec["intent"],)); return None
            source, items = ("intent", spec["intent"]), tuple(intent_names[spec["intent"]])
        else:
            raw = spec["items"]
            if not isinstance(raw, list) or len(raw) > LIST_MAX:
                parser.err(w, "`items:` must be a list of at most %d elements" % LIST_MAX); return None
            n_err = len(parser.errors)
            for i, it in enumerate(raw):
                parser.check_value(w, "item #%d" % (i + 1), lt, (), it)
                if isinstance(it, str) and it.startswith("$"):
                    parser.err(w, "item #%d: a list item cannot be a reference" % (i + 1))
            if len(parser.errors) > n_err:
                return None
            items = tuple(raw)
        if source and lt != "string":
            parser.err(w, "a bound list holds texts: type string"); return None
        if source and (not LISTMODES[mode].bound_ok or maxlen is not None or persist or scope != "global"):
            parser.err(w, "a bound list is read-only: only `mode: shuffle` applies (no history, max, scope or persist)"); return None
        if not source and maxlen is not None and len(items) > maxlen:
            parser.err(w, "`items:` has more than `max:` (%d) elements" % maxlen); return None
        return VarList(name, lt, items, desc, source, self.id, mode, maxlen, scope, persist)

    def fresh(self, items):
        return list(items)

    def serialize(self, items, vtype):
        return [vtype.serialize(x) for x in (items or [])]

    def restore(self, graph, li, items):
        from nanterino.graph import LIST_MAX, persisted_ok
        if not isinstance(items, list):
            return None
        if len(items) > LIST_MAX or not all(persisted_ok(graph, li.type, x) for x in items):
            return None
        from nanterino.vartypes import VARTYPES
        vals = [VARTYPES[li.type].deserialize(x) for x in items]
        return vals[-li.maxlen:] if li.maxlen else vals

    def editor_items(self, li, cfg):
        return list(cfg.get(li.source[1]) or []) if li.source and li.source[0] == "cfg" else list(li.items)
