"""Variable type `expression`: a face expression id of graph.EXPRESSIONS."""
from nanterino.vartypes import VarType


class Expression(VarType):
    id = "expression"
    order = 100
    label = "Expression du visage"
    control = "select"
    default = "neutre"
    textlike = True

    def validate(self, v, choices=()):
        from nanterino.graph import EXPRESSIONS
        return isinstance(v, str) and v in EXPRESSIONS

    def editor_choices(self, graph, cfg):
        from nanterino.graph import EXPRESSIONS
        return [{"id": i, "label": lab} for i, lab in EXPRESSIONS.items()]
