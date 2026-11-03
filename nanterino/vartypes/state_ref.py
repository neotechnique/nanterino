"""Reference type `state_ref`: a state name of the graph or null."""
from nanterino.vartypes import VarType


class StateRef(VarType):
    id = "state_ref"
    order = 160
    label = "État"
    control = "select"
    default = None
    textlike = ref = nullable = True

    def validate(self, v, choices=()):
        return v is None or (isinstance(v, str) and v in choices)

    def choices(self, ctx, declared=()):
        return tuple(ctx.state_names)

    def editor_choices(self, graph, cfg):
        from nanterino.graph import STATE_DOC
        return [{"id": n, "label": STATE_DOC.get(n, n.capitalize())} for n in graph.states] if graph is not None else []
