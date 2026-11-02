"""Robot journal tap (lot N1, 2026-11-02): WARNING / ERROR records of the live robot's log feed the Brain's journal.

Purpose
    The N1 nodes `journal_entry` (trigger), `recent_error` (condition) and `log_note` (action) read and write ONE robot
    journal: Brain.journal_notes. log_note adds its own entries directly; this module adds the warnings and errors the
    robot itself logs (logger `robot.nanterino` of nanterino.log), by attaching one logging.Handler that forwards each
    record's level (never its text: the log already follows the privacy rule) to every attached Brain.
Boundary
    Only the live (threaded) Brain attaches itself (Brain.__init__); simulator and test brains stay detached so a
    simulation never sees the live robot's errors (tests call attach() explicitly). Brains are held weakly.
Invariants
    - one handler per process, installed at the first attach(), level WARNING;
    - records logged by log_note itself carry `graph_note=True` (logging `extra`) and are skipped (no double entry);
    - the handler never raises (a failing brain is ignored) and never logs (no recursion).
How to test
    .venv/bin/python -m tests.test_nodes_n1   (journal tests attach a non-threaded Brain, log a warning, read it back)
"""
import logging
import weakref

from .log import log

_BRAINS = weakref.WeakSet()
_TAP = None


class _Tap(logging.Handler):
    def emit(self, record):
        if getattr(record, "graph_note", False):
            return
        level = "error" if record.levelno >= logging.ERROR else "warning"
        for b in list(_BRAINS):
            try:
                b.note_journal(level, "robot", external=True)
            except Exception:   # noqa: BLE001 - a logging handler must never raise nor log
                pass


def attach(brain) -> None:
    """Forward the robot log's WARNING / ERROR records to `brain.note_journal` (installs the handler once)."""
    global _TAP
    if _TAP is None:
        _TAP = _Tap(level=logging.WARNING)
        log.addHandler(_TAP)
    _BRAINS.add(brain)


def detach(brain) -> None:
    _BRAINS.discard(brain)
