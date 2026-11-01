"""Tests of the node registry (lot M1, 2026-11-01): nanterino/nodes (discovery, checks) + the vocab golden files.

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
res = {"actions": list(nodes.ACTIONS), "specs": sorted(G.ACTION_SPECS), "golden_diff": golden_diff(vocab_dumps(G))}
v = G.vocabulary({"media_dir": "/nonexistent"})
res["vocab_actions"] = [a["id"] for a in v["actions"]]
res["vocab_hello"] = next((a for a in v["actions"] if a["id"] == "say_hello"), None)
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


def expect_registry_error(files: dict, tag: str, needle: str, check=False):
    pkg = temp_family(tag, files)
    try:
        found = scan(pkg, "actions")
        if check:
            nodes.check_family(found, "actions", G.THEME_DOC, G.ARG_KINDS)
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
    assert len(files) == 38, len(files)
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
    assert nodes.PACKAGES == {"actions": "nanterino.nodes.actions"}, nodes.PACKAGES
    again = scan(nodes.PACKAGES["actions"], "actions")
    assert list(again) == list(nodes.ACTIONS)
    src = open(os.path.join(PKG, "nodes", "__init__.py"), encoding="utf-8").read()
    assert "ACTIONS = scan(PACKAGES[\"actions\"], \"actions\")" in src
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
    assert res["actions"][-1] == "say_hello" and len(res["actions"]) == 39, res["actions"]   # no `order`: last
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
    assert "say_text" not in res["actions"] and len(res["actions"]) == 37
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


TESTS = [test_golden_vocab, test_discovery_finds_every_action, test_ids_unique_themes_kinds_icons_valid,
         test_production_scan_is_closed, test_brain_binds_every_action, test_drop_a_file, test_missing_module_breaks_golden,
         test_bad_theme_stops_graph_import, test_broken_modules_fail_clearly]


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
