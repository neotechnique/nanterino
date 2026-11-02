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
    help = "Écrit dans le journal l'état, les tours, les visages, le micro, muet, sourd, le volume, les visiteurs du jour et de la veille et les erreurs et avertissements des dernières 24 h (jamais ce que dit le visiteur), puis « Une entrée arrive au journal »."
    icon = 'flag'
    theme = 'systeme'
    args = {}

    def run(self, ctx):
        b = ctx.brain
        # Never user texts (privacy rule of the robot's log): counters and flags only.
        # Lot G3 (daily / hourly summary of the shipped graph): visitors of today (the read rolls the counter over at
        # midnight and keeps the finished day in _visitors_prev) and errors / warnings among the kept journal entries
        # (JOURNAL_KEEP newest, so a count is a lower bound after a burst; clear_errors removes errors).
        today = b._visitors_today()
        prev = b._visitors_prev
        wall = b.wall()
        recent = [lv for t, lv, _src in list(b.journal_notes) if wall - t <= 86400]
        log.info("graph state: etat=%s tours=%d visages=%d micro=%s muet=%s sourd=%s volume=%s visiteurs_jour=%d "
                 "visiteurs_veille=%s erreurs_24h=%d avertissements_24h=%d",
                 b.state, b.turns, b.faces, bool(b.mic.active), bool(b.out.muted), bool(b.deaf), b.var_value("volume"),
                 today, "%d (%s)" % (prev["count"], prev["date"]) if prev else "?",
                 recent.count("error"), recent.count("warning"), extra={"graph_note": True})
        b.note_journal("info", "graph")
