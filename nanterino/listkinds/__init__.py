"""List kind registry (lot M3, 2026-11-01): one module per list kind (`variables.lists.<n>.kind`).

Purpose
    nanterino/listkinds/list.py (items in order) and dict.py (key -> value pairs) own what differs between kinds:
    parsing of the declaration body (graph._Parser.variables calls parse() after the common keys), the fresh mutable
    container the brain starts from, the editor row items (graph.variable_entries), and the persistence format
    (serialize / restore of the `items` of a state/vars.json entry). graph.LIST_KINDS and the vocabulary's
    `list_kinds` are views of LISTKINDS.

How to add a kind (drop a file)
    nanterino/listkinds/<id>.py with exactly one ListKind subclass (id = file name, label, help, order) implementing
    parse(), fresh(), serialize(), restore() and editor_items(). Actions / conditions that act on it check the kind
    through their argument kinds (graph.LIST_KIND_RULES).

Boundary
    No module-level import of nanterino.graph / nanterino.brain (graph.py imports this package); graph helpers are
    imported inside methods. Closed discovery: PACKAGE only.

Invariants (checked at import, RegistryError naming the file)
    one ListKind subclass per module, id = file name, unique; label / help non-empty; parse / fresh / serialize /
    restore / editor_items implemented; DEFAULT ("list", the kind of a declaration without `kind:`) exists.

How to test
    .venv/bin/python -m tests.test_vartypes_registry
"""
from nanterino.registry import RegistryError, check_identity, check_text, failer, scan_package

PACKAGE = "nanterino.listkinds"
# Note: importing listkinds/list.py and dict.py binds `list` / `dict` as attributes of THIS module (one package attribute
# per imported submodule), shadowing the builtins here after the scan: this file must not call list() / dict().
DEFAULT = "list"          # kind of a list declared without `kind:`
METHODS = ("parse", "fresh", "serialize", "restore", "editor_items")


class ListKind:
    id: str = ""
    order = None
    label: str = ""
    help: str = ""

    def parse(self, parser, where, name, spec, item_type, mode, maxlen, scope, persist, desc, intent_names):
        """Kind-specific part of a list declaration: a graph.VarList, or None after reporting errors."""
        raise NotImplementedError

    def fresh(self, items):
        """A new mutable container holding the declared initial items (the brain's live value)."""
        raise NotImplementedError

    def serialize(self, items, vtype):
        """Live items -> the JSON `items` of a state/vars.json entry (values through the item type)."""
        raise NotImplementedError

    def restore(self, graph, li, items):
        """Stored `items` -> live container, or None when they no longer fit (type-checked per item)."""
        raise NotImplementedError

    def editor_items(self, li, cfg):
        """Items shown by the variable manager (GET /api/graph/vocab variables.lists[].items)."""
        raise NotImplementedError


_fail = failer("list kind")


def _check(cls, modname: str, where: str):
    check_identity(cls, modname, where, _fail, "kind")
    check_text(cls, where, _fail, "label", "help")
    for m in METHODS:
        if getattr(cls, m) is getattr(ListKind, m):
            _fail(where, "%s does not implement %s()" % (cls.id, m))


def scan(package_name: str = PACKAGE) -> dict:
    found = scan_package(package_name, ListKind, "listkinds", "list kind", RegistryError, _check)
    if package_name == PACKAGE and DEFAULT not in found:
        raise RegistryError("list kind module listkinds/%s.py is missing (default kind)" % DEFAULT)
    return found


LISTKINDS = scan(PACKAGE)
