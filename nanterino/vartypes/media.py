"""Variable type `media`: a bare file name of media/ (or null); choices = graph.media_files(cfg)."""
from nanterino.vartypes import VarType


class Media(VarType):
    id = "media"
    order = 130
    label = "Média"
    control = "select"
    default = None
    textlike = nullable = True

    def validate(self, v, choices=()):
        from nanterino.graph import MEDIA_NAME
        return v is None or (isinstance(v, str) and bool(MEDIA_NAME.match(v)))

    def editor_choices(self, graph, cfg):
        from nanterino.graph import media_files
        return [{"id": f, "label": f} for f in media_files(cfg)]
