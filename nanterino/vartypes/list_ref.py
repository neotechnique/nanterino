"""Reference type `list_ref`: a list name of the graph or null."""
from nanterino.vartypes import VarType


class ListRef(VarType):
    id = "list_ref"
    order = 150
    label = "Liste"
    control = "select"
    default = None
    textlike = ref = nullable = True

    def validate(self, v, choices=()):
        return v is None or (isinstance(v, str) and v in choices)

    def choices(self, ctx, declared=()):
        return tuple(ctx.list_names)

    def editor_choices(self, graph, cfg):
        return [{"id": n, "label": li.description or n} for n, li in graph.lists.items()] if graph is not None else []
