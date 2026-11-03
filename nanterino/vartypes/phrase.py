"""Variable type `phrase`: spoken text (pre-synthesised like say_text), a text type."""
from nanterino.vartypes import VarType, short_text


class Phrase(VarType):
    id = "phrase"
    order = 120
    label = "Phrase dite"
    control = "textarea"
    default = ""
    text = True

    def validate(self, v, choices=()):
        return short_text(v)
