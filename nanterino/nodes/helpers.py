"""Runtime helpers shared by several node modules (lot M1, 2026-11-01).

Purpose
    Small pieces of brain-side logic used by more than one node file (and, until lot M2 migrates the guards, by the
    guard closures of brain._build_engine), kept in one place instead of being copied into each node.
Boundary
    Operates on a Brain through its public-ish attributes (`lists`, `_resolve`); no import of graph.py / brain.py.
Invariants
    Behaviour is byte-for-byte the former brain._build_engine closures `list_push` and `match_key`.
How to test
    .venv/bin/python -m tests.test_graph_vars2 (lists, history / max, dictionaries) and tests.test_nodes_registry.
"""


def list_push(ctx, name: str, value) -> None:
    """Append to a user list; history / max lists drop their oldest items first."""
    items = ctx.brain.lists.setdefault(name, [])
    items.append(value)
    cap = ctx.graph.lists[name].maxlen
    if cap and len(items) > cap:
        del items[:len(items) - cap]


def match_key(brain, kw: dict, name: str, key):
    """Key of a dictionary call: a literal / `$<var>`, or for `$utterance` the first key found in the sentence."""
    d = brain.lists.get(name) or {}
    if key == "$utterance":
        text = str(brain._resolve(key, kw) or "").lower()
        return next((k for k in d if k.strip() and k.lower() in text), None)
    k = brain._resolve(key, kw)
    return k if isinstance(k, str) and k in d else None
