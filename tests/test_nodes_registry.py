"""Tests of the node registry (lots M1 + M2, 2026-11-01): nanterino/nodes (discovery, checks) + the vocab golden files.

Purpose
    Prove that moving the actions into one module each changed nothing for the editor and the robot, and that the
    registry's rules hold:
    (1) GET /api/graph/vocab content (graph.vocabulary) is BYTE-identical to tests/golden/vocab-*.json, captured from
        the code before lot M1 (default graph + no graph; media folder pinned to two fixed names);
    (2) discovery finds every file of nanterino/nodes/actions/, ids are unique and equal the file names, every theme /
        argument kind / icon is known, ACTION_DOC / ACTION_SPECS are views of the registry in its order;
    (3) the Brain binds every registered action and a bound action runs through its module;
    (4) drop-a-file: in a temporary COPY of the package, a new actions/<id>.py appears in the registry, in
        ACTION_SPECS, in the vocabulary and is accepted by the graph parser (production discovery is untouched:
        only the copy is scanned, by importing that copy in a subprocess);
    (5) a broken module (syntax error, no class, two classes, id != file name, run() arguments != args, bad theme,
        unknown argument kind) fails with NodeRegistryError naming the file; a bad theme stops `import graph`;
    (6) built-in mutation check: the same copy with one action file removed no longer matches the golden file.
    Lot M2 extends (2)-(6) to the conditions (guards, test()) and triggers (events, match()): all three families
    discovered with their counts, GUARD_* / EVENT_* / WATCH_EVENTS are views of the registry, the Brain binds every
    guard, var_changed / timer_reached match() + subscribe(), drop-a-file / broken module / missing file per family.
    Lot N2 adds (7) test_node_parity: the user's parity rule, visible Triggers == Actions == Conditions (internal
    triggers excluded); the failure message prints the T / A / C table per theme; a package copy with one condition
    file removed must break it (built-in mutation check).

Boundary
    No hardware, muted fake world (tests.test_graph_vars2 harness), nanterino.server never imported. Temporary
    files only under /tmp/test_nodes_registry (removed at the end).

How to run (repo root):
    .venv/bin/python -m tests.test_nodes_registry            # ~15 s
    .venv/bin/python -m tests.test_nodes_registry test_golden_vocab
"""
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, "/opt/robot/lib")

from nanterino import config, graph as G, nodes  # noqa: E402
from nanterino.nodes import NodeRegistryError, scan  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "nanterino")
GOLDEN = os.path.join(ROOT, "tests", "golden")
TMP = "/tmp/test_nodes_registry"
GOLDEN_MEDIA = ("alpha.wav", "beta.json")   # the media folder is pinned: real media/ changes must not move the golden


def vocab_dumps(graph_mod) -> dict:
    """{golden file name: JSON text} of the vocabulary, serialised like the golden capture (order preserved)."""
    out = {}
    with tempfile.TemporaryDirectory() as md:
        for n in GOLDEN_MEDIA:
            open(os.path.join(md, n), "w").close()
        cfg = dict(config.DEFAULTS)
        cfg["media_dir"] = md
        g = graph_mod.load_graph(graph_mod.DEFAULT_PATH, cfg)
        out["vocab-default-graph.json"] = json.dumps(graph_mod.vocabulary(cfg, g), ensure_ascii=False, indent=1) + "\n"
        out["vocab-no-graph.json"] = json.dumps(graph_mod.vocabulary(cfg), ensure_ascii=False, indent=1) + "\n"
    return out


def golden_diff(dumps: dict) -> list:
    """Names of the golden files the given dumps do NOT reproduce byte for byte."""
    bad = []
    for name, text in dumps.items():
        with open(os.path.join(GOLDEN, name), "rb") as f:
            if f.read() != text.encode("utf-8"):
                bad.append(name)
    return bad


# ---------------------------------------------------------------- package copies (drop-a-file / broken module)
PROBE = r'''
import json, os, sys
sys.path.insert(0, "/opt/robot/lib")
root = os.path.dirname(os.path.abspath(__file__))
import nanterino
assert os.path.dirname(os.path.abspath(nanterino.__file__)) == os.path.join(root, "nanterino"), nanterino.__file__
try:
    from nanterino import graph as G, nodes
except Exception as e:
    print("IMPORT_ERROR %s: %s" % (type(e).__name__, e)); sys.exit(3)
sys.path.insert(0, sys.argv[1])            # the real tests/ folder: reuse the golden serialiser
import test_nodes_registry_probe_helpers as H
H.GOLDEN = sys.argv[2]                     # the real golden files, not a path relative to the helper copy
vocab_dumps, golden_diff = H.vocab_dumps, H.golden_diff
res = {"actions": list(nodes.ACTIONS), "specs": sorted(G.ACTION_SPECS), "golden_diff": golden_diff(vocab_dumps(G)),
       "conditions": list(nodes.CONDITIONS), "guards": sorted(G.GUARDS), "triggers": list(nodes.TRIGGERS),
       "events": sorted(G.EVENTS)}
v = G.vocabulary({"media_dir": "/nonexistent"})
res["vocab_actions"] = [a["id"] for a in v["actions"]]
res["vocab_hello"] = next((a for a in v["actions"] if a["id"] == "say_hello"), None)
res["vocab_guards"] = [a["id"] for a in v["guards"]]
res["vocab_always"] = next((a for a in v["guards"] if a["id"] == "always_true"), None)
res["vocab_events"] = [a["id"] for a in v["events"]]
res["vocab_bouton"] = next((a for a in v["events"] if a["id"] == "bouton_test"), None)
res["emit_options"] = next(a for a in v["actions"] if a["id"] == "emit")["args"][0]["options"]
# lot N2: palette counts per family and theme (internal triggers excluded), for the parity mutation check
res["palette"] = {fam: [[n.theme, n.id] for n in reg.values() if not getattr(n, "internal", False)]
                  for fam, reg in (("triggers", nodes.TRIGGERS), ("actions", nodes.ACTIONS), ("conditions", nodes.CONDITIONS))}
if "always_true" in nodes.CONDITIONS and "bouton_test" in nodes.TRIGGERS:
    raw = {"states": {"veille": {"transitions": [{"on": "bouton_test", "when": ["always_true", {"not": "always_true"}],
                                                  "to": "eteint", "description": "test"}]}, "eteint": {}}}
    G.parse_graph(raw, {}, "<probe>")       # raises GraphError if the parser refused the new guard / event
    res["parsed_m2"] = True
if "say_hello" in nodes.ACTIONS:
    raw = {"states": {"veille": {"on_enter": [{"say_hello": {"name": "Marie"}}], "transitions": []}, "eteint": {}}}
    G.parse_graph(raw, {}, "<probe>")       # raises GraphError if the parser refused the new action
    res["parsed"] = True
print("RESULT " + json.dumps(res, ensure_ascii=False))
'''

HELLO = '''"""Test-only action dropped into a temporary package copy (tests/test_nodes_registry.py)."""
from nanterino.nodes.base import Action, Arg


class SayHello(Action):
    id = "say_hello"
    label = "Dire bonjour"
    help = "Dit bonjour au visiteur nommé."
    icon = "volume"
    theme = "parole"
    args = {"name": Arg("text", "Nom")}

    def run(self, ctx, name):
        ctx.brain._speak_then("Bonjour " + name, "say_done")
'''


def package_copy(tag: str) -> str:
    """Copy nanterino/ (code + graph.yaml, no caches) to TMP/<tag>/nanterino; returns TMP/<tag>."""
    root = os.path.join(TMP, tag)
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(PKG, os.path.join(root, "nanterino"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.npz", "*.onnx", "*.engine"))
    with open(os.path.join(root, "probe.py"), "w", encoding="utf-8") as f:
        f.write(PROBE)
    return root


def run_probe(root: str) -> tuple:
    """Import the COPY in a fresh interpreter (cwd and sys.path = the copy only). Returns (exit code, stdout)."""
    helpers = os.path.join(TMP, "helpers")
    os.makedirs(helpers, exist_ok=True)
    shutil.copy(os.path.abspath(__file__), os.path.join(helpers, "test_nodes_registry_probe_helpers.py"))
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    p = subprocess.run([sys.executable, os.path.join(root, "probe.py"), helpers, GOLDEN], cwd=root, env=env,
                       capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout + p.stderr


def probe_result(out: str) -> dict:
    line = next((x for x in out.splitlines() if x.startswith("RESULT ")), None)
    assert line, out[-2000:]
    return json.loads(line[len("RESULT "):])


ALWAYS = '''"""Test-only condition dropped into a temporary package copy (tests/test_nodes_registry.py)."""
from nanterino.nodes.base import Condition


class AlwaysTrue(Condition):
    id = "always_true"
    label = "Toujours vrai"
    help = "Condition de test, toujours vraie."
    icon = "circle-dot"
    theme = "variables"

    def test(self, ctx):
        return True
'''

BOUTON = '''"""Test-only trigger dropped into a temporary package copy (tests/test_nodes_registry.py)."""
from nanterino.nodes.base import Trigger


class BoutonTest(Trigger):
    id = "bouton_test"
    label = "Bouton de test"
    help = "Déclencheur de test."
    icon = "bolt"
    theme = "systeme"
'''

WATCH = '''"""Test-only argument-carrying trigger (tests/test_nodes_registry.py)."""
from nanterino.nodes.base import ANY, Arg, Trigger


class Surveille(Trigger):
    id = "surveille"
    label = "Surveille"
    help = "Déclencheur de test avec argument."
    icon = "bolt"
    theme = "variables"
    args = {"name": Arg("anyvar", "Variable")}

    def match(self, ctx, event, name):
        return name == ctx.kw.get("name")

    def editor_args(self, g):
        return []
'''


def temp_family(tag: str, files: dict) -> str:
    """A minimal importable actions package TMP/<tag>/<pkg>/ with `files` ({name: source}); returns its name."""
    pkg = "m1tmp_" + tag
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


def expect_registry_error(files: dict, tag: str, needle: str, check=False, family="actions"):
    pkg = temp_family(tag, files)
    try:
        found = scan(pkg, family)
        if check:
            nodes.check_family(found, family, G.THEME_DOC, G.ARG_KINDS)
    except NodeRegistryError as e:
        msg = str(e)
        assert needle in msg, "message %r lacks %r" % (msg, needle)
        return msg
    raise AssertionError("no NodeRegistryError for %s" % tag)


# ---------------------------------------------------------------- tests
def test_golden_vocab():
    bad = golden_diff(vocab_dumps(G))
    assert not bad, "vocabulary differs from the pre-M1 golden capture: %s" % bad


def test_discovery_finds_every_action():
    files = sorted(f[:-3] for f in os.listdir(os.path.join(PKG, "nodes", "actions"))
                   if f.endswith(".py") and not f.startswith("_"))
    assert sorted(nodes.ACTIONS) == files, set(files) ^ set(nodes.ACTIONS)
    assert len(files) == 50, len(files)   # 38 + 12 (lot N1)
    assert list(G.ACTION_DOC) == list(nodes.ACTIONS) == list(G.ACTION_SPECS)
    for nid, n in nodes.ACTIONS.items():
        assert n.id == nid and type(n).__module__ == "nanterino.nodes.actions." + nid, (nid, type(n).__module__)
        assert G.ACTION_SPECS[nid] == {a: d.kind for a, d in n.args.items()}
        assert G.ACTION_DOC[nid] == (n.label, n.help, dict(n.args))
    orders = [n.order for n in nodes.ACTIONS.values()]
    assert orders == sorted(orders) and len(set(orders)) == len(orders), "palette order must be strict"


def test_ids_unique_themes_kinds_icons_valid():
    ids = [n.id for n in nodes.ACTIONS.values()]
    assert len(ids) == len(set(ids))
    icons = set(G.all_icons())
    for n in nodes.ACTIONS.values():
        assert n.theme in G.THEME_DOC, (n.id, n.theme)
        assert n.icon in icons, (n.id, n.icon)
        for a, d in n.args.items():
            assert d.kind in G.ARG_KINDS, (n.id, a, d.kind)
            assert G.ARG_KIND_HELP.get(d.kind), "argument kind without inspector help: %s.%s" % (n.id, a)
    nodes.check_family(nodes.ACTIONS, "actions", G.THEME_DOC, G.ARG_KINDS)   # the import-time check, again


def test_production_scan_is_closed():
    assert nodes.PACKAGES == {"actions": "nanterino.nodes.actions", "conditions": "nanterino.nodes.conditions",
                              "triggers": "nanterino.nodes.triggers"}, nodes.PACKAGES
    registry = {"actions": nodes.ACTIONS, "conditions": nodes.CONDITIONS, "triggers": nodes.TRIGGERS}
    src = open(os.path.join(PKG, "nodes", "__init__.py"), encoding="utf-8").read()
    for fam, reg in registry.items():
        again = scan(nodes.PACKAGES[fam], fam)
        assert list(again) == list(reg), fam
        assert "%s = scan(PACKAGES[\"%s\"], \"%s\")" % (fam.upper(), fam, fam) in src, fam
    code = src.split('"""', 2)[2]   # code after the module docstring
    assert "environ" not in code and "yaml" not in code, "discovery must not read names from outside the code"


def test_brain_binds_every_action():
    from tests import test_graph_vars as tgv
    from tests import test_graph_vars2 as tv2
    b, _clock = tv2.brain(tgv.mini())
    assert set(b.engine.actions) == set(nodes.ACTIONS)
    t0 = b.turns
    tv2.act(b, "count_turn")
    assert b.turns == t0 + 1
    tv2.act(b, "set_expression", name="triste", seconds=2)
    assert b._expression[0] == "triste"
    assert b.engine.actions["say_text"].__name__ == "action_say_text"


def test_drop_a_file():
    root = package_copy("drop")
    with open(os.path.join(root, "nanterino", "nodes", "actions", "say_hello.py"), "w", encoding="utf-8") as f:
        f.write(HELLO)
    rc, out = run_probe(root)
    assert rc == 0, out[-2000:]
    res = probe_result(out)
    assert res["actions"][-1] == "say_hello" and len(res["actions"]) == 51, res["actions"]   # no `order`: last (50 since lot N1)
    assert "say_hello" in res["specs"] and res["vocab_actions"][-1] == "say_hello"
    h = res["vocab_hello"]
    assert h["label"] == "Dire bonjour" and h["theme"] == "parole" and h["icon"] == "volume", h
    assert h["args"] == [{"name": "name", "type": "text", "max_len": G.TEXT_MAX, "label": "Nom",
                          "help": G.ARG_KIND_HELP["text"]}], h["args"]
    assert res["parsed"] is True
    assert "say_hello" not in nodes.ACTIONS, "the production registry must not see the copy"


def test_missing_module_breaks_golden():
    """Built-in mutation check: the golden test detects an action file that disappeared."""
    root = package_copy("mutant")
    os.remove(os.path.join(root, "nanterino", "nodes", "actions", "say_text.py"))
    rc, out = run_probe(root)
    assert rc == 0, out[-2000:]
    res = probe_result(out)
    assert "say_text" not in res["actions"] and len(res["actions"]) == 49
    assert sorted(res["golden_diff"]) == ["vocab-default-graph.json", "vocab-no-graph.json"], res["golden_diff"]


def test_bad_theme_stops_graph_import():
    root = package_copy("badtheme")
    p = os.path.join(root, "nanterino", "nodes", "actions", "mic_off.py")
    src = open(p, encoding="utf-8").read()
    assert "theme = 'micro'" in src
    open(p, "w", encoding="utf-8").write(src.replace("theme = 'micro'", "theme = 'nulle_part'"))
    rc, out = run_probe(root)
    assert rc == 3, (rc, out[-2000:])
    assert "IMPORT_ERROR NodeRegistryError: node module actions/mic_off.py: unknown theme 'nulle_part'" in out, out[-2000:]


def test_broken_modules_fail_clearly():
    ok = HELLO
    expect_registry_error({"say_hello.py": ok.replace("def run(self, ctx, name):", "def run(self, ctx, name)")},
                          "syntax", "node module actions/say_hello.py failed to import: SyntaxError")
    expect_registry_error({"say_hello.py": '"""no node here"""\nX = 1\n'}, "empty",
                          "actions/say_hello.py: expected exactly one Action subclass, found 0")
    two = ok + "\n\nclass Other(SayHello.__mro__[1]):\n    id = 'other'\n"
    expect_registry_error({"say_hello.py": two}, "two", "expected exactly one Action subclass, found 2")
    expect_registry_error({"hello.py": ok}, "idname", "actions/hello.py: id 'say_hello' must equal the file name 'hello'")
    expect_registry_error({"say_hello.py": ok.replace("def run(self, ctx, name):", "def run(self, ctx, nom):")},
                          "args", "run() arguments ['nom'] differ from args ['name']")
    expect_registry_error({"say_hello.py": ok.replace("def run(self, ctx, name):", "def run(self, ctx, **args):")},
                          "kwargs", "must name its arguments")
    expect_registry_error({"say_hello.py": ok.replace('icon = "volume"', 'icon = ""')}, "icon", "say_hello.icon must be a non-empty string")
    expect_registry_error({"say_hello.py": ok.replace('Arg("text", "Nom")', '("text", "Nom")')}, "argshape",
                          "say_hello.name must be Arg(kind, label)")
    expect_registry_error({"say_hello.py": ok.replace('theme = "parole"', 'theme = "nulle_part"')}, "theme",
                          "unknown theme 'nulle_part'", check=True)
    expect_registry_error({"say_hello.py": ok.replace('Arg("text", "Nom")', 'Arg("txet", "Nom")')}, "kind",
                          "say_hello.name: unknown argument kind 'txet'", check=True)
    valueof = ok.replace('{"name": Arg("text", "Nom")}', '{"what": Arg("value", "Nom")}').replace("ctx, name):", "ctx, what):")
    expect_registry_error({"say_hello.py": valueof}, "valueof",
                          "a value argument needs a `name`, `list` or `dict` argument", check=True)
    # a private file (leading underscore) is skipped, a valid module loads
    pkg = temp_family("good", {"say_hello.py": ok, "_draft.py": "raise SystemExit('never imported')\n"})
    assert list(scan(pkg, "actions")) == ["say_hello"]


# ---------------------------------------------------------------- lot M2: conditions + triggers
def family_files(fam: str) -> list:
    return sorted(f[:-3] for f in os.listdir(os.path.join(PKG, "nodes", fam)) if f.endswith(".py") and not f.startswith("_"))


def test_discovery_finds_every_condition_and_trigger():
    assert sorted(nodes.CONDITIONS) == family_files("conditions") and len(nodes.CONDITIONS) == 50, list(nodes.CONDITIONS)   # 18 + 13 (N1) + 19 (N2)
    assert sorted(nodes.TRIGGERS) == family_files("triggers") and len(nodes.TRIGGERS) == 52, list(nodes.TRIGGERS)   # 25 + 13 (N1) + 14 (N2)
    assert len(nodes.ACTIONS) + len(nodes.CONDITIONS) + len(nodes.TRIGGERS) == 152   # 81 + 38 (N1) + 33 (N2)
    for fam, reg in (("conditions", nodes.CONDITIONS), ("triggers", nodes.TRIGGERS)):
        for nid, n in reg.items():
            assert n.id == nid and type(n).__module__ == "nanterino.nodes.%s.%s" % (fam, nid), (nid, type(n).__module__)
        orders = [n.order for n in reg.values()]
        assert orders == sorted(orders) and len(set(orders)) == len(orders), "palette order must be strict: " + fam
    # graph.py tables are views of the registry, in its order (no second list of guards / events)
    assert list(G.GUARD_DOC) == list(nodes.CONDITIONS) == list(G.GUARD_ICON) == list(G.GUARD_THEME)
    assert list(G.EVENT_DOC) == list(nodes.TRIGGERS) == list(G.EVENT_ICON) == list(G.EVENT_THEME)
    for nid, n in nodes.CONDITIONS.items():
        assert G.GUARD_DOC[nid] == (n.label, n.help) and G.GUARD_SPECS[nid] == {a: d.kind for a, d in n.args.items()}
        assert G.GUARD_AS_VARS.get(nid) == n.as_vars
    assert G.GUARD_AS_VARS == {"turns_left": "tours < max_tours", "repairs_left": "reparations < max_reparations"}
    assert G.INTERNAL_EVENTS == {"utterance", "tick"} and G.EVENTS == frozenset(nodes.TRIGGERS)
    assert G.WATCH_EVENTS == ("var_changed", "timer_reached", "list_changed", "dict_changed", "timer_stopped", "journal_entry",
                             "list_item_added", "list_item_removed"), G.WATCH_EVENTS   # lot N1, lot N2
    for fam, reg in (("conditions", nodes.CONDITIONS), ("triggers", nodes.TRIGGERS)):
        icons = set(G.all_icons())
        for n in reg.values():
            assert n.theme in G.THEME_DOC and n.icon in icons, (fam, n.id, n.theme, n.icon)
            for a, d in n.args.items():
                assert d.kind in G.ARG_KINDS, (n.id, a, d.kind)
        nodes.check_family(reg, fam, G.THEME_DOC, G.ARG_KINDS)
    # source of truth: graph.py / brain.py no longer spell out the guard / event tables or closures
    gsrc = open(os.path.join(PKG, "graph.py"), encoding="utf-8").read()
    bsrc = open(os.path.join(PKG, "brain.py"), encoding="utf-8").read()
    for needle in ("\"stop\": (\"Bouton Stop\"", "\"var_compare\": (\"Comparer une variable\"", "\"auto_greet_on_face\": \"scan-eye\"",
                   "\"dict_has\": \"listes\"", "\"var_types\": list(VAR_TYPES), \"writable\": False"):
        assert needle not in gsrc, "graph.py still holds a guard / event table: " + needle
    for needle in ("def var_compare(", "def list_contains(", "\"not_busy\": lambda", "def time_between("):
        assert needle not in bsrc, "brain.py still holds a guard closure: " + needle


def test_brain_binds_every_guard_and_watch_trigger():
    from tests import test_graph_vars as tgv
    from tests import test_graph_vars2 as tv2
    from nanterino import brain as brain_mod
    b, _clock = tv2.brain(tgv.mini())
    eng = b.engine
    assert set(eng.guards) == set(nodes.CONDITIONS) and eng.guards["var_true"].__name__ == "guard_var_true"
    old = brain_mod.MAX_TURNS
    try:
        b.turns = 3
        brain_mod.MAX_TURNS = 3          # looked up at call time by conditions/turns_left.py
        assert not eng.guards["turns_left"]({})
        brain_mod.MAX_TURNS = 4
        assert eng.guards["turns_left"]({})
    finally:
        brain_mod.MAX_TURNS = old
    assert eng.guards["time_between"]({}, start="00:00", end="00:00") is False   # empty range
    assert eng.guards["weekday_in"]({}, days=list(G.WEEKDAYS)) is True
    # var_changed / timer_reached: the module's match() decides (missing `value:` = ANY)
    ctx = nodes.NodeContext(b, {"name": "x", "value": 2}, b.cfg, b._graph)
    vc, tr = nodes.TRIGGERS["var_changed"], nodes.TRIGGERS["timer_reached"]
    assert vc.match(ctx, "var_changed", name="x") and vc.match(ctx, "var_changed", name="x", value=2)
    assert not vc.match(ctx, "var_changed", name="x", value=3) and not vc.match(ctx, "var_changed", name="y")
    assert tr.match(ctx, "timer_reached", name="x", value=2) and not tr.match(ctx, "timer_reached", name="x", value=5)
    assert nodes.TRIGGERS["stop"].match(ctx, "stop") and nodes.ANY is not None
    raw = {"variables": {"names": {"n": {"type": "number", "value": 0, "description": "n"},
                                   "c": {"type": "timer", "value": None, "description": "c"}}},
           "states": {"veille": {"transitions": [
               {"on": "var_changed", "var": "n", "description": "a"},
               {"on": "timer_reached", "var": "c", "value": 3, "description": "b"},
               {"on": "timer_reached", "var": "c", "value": 3, "description": "dup", "enabled": True}]}, "eteint": {}}}
    g = G.parse_graph(raw, {}, "<m2>")
    assert g.watched_vars() == frozenset({"n"}) == vc.subscribe(g)
    assert g.timer_watches() == (("c", 3),) == tr.subscribe(g)
    for bad, needle in ((dict(raw["states"]["veille"]["transitions"][0], var="nope"), "`on: var_changed` needs `var:`"),
                        (dict(raw["states"]["veille"]["transitions"][1], value=0), "needs `value:` = a number of seconds")):
        r2 = {"variables": raw["variables"], "states": {"veille": {"transitions": [bad]}, "eteint": {}}}
        try:
            G.parse_graph(r2, {}, "<m2>")
        except G.GraphError as e:
            assert needle in str(e), str(e)
        else:
            raise AssertionError("parser accepted " + needle)


def test_engine_dispatch_goes_through_trigger_match():
    """End to end: the engine's `var:` / `value:` filtering of var_changed / timer_reached is the modules' match()."""
    from tests import test_graph_vars as tgv
    from tests import test_graph_vars2 as tv2
    variables = {"names": {k: {"type": "integer", "value": 0} for k in ("n", "m", "k", "t3", "t5")}}
    variables["names"]["c"] = {"type": "timer", "value": None}
    raw = tgv.mini(glob=[{"on": "var_changed", "var": "n", "value": 2, "do": [{"add_var": {"name": "m", "delta": 1}}]},
                         {"on": "var_changed", "var": "n", "do": [{"add_var": {"name": "k", "delta": 1}}]},
                         {"on": "timer_reached", "var": "c", "value": 3, "do": [{"add_var": {"name": "t3", "delta": 1}}]},
                         {"on": "timer_reached", "var": "c", "value": 5, "do": [{"add_var": {"name": "t5", "delta": 1}}]}],
                   variables=variables)
    b, clock = tv2.brain(raw)
    tv2.act(b, "set_var", name="n", value=1)
    assert (b.vars["k"], b.vars["m"]) == (1, 0), b.vars     # any change: k; value 2 only: not m
    tv2.act(b, "set_var", name="n", value=2)
    assert (b.vars["k"], b.vars["m"]) == (2, 1), b.vars
    tv2.act(b, "timer_start", name="c")
    tv2.adv(b, clock, 3.5)
    assert (b.vars["t3"], b.vars["t5"]) == (1, 0), b.vars    # the 3 s post must not fire the 5 s transition
    tv2.adv(b, clock, 2)
    assert (b.vars["t3"], b.vars["t5"]) == (1, 1), b.vars


def test_drop_a_condition_and_a_trigger():
    root = package_copy("drop2")
    for fam, name, src in (("conditions", "always_true", ALWAYS), ("triggers", "bouton_test", BOUTON)):
        with open(os.path.join(root, "nanterino", "nodes", fam, name + ".py"), "w", encoding="utf-8") as f:
            f.write(src)
    rc, out = run_probe(root)
    assert rc == 0, out[-2000:]
    res = probe_result(out)
    assert res["conditions"][-1] == "always_true" and len(res["conditions"]) == 51, res["conditions"]
    assert res["triggers"][-1] == "bouton_test" and len(res["triggers"]) == 53, res["triggers"]
    assert "always_true" in res["guards"] and "bouton_test" in res["events"]
    assert res["vocab_guards"][-1] == "always_true" and res["vocab_events"][-1] == "bouton_test"
    a = res["vocab_always"]
    assert a == {"id": "always_true", "label": "Toujours vrai", "help": "Condition de test, toujours vraie.",
                 "icon": "circle-dot", "theme": "variables", "args": []}, a
    assert res["vocab_bouton"] == {"id": "bouton_test", "label": "Bouton de test", "help": "Déclencheur de test.",
                                   "icon": "bolt", "theme": "systeme"}, res["vocab_bouton"]
    assert "bouton_test" in res["emit_options"], "a dropped event must be offered by the emit action"
    assert res["parsed_m2"] is True
    assert "always_true" not in nodes.CONDITIONS and "bouton_test" not in nodes.TRIGGERS


def test_missing_condition_or_trigger_breaks_golden():
    """Built-in mutation check per family: a guard / event file that disappeared changes the vocabulary."""
    for fam, name in (("conditions", "list_empty"), ("triggers", "say_done")):
        root = package_copy("mutant_" + fam)
        os.remove(os.path.join(root, "nanterino", "nodes", fam, name + ".py"))
        rc, out = run_probe(root)
        assert rc == 0, out[-2000:]
        res = probe_result(out)
        assert name not in res[fam], (fam, name)
        assert sorted(res["golden_diff"]) == ["vocab-default-graph.json", "vocab-no-graph.json"], (fam, res["golden_diff"])


def test_bad_condition_or_trigger_stops_graph_import():
    for fam, name, theme in (("conditions", "mic_active", "micro"), ("triggers", "hush", "parole")):
        root = package_copy("badtheme_" + fam)
        p = os.path.join(root, "nanterino", "nodes", fam, name + ".py")
        src = open(p, encoding="utf-8").read()
        assert "theme = '%s'" % theme in src, (fam, name)
        open(p, "w", encoding="utf-8").write(src.replace("theme = '%s'" % theme, "theme = 'nulle_part'"))
        rc, out = run_probe(root)
        assert rc == 3, (fam, rc, out[-2000:])
        assert ("IMPORT_ERROR NodeRegistryError: node module %s/%s.py: unknown theme 'nulle_part'" % (fam, name)) in out, out[-2000:]


def test_broken_conditions_and_triggers_fail_clearly():
    c, w = ALWAYS, WATCH
    with_arg = c.replace('theme = "variables"', 'theme = "variables"\n    args = {"name": Arg("anyvar", "Variable")}') \
                .replace("import Condition", "import Arg, Condition").replace("def test(self, ctx):", "def test(self, ctx, name):")
    assert list(scan(temp_family("c_ok", {"always_true.py": with_arg}), "conditions")) == ["always_true"]
    expect_registry_error({"always_true.py": c.replace("def test(self, ctx):", "def tst(self, ctx):")}, "c_notest",
                          "conditions/always_true.py: always_true does not implement test()", family="conditions")
    expect_registry_error({"always_true.py": with_arg.replace("ctx, name):", "ctx, nom):")}, "c_args",
                          "always_true.test() arguments ['nom'] differ from args ['name']", family="conditions")
    expect_registry_error({"always_true.py": with_arg.replace("ctx, name):", "ctx, **args):")}, "c_kwargs",
                          "always_true.test() must name its arguments", family="conditions")
    expect_registry_error({"always_true.py": c.replace('theme = "variables"', 'theme = "variables"\n    as_vars = 3')},
                          "c_asvars", "always_true.as_vars must be None or a non-empty string", family="conditions")
    expect_registry_error({"always_true.py": c}, "c_wrongfam", "expected exactly one Trigger subclass, found 0",
                          family="triggers")
    expect_registry_error({"always_true.py": c.replace('theme = "variables"', 'theme = "nulle_part"')}, "c_theme",
                          "conditions/always_true.py: unknown theme 'nulle_part'", check=True, family="conditions")
    expect_registry_error({"always_true.py": with_arg.replace('Arg("anyvar"', 'Arg("nyvar"')}, "c_kind",
                          "always_true.name: unknown argument kind 'nyvar'", check=True, family="conditions")
    # triggers
    assert list(scan(temp_family("t_ok", {"surveille.py": w, "bouton_test.py": BOUTON}), "triggers")) == ["bouton_test", "surveille"]
    expect_registry_error({"surveille.py": w.replace("def match(self, ctx, event, name):", "def mtch(self, ctx, event, name):")},
                          "t_nomatch", "triggers/surveille.py: surveille does not implement match()", family="triggers")
    expect_registry_error({"surveille.py": w.replace("ctx, event, name):", "ctx, event, nom):")}, "t_args",
                          "surveille.match() arguments ['nom'] differ from args ['name']", family="triggers")
    expect_registry_error({"surveille.py": w.replace("ctx, event, name):", "ctx, name):")}, "t_noevent",
                          "surveille.match() arguments [] differ from args ['name']", family="triggers")
    expect_registry_error({"surveille.py": w.replace("def editor_args(self, g):", "def editor_arg(self, g):")}, "t_noschema",
                          "surveille has args but does not implement editor_args()", family="triggers")
    expect_registry_error({"bouton_test.py": BOUTON.replace('theme = "systeme"', 'theme = "systeme"\n    internal = "oui"')},
                          "t_internal", "bouton_test.internal must be True or False", family="triggers")
    expect_registry_error({"bouton_test.py": BOUTON + "\n\nclass Other(BoutonTest.__mro__[1]):\n    id = 'other'\n"}, "t_two",
                          "expected exactly one Trigger subclass, found 2", family="triggers")
    expect_registry_error({"bouton.py": BOUTON}, "t_idname", "triggers/bouton.py: id 'bouton_test' must equal the file name 'bouton'",
                          family="triggers")
    expect_registry_error({"bouton_test.py": BOUTON.replace("theme = \"systeme\"\n", "theme = \"systeme\"\n\n    def match(self, ctx, event, x):\n        return True\n")},
                          "t_plainargs", "bouton_test.match() arguments ['x'] differ from args []", family="triggers")
    expect_registry_error({"surveille.py": w.replace('Arg("anyvar"', 'Arg("nyvar"')}, "t_kind",
                          "surveille.name: unknown argument kind 'nyvar'", check=True, family="triggers")


# ---------------------------------------------------------------- lot N2: the parity rule (Notes/HOWTO-add-node.md)
def palette_of(registries) -> dict:
    """{family: [[theme, id], ...]} of the nodes visible in the editor's palette (internal triggers left out)."""
    return {fam: [[n.theme, n.id] for n in reg.values() if not getattr(n, "internal", False)] for fam, reg in registries}


def parity_problem(palette: dict):
    """None when Déclencheurs == Actions == Conditions (visible counts); else a message with the table per theme."""
    import collections
    fams = ("triggers", "actions", "conditions")
    totals = [len(palette[f]) for f in fams]
    if totals[0] == totals[1] == totals[2]:
        return None
    per = {f: collections.Counter(t for t, _i in palette[f]) for f in fams}
    themes = [t for t in G.THEME_DOC if any(per[f].get(t) for f in fams)]
    rows = ["%-13s %4s %4s %4s" % ("theme", "T", "A", "C")]
    rows += ["%-13s %4d %4d %4d" % (t, per["triggers"][t], per["actions"][t], per["conditions"][t]) for t in themes]
    rows.append("%-13s %4d %4d %4d" % ("TOTAL", *totals))
    return ("parity rule broken: Triggers %d / Actions %d / Conditions %d must be equal (one concept = action + trigger "
            "+ condition, Notes/HOWTO-add-node.md « Règle de parité »)\n%s" % (*totals, "\n".join(rows)))


def test_node_parity():
    """Lot N2 (durable user rule): the palette shows as many triggers as actions as conditions. Built-in mutation check:
    a package copy with one condition file removed breaks the rule (and the message names the counts per theme)."""
    pal = palette_of((("triggers", nodes.TRIGGERS), ("actions", nodes.ACTIONS), ("conditions", nodes.CONDITIONS)))
    problem = parity_problem(pal)
    assert problem is None, problem
    assert len(pal["triggers"]) >= 50, "lot N2 reached 50 / 50 / 50: never shrink the palette silently"
    root = package_copy("mutant_parity")
    os.remove(os.path.join(root, "nanterino", "nodes", "conditions", "is_question.py"))
    rc, out = run_probe(root)
    assert rc == 0, out[-2000:]
    msg = parity_problem(probe_result(out)["palette"])
    assert msg and "Conditions %d" % (len(pal["conditions"]) - 1) in msg and "conversation" in msg, msg


TESTS = [test_golden_vocab, test_discovery_finds_every_action, test_ids_unique_themes_kinds_icons_valid,
         test_production_scan_is_closed, test_brain_binds_every_action, test_drop_a_file, test_missing_module_breaks_golden,
         test_bad_theme_stops_graph_import, test_broken_modules_fail_clearly,
         # lot M2
         test_discovery_finds_every_condition_and_trigger, test_brain_binds_every_guard_and_watch_trigger,
         test_engine_dispatch_goes_through_trigger_match, test_drop_a_condition_and_a_trigger, test_missing_condition_or_trigger_breaks_golden,
         test_bad_condition_or_trigger_stops_graph_import, test_broken_conditions_and_triggers_fail_clearly,
         # lot N2
         test_node_parity]


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
    print("nodes_registry tests: %d passed, %d failed" % (ran - failed, failed))
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
