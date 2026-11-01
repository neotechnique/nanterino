"""Graph conditions (guards, `when:`), one module per condition (lot M2, 2026-11-01).

Each file `<id>.py` defines exactly one nanterino.nodes.base.Condition subclass whose `id` is the file name; the
registry (nanterino/nodes/__init__.py, `CONDITIONS`) discovers them with pkgutil. The folder is flat: the menu theme
is the `theme` attribute of each file, never the folder. Files starting with `_` are skipped. This file holds no node.
How to test: .venv/bin/python -m tests.test_nodes_registry
"""
