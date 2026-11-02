"""Action `random_choice` (Choisir au hasard) - graph node module (lot N1, 2026-11-02).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Writes through the `variable` set target (clamp, var_changed when listened).
How to test: .venv/bin/python -m tests.test_nodes_n1 (behaviour) + tests.test_nodes_registry (metadata).
"""
from nanterino.nodes.base import Action, Arg


class RandomChoice(Action):
    id = 'random_choice'
    order = 500
    label = 'Choisir au hasard'
    help = "Tire un nombre entier au hasard entre 1 et N et le met dans une variable nombre (par exemple pour choisir une branche)."
    icon = 'question-mark'
    theme = 'variables'
    args = {'name': Arg('numvar', 'Variable (reçoit 1 à N)'), 'count': Arg('number', 'Nombre de choix (N)')}

    def run(self, ctx, name, count):
        from nanterino import properties   # lazy: graph.py imports the node packages
        n = count if isinstance(count, (int, float)) and not isinstance(count, bool) else 1
        n = max(1, min(int(n), 10 ** 6))
        properties.write("variable", ctx, ctx.brain.rng.randint(1, n), name=name)
