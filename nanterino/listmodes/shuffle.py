"""List mode `shuffle`: say_random draws from a shuffle bag (no repeat until every item was said once)."""
from nanterino.listmodes import ListMode


class Shuffle(ListMode):
    id = "shuffle"
    order = 20
    label = "Sac mélangé"
    help = "« Dire une phrase au hasard » ne répète rien tant que toutes les phrases n'ont pas été dites."

    def pick(self, brain, name, items):
        """Shuffle-bag draw: the bag (brain._bags[name]) refills, reshuffled with brain.rng, when it is empty or when
        the list content changed. Former Brain._bag_pick body (same rng calls: traces unchanged)."""
        sig, bag = brain._bags.get(name, (None, []))
        if sig != tuple(items) or not bag:
            bag = list(items)
            brain.rng.shuffle(bag)
        pick = bag.pop()
        brain._bags[name] = (tuple(items), bag)
        return pick
