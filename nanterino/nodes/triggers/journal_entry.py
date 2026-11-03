"""Trigger `journal_entry` (Une entrée arrive au journal) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); the event is POSTED by brain.py (see
the producer named below); transitions with `on: journal_entry` react to it.
Producer: Brain.note_journal (log_note + the live log's WARNING/ERROR records, nanterino/journal.py).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import ANY, Arg, Trigger


class JournalEntry(Trigger):
    id = 'journal_entry'
    order = 380
    label = 'Une entrée arrive au journal'
    help = "Une entrée arrive au journal du robot : « Écrire dans le journal », ou un avertissement / une erreur du robot lui-même (niveau précis facultatif). Une rafale d'erreurs ne compte qu'une fois par 0,2 s ; anti-boucle comme « Une variable change »."
    icon = 'flag'
    theme = 'systeme'
    args = {'value': Arg('loglevel', 'Niveau (facultatif)')}   # the transition's `value:` (no `var:`)

    def editor_args(self, g):
        return [{"name": "value", "type": "enum", "options": list(g.LOG_LEVELS), "labels": dict(g.LOG_LEVELS),
                 "optional": True, "label": "Niveau (facultatif)",
                 "help": "Seulement les entrées de ce niveau ; vide = toutes."}]

    def subscribe(self, graph):
        """Levels listened to ("*" = any): the brain posts journal_entry only when this is not empty."""
        from nanterino.graph import NOVALUE
        trs = list(graph.globals) + [t for s in graph.states.values() for t in s.transitions]
        return frozenset("*" if t.value is NOVALUE else t.value for t in trs if t.enabled and t.on == self.id)

    def match(self, ctx, event, value=ANY):
        return value is ANY or value == ctx.kw.get("value")

    def check(self, parser, where, name, value):
        from nanterino.graph import LOG_LEVELS, NOVALUE
        if name is not None:
            parser.err(where, "`on: journal_entry` takes no `var:`")
        if value is not NOVALUE and value not in LOG_LEVELS:
            parser.err(where, "`on: journal_entry` `value:` must be one of %s, got %r" % (", ".join(LOG_LEVELS), value))
