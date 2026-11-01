"""Shared module scanner of the closed registries (nodes lots M1/M2, variable types / list kinds / list modes lot M3).

Purpose
    One implementation of "one class per file, discovered in a flat folder": nanterino.nodes (actions, conditions,
    triggers), nanterino.vartypes, nanterino.listkinds and nanterino.listmodes all call scan_package(). Each registry
    keeps its own structural checks (passed as `check`) and its own error class (a RegistryError subclass or
    RegistryError itself).

Boundary / security
    The scanned package name is always a code constant of the calling registry (closed vocabulary): never a name read
    from YAML, a request or the environment. Tests may pass the name of a temporary COPY of a family.

Invariants
    - every public module (name not starting with `_`) of the package is imported; sub-packages are refused (a family
      folder is flat);
    - a module defines exactly one subclass of `base` (defined in that module), its `id` is unique;
    - the result is ordered by (order, id) with unnumbered classes last: byte-stable, independent of file system order.

How to test
    .venv/bin/python -m tests.test_nodes_registry ; .venv/bin/python -m tests.test_vartypes_registry
"""
import importlib
import inspect
import pkgutil
import re

NAME = re.compile(r"^[a-z][a-z0-9_]{0,47}$")   # id = file name: lower snake case


class RegistryError(RuntimeError):
    """A registry module is invalid: the robot must not start with a half-loaded vocabulary."""


def failer(noun: str, error=RegistryError):
    """fail(where, msg) raising `error` with the house message format "<noun> module <where>: <msg>"."""
    def fail(where: str, msg: str):
        raise error("%s module %s: %s" % (noun, where, msg))
    return fail


def check_identity(cls, modname: str, where: str, fail, what: str = "type") -> None:
    """id is lower snake case and equals the file name; `order` is an int or None (shared by the M3 registries)."""
    rid = getattr(cls, "id", None)
    if not (isinstance(rid, str) and NAME.match(rid)):
        fail(where, "id %r is not a lower snake case name" % (rid,))
    if rid != modname:
        fail(where, "id %r must equal the file name %r (one file per %s)" % (rid, modname, what))
    order = getattr(cls, "order", None)
    if order is not None and not (isinstance(order, int) and not isinstance(order, bool)):
        fail(where, "%s.order must be an int or None" % rid)


def check_text(cls, where: str, fail, *attrs) -> None:
    """Each attribute is a non-empty string."""
    for attr in attrs:
        v = getattr(cls, attr, None)
        if not (isinstance(v, str) and v.strip()):
            fail(where, "%s.%s must be a non-empty string" % (cls.id, attr))


def scan_package(package_name: str, base, family: str, noun: str, error=RegistryError, check=None) -> dict:
    """Import every module of `package_name` and return {id: instance} ordered by (order, id).

    `family` is the folder name used in messages (`<family>/<file>.py`), `noun` the message prefix ("node",
    "variable type" ...), `check(cls, modname, where)` the registry's structural checks of the found class.
    """
    fail = failer(noun, error)
    try:
        pkg = importlib.import_module(package_name)
    except Exception as e:  # noqa: BLE001 (re-raised with context)
        raise error("%s package %s cannot be imported: %s: %s" % (noun, package_name, type(e).__name__, e)) from e
    found = {}
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue   # private helpers / disabled files
        where = "%s/%s.py" % (family, info.name)
        if info.ispkg:
            fail(where, "sub-packages are not allowed: a family folder is flat")
        try:
            mod = importlib.import_module("%s.%s" % (package_name, info.name))
        except Exception as e:  # noqa: BLE001 (re-raised with context)
            raise error("%s module %s failed to import: %s: %s" % (noun, where, type(e).__name__, e)) from e
        classes = [c for c in vars(mod).values()
                   if inspect.isclass(c) and issubclass(c, base) and c is not base and c.__module__ == mod.__name__]
        if len(classes) != 1:
            fail(where, "expected exactly one %s subclass, found %d" % (base.__name__, len(classes)))
        cls = classes[0]
        if check is not None:
            check(cls, info.name, where)
        if cls.id in found:
            fail(where, "duplicate id %r" % cls.id)
        found[cls.id] = cls()
    order = sorted(found.values(), key=lambda n: (n.order is None, n.order or 0, n.id))
    return {n.id: n for n in order}
