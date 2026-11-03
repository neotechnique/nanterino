"""Graph triggers (events, `on:`), one module per trigger (lot M2, 2026-11-01).

Each file `<id>.py` defines exactly one nanterino.nodes.base.Trigger subclass whose `id` is the file name; the
registry (nanterino/nodes/__init__.py, `TRIGGERS`) discovers them with pkgutil. The folder is flat: the menu theme is
the `theme` attribute of each file, never the folder. Files starting with `_` are skipped. This file holds no node.
Data-derived triggers (one per intent `intent.<name>`, the `after:` delay, one per state entry) are NOT modules:
graph.vocabulary() builds them from the active graph (see nanterino/nodes/__init__.py).
How to test: .venv/bin/python -m tests.test_nodes_registry
"""
