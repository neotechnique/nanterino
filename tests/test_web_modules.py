"""Static check of the editor ES modules under web/editor/ (lot M7), fast (about 1 s, no browser, no server).

Purpose : every module parses as an ES module, every import names an existing module and an existing export, no
          import is unused, every free identifier is a known browser / language global, no module exceeds 40 KB,
          and every module is reachable from main.js. A self-test on fixture modules proves each rule can fail.
Boundary: reads web/editor/** and runs `gjs tests/web_modules_scan.js` (SpiderMonkey Reflect.parse); imports nothing
          from nanterino (never nanterino.server).
Invariant: the allow-list below is the browser surface the editor may touch; a new global (or a typo that looks
          like one) must be added here on purpose. The scanner reports facts, the policy lives here.
Test    : .venv/bin/python -m tests.test_web_modules   (prints PASS / FAIL lines, `web_modules tests: n/n passed`
          and a SUMMARY line; exit 1 on failure). Optional arg: another editor root (used by the mutation run).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANNER = os.path.join(REPO, "tests", "web_modules_scan.js")
EDITOR = os.path.join(REPO, "web", "editor")
MAX_BYTES = 40 * 1024   # plan M6/M7: no module over 40 KB (the biggest was 27.5 KB at M6)

# Globals the editor may use: JS language built-ins, the browser APIs it calls, and the Drawflow library
# (a classic <script> loaded by /editor before the modules).
ALLOWED_GLOBALS = {
    # language
    "Array", "ArrayBuffer", "BigInt", "Boolean", "DataView", "Date", "Error", "Float32Array", "Float64Array",
    "Function", "Infinity", "Int32Array", "Intl", "JSON", "Map", "Math", "NaN", "Number", "Object", "Promise",
    "Proxy", "RangeError", "Reflect", "RegExp", "Set", "String", "Symbol", "SyntaxError", "TypeError",
    "Uint8Array", "Uint8ClampedArray", "Uint16Array", "Uint32Array", "WeakMap", "WeakSet", "arguments",
    "decodeURIComponent", "encodeURIComponent", "globalThis", "isFinite", "isNaN", "parseFloat", "parseInt",
    "structuredClone", "undefined",
    # browser
    "AbortController", "Blob", "CSS", "CustomEvent", "DOMParser", "DOMRect", "Event", "File", "FileReader",
    "FormData", "HTMLElement", "Image", "KeyboardEvent", "MouseEvent", "MutationObserver", "PointerEvent",
    "ResizeObserver", "TextDecoder", "TextEncoder", "URL", "URLSearchParams", "WebSocket", "alert",
    "cancelAnimationFrame", "clearInterval", "clearTimeout", "confirm", "console", "devicePixelRatio", "document",
    "fetch", "getComputedStyle", "history", "innerHeight", "innerWidth", "localStorage", "location", "navigator",
    "performance", "prompt", "queueMicrotask", "requestAnimationFrame", "sessionStorage", "setInterval",
    "setTimeout", "window",
    # libraries loaded as classic scripts by /editor
    "Drawflow",
}

results = []


def check(name, ok, info=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  " + str(info)), flush=True)


def scan(paths):
    """Run the gjs scanner; {abs path: record}."""
    out = subprocess.run(["gjs", SCANNER] + paths, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError("scanner exit %s: %s" % (out.returncode, out.stderr.strip()[-400:]))
    return {os.path.abspath(f["path"]): f for f in json.loads(out.stdout)["files"]}


def modules(root):
    found = []
    for d, _, files in os.walk(root):
        found += [os.path.join(d, f) for f in files if f.endswith(".js")]
    return sorted(found)


def analyse(root):
    """Problems of the module tree at root, by rule: {rule: [messages]}."""
    paths = modules(root)
    recs = scan(paths)
    probs = {"parse": [], "size": [], "import": [], "unused": [], "free": [], "orphan": []}

    def rel(p):
        return os.path.relpath(p, root)

    def exports_of(path, seen=()):
        """Exported names of a module, following `export * from` (cycles cut)."""
        r = recs.get(path)
        if not r or path in seen:
            return set()
        names = set(r["exports"])
        for s in r["stars"]:
            names |= exports_of(os.path.normpath(os.path.join(os.path.dirname(path), s)), seen + (path,)) - {"default"}
        return names

    edges = {}
    for p in paths:
        r = recs[p]
        if r["error"]:
            probs["parse"].append("%s: %s" % (rel(p), r["error"]))
            continue
        if r["size"] > MAX_BYTES:
            probs["size"].append("%s: %d bytes" % (rel(p), r["size"]))
        edges[p] = set()
        for imp in r["imports"]:
            src = imp["source"]
            if not (src.startswith("./") or src.startswith("../")) or not src.endswith(".js"):
                probs["import"].append("%s: non-relative or non-.js specifier %r" % (rel(p), src))
                continue
            target = os.path.normpath(os.path.join(os.path.dirname(p), src))
            if target not in recs:
                probs["import"].append("%s: %s does not exist under the editor root" % (rel(p), src))
                continue
            edges[p].add(target)
            for s in recs[target]["stars"]:
                edges[p].add(os.path.normpath(os.path.join(os.path.dirname(target), s)))
            if imp["imported"] not in (None, "*") and imp["imported"] not in exports_of(target):
                probs["import"].append("%s: %s has no export %r" % (rel(p), src, imp["imported"]))
        for u in r["unused"]:
            probs["unused"].append("%s: %s" % (rel(p), u))
        for n in r["free"]:
            if n not in ALLOWED_GLOBALS:
                probs["free"].append("%s: %s" % (rel(p), n))
    entry = os.path.join(root, "main.js")
    seen, todo = set(), [entry]
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        todo += sorted(edges.get(p, ()))
    probs["orphan"] = [rel(p) for p in paths if p not in seen]
    return paths, probs


def report_tree(root, label):
    paths, probs = analyse(root)
    check("%s: modules found (%d)" % (label, len(paths)), len(paths) > 0 and os.path.join(root, "main.js") in paths)
    check("%s: every module parses as an ES module" % label, not probs["parse"], probs["parse"])
    check("%s: no module over %d bytes" % (label, MAX_BYTES), not probs["size"], probs["size"])
    check("%s: every import resolves to an existing module and export" % label, not probs["import"], probs["import"])
    check("%s: no unused import" % label, not probs["unused"], probs["unused"])
    check("%s: free identifiers are allowed globals" % label, not probs["free"], probs["free"])
    check("%s: every module reachable from main.js" % label, not probs["orphan"], probs["orphan"])
    return probs


def self_test():
    """Fixture trees: one per rule, each must be caught by exactly that rule (proves the scanner + policy can fail)."""
    good = {
        "main.js": "import { a, A } from './core/a.js';\nimport * as ns from './core/b.js';\n"
                   "export function run(x = a) { const {k = A, ...r} = x; for (const i of r) console.log(i, k, ns.b); "
                   "try { window.go(); } catch ({message}) { return message; } return class Q { #p = 1; m() { return this.#p; } }; }\n",
        "core/a.js": "export * from './c.js';\nexport const a = 1;\n",
        "core/b.js": "export let b = 2; label: for (;;) { break label; }\n",
        "core/c.js": "export const A = () => { var v = 1; { let w = v; return w; } };\n",
    }
    cases = [
        ("clean fixture", {}, None),
        ("missing export", {"core/b.js": "export let bb = 2;\n", "main.js": good["main.js"].replace("* as ns", "{ b as nsb }").replace("ns.b", "nsb")}, "import"),
        # b.js is then imported by nobody, so it is an orphan too
        ("missing module", {"main.js": good["main.js"].replace("./core/b.js", "./core/zz.js")}, ("import", "orphan")),
        ("unused import", {"main.js": good["main.js"].replace("{ a, A }", "{ a, A, x }"), "core/c.js": good["core/c.js"] + "export const x = 0;\n"}, "unused"),
        ("free identifier (typo)", {"core/c.js": good["core/c.js"].replace("return w;", "return ww;")}, "free"),
        ("implicit global write", {"core/b.js": good["core/b.js"] + "function f() { leak = 3; }\nexport { f };\n"}, "free"),
        ("parse error", {"core/c.js": "export const = 1;\n"}, "parse"),
        ("oversize module", {"core/c.js": good["core/c.js"] + "// " + "x" * MAX_BYTES + "\n"}, "size"),
        ("orphan module", {"extra.js": "export const e = 1;\n"}, "orphan"),
    ]
    tmp = tempfile.mkdtemp(prefix="m7-webmod-")
    try:
        for name, patch, rule in cases:
            root = os.path.join(tmp, name.replace(" ", "_").replace("(", "").replace(")", ""))
            files = dict(good, **patch)
            for rel_path, text in files.items():
                os.makedirs(os.path.dirname(os.path.join(root, rel_path)), exist_ok=True)
                with open(os.path.join(root, rel_path), "w") as f:
                    f.write(text)
            _, probs = analyse(root)
            hit = sorted(k for k, v in probs.items() if v)
            # a parse error also hides that module's exports, hence the import problem it causes downstream
            want = sorted(rule) if isinstance(rule, tuple) else ([rule] if rule else [])
            ok = hit == want or (rule == "parse" and hit == ["import", "parse"])
            label = "+".join(want) or "no problem"
            check("self-test %s -> %s" % (name, label), ok, {k: v for k, v in probs.items() if v})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    root = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else EDITOR
    check("gjs available", shutil.which("gjs") is not None)
    report_tree(root, "web/editor" if root == EDITOR else root)
    self_test()
    bad = [n for n, ok in results if not ok]
    print("web_modules tests: %d/%d passed" % (len(results) - len(bad), len(results)))
    print("SUMMARY %d checks, %d failed: %s" % (len(results), len(bad), bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
