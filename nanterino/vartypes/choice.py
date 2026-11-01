"""Variable type `choice`: one of the variable's own `choices:` (not a list item type)."""
from nanterino.vartypes import VarType


class Choice(VarType):
    id = "choice"
    order = 40
    label = "Choix"
    control = "select"
    default = None        # the editor picks the first choice
    text = True
    item_ok = False       # a list has no per-list choices

    def validate(self, v, choices=()):
        return isinstance(v, str) and v in choices

    def parse_choices(self, parser, where, spec):
        from nanterino.graph import CHOICE_MAX
        ch = spec.get("choices")
        if not (isinstance(ch, list) and 0 < len(ch) <= CHOICE_MAX and all(isinstance(c, str) and c.strip() and len(c) <= 60 for c in ch)
                and len(set(ch)) == len(ch)):
            parser.err(where, "a choice variable needs `choices:` (1..%d distinct texts)" % CHOICE_MAX)
            return None
        return tuple(ch)
