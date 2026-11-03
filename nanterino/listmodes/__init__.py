"""List mode registry (lot M3, 2026-11-01): one module per list mode (`variables.lists.<n>.mode`).

Purpose
    nanterino/listmodes/plain.py, shuffle.py and history.py own the run-time behaviour of a list of kind `list`:
    pick() (say_random's draw: random, or a shuffle bag without repeats) and push() (list_add / remember_utterance:
    append, oldest items dropped beyond `max`), plus their declaration rules (needs_max: `max:` required;
    bound_ok: allowed on a list bound to a config key / an intent). graph.LIST_MODES and the vocabulary's
    `list_modes` are views of LISTMODES.

How to add a mode (drop a file)
    nanterino/listmodes/<id>.py with exactly one ListMode subclass (id = file name, label, help, order) overriding
    pick() and / or push().

Boundary
    Operates on a Brain through its attributes (`lists`, `rng`, `_bags`); no module-level import of graph / brain.
    Closed discovery: PACKAGE only.

Invariants (checked at import, RegistryError naming the file)
    one ListMode subclass per module, id = file name, unique; label / help non-empty; needs_max / bound_ok booleans;
    DEFAULT ("plain", the mode of a declaration without `mode:`) exists.

How to test
    .venv/bin/python -m tests.test_vartypes_registry ; .venv/bin/python -m tests.test_graph_vars2 (bag, history)
"""
from nanterino.registry import RegistryError, check_identity, check_text, failer, scan_package

PACKAGE = "nanterino.listmodes"
DEFAULT = "plain"


class ListMode:
    id: str = ""
    order = None
    label: str = ""
    help: str = ""
    needs_max = False     # the declaration must give `max:`
    bound_ok = True       # allowed on a read-only list bound to `from:` / `intent:`

    def pick(self, brain, name: str, items: list):
        """say_random's draw among the non-empty texts `items` of list `name`."""
        return brain.rng.choice(items)

    def push(self, brain, li, value) -> None:
        """Append to a user list; a list with `max` drops its oldest items first."""
        items = brain.lists.setdefault(li.name, [])
        items.append(value)
        cap = li.maxlen
        if cap and len(items) > cap:
            del items[:len(items) - cap]


_fail = failer("list mode")


def _check(cls, modname: str, where: str):
    check_identity(cls, modname, where, _fail, "mode")
    check_text(cls, where, _fail, "label", "help")
    for f in ("needs_max", "bound_ok"):
        if not isinstance(getattr(cls, f), bool):
            _fail(where, "%s.%s must be True or False" % (cls.id, f))


def scan(package_name: str = PACKAGE) -> dict:
    found = scan_package(package_name, ListMode, "listmodes", "list mode", RegistryError, _check)
    if package_name == PACKAGE and DEFAULT not in found:
        raise RegistryError("list mode module listmodes/%s.py is missing (default mode)" % DEFAULT)
    return found


LISTMODES = scan(PACKAGE)
