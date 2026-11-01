"""Variable type `string` (a text of at most graph.TEXT_MAX characters); $utterance fits it."""
from nanterino.vartypes import VarType, short_text


class String(VarType):
    id = "string"
    order = 30
    label = "Texte"
    control = "text"
    default = ""
    text = True
    item_label = "Textes"
    item_order = 1        # first item type: the default `type:` of a list

    def validate(self, v, choices=()):
        return short_text(v)
