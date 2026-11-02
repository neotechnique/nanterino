"""Action `log_state` (Noter l'état du robot dans le journal) - graph node module (lot N3, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_n3 (behaviour) + tests.test_nodes_registry (metadata, parity).
"""
from nanterino.log import log
from nanterino.nodes.base import Action


class LogState(Action):
    id = 'log_state'
    order = 640
    label = "Noter l'état du robot dans le journal"
    help = "Écrit dans le journal l'état, les tours, les visages, le micro, muet, sourd et le volume (jamais ce que dit le visiteur), puis « Une entrée arrive au journal »."
    icon = 'flag'
    theme = 'systeme'
    args = {}

    def run(self, ctx):
        b = ctx.brain
        # Never user texts (privacy rule of the robot's log): counters and flags only.
        log.info("graph state: etat=%s tours=%d visages=%d micro=%s muet=%s sourd=%s volume=%s",
                 b.state, b.turns, b.faces, bool(b.mic.active), bool(b.out.muted), bool(b.deaf), b.var_value("volume"),
                 extra={"graph_note": True})
        b.note_journal("info", "graph")
