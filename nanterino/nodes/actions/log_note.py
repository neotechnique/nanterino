"""Action `log_note` (Écrire dans le journal) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Producer of journal_entry: Brain.note_journal (the robot journal, also fed by the live log).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
import logging

from nanterino.log import log
from nanterino.nodes.base import Action, Arg

_LEVELNO = {"info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}


class LogNote(Action):
    id = 'log_note'
    order = 480
    label = 'Écrire dans le journal'
    help = "Écrit un message dans le journal du robot (nanterino.log ; avertissements et erreurs aussi dans errors.log), puis « Une entrée arrive au journal »."
    icon = 'flag'
    theme = 'systeme'
    args = {'level': Arg('loglevel', 'Niveau'), 'text': Arg('text', 'Message')}

    def run(self, ctx, level, text):
        # graph_note: the journal tap (nanterino/journal.py) skips this record, note_journal adds the entry itself
        log.log(_LEVELNO.get(level, logging.INFO), "graph note: %s", text, extra={"graph_note": True})
        ctx.brain.note_journal(level, "graph")
