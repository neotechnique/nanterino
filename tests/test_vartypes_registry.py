"""Tests of the variable type / list kind / list mode registries (lot M3, 2026-11-01).

Purpose
    Prove that moving the variable types (nanterino/vartypes/), list kinds (nanterino/listkinds/) and list modes
    (nanterino/listmodes/) into one module each changed nothing for the editor, the robot and state/vars.json, and that
    the registries' rules hold:
    (1) discovery finds every file of each family (19 types, 2 kinds, 3 modes) in the pinned order, ids = file names,
        graph.py's VAR_TYPES / LIST_TYPES / TYPE_CONTROL / TYPE_DEFAULT / *_TYPES / LIST_KINDS / LIST_MODES are views;
    (2) per type: default valid, validate / coerce / compare / clamp / serialize-deserialize-stored_ok round trips,
        reference choices from the context, vocabulary entry shape; per kind: fresh / serialize / restore; per mode:
        pick / push and the declaration rules;
    (3) persistence back-compat: tests/golden/vars-pre-m3.json (written by the pre-M3 code, same graph) loads with every
        value kept, nothing ignored, and is re-written byte for byte;
    (4) the vocabulary stays byte-identical to tests/golden/vocab-*.json;
    (5) drop-a-file per family (temporary COPY of the package imported in a subprocess): the new type / kind / mode
        appears in the views and the vocabulary and the parser accepts it;
    (6) a broken module per family fails with RegistryError naming the file; a bad type default stops `import graph`;
    (7) built-in mutation check: the copy without vartypes/color.py no longer matches the golden files.

Boundary
    No hardware, muted fake world (tests.test_graph_vars2 harness), nanterino.server never imported. Temporary files only
    under /tmp/test_vartypes_registry (removed at the end).

How to run (repo root):
    .venv/bin/python -m tests.test_vartypes_registry            # ~15 s
    .venv/bin/python -m tests.test_vartypes_registry test_persistence_back_compat
"""
import copy
import datetime
import importlib
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, "/opt/robot/lib")

from nanterino import graph as G, listkinds, listmodes, vartypes  # noqa: E402
from nanterino.brain import Brain  # noqa: E402
from nanterino.registry import RegistryError  # noqa: E402
from nanterino.var_store import VarStore  # noqa: E402
from tests import test_graph_vars2 as T  # noqa: E402
from tests.test_graph_vars import mini, parse  # noqa: E402
from tests.test_nodes_registry import golden_diff, vocab_dumps  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "nanterino")
GOLDEN = os.path.join(ROOT, "tests", "golden")
TMP = "/tmp/test_vartypes_registry"

TYPE_IDS = ["bool", "number", "string", "choice", "duration", "integer", "percent", "datetime", "timer", "expression",
            "gaze", "phrase", "media", "intent_ref", "list_ref", "state_ref", "color", "vector2", "vector3"]
# One valid non-default sample per type (choices given where the type needs them).
SAMPLES = {"bool": True, "number": -2.5, "string": "salut", "choice": "b", "duration": 12, "integer": 7, "percent": 42,
           "datetime": "2026-11-02T09:00", "timer": None, "expression": "triste", "gaze": "errer", "phrase": "Bonjour.",
           "media": "chanson.wav", "intent_ref": "question", "list_ref": "faq", "state_ref": "veille", "color": "#00ff00",
           "vector2": [1, 2.5], "vector3": [0, 0, 1]}
CHOICES = ("a", "b", "question", "faq", "veille")


def persisted_graph_raw():
    """The graph the pre-M3 fixture was written with: T.ALL, every non-conversation name / list persisted."""
    allp = copy.deepcopy(T.ALL)
    for part in ("names", "lists"):
        for s in allp[part].values():
            if s.get("scope") != "conversation":
                s["persist"] = True
    return mini(variables=allp)


# ---------------------------------------------------------------- (1) discovery + views
def test_discovery_and_views():
    for pkg, reg, n in (("vartypes", vartypes.VARTYPES, 19), ("listkinds", listkinds.LISTKINDS, 2),
                        ("listmodes", listmodes.LISTMODES, 3)):
        files = sorted(f[:-3] for f in os.listdir(os.path.join(PKG, pkg)) if f.endswith(".py") and not f.startswith("_"))
        assert sorted(reg) == files and len(files) == n, (pkg, files, list(reg))
        for rid, obj in reg.items():
            assert obj.id == rid and type(obj).__module__ == "nanterino.%s.%s" % (pkg, rid), (pkg, rid)
    assert list(vartypes.VARTYPES) == TYPE_IDS, list(vartypes.VARTYPES)
    assert list(listkinds.LISTKINDS) == ["list", "dict"] and list(listmodes.LISTMODES) == ["plain", "shuffle", "history"]
    V = vartypes.VARTYPES
    assert G.VARTYPES is V
    assert G.VAR_TYPES == {k: t.label for k, t in V.items()} and list(G.VAR_TYPES) == TYPE_IDS
    assert list(G.LIST_TYPES) == ["string", "number", "bool"] + [k for k in TYPE_IDS if k not in ("bool", "number", "string",
                                                                                                  "choice", "timer")]
    assert G.LIST_TYPES["string"] == "Textes" and G.LIST_TYPES["number"] == "Nombres" and G.LIST_TYPES["bool"] == "Vrai / faux"
    assert G.TYPE_CONTROL == {k: t.control for k, t in V.items()} and G.TYPE_DEFAULT == {k: t.default for k, t in V.items()}
    assert G.NUMERIC_TYPES == {"number", "duration", "integer", "percent", "timer"}
    assert G.ORDERED_TYPES == G.NUMERIC_TYPES | {"datetime"}
    assert G.TEXT_TYPES == {"string", "choice", "phrase"}
    assert G.TEXTLIKE_TYPES == {"expression", "gaze", "media", "intent_ref", "list_ref", "state_ref", "color", "datetime"}
    assert G.BOUNDED_TYPES == {"number", "integer"} and G.REF_TYPES == {"intent_ref", "list_ref", "state_ref"}
    assert G.NULLABLE_TYPES == {"datetime", "timer", "media"} | G.REF_TYPES
    assert G.LIST_KINDS == {k: (m.label, m.help) for k, m in listkinds.LISTKINDS.items()}
    assert G.LIST_MODES == {k: (m.label, m.help) for k, m in listmodes.LISTMODES.items()}
    assert G.VAR_KIND_TYPES["numvar"][1] == {"number", "duration", "integer", "percent"}


def test_production_scan_is_closed():
    for mod, attr in ((vartypes, "VARTYPES"), (listkinds, "LISTKINDS"), (listmodes, "LISTMODES")):
        pkg = mod.__name__
        assert mod.PACKAGE == pkg, (mod.PACKAGE, pkg)
        assert list(mod.scan(mod.PACKAGE)) == list(getattr(mod, attr))
        src = open(mod.__file__, encoding="utf-8").read()
        assert "%s = scan(PACKAGE)" % attr in src, pkg
        code = src.split('"""', 2)[2]
        assert "environ" not in code and "yaml" not in code, "discovery must not read names from outside the code"


def test_golden_vocab():
    bad = golden_diff(vocab_dumps(G))
    assert not bad, "vocabulary differs from the golden capture: %s" % bad


# ---------------------------------------------------------------- (2) per-type contract
def test_every_type_contract():
    names = vartypes.Names(("salut", "question"), ("faq",), ("veille", "a"))
    for k, t in vartypes.VARTYPES.items():
        assert t.default is None or t.validate(t.default, ()), (k, t.default)
        assert t.validate(SAMPLES[k], CHOICES), (k, SAMPLES[k])
        assert not t.validate(object(), CHOICES), k
        assert t.coerce("pas un nombre") == "pas un nombre", k
        # choice's default None is a placeholder (the editor picks the first choice), never a stored value
        for v in ((t.default,) if t.default is not None or t.nullable else ()) + (SAMPLES[k],):
            assert t.compare(v, "=", v) and not t.compare(v, "!=", v), (k, v)
            back = t.deserialize(json.loads(json.dumps(t.serialize(v))))
            assert back == v and t.stored_ok(back, CHOICES), (k, v, back)
        assert t.clamp("x", 0, 1) == "x" and t.clamp(None) is None, k
        e = t.entry(None, {"media_dir": "/nonexistent"})
        assert list(e)[:9] == ["id", "label", "control", "options", "ops", "item", "nullable", "default", "persist"], (k, list(e))
        assert set(e["ops"]) <= set(G.OPS) and e["item"] == (k in G.LIST_TYPES), k
        assert t.choices(names, ("p",)) == ({"intent_ref": ("salut", "question"), "list_ref": ("faq",),
                                             "state_ref": ("veille", "a")}.get(k, ("p",))), k
    V = vartypes.VARTYPES
    assert V["integer"].clamp(5.6, 0, 10) == 6 and V["integer"].clamp(50, 0, 10) == 10
    assert V["percent"].clamp(130) == 100 and V["percent"].clamp(-3) == 0 and V["number"].clamp(-7, -1, 1) == -1
    assert V["timer"].stored_ok(1793613601.0) and not V["timer"].validate(1793613601.0)
    assert V["datetime"].compare("2026-11-02T09:00", "<", "2026-11-02T10:00")
    assert not V["datetime"].compare("2026-11-02T09:00", "<", "nope") and not V["number"].compare(True, "<", 2)
    assert V["number"].coerce(" 3.0 ") == 3 and V["percent"].coerce("-2.5") == -2.5 and V["timer"].coerce("3") == "3"
    assert V["vector2"].coerce("1, 2.5") == [1, 2.5] and V["bool"].coerce("Faux") is False
    assert vartypes.compare(1, "<", 2) and Brain._compare(datetime.datetime(2026, 1, 1), "<", datetime.datetime(2026, 1, 2))
    assert G.coerce_value("integer", "07") == 7 and G.coerce_value("integer", "$n") == "$n" and G.coerce_value("nope", "3") == "3"
    assert not G.type_ok("nope", 1) and not G.persisted_ok(parse(mini()), "nope", 1)


def test_list_kinds_and_modes():
    g = parse(mini(variables=T.ALL))
    L, M = listkinds.LISTKINDS, listmodes.LISTMODES
    for name in ("faq", "scores", "sac", "derniers", "points"):
        li = g.lists[name]
        k, vt = L[li.kind], vartypes.VARTYPES[li.type]
        fresh = k.fresh(li.items)
        assert fresh == (dict(li.items) if li.kind == "dict" else list(li.items)) and fresh is not li.items, name
        stored = json.loads(json.dumps(k.serialize(fresh, vt)))
        assert k.restore(g, li, stored) == fresh, name
    assert L["list"].restore(g, g.lists["points"], [[1]]) is None and L["list"].restore(g, g.lists["points"], {"a": 1}) is None
    assert L["dict"].restore(g, g.lists["scores"], {" ": 1}) is None and L["dict"].restore(g, g.lists["scores"], [1]) is None
    assert L["list"].restore(g, g.lists["derniers"], ["a", "b", "c"]) == ["b", "c"], "history keeps the last `max`"
    assert M["history"].needs_max and not M["history"].bound_ok and M["shuffle"].bound_ok and not M["plain"].needs_max
    b, _clock = T.brain(mini(variables=T.ALL))
    items = ["a", "b", "c", "d"]
    bag = [M["shuffle"].pick(b, "sac", items) for _ in range(4)]
    assert sorted(bag) == items, bag
    b.rng.seed(5)
    a1 = [M["plain"].pick(b, "sac", items) for _ in range(6)]
    b.rng.seed(5)
    assert a1 == [b.rng.choice(items) for _ in range(6)], "plain = rng.choice"
    for v in (1, 2, 3, 4):
        M["history"].push(b, g.lists["court"], v)
    assert b.lists["court"] == [2, 3, 4], b.lists["court"]
    for raw, needle in (({"l": {"items": [], "mode": "history"}}, "mode history needs `max:`"),
                        ({"l": {"items": [], "mode": "random"}}, "mode must be one of plain, shuffle, history"),
                        ({"l": {"kind": "dict", "items": {}, "mode": "shuffle"}}, "`mode:` / `max:` only go with kind list"),
                        ({"l": {"from": "refusal_words", "mode": "history", "max": 3}}, "a bound list is read-only")):
        T.refused(mini(variables={"lists": raw}), needle)
    parse(mini(variables={"lists": {"l": {"from": "refusal_words", "mode": "shuffle"}}}))


# ---------------------------------------------------------------- (3) persistence back-compat
def test_persistence_back_compat():
    fixture = os.path.join(GOLDEN, "vars-pre-m3.json")
    d = os.path.join(TMP, "persist")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    path = os.path.join(d, "vars.json")
    shutil.copy(fixture, path)
    b, _clock = T.brain(persisted_graph_raw(), store=VarStore(path))
    assert b.var_store_info()["ignored"] == [], b.var_store_info()["ignored"]
    saved = json.load(open(fixture, encoding="utf-8"))
    for part in ("names", "lists"):
        for name, e in saved[part].items():
            assert b._persist_entry(part, name) == e, (part, name, b._persist_entry(part, name), e)
    assert b.vars["chrono"] == saved["names"]["chrono"]["value"] and b.lists["scores"] == {"alice": 3, "bob": 4}
    st = b._store
    st._dirty = True
    assert st.flush()
    assert open(path, "rb").read() == open(fixture, "rb").read(), "state/vars.json format changed"


# ---------------------------------------------------------------- package copies (drop-a-file / mutation / bad default)
PROBE = r'''
import json, os, sys
sys.path.insert(0, "/opt/robot/lib")
root = os.path.dirname(os.path.abspath(__file__))
import nanterino
assert os.path.dirname(os.path.abspath(nanterino.__file__)) == os.path.join(root, "nanterino"), nanterino.__file__
try:
    from nanterino import graph as G, listkinds, listmodes, vartypes
except Exception as e:
    print("IMPORT_ERROR %s: %s" % (type(e).__name__, e)); sys.exit(3)
sys.path.insert(0, sys.argv[1])
import test_vartypes_probe_helpers as H
H.GOLDEN = sys.argv[2]
v = G.vocabulary({"media_dir": "/nonexistent"})
res = {"types": list(G.VAR_TYPES), "list_types": list(G.LIST_TYPES), "kinds": list(G.LIST_KINDS), "modes": list(G.LIST_MODES),
       "vocab_types": [t["id"] for t in v["var_types"]], "vocab_kinds": [k["id"] for k in v["list_kinds"]],
       "vocab_modes": [m["id"] for m in v["list_modes"]], "golden_diff": H.golden_diff(H.vocab_dumps(G)),
       "mood": next((t for t in v["var_types"] if t["id"] == "mood"), None), "op_mood": v["op_sets"].get("mood")}
CFG = {}
def parse(variables):
    raw = {"states": {"veille": {"transitions": []}, "eteint": {}}, "variables": variables}
    return G.parse_graph(raw, CFG, "<probe>")
if "mood" in vartypes.VARTYPES:
    g = parse({"names": {"m": {"type": "mood", "value": "joyeux"}}, "lists": {"ms": {"type": "mood", "items": ["calme"]}}})
    res["parsed_type"] = [g.variables["m"].type, g.lists["ms"].type]
    try:
        parse({"names": {"m": {"type": "mood", "value": "triste"}}})
        res["refused_type"] = False
    except G.GraphError as e:
        res["refused_type"] = "is not a valid mood value" in str(e)
if "pile" in listkinds.LISTKINDS:
    g = parse({"lists": {"p": {"kind": "pile", "items": ["a"]}}})
    res["parsed_kind"] = g.lists["p"].kind
if "rotation" in listmodes.LISTMODES:
    g = parse({"lists": {"r": {"items": ["a", "b"], "mode": "rotation"}}})
    res["parsed_mode"] = g.lists["r"].mode
print("RESULT " + json.dumps(res, ensure_ascii=False))
'''

MOOD = '''"""Test-only variable type dropped into a temporary package copy (tests/test_vartypes_registry.py)."""
from nanterino.vartypes import VarType


class Mood(VarType):
    id = "mood"
    order = 200
    label = "Humeur"
    control = "select"
    default = "calme"
    textlike = True

    def validate(self, v, choices=()):
        return v in ("calme", "joyeux")
'''

PILE = '''"""Test-only list kind (tests/test_vartypes_registry.py): parsed like a list."""
from nanterino.listkinds.list import ListOfItems


class Pile(ListOfItems):
    id = "pile"
    order = 30
    label = "Pile"
    help = "Liste de test."
'''

ROTATION = '''"""Test-only list mode (tests/test_vartypes_registry.py): always the first item."""
from nanterino.listmodes import ListMode


class Rotation(ListMode):
    id = "rotation"
    order = 40
    label = "Rotation"
    help = "Mode de test."

    def pick(self, brain, name, items):
        return items[0]
'''


def package_copy(tag: str) -> str:
    root = os.path.join(TMP, tag)
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(PKG, os.path.join(root, "nanterino"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.npz", "*.onnx", "*.engine"))
    with open(os.path.join(root, "probe.py"), "w", encoding="utf-8") as f:
        f.write(PROBE)
    return root


def run_probe(root: str) -> tuple:
    helpers = os.path.join(TMP, "helpers")
    os.makedirs(helpers, exist_ok=True)
    shutil.copy(os.path.join(ROOT, "tests", "test_nodes_registry.py"), os.path.join(helpers, "test_vartypes_probe_helpers.py"))
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    p = subprocess.run([sys.executable, os.path.join(root, "probe.py"), helpers, GOLDEN], cwd=root, env=env,
                       capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout + p.stderr


def probe_result(out: str) -> dict:
    line = next((x for x in out.splitlines() if x.startswith("RESULT ")), None)
    assert line, out[-2000:]
    return json.loads(line[len("RESULT "):])


def test_drop_a_file_per_family():
    root = package_copy("drop")
    for rel, src in (("vartypes/mood.py", MOOD), ("listkinds/pile.py", PILE), ("listmodes/rotation.py", ROTATION)):
        with open(os.path.join(root, "nanterino", rel), "w", encoding="utf-8") as f:
            f.write(src)
    rc, out = run_probe(root)
    assert rc == 0, out[-2000:]
    r = probe_result(out)
    assert r["types"] == TYPE_IDS + ["mood"] and r["vocab_types"] == r["types"], r["types"]
    assert r["list_types"][-1] == "mood" and r["op_mood"] == ["=", "!="]
    assert r["mood"]["control"] == "select" and r["mood"]["default"] == "calme" and r["mood"]["label"] == "Humeur", r["mood"]
    assert r["parsed_type"] == ["mood", "mood"] and r["refused_type"] is True, r
    assert r["kinds"] == ["list", "dict", "pile"] == r["vocab_kinds"] and r["parsed_kind"] == "pile", r
    assert r["modes"] == ["plain", "shuffle", "history", "rotation"] == r["vocab_modes"] and r["parsed_mode"] == "rotation", r
    assert sorted(r["golden_diff"]) == ["vocab-default-graph.json", "vocab-no-graph.json"], "a new type changes the vocab"
    assert "mood" not in vartypes.VARTYPES and "pile" not in listkinds.LISTKINDS, "production registries must not see the copy"


def test_missing_type_module_breaks_golden():
    """Built-in mutation check: the golden test detects a type file that disappeared."""
    root = package_copy("mutant")
    os.remove(os.path.join(root, "nanterino", "vartypes", "color.py"))
    rc, out = run_probe(root)
    assert rc == 0, out[-2000:]
    r = probe_result(out)
    assert "color" not in r["types"] and len(r["types"]) == 18
    assert sorted(r["golden_diff"]) == ["vocab-default-graph.json", "vocab-no-graph.json"], r["golden_diff"]


def test_bad_default_stops_graph_import():
    root = package_copy("baddefault")
    p = os.path.join(root, "nanterino", "vartypes", "color.py")
    src = open(p, encoding="utf-8").read()
    assert 'default = "#ffffff"' in src
    open(p, "w", encoding="utf-8").write(src.replace('default = "#ffffff"', 'default = "rouge"'))
    rc, out = run_probe(root)
    assert rc == 3, (rc, out[-2000:])
    assert "IMPORT_ERROR RegistryError: variable type module vartypes/color.py: color.default 'rouge' is not a valid value" in out, out[-2000:]


# ---------------------------------------------------------------- (6) broken modules
def temp_family(tag: str, files: dict) -> str:
    pkg = "m3tmp_" + tag
    d = os.path.join(TMP, "fam", pkg)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "__init__.py"), "w").close()
    for name, src in files.items():
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(src)
    importlib.invalidate_caches()   # the folder is new: refresh the path finders
    if os.path.join(TMP, "fam") not in sys.path:
        sys.path.insert(0, os.path.join(TMP, "fam"))
    return pkg


def expect_error(mod, files: dict, tag: str, needle: str):
    pkg = temp_family(tag, files)
    try:
        mod.scan(pkg)
    except RegistryError as e:
        assert needle in str(e), "message %r lacks %r" % (str(e), needle)
        return
    raise AssertionError("no RegistryError for %s" % tag)


def test_broken_modules_fail_clearly():
    V, K, M = vartypes, listkinds, listmodes
    expect_error(V, {"mood.py": MOOD.replace("def validate", "def validate(")}, "v_syntax",
                 "variable type module vartypes/mood.py failed to import: SyntaxError")
    expect_error(V, {"mood.py": '"""no class"""\n'}, "v_none", "vartypes/mood.py: expected exactly one VarType subclass, found 0")
    expect_error(V, {"mood.py": MOOD + "\n\nclass Other(VarType):\n    id = 'other'\n"}, "v_two",
                 "expected exactly one VarType subclass, found 2")
    expect_error(V, {"humeur.py": MOOD}, "v_idname", "vartypes/humeur.py: id 'mood' must equal the file name 'humeur'")
    expect_error(V, {"mood.py": MOOD.replace('control = "select"', 'control = "knob"')}, "v_control",
                 "mood.control 'knob' has no editor widget")
    expect_error(V, {"mood.py": MOOD.replace("textlike = True", "textlike = 1")}, "v_flag", "mood.textlike must be True or False")
    expect_error(V, {"mood.py": MOOD.replace("textlike = True", "numeric = True")}, "v_order", "a numeric type must be ordered")
    expect_error(V, {"mood.py": MOOD.replace('label = "Humeur"', 'label = ""')}, "v_label", "mood.label must be a non-empty string")
    expect_error(K, {"pile.py": PILE.replace('id = "pile"', 'id = "Pile"')}, "k_id", "listkinds/pile.py: id 'Pile' is not a lower snake case name")
    expect_error(K, {"pile.py": '"""kind without methods"""\nfrom nanterino.listkinds import ListKind\n\n\nclass Pile(ListKind):\n'
                                '    id = "pile"\n    label = "Pile"\n    help = "x"\n'}, "k_methods", "pile does not implement parse()")
    expect_error(K, {"pile.py": PILE.replace('help = "Liste de test."', 'help = None')}, "k_help", "pile.help must be a non-empty string")
    expect_error(M, {"rotation.py": ROTATION.replace('help = "Mode de test."', 'help = "Mode de test."\n    needs_max = "oui"')},
                 "m_flag", "list mode module listmodes/rotation.py: rotation.needs_max must be True or False")
    expect_error(M, {"rotation.py": ROTATION.replace("order = 40", "order = 4.5")}, "m_order", "rotation.order must be an int or None")


TESTS = [test_discovery_and_views, test_production_scan_is_closed, test_golden_vocab, test_every_type_contract,
         test_list_kinds_and_modes, test_persistence_back_compat, test_drop_a_file_per_family,
         test_missing_type_module_breaks_golden, test_bad_default_stops_graph_import, test_broken_modules_fail_clearly]


def main(only):
    failed = 0
    for fn in TESTS:
        if only and fn.__name__ not in only:
            continue
        try:
            fn()
            print("PASS", fn.__name__, flush=True)
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print("FAIL", fn.__name__, "%s: %s" % (type(e).__name__, e), flush=True)
    ran = len([f for f in TESTS if not only or f.__name__ in only])
    print("vartypes_registry tests: %d passed, %d failed" % (ran - failed, failed))
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
