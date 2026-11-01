"""Variable type registry (lot M3, 2026-11-01): one module per variable type, like Game Creator 2's ValueTypes.

Purpose
    Every type a graph variable (`variables.names.<n>.type`) or a list item (`variables.lists.<n>.type`) may have is
    one class in nanterino/vartypes/<id>.py. The class owns everything type-specific: editor metadata (label, control,
    options, operators, list use, nullable, default, choices), literal validation, editor-text coercion, comparison,
    clamping, persistence (de)serialisation and, for references, the allowed choices. graph.py keeps VIEWS of this
    registry (VAR_TYPES, LIST_TYPES, TYPE_CONTROL, TYPE_DEFAULT, NUMERIC_TYPES ... and the vocabulary's var_types /
    list_types / op_sets) and its helpers (type_ok, coerce_value, compatible, fit_value, persisted_ok, graph_choices)
    call the type modules; brain.py compares and (de)serialises through them.

How to add a type (drop a file)
    1. Create nanterino/vartypes/<id>.py (file name = type id) with a module docstring and exactly one VarType subclass:
           from nanterino.vartypes import VarType

           class Mood(VarType):
               id = "mood"
               order = 200                 # position in the type menus (VAR_TYPES order)
               label = "Humeur"
               control = "select"          # an editor widget of CONTROLS
               default = "calme"
               textlike = True             # may feed a text value

               def validate(self, v, choices=()):
                   return v in ("calme", "joyeux")
    2. Add tests (tests/test_vartypes_registry.py covers the generic contract; behaviour goes to the vars suites).
    A new `control` also needs its widget in web/editor.js.

Flags (class attributes; graph.py derives its frozensets from them)
    numeric (NUMERIC_TYPES: compares / converts as numbers), ordered (ORDERED_TYPES: < <= > >= allowed), text
    (TEXT_TYPES: interchangeable texts, $utterance fits), textlike (TEXTLIKE_TYPES: may feed a string / phrase),
    bounded (BOUNDED_TYPES: min / max / step), integral (integer bounds), ref (REF_TYPES: choices from the graph),
    nullable (NULLABLE_TYPES: `value: null` allowed), item_ok (LIST_TYPES: usable as a list item type, label
    item_label or label, position item_order then type order).

Boundary
    Pure Python at import time: a type module never imports nanterino.graph / nanterino.brain at module level (graph.py
    imports this package while it is being imported); graph tables (EXPRESSIONS, TEXT_MAX, OPS ...) are read lazily
    inside methods. Discovery is closed: only PACKAGE is scanned in production.

Invariants (checked at import; a violation raises RegistryError naming the file, which stops the robot's start)
    - one VarType subclass per module, id = file name, unique ids; label / control non-empty, control in CONTROLS;
    - flags are booleans, numeric implies ordered, bounded implies numeric; item_order an int or None;
    - check_registry() (called by graph.py once its tables exist): every non-None default validates.
    Registry order = (order, id): the editor's type menu order and the order of the error messages' type lists.

How to test
    .venv/bin/python -m tests.test_vartypes_registry
"""
import datetime as _dt
import re
from typing import NamedTuple

from nanterino.registry import RegistryError, check_identity, check_text, failer, scan_package

PACKAGE = "nanterino.vartypes"   # closed: the only package scanned in production
# Editor widgets web/editor.js renders for a variable type's `control` (inspector + variable manager).
CONTROLS = frozenset({"checkbox", "number", "text", "select", "slider", "datetime", "timer", "textarea", "color", "vector"})
# Importing the type modules binds `nanterino.vartypes.bool`, `.datetime` ... as attributes of THIS module (Python
# sets a package attribute per imported submodule), shadowing the builtins / stdlib names here: keep private aliases.
_BOOL = bool
FLAGS = ("numeric", "ordered", "text", "textlike", "bounded", "integral", "ref", "nullable", "item_ok")
NUMBER_TEXT = re.compile(r"-?\d+(\.\d+)?")


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, _BOOL)


def generic_compare(a, op, b) -> bool:
    """= and != on anything, order on datetimes and on numbers (bools excluded); former Brain._compare body."""
    if op == "=":
        return a == b
    if op == "!=":
        return a != b
    if isinstance(a, _dt.datetime) and isinstance(b, _dt.datetime):
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    if not (_num(a) and _num(b)):
        return False
    return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


class Names(NamedTuple):
    """What a reference type chooses from: the parser exposes the same three attributes while parsing."""
    intent_names: tuple
    list_names: tuple
    state_names: tuple


class VarType:
    """Base of a variable type module (see the module docstring). Defaults = a plain, non-orderable value."""
    id: str = ""
    order = None
    label: str = ""
    control: str = ""
    default = None
    numeric = ordered = text = textlike = bounded = integral = ref = nullable = False
    item_ok = True          # usable as a list item type
    item_label = None       # label in LIST_TYPES (None = label)
    item_order = None       # position in LIST_TYPES (None = after the numbered ones, in type order)

    # -- editor description (GET /api/graph/vocab var_types / op_sets)
    def options(self) -> list:
        return ["min", "max", "step"] if self.bounded else []

    def ops(self) -> list:
        from nanterino.graph import OPS
        return list(OPS) if self.ordered else ["=", "!="]

    def editor_extra(self) -> dict:
        """Extra keys of the vocabulary entry after `persist` (range, size); key order is part of the golden."""
        return {}

    def editor_choices(self, graph, cfg):
        """[{id, label}] offered by the editor, or None when the type has no fixed choices."""
        return None

    def entry(self, graph, cfg) -> dict:
        d = {"id": self.id, "label": self.label, "control": self.control, "options": self.options(), "ops": self.ops(),
             "item": self.item_ok, "nullable": self.nullable, "default": self.default, "persist": True}
        d.update(self.editor_extra())
        ch = self.editor_choices(graph, cfg)
        if ch is not None:
            d["choices"] = ch
        return d

    # -- values
    def validate(self, v, choices=()) -> bool:
        """Is `v` a valid literal of this type? `choices` = resolved allowed values (choice / reference types)."""
        return False

    def coerce(self, v):
        """Editor text (a str not starting with `$`) -> typed literal; unchanged when it does not parse."""
        return v

    def compare(self, a, op, b) -> bool:
        return generic_compare(a, op, b)

    def fit(self, v):
        """Type-specific run-time fit of a number (integer rounding, percent range) before min / max."""
        return v

    def clamp(self, v, vmin=None, vmax=None):
        """Run-time value written by set_var / add_var: non-numbers unchanged, else fit() then min / max."""
        if not _num(v):
            return v
        v = self.fit(v)
        if vmin is not None and v < vmin:
            v = vmin
        if vmax is not None and v > vmax:
            v = vmax
        return v

    def choices(self, ctx, declared=()) -> tuple:
        """Allowed values: the declared `choices:` by default; a reference reads ctx (Names or the parser)."""
        return tuple(declared)

    def parse_choices(self, parser, where, spec):
        """`choices:` of a variable declaration: () when none, None when an error was reported (skip the variable)."""
        if "choices" in spec:
            parser.err(where, "`choices:` only goes with type choice")
        return ()

    # -- persistence (state/vars.json through brain.py + var_store.py; the format must not change)
    def serialize(self, v):
        """In-memory value -> JSON value stored in state/vars.json."""
        return v

    def deserialize(self, v):
        """Stored JSON value (already accepted by stored_ok) -> in-memory value."""
        return v

    def stored_ok(self, v, choices=()) -> bool:
        """A value read back from state/vars.json still fits the type."""
        return self.validate(v, choices)


# ---------------------------------------------------------------- shared helpers of several type modules
def coerce_number(v):
    """'3' -> 3, ' 2.5 ' -> 2.5 (number, duration, integer, percent); other texts unchanged."""
    s = v.strip()
    if NUMBER_TEXT.fullmatch(s):
        f = float(s)
        return int(f) if f == int(f) else f
    return v


def coerce_vector(v):
    """'1, 2.5' -> [1, 2.5] (vector2 / vector3; the length is checked by validate)."""
    s = v.strip()
    if re.fullmatch(r"\s*-?\d+(\.\d+)?(\s*,\s*-?\d+(\.\d+)?)*\s*", s):
        return [int(float(x)) if float(x) == int(float(x)) else float(x) for x in s.split(",")]
    return v


def short_text(v) -> bool:
    from nanterino.graph import TEXT_MAX
    return isinstance(v, str) and len(v) <= TEXT_MAX


# ---------------------------------------------------------------- discovery + checks
_fail = failer("variable type")


def _check(cls, modname: str, where: str):
    check_identity(cls, modname, where, _fail, "type")
    check_text(cls, where, _fail, "label", "control")
    if cls.control not in CONTROLS:
        _fail(where, "%s.control %r has no editor widget (allowed: %s)" % (cls.id, cls.control, ", ".join(sorted(CONTROLS))))
    for f in FLAGS:
        if not isinstance(getattr(cls, f), _BOOL):
            _fail(where, "%s.%s must be True or False" % (cls.id, f))
    if cls.numeric and not cls.ordered:
        _fail(where, "%s: a numeric type must be ordered" % cls.id)
    if cls.bounded and not cls.numeric:
        _fail(where, "%s: a bounded type must be numeric" % cls.id)
    if cls.item_label is not None and not (isinstance(cls.item_label, str) and cls.item_label.strip()):
        _fail(where, "%s.item_label must be None or a non-empty string" % cls.id)
    if cls.item_order is not None and not (isinstance(cls.item_order, int) and not isinstance(cls.item_order, _BOOL)):
        _fail(where, "%s.item_order must be an int or None" % cls.id)


def scan(package_name: str = PACKAGE) -> dict:
    """{id: VarType instance} in menu order. Production passes PACKAGE only (tests: a temporary copy)."""
    return scan_package(package_name, VarType, "vartypes", "variable type", RegistryError, _check)


def item_types(types: dict) -> list:
    """The list item types (item_ok) in LIST_TYPES order: item_order first, then the type order."""
    pos = {k: i for i, k in enumerate(types)}
    return sorted((t for t in types.values() if t.item_ok),
                  key=lambda t: (t.item_order is None, t.item_order or 0, pos[t.id]))


def check_registry(types: dict) -> None:
    """Checks that need graph.py's tables (called by graph.py once they exist): defaults are valid values."""
    for t in types.values():
        if t.default is not None and not t.validate(t.default, ()):
            _fail("vartypes/%s.py" % t.id, "%s.default %r is not a valid value of the type" % (t.id, t.default))


def compare(a, op, b, vtype=None) -> bool:
    """var_compare / dict_value_compare / date_compare / elapsed_since: through the type module (vtype None or
    unknown = generic comparison)."""
    t = VARTYPES.get(vtype) if vtype is not None else None
    return t.compare(a, op, b) if t is not None else generic_compare(a, op, b)


VARTYPES = scan(PACKAGE)
