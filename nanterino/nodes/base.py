"""Node base classes and argument descriptors (lot M1, 2026-11-01).

Purpose
    One class per node, one file per node, modelled on Game Creator 2 (Instructions / Conditions / Events). A node
    class carries its editor metadata (id, label, help, icon, theme, args) AND its runtime code, so adding a node
    means dropping one file into its family folder (see nanterino/nodes/__init__.py).

Boundary
    Pure Python: nothing here (nor in a node module, at import time) imports nanterino.graph or nanterino.brain,
    because graph.py imports this package while it is itself being imported. Node runtime code reaches the robot
    only through the NodeContext it is given; a node that needs a graph.py helper imports it lazily inside run().

Invariants
    - `args` maps argument name -> Arg(kind, label), the exact shape of the former graph.ACTION_DOC tuples; the
      kinds are the graph.py argument kinds (graph.ARG_KINDS, checked at import of graph.py).
    - Action.run(self, ctx, **args) accepts exactly the declared argument names (checked at discovery).
    - Families: actions (M1, migrated). Condition / Trigger are sketched for lot M2 (guards / events), not used yet.

How to test
    .venv/bin/python -m tests.test_nodes_registry
"""
from dataclasses import dataclass
from typing import Any, NamedTuple


class Arg(NamedTuple):
    """Argument descriptor (kind, French label). A tuple, so `kind, label = arg` and `arg[0]` keep working."""
    kind: str
    label: str


@dataclass(frozen=True)
class NodeContext:
    """What a node's runtime code may touch.

    brain : the Brain (live robot or simulator); attributes are looked up at call time, so tests that wrap a
            Brain method (e.g. `_speak_then`, `_go`) still see the wrapped one.
    kw    : the event payload of the running chain (`text`, `t_end`, `source` ...).
    cfg   : the brain's config dict captured when the engine was built.
    graph : the Graph the engine was built from (variables / lists declarations).
    """
    brain: Any
    kw: dict
    cfg: dict
    graph: Any


class Node:
    """Common metadata of every node. Subclasses set the class attributes; the registry keeps one instance."""
    family = ""        # set by each family base class: the sub-package name under nanterino/nodes/
    id = ""            # unique within the family; must equal the module (file) name
    order = None       # optional palette position (small first); None = after the numbered nodes, by id
    label = ""         # French label shown by the editor
    help = ""          # French help text (tooltip)
    icon = ""          # Tabler icon name (the editor vendors graph.all_icons())
    theme = ""         # one of graph.THEME_DOC (node menu theme), declared in the file, not by folder
    args: dict = {}    # argument name -> Arg(kind, label), in display order

    def __repr__(self):
        return "<%s node %s>" % (self.family or "?", self.id)


class Action(Node):
    """A graph action (`do:` / `then:` / `on_enter:` step)."""
    family = "actions"

    def run(self, ctx: NodeContext, **args):
        """Perform the action. Return value is ignored. Must not block the brain loop thread."""
        raise NotImplementedError


class Condition(Node):
    """Lot M2 sketch: a guard (`when:`). test() returns a bool; no module of this family exists yet."""
    family = "conditions"
    as_vars = None     # optional French reading as variables (graph.GUARD_AS_VARS)

    def test(self, ctx: NodeContext, **args) -> bool:
        raise NotImplementedError


class Trigger(Node):
    """Lot M2 sketch: an event a transition reacts to (`on:`); no module of this family exists yet.

    `internal` events (utterance, tick) are engine-only. match() lets an argument-carrying trigger (var_changed,
    timer_reached) decide whether an arriving event fits a transition; subscribe() names what it watches.
    """
    family = "triggers"
    internal = False

    def subscribe(self, graph) -> set:
        """Names (variables, timers ...) this trigger watches in `graph`; empty for plain events."""
        return set()

    def match(self, ctx: NodeContext, event: str, **args) -> bool:
        return event == self.id
