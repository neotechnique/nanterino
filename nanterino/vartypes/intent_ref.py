"""Reference type `intent_ref`: an intent name of the graph (incl. the implicit `question`) or null."""
from nanterino.vartypes import VarType


class IntentRef(VarType):
    id = "intent_ref"
    order = 140
    label = "Intention"
    control = "select"
    default = None
    textlike = ref = nullable = True

    def validate(self, v, choices=()):
        return v is None or (isinstance(v, str) and v in choices)

    def choices(self, ctx, declared=()):
        return tuple(ctx.intent_names)

    def editor_choices(self, graph, cfg):
        return ([{"id": i.name, "label": i.description or i.name} for i in graph.intents] if graph is not None else []) \
            + [{"id": "question", "label": "Une question (aucun autre motif reconnu)"}]
