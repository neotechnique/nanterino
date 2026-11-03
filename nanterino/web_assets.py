"""Editor ES module tree (lot M6): safe resolution of GET /web/editor/<path> and the file list of the tree.

Purpose : the visual editor is split into native ES modules under web/editor/ (no bundler); the server exposes ONLY
          that tree, read-only, through `editor_module()`; `editor_module_files()` feeds the L14 snapshot cache key.
Boundary: pure path logic (os only, no FastAPI import) so tests never import nanterino.server.
Invariants:
  - a request path must be lowercase `[a-z0-9_-]` segments (at most 5) ending in .js or .css: no `..`, no dot
    segment, no backslash, no absolute path, no other extension; the resolved real path must stay under web/editor/
    (a symlink pointing outside is refused) and be a regular file.
  - media types: .js = text/javascript (required for <script type="module">), .css = text/css.
  - ModuleCache keeps the bytes of a module keyed by (size, mtime_ns): a redeployed file is re-read at once; the ETag
    is derived from the same key, so a browser revalidation (no-cache) gets a 304 while the file is unchanged.
  - modulepreload_links() lists the whole tree for the /editor page so the browser fetches every module in one wave
    instead of discovering the import graph level by level (load time of the split editor, lot M6).
Test    : tests/test_web_assets.py (traversal, encoded traversal after URL decoding, extension, symlink, listing,
          cache invalidation, preload links).
"""
import os
import re

_MODULE_PATH = re.compile(r"[a-z0-9_-]{1,60}(?:/[a-z0-9_-]{1,60}){0,4}\.(?:js|css)")
MEDIA_TYPES = {".js": "text/javascript", ".css": "text/css"}


def editor_root(web_dir: str) -> str:
    return os.path.join(web_dir, "editor")


def editor_module(web_dir: str, rel) -> tuple[str, str] | None:
    """(absolute path, media type) of web/editor/<rel>, or None when `rel` is not an allowed module path."""
    if not isinstance(rel, str) or not _MODULE_PATH.fullmatch(rel):
        return None
    root = os.path.realpath(editor_root(web_dir))
    path = os.path.realpath(os.path.join(root, rel))
    if os.path.commonpath([root, path]) != root or not os.path.isfile(path):
        return None
    return path, MEDIA_TYPES[os.path.splitext(path)[1]]


def editor_module_files(web_dir: str) -> list[str]:
    """Every .js / .css file of the module tree, sorted (stable signature input)."""
    out = []
    for base, dirs, files in os.walk(editor_root(web_dir)):
        dirs.sort()
        out.extend(os.path.join(base, f) for f in sorted(files) if os.path.splitext(f)[1] in MEDIA_TYPES)
    return sorted(out)


class ModuleCache:
    """Bytes + ETag of served modules, re-read when (size, mtime_ns) changes. Not thread-safe by design: used from
    the server's event loop only (async route)."""

    def __init__(self):
        self._items = {}

    def get(self, path: str) -> tuple[bytes, str]:
        st = os.stat(path)
        key = (st.st_size, st.st_mtime_ns)
        hit = self._items.get(path)
        if hit is None or hit[0] != key:
            with open(path, "rb") as f:
                body = f.read()
            hit = (key, body, '"%x-%x"' % key)
            self._items[path] = hit
        return hit[1], hit[2]


def modulepreload_links(web_dir: str, url_prefix: str = "/web/editor/") -> str:
    """<link rel="modulepreload"> tags for every .js of the tree (sorted), one per line."""
    root = editor_root(web_dir)
    out = []
    for f in editor_module_files(web_dir):
        rel = os.path.relpath(f, root).replace(os.sep, "/")
        if f.endswith(".js") and editor_module(web_dir, rel) is not None:   # only what the route would serve
            out.append('<link rel="modulepreload" href="%s%s">' % (url_prefix, rel))
    return "\n".join(out)
