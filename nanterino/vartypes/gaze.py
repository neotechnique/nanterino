"""Variable type `gaze`: a gaze mode id of graph.GAZE_MODES."""
from nanterino.vartypes import VarType


class Gaze(VarType):
    id = "gaze"
    order = 110
    label = "Regard"
    control = "select"
    default = "suivre"
    textlike = True

    def validate(self, v, choices=()):
        from nanterino.graph import GAZE_MODES
        return isinstance(v, str) and v in GAZE_MODES

    def editor_choices(self, graph, cfg):
        from nanterino.graph import GAZE_MODES
        return [{"id": i, "label": lab} for i, lab in GAZE_MODES.items()]
