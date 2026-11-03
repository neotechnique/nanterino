"""Property registry (lot M4, 2026-11-01): typed value sources and write targets, like Game Creator 2's PropertyGet /
PropertySet.

Purpose
    A field of an action / condition (a `value`, a number, a dictionary key ...) used to hold a constant or a `$x` /
    `$utterance` reference coded case by case. Now every such field may hold a *value source*:
        plain constant                     ->  3, "bonjour", true            (unchanged, the common case)
        `$x`                               ->  shorthand of {get: variable, name: x}
        `$utterance`                       ->  shorthand of {get: utterance}
        {get: <source id>, <arg>: ...}     ->  any source of nanterino/properties/get/<id>.py
    Sources: one class per file in properties/get/ (constant, variable, list_item, dict_value, utterance, system,
    random_number, random_from_list, intent_match, config_value, elapsed, calc). Write targets: one class per file in
    properties/set/ (variable, list_item, dict_key), used by set_var / list_add / dict_set to write through the type
    modules (VARTYPES clamp, LISTMODES push).

Typing (end to end, checked when the graph is parsed)
    Each source declares its output type (`out`): a variable type id, "same" (= the type of the field, e.g. a
    constant) or ("of", <arg>) (the type of the variable / list / dictionary / config key that argument names). The
    output must be graph.compatible() with the field type, else the graph is refused with a clear message.
    Source arguments have their own kinds (ARG_KINDS below): the NESTED kinds (value, number, key) accept a literal, a
    `$` shorthand or another property (calc of calc ...), at most MAX_DEPTH levels; the other kinds are plain names of
    things (variables, lists, intents, config keys, enumerations) and never take a property.
    No eval anywhere: calc applies one operator of CALC_OPS to two numbers.

Compiled form (graph.Graph / Call.args)
    check_field() normalises a property: {get: constant, value: v} -> v; {get: variable, name: x} -> "$x" and
    {get: utterance} -> "$utterance" in the fields that always accepted `$` (graph.SHORTHAND_KINDS), so a shorthand
    and its long form compile (and run) identically. Other sources stay plain dicts {get: ..., ...} (JSON friendly,
    visual round trip unchanged); the raw YAML is never rewritten.

Run time
    evaluate(brain, kw, prop) runs the source with a NodeContext; brain._resolve() calls it for a property, so every
    node that resolved `$x` resolves properties too. Fallbacks (never an exception on the brain loop): an empty list,
    a missing key, a stopped timer or a failing source give the output type's default (VARTYPES[t].default, 0 for
    numbers); calc divides by zero as 0 (the parser adds a `division_by_zero` diagnostic when the divisor is a
    literal 0).

How to add a source / target (drop a file)
    nanterino/properties/get/<id>.py with exactly one GetSource subclass (id = file name, order, label, help, icon,
    out, args, optional `defaults`, get(ctx, **args), optional check(parser, field_type, **args) returning the output
    type or None after reporting). Same for set/<id>.py with a SetTarget subclass (write(ctx, value, **args),
    check(parser, **args) returning the type written). The icon must be one of graph.all_icons() (vendored SVGs).

Boundary / security
    Closed discovery: only PACKAGES are scanned (registry.scan_package), never a name read from YAML. No module-level
    import of nanterino.graph / nanterino.brain (graph.py imports this package): graph helpers are imported lazily.

Invariants (checked at import; a violation raises RegistryError naming the file)
    one subclass per module, id = file name, unique ids, label / help / icon non-empty, argument kinds in ARG_KINDS,
    `defaults` only for declared arguments, get() / write() signatures = declared arguments; check_registry() (called
    by graph.py) also checks icons and output types against graph's tables.

How to test
    .venv/bin/python -m tests.test_properties
"""
import inspect

from nanterino.log import log
from nanterino.nodes.base import Arg, NodeContext
from nanterino.registry import RegistryError, check_identity, check_text, failer, scan_package

# Importing the sub-packages get/ and set/ binds `nanterino.properties.get` / `.set` as attributes of THIS module and
# shadows the builtin `set` here: keep private aliases of the builtins used below.
_set, _dict = set, dict

PACKAGES = {"get": "nanterino.properties.get", "set": "nanterino.properties.set"}   # closed: the only packages scanned
MAX_DEPTH = 4            # a property inside a property ... at most 4 levels (calc of calc of calc of a source)

# Argument kinds of the property modules (one place). NESTED: literal, `$` shorthand or a nested property; the value
# is the field type the nested value must fit ("same" = the type of the field the outer property fills).
NESTED_KINDS = {"value": "same", "number": "number", "key": "string"}
ARG_KINDS = frozenset(NESTED_KINDS) | frozenset({
    "var",       # any variable, user or system (read)
    "wvar",      # a writable user variable (set targets)
    "list",      # a list (kind list)
    "wlist",     # a writable list
    "dict",      # a dictionary (kind dict)
    "wdict",     # a writable dictionary
    "timeref",   # a datetime or timer variable
    "sysvar",    # a system variable (graph.SYSTEM_VARS)
    "intent",    # an intent of the graph (not the implicit `question`)
    "cfgkey",    # a config key holding a number, a text or true/false
    "pick",      # list_item position: PICKS
    "calcop",    # calc operator: CALC_OPS
})
CALC_OPS = {"+": "plus", "-": "moins", "*": "multiplié par", "/": "divisé par", "min": "le plus petit de", "max": "le plus grand de"}
PICKS = {"first": "Le premier", "last": "Le dernier", "random": "Au hasard", "index": "À la position"}
CFG_TYPES = ((bool, "bool"), ((int, float), "number"), (str, "string"))   # config_value output type by Python type
# Config keys a graph may read (config_value): delays, switches and the spoken phrases. Never the URLs, prompts, device
# names or network settings (a graph must not be able to say them aloud).
CFG_PUBLIC = ("silence_relance_s", "silence_cloture_s", "cloture_to_veille_s", "lost_face_s", "idle_long_s", "volume",
              "face_scale", "auto_greet_on_face", "barge_in", "greeting", "relance", "goodbye", "repair_text")


class PropertyError(ValueError):
    """A static problem of one property (the framework reports it on the field being parsed)."""


class _Invalid:
    """check_field() result after an error was reported (the caller skips the field)."""
    __slots__ = ()

    def __repr__(self):
        return "INVALID"


INVALID = _Invalid()


def is_property(v) -> bool:
    """A `{get: ...}` mapping (the long form; `$x` strings are handled as before by the callers)."""
    return isinstance(v, _dict) and "get" in v


def num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def default_of(vtype):
    """Run-time fallback value of an output type (its type module's default; 0 for numbers without one)."""
    from nanterino.vartypes import VARTYPES
    t = VARTYPES.get(vtype)
    if t is None:
        return None
    if t.default is None and t.numeric:
        return 0
    return t.default


# ---------------------------------------------------------------- base classes
class GetSource:
    """A value source (`{get: <id>, ...}`). Class attributes = metadata; the registry keeps one instance."""
    family = "get"
    id = ""
    order = None
    label = ""
    help = ""
    icon = ""
    out = "same"          # vartype id, "same" (= field type) or ("of", <argument name>)
    args: dict = {}       # argument name -> Arg(kind of ARG_KINDS, French label), in display order
    defaults: dict = {}   # optional arguments: name -> value used when the YAML leaves it out
    shorthand = None      # "variable" / "utterance" / "constant": how check_field() may collapse the compiled form
    literal_args = ()     # NESTED arguments that must be plain literals (no `$x`, no nested source): constant's value

    def check(self, parser, field_type, **args):
        """Static checks after the generic ones (argument kinds, nesting). Return the output type, or None after
        reporting an error through parser.err / parser.fail; raise PropertyError(msg) for a simple refusal."""
        if self.out == "same":
            return field_type
        if isinstance(self.out, tuple):
            raise NotImplementedError("%s: a dynamic output type needs its own check()" % self.id)
        return self.out

    def get(self, ctx: NodeContext, **args):
        """The value, at run time (brain loop thread). Must return a value of the output type (fallback included)."""
        raise NotImplementedError

    def __repr__(self):
        return "<property source %s>" % self.id


class SetTarget:
    """A write target (variable, list item, dictionary key): writes a value through the type modules."""
    family = "set"
    id = ""
    order = None
    label = ""
    help = ""
    icon = ""
    args: dict = {}
    defaults: dict = {}

    def check(self, parser, **args):
        """Type of the value written (the field type of the value it receives), or None after reporting."""
        raise NotImplementedError

    def write(self, ctx: NodeContext, value, **args):
        raise NotImplementedError

    def __repr__(self):
        return "<property target %s>" % self.id


# ---------------------------------------------------------------- discovery + checks
_fail = failer("property")


def _signature_ok(fn, names) -> bool:
    params = list(inspect.signature(fn).parameters.values())[2:]   # skip self, ctx
    return [p.name for p in params] == list(names)


def _check(cls, modname: str, where: str):
    check_identity(cls, modname, where, _fail, "property")
    check_text(cls, where, _fail, "label", "help", "icon")
    if not isinstance(cls.args, _dict) or not all(isinstance(a, Arg) for a in cls.args.values()):
        _fail(where, "%s.args must map names to Arg(kind, label)" % cls.id)
    for a, d in cls.args.items():
        if d.kind not in ARG_KINDS:
            _fail(where, "%s.%s: unknown argument kind %r (allowed: %s)" % (cls.id, a, d.kind, ", ".join(sorted(ARG_KINDS))))
        if a == "get":
            _fail(where, "%s: an argument cannot be named `get`" % cls.id)
    if not isinstance(cls.defaults, _dict) or _set(cls.defaults) - _set(cls.args):
        _fail(where, "%s.defaults may only name declared arguments" % cls.id)
    if cls.family == "get":
        fn, names = cls.get, list(cls.args)
        out = cls.out
        if not (isinstance(out, str) or (isinstance(out, tuple) and len(out) == 2 and out[0] == "of" and out[1] in cls.args)):
            _fail(where, "%s.out must be a type id, \"same\" or (\"of\", <argument>)" % cls.id)
        if cls.get is GetSource.get:
            _fail(where, "%s does not implement get()" % cls.id)
    else:
        fn, names = cls.write, ["value"] + list(cls.args)
        if cls.write is SetTarget.write or cls.check is SetTarget.check:
            _fail(where, "%s must implement write() and check()" % cls.id)
    if not _signature_ok(fn, names):
        _fail(where, "%s.%s() must take (ctx, %s)" % (cls.id, fn.__name__, ", ".join(names)))


def scan(family: str, package_name: str = None) -> dict:
    """{id: instance} of one family ("get" / "set") in palette order. Production passes PACKAGES only."""
    base = GetSource if family == "get" else SetTarget
    return scan_package(package_name or PACKAGES[family], base, "properties/" + family, "property", RegistryError, _check)


def check_registry(gets: dict, sets: dict, icons, type_ids) -> None:
    """Checks that need graph.py's tables (called by graph.py once they exist): vendored icons, known output types."""
    for fam, reg in (("get", gets), ("set", sets)):
        for p in reg.values():
            where = "properties/%s/%s.py" % (fam, p.id)
            if p.icon not in icons:
                _fail(where, "%s.icon %r is not a vendored icon (graph.all_icons())" % (p.id, p.icon))
            if fam == "get" and isinstance(p.out, str) and p.out != "same" and p.out not in type_ids:
                _fail(where, "%s.out %r is not a variable type" % (p.id, p.out))


# ---------------------------------------------------------------- static checks (graph._Parser)
class Checker:
    """What a source's check() receives as `parser`: the graph parser (attributes proxied) plus the field being
    checked, so a module reports with `fail(msg)` / `warn(msg, kind)` without knowing where it is."""

    def __init__(self, parser, where, what, choices=()):
        self.parser, self.where, self.what, self.choices = parser, where, what, tuple(choices)

    def __getattr__(self, name):
        return getattr(self.parser, name)

    def fail(self, msg):
        self.parser.err(self.where, "%s: %s" % (self.what, msg))

    def warn(self, msg, kind):
        self.parser.diag(self.where, "%s: %s" % (self.what, msg), kind)

    def value_ok(self, field_type, v, choices=None) -> bool:
        """The parser's own literal / `$ref` check (same messages as before M4); True when nothing was reported."""
        n = len(self.parser.errors)
        self.parser.check_value(self.where, self.what, field_type, self.choices if choices is None else choices, v)
        return len(self.parser.errors) == n


def _ref_problem(parser, kind, v):
    """Generic check of a names-of-things argument; None when fine, else the French-free message (house style)."""
    from nanterino import graph as G
    if kind in ("var", "wvar", "timeref"):
        info = parser.var_info(v) if isinstance(v, str) else None
        if info is None:
            return "unknown variable %r" % (v,)
        if kind == "wvar" and (v in G.SYSTEM_VARS or info[0] == "timer"):
            return "%r cannot be written (system variable or timer)" % (v,)
        if kind == "timeref" and info[0] not in ("datetime", "timer"):
            return "%r is of type %s, expected datetime / timer" % (v, info[0])
        return None
    if kind in ("list", "wlist", "dict", "wdict"):
        lkind = "dict" if kind in ("dict", "wdict") else "list"
        li = parser.lists.get(v) if isinstance(v, str) else None
        if li is None:
            return "unknown %s %r" % ("dictionary" if lkind == "dict" else "list", v)
        if li.kind != lkind:
            return "%r is %s" % (v, "a list, not a dictionary" if lkind == "dict" else "a dictionary, not a list")
        if kind in ("wlist", "wdict") and li.source:
            return "list %r is bound to %s (read-only)" % (v, li.source[0])
        return None
    if kind == "sysvar":
        return None if v in G.SYSTEM_VARS else "unknown system variable %r (allowed: %s)" % (v, ", ".join(G.SYSTEM_VARS))
    if kind == "intent":
        return None if isinstance(v, str) and v in parser.intent_names else "unknown intent %r" % (v,)
    if kind == "cfgkey":
        if not (isinstance(v, str) and v in CFG_PUBLIC):
            return "%r is not a readable config key (allowed: %s)" % (v, ", ".join(CFG_PUBLIC))
        return None if v in parser.cfg else "%r is not a config key" % (v,)
    if kind == "pick":
        return None if v in PICKS else "unknown position %r (allowed: %s)" % (v, ", ".join(PICKS))
    if kind == "calcop":
        return None if v in CALC_OPS else "unknown operator %r (allowed: %s)" % (v, " ".join(CALC_OPS))
    return "unknown argument kind %r" % kind


def check_field(parser, where, what, field_type, choices, val, shorthand=True, depth=1):
    """Validate the property `val` filling a field of `field_type` (choices = allowed values of a choice field).

    Returns the compiled value (see the module docstring), or INVALID after reporting every problem on (where, what).
    shorthand=False keeps variable / utterance sources as dicts (fields that never accepted `$x`, e.g. a number)."""
    from nanterino import graph as G
    gets = GETS
    pc = Checker(parser, where, what, choices)
    src = gets.get(val.get("get")) if isinstance(val.get("get"), str) else None
    if src is None:
        pc.fail("unknown value source %r (allowed: %s)" % (val.get("get"), ", ".join(gets)))
        return INVALID
    if depth > MAX_DEPTH:
        pc.fail("value sources nested deeper than %d levels" % MAX_DEPTH)
        return INVALID
    given = {k: v for k, v in val.items() if k != "get"}
    need = _set(src.args) - _set(src.defaults)
    if _set(given) - _set(src.args) or need - _set(given):
        pc.fail("source %s takes %s, got %s" % (src.id, sorted(src.args) or "no argument", sorted(given)))
        return INVALID
    ok, compiled = True, {"get": src.id}
    for k, d in src.args.items():
        if k not in given:
            continue
        v, sub = given[k], "%s.%s" % (what, k)
        if k in src.literal_args and (is_property(v) or isinstance(v, str) and v.startswith("$")):
            pc.fail("a %s cannot be a reference or another source" % src.id)
            ok = False
            continue
        if d.kind in NESTED_KINDS:
            ft = field_type if NESTED_KINDS[d.kind] == "same" else NESTED_KINDS[d.kind]
            ch = choices if NESTED_KINDS[d.kind] == "same" else ()
            if is_property(v):
                v = check_field(parser, where, sub, ft, ch, v, True, depth + 1)
                if v is INVALID:
                    ok = False
                    continue
            elif isinstance(v, _dict) or isinstance(v, list) and d.kind != "value":
                Checker(parser, where, sub).fail("expected a value or {get: ...}")
                ok = False
                continue
            elif not Checker(parser, where, sub, ch).value_ok(ft, v):
                ok = False
                continue
        else:
            msg = _ref_problem(parser, d.kind, v)
            if msg is not None:
                Checker(parser, where, sub).fail(msg)
                ok = False
                continue
        compiled[k] = v
    if not ok:
        return INVALID
    args = _dict(src.defaults, **{k: v for k, v in compiled.items() if k != "get"})
    n_err = len(parser.errors)
    try:
        out = src.check(pc, field_type, **args)
    except PropertyError as e:
        pc.fail(str(e))
        return INVALID
    if out is None or len(parser.errors) > n_err:
        return INVALID
    if not G.compatible(out, field_type):
        pc.fail("source %s gives a %s value, %s expected" % (src.id, out, field_type))
        return INVALID
    if src.shorthand == "constant":
        return compiled["value"]
    if shorthand and src.shorthand == "variable":
        return "$" + compiled["name"]
    if shorthand and src.shorthand == "utterance":
        return "$utterance"
    return compiled


# ---------------------------------------------------------------- run time
def value(brain, kw, v, depth=1):
    """A nested argument at run time: a property, a `$` shorthand (brain._resolve) or a literal."""
    if is_property(v):
        return evaluate(brain, kw, v, depth + 1)
    return brain._resolve(v, kw)


def evaluate(brain, kw, prop, depth=1):
    """Value of a compiled property. NESTED arguments are resolved first, except `key` (a source reads its own key:
    dict_value matches `$utterance` like the dictionary conditions). Never raises: a failing source gives None."""
    src = GETS.get(prop.get("get"))
    if src is None or depth > MAX_DEPTH:
        log.warning("property: %r cannot run (unknown source or too deep)", prop.get("get"))
        return None
    args = _dict(src.defaults)
    for k, v in prop.items():
        if k == "get":
            continue
        kind = src.args[k].kind
        args[k] = value(brain, kw, v, depth) if kind in ("value", "number") else v
    try:
        return src.get(NodeContext(brain, kw, brain.cfg, brain._graph), **args)
    except Exception:  # noqa: BLE001 (the brain loop must keep running; the error is logged)
        log.exception("property %s failed", src.id)
        return None


def write(target: str, ctx: NodeContext, value_, **args):
    """Write through a set target (set_var / list_add / dict_set)."""
    return SETS[target].write(ctx, value_, **args)


# ---------------------------------------------------------------- editor vocabulary (GET /api/graph/vocab `properties`)
def arg_schema(name, arg, graph_mod, cfg, default=None, has_default=False) -> dict:
    """Inspector schema of one property argument (same shapes as the action / guard arguments)."""
    G = graph_mod
    k, d = arg.kind, {"name": name}
    if k == "value":
        d.update(type="value", props="same")
    elif k == "number":
        d.update(type="number", options=[], props="number")
    elif k == "key":
        d.update(type="text", max_len=G.KEY_MAX, utterance=True, vars=True, props="string")
    elif k in ("var", "wvar", "timeref"):
        types_ = [t for t in G.VAR_TYPES if (k == "var" or (k == "wvar" and t != "timer") or (k == "timeref" and t in ("datetime", "timer")))]
        d.update(type="var", var_types=types_, writable=k == "wvar")
    elif k in ("list", "wlist", "dict", "wdict"):
        d.update(type="list", list_types=list(G.LIST_TYPES), list_kinds=["dict" if k in ("dict", "wdict") else "list"],
                 writable=k in ("wlist", "wdict"))
    elif k == "sysvar":
        d.update(type="enum", options=list(G.SYSTEM_VARS), labels={n: v[1] for n, v in G.SYSTEM_VARS.items()})
    elif k == "intent":
        d.update(type="intent")
    elif k == "cfgkey":
        opts = [n for n in CFG_PUBLIC if cfg_type((cfg or {}).get(n)) is not None]
        # lot M5 (additive): output type per key, so the editor only offers the keys a field can take
        d.update(type="enum", options=opts, types={n: cfg_type(cfg[n]) for n in opts})
    elif k == "pick":
        d.update(type="enum", options=list(PICKS), labels=_dict(PICKS))
    elif k == "calcop":
        d.update(type="enum", options=list(CALC_OPS), labels=_dict(CALC_OPS))
    d["label"] = arg.label
    if has_default:
        d["default"] = default
    return d


def cfg_type(v):
    """Output type of a config value (config_value), None when it is not a scalar."""
    for py, t in CFG_TYPES:
        if isinstance(v, py):
            return t
    return None


def vocabulary(graph_mod, cfg) -> dict:
    """{"get": [...], "set": [...]} for the editor's source picker (lot M5)."""
    def entry(p, fam):
        e = {"id": p.id, "label": p.label, "help": p.help, "icon": p.icon}
        if fam == "get":
            e["out"] = {"of": p.out[1]} if isinstance(p.out, tuple) else p.out
        e["args"] = [arg_schema(n, a, graph_mod, cfg, p.defaults.get(n), n in p.defaults) for n, a in p.args.items()]
        return e
    return {"get": [entry(p, "get") for p in GETS.values()], "set": [entry(p, "set") for p in SETS.values()]}


GETS = scan("get")
SETS = scan("set")
