"""Action `motion_stop` (Arrêter les mouvements) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Effect: brain.motion.stop() -> Body.stop(source="graph").
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Action


class MotionStop(Action):
    id = 'motion_stop'
    order = 790
    label = 'Arrêter les mouvements'
    help = "Arrêt simple : chaque articulation s'arrête là où elle est, les gestes et les déplacements en cours sont interrompus. Pas de verrouillage : une commande suivante repart tout de suite."
    icon = 'hand-stop'
    theme = 'mouvement'

    def run(self, ctx):
        ctx.brain.motion.stop()
