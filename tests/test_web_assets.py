"""Tests of nanterino.web_assets (lot M6): the /web/editor/<path> module route resolver.

Purpose : the editor module tree is served read-only; every traversal / extension / symlink trick must be refused.
Boundary: imports nanterino.web_assets only (never nanterino.server: it builds the live Brain).
Test    : .venv/bin/python -m tests.test_web_assets   (prints PASS lines and a SUMMARY, exit 1 on failure)
"""
import os
import sys
import tempfile
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nanterino import web_assets as wa  # noqa: E402

results = []


def check(name, ok, info=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  " + str(info)))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        web = os.path.join(tmp, "web")
        os.makedirs(os.path.join(web, "editor", "core"))
        open(os.path.join(web, "editor", "main.js"), "w").write("export {};\n")
        open(os.path.join(web, "editor", "core", "state.js"), "w").write("export const S = {};\n")
        open(os.path.join(web, "editor", "core", "notes.txt"), "w").write("x")
        # existing files whose name only STARTS like a module path (a prefix match would serve them)
        open(os.path.join(web, "editor", "main.js.map"), "w").write("x")
        open(os.path.join(web, "editor", "extra.jsx"), "w").write("x")
        open(os.path.join(web, "secret.js"), "w").write("leak")
        open(os.path.join(tmp, "server.py"), "w").write("leak")
        os.symlink(os.path.join(web, "secret.js"), os.path.join(web, "editor", "link.js"))

        r = wa.editor_module(web, "main.js")
        check("main.js served as text/javascript", r and r[1] == "text/javascript" and r[0].endswith("main.js"), r)
        r = wa.editor_module(web, "core/state.js")
        check("nested module served", r and r[0].endswith(os.path.join("core", "state.js")), r)
        bad = ["../server.py", "../secret.js", "core/../../secret.js", "./main.js", "core//state.js", "/etc/passwd",
               "core\\state.js", "Main.js", "core/notes.txt", "main.js.map", "main.py", "", "core/", ".hidden.js",
               "missing.js", "link.js", "a/b/c/d/e/f.js", "main.js\n", "main.js%00", "extra.jsx", None, 42]
        for p in bad:
            check("refused %r" % (p,), wa.editor_module(web, p) is None, wa.editor_module(web, p))
        # what the ASGI server hands the route after URL decoding: encoded traversal must still be refused
        for raw in ["%2e%2e/server.py", "..%2fserver.py", "%2E%2E%2Fsecret.js", "core%2f..%2f..%2fsecret.js"]:
            dec = urllib.parse.unquote(raw)
            check("refused encoded %s (decoded %r)" % (raw, dec), wa.editor_module(web, dec) is None)
        files = wa.editor_module_files(web)
        rel = [os.path.relpath(f, os.path.join(web, "editor")) for f in files]
        check("listing = .js / .css of the tree, sorted", rel == sorted(["core/state.js", "link.js", "main.js"]), rel)
        check("missing tree lists nothing", wa.editor_module_files(os.path.join(tmp, "nope")) == [])
        # preload links: every servable .js once, never a refused file (symlink escape, non-module names)
        links = wa.modulepreload_links(web).split("\n")
        check("preload links = servable modules", links == ['<link rel="modulepreload" href="/web/editor/core/state.js">',
                                                            '<link rel="modulepreload" href="/web/editor/main.js">'], links)
        # cache: same bytes + ETag while unchanged, re-read at once when the file changes (size or mtime)
        mc = wa.ModuleCache()
        p = os.path.join(web, "editor", "main.js")
        b1, e1 = mc.get(p)
        b2, e2 = mc.get(p)
        check("cache hit keeps bytes and etag", (b1, e1) == (b2, e2) and b1 == b"export {};\n", (b1, e1, b2, e2))
        open(p, "w").write("export const x = 1;\n")
        st = os.stat(p)
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1000))
        b3, e3 = mc.get(p)
        check("changed file re-read with a new etag", b3 == b"export const x = 1;\n" and e3 != e1, (b3, e3, e1))
        open(p, "w").write("export const y = 2;\n")      # same size: mtime alone must invalidate
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5000))
        b4, e4 = mc.get(p)
        check("same-size edit re-read (mtime key)", b4 == b"export const y = 2;\n" and e4 != e3, (b4, e4))
    bad = [n for n, ok in results if not ok]
    print("SUMMARY %d checks, %d failed: %s" % (len(results), len(bad), bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
