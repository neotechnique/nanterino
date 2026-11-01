"""Action `start_answer` (Répondre à la question) - graph node module (lot M1, 2026-11-01).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
How to test: .venv/bin/python -m tests.test_nodes_registry (+ tests.test_brain_graph for behaviour).
"""
import threading
from nanterino.nodes.base import Action


class StartAnswer(Action):
    id = 'start_answer'
    order = 140
    label = 'Répondre à la question'
    help = 'Lance la recherche et la réponse à la phrase du visiteur.'
    icon = 'message'
    theme = 'conversation'
    args = {}

    def run(self, ctx):
        b = ctx.brain
        if not b._threaded:   # simulator: a fixed fake answer, finished after SIM_ANSWER_S virtual seconds
            from nanterino import brain as brain_mod   # lazy: brain.py imports graph.py, which imports this package
            b.subtitle = "(réponse simulée)"
            b.llm.simulate_answer()   # the simulator's fake LLM records that an answer started
            b._schedule_at(b.now() + brain_mod.SIM_ANSWER_S, "answer_done")
            return
        threading.Thread(target=b._answer, args=(ctx.kw["text"], ctx.kw["t_end"], b.gen), daemon=True).start()
