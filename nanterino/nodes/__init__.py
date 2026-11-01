"""Node registry: auto-discovery of the graph's node modules (lot M1 actions, lot M2 conditions + triggers).

Purpose
    The graph vocabulary (what a graph.yaml may use and what the visual editor offers) is built from one Python
    file per node, in three flat family folders: actions/ (`do:` steps), conditions/ (`when:` guards) and
    triggers/ (`on:` events). graph.py derives its validation tables (ACTION_* / GUARD_* / EVENT_*) and the
    /api/graph/vocab entries from ACTIONS / CONDITIONS / TRIGGERS; brain.py binds each action's run() and each
    condition's test() to the live Brain; the engine asks an argument-carrying trigger's match() whether an event
    fits a transition.

How to add an action (drop a file)
    1. Create nanterino/nodes/actions/<id>.py (file name = action id, lower snake case; a leading `_` = skipped).
    2. Start it with a module docstring, then exactly one subclass of nanterino.nodes.base.Action:
           from nanterino.nodes.base import Action, Arg

           class SayHello(Action):
               id = "say_hello"
               order = 395                      # optional palette position (see the other files)
               label = "Dire bonjour"
               help = "Dit bonjour, puis déclenche say_done."
               icon = "volume"                  # a Tabler icon (add it to the editor's vendored set if new)
               theme = "parole"                 # one of graph.THEME_DOC
               args = {"name": Arg("text", "Nom")}   # kinds: graph.ARG_KINDS

               def run(self, ctx, name):
                   ctx.brain._speak_then("Bonjour " + name, "say_done")
    3. Add its tests (tests/test_nodes_registry.py checks the metadata; behaviour goes to the graph suites).
    Nothing else changes: graph.py, brain.py and the editor pick it up at the next start.

How to add a condition / a trigger (same rules, other folder and base class)
    conditions/<id>.py: one nanterino.nodes.base.Condition subclass with `def test(self, ctx, <args>)` returning
    a truthy value (the engine applies `{not: ...}`); optional `as_vars` (French reading as variables).
    triggers/<id>.py: one Trigger subclass; a plain event needs metadata only (`internal = True` for engine-only
    events). An event that carries the transition's `var:` / `value:` declares `args` and implements match(),
    editor_args() (exact inspector schema), check() (parser validation) and subscribe() (what the brain watches);
    the brain still POSTS the event (see base.Trigger).

Generated entries (data, not modules; decision of lot M2)
    graph.vocabulary() also builds palette entries from the ACTIVE GRAPH, not from code: one trigger per intent
    (`intent.<name>` events, intents are graph data edited in the Intentions panel), the delay trigger (`after:` +
    `since:`, a transition field, not an event), and per state the "etat becomes X" trigger / "etat = X"
    condition / "Changer d'état -> X" action (states are graph data). They have no module because their set
    changes with the graph; their themes are graph.THEME_SLOTS. The var_changed / timer_reached anti-loop
    (depth = MAX_VAR_CASCADE) and their posting stay in brain.py (event producers), the triggers' modules own
    their matching, validation, subscription and editor schema.

Boundary / security
    The vocabulary stays CLOSED: discovery scans only the packages named in PACKAGES (code constants), never a
    name read from YAML, a request or the environment. scan() accepts another package name only so the tests can
    load a temporary COPY of a family (drop-a-file test); production code never calls it with anything else.

Invariants (checked at import; a violation raises NodeRegistryError, which stops the robot's start like the
former theme asserts, with the offending file in the message)
    - a module defines exactly one node class of its family, whose `id` equals the module name;
    - ids are unique; label / help / icon / theme are non-empty strings; args is {name: Arg(str, str)};
    - run() / test() / match() (after `ctx, event`) take exactly the declared argument names (no *args /
      **kwargs; a trigger argument may have a default, ANY); a trigger with args implements match() and
      editor_args(); a condition implements test();
    - theme and argument kinds are checked against graph.py's tables by check_family() (called by graph.py, which
      owns THEME_DOC and ARG_KINDS).
    Order of the registry = (order, id) with unnumbered nodes last: it is the editor's palette order.

How to test
    .venv/bin/python -m tests.test_nodes_registry
"""
import importlib
import inspect
import pkgutil
import re

from .base import ANY, Action, Arg, Condition, Node, NodeContext, Trigger  # noqa: F401 (re-exported)

# Family -> package scanned in production (closed list: code constants only).
PACKAGES = {"actions": "nanterino.nodes.actions", "conditions": "nanterino.nodes.conditions",
            "triggers": "nanterino.nodes.triggers"}
BASES = {"actions": Action, "conditions": Condition, "triggers": Trigger}
NODE_ID = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


class NodeRegistryError(RuntimeError):
    """A node module is invalid: the robot must not start with a half-loaded vocabulary."""


def _fail(where: str, msg: str):
    raise NodeRegistryError("node module %s: %s" % (where, msg))


def _check_node(cls, modname: str, where: str):
    """Structural checks of one node class (graph-independent ones; see check_family for the rest)."""
    nid = cls.id
    if not (isinstance(nid, str) and NODE_ID.match(nid)):
        _fail(where, "id %r is not a lower snake case name" % (nid,))
    if nid != modname:
        _fail(where, "id %r must equal the file name %r (one file per node)" % (nid, modname))
    for attr in ("label", "help", "icon", "theme"):
        v = getattr(cls, attr, None)
        if not (isinstance(v, str) and v.strip()):
            _fail(where, "%s.%s must be a non-empty string" % (nid, attr))
    if cls.order is not None and not (isinstance(cls.order, int) and not isinstance(cls.order, bool)):
        _fail(where, "%s.order must be an int or None" % nid)
    if not isinstance(cls.args, dict):
        _fail(where, "%s.args must be a dict {name: Arg(kind, label)}" % nid)
    for a, d in cls.args.items():
        if not (isinstance(a, str) and NODE_ID.match(a)):
            _fail(where, "%s: argument name %r is not a lower snake case name" % (nid, a))
        if not (isinstance(d, Arg) and isinstance(d.kind, str) and d.kind and isinstance(d.label, str) and d.label):
            _fail(where, "%s.%s must be Arg(kind, label) with non-empty strings" % (nid, a))
    family = cls.family
    if family == "conditions" and not (cls.as_vars is None or (isinstance(cls.as_vars, str) and cls.as_vars.strip())):
        _fail(where, "%s.as_vars must be None or a non-empty string" % nid)
    if family == "triggers" and not isinstance(cls.internal, bool):
        _fail(where, "%s.internal must be True or False" % nid)
    entry, skip = {"actions": ("run", 2), "conditions": ("test", 2), "triggers": ("match", 3)}[family]
    fn = getattr(cls, entry)
    inherited = fn is BASES[family].__dict__[entry]
    if family == "triggers" and inherited and not cls.args:
        return   # a plain event: the base match() (event name equality) is right, nothing to check
    if inherited:
        _fail(where, "%s does not implement %s()" % (nid, entry))
    if family == "triggers" and cls.args and cls.editor_args is Trigger.editor_args:
        _fail(where, "%s has args but does not implement editor_args() (its inspector schema)" % nid)
    params = list(inspect.signature(fn).parameters.values())[skip:]   # drop self, ctx (and event for a trigger)
    if any(p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) for p in params):
        _fail(where, "%s.%s() must name its arguments (no *args / **kwargs)" % (nid, entry))
    if [p.name for p in params] != list(cls.args):
        _fail(where, "%s.%s() arguments %s differ from args %s" % (nid, entry, [p.name for p in params], list(cls.args)))


def scan(package_name: str, family: str) -> dict:
    """Import every module of `package_name` and return {id: node instance} in palette order.

    Production passes PACKAGES[family] only. A module that fails to import, or defines zero / several node
    classes of the family, raises NodeRegistryError naming the file.
    """
    base = BASES[family]
    try:
        pkg = importlib.import_module(package_name)
    except Exception as e:  # noqa: BLE001 (re-raised with context)
        raise NodeRegistryError("node package %s cannot be imported: %s: %s" % (package_name, type(e).__name__, e)) from e
    found = {}
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue   # private helpers / disabled files
        where = "%s/%s.py" % (family, info.name)
        if info.ispkg:
            _fail(where, "sub-packages are not allowed: a family folder is flat")
        try:
            mod = importlib.import_module("%s.%s" % (package_name, info.name))
        except Exception as e:  # noqa: BLE001 (re-raised with context)
            raise NodeRegistryError("node module %s failed to import: %s: %s" % (where, type(e).__name__, e)) from e
        classes = [c for c in vars(mod).values()
                   if inspect.isclass(c) and issubclass(c, base) and c is not base and c.__module__ == mod.__name__]
        if len(classes) != 1:
            _fail(where, "expected exactly one %s subclass, found %d" % (base.__name__, len(classes)))
        cls = classes[0]
        _check_node(cls, info.name, where)
        if cls.id in found:
            _fail(where, "duplicate id %r" % cls.id)
        found[cls.id] = cls()
    order = sorted(found.values(), key=lambda n: (n.order is None, n.order or 0, n.id))
    return {n.id: n for n in order}


def check_family(nodes: dict, family: str, themes, kinds) -> None:
    """Checks that need graph.py's tables: every theme is a known theme, every argument kind a known kind,
    and a `value` / `listvalue` argument has the variable / list / dictionary argument it refers to."""
    for n in nodes.values():
        where = "%s/%s.py" % (family, n.id)
        if n.theme not in themes:
            _fail(where, "unknown theme %r (allowed: %s)" % (n.theme, ", ".join(themes)))
        for a, d in n.args.items():
            if d.kind not in kinds:
                _fail(where, "%s.%s: unknown argument kind %r (allowed: %s)" % (n.id, a, d.kind, ", ".join(sorted(kinds))))
            if d.kind in ("value", "listvalue") and not any(k in n.args for k in ("name", "list", "dict")):
                _fail(where, "%s.%s: a %s argument needs a `name`, `list` or `dict` argument" % (n.id, a, d.kind))


ACTIONS = scan(PACKAGES["actions"], "actions")
CONDITIONS = scan(PACKAGES["conditions"], "conditions")
TRIGGERS = scan(PACKAGES["triggers"], "triggers")
