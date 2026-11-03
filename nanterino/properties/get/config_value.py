"""Value source `config_value` (Réglage du robot) - property module (lot M4, 2026-11-01).

Reads one of properties.CFG_PUBLIC (delays, switches, spoken phrases; never URLs, prompts or devices). Output type
from the value at parse time: true/false -> bool, number -> number, text -> string. Run time reads the live config;
a value that is no longer a scalar gives "".
How to test: .venv/bin/python -m tests.test_properties
"""
from nanterino.nodes.base import Arg
from nanterino.properties import GetSource, PropertyError, cfg_type, default_of


class ConfigValue(GetSource):
    id = "config_value"
    order = 100
    label = "Réglage du robot"
    help = "La valeur d'un réglage (délais, interrupteurs, phrases du robot)."
    icon = "lock"
    out = ("of", "key")
    args = {"key": Arg("cfgkey", "Réglage")}

    def check(self, parser, field_type, key):
        t = cfg_type(parser.cfg.get(key))
        if t is None:
            raise PropertyError("config key %r is not a number, a text or true/false" % (key,))
        return t

    def get(self, ctx, key):
        v = ctx.brain.cfg.get(key)
        return v if cfg_type(v) is not None else default_of("string")   # a non-scalar live value: "" (never raises)
