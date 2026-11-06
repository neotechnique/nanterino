"""Action `emergency_stop` (Déclencher l'arrêt d'urgence) - graph node module (lot B1, 2026-11-04).

Boundary: metadata read by graph.py (validation, GET /api/graph/vocab); run() is bound to the Brain by
brain._build_engine and called on the brain loop thread with a NodeContext (brain, kw, cfg, graph).
Effect: brain.motion.emergency_stop() -> Body.stop_all(reason="graphe", source="graph") (latched).
Theme mouvement: every effect goes through brain.motion / brain.body (nanterino/body: limits, latched emergency stop).
How to test: .venv/bin/python -m tests.test_nodes_motion (behaviour on the sim body) + tests.test_nodes_registry.
"""
from nanterino.nodes.base import Action


class EmergencyStop(Action):
    id = 'emergency_stop'
    order = 800
    label = "Déclencher l'arrêt d'urgence"
    help = "Arrête tous les moteurs tout de suite et VERROUILLE : toute commande est refusée jusqu'au bouton « Réarmer » du tableau de bord (écran Mécanique). Le graphe ne peut pas réarmer."
    icon = 'lock'
    theme = 'mouvement'

    def run(self, ctx):
        ctx.brain.motion.emergency_stop()
