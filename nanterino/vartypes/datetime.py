"""Variable type `datetime`: local ISO text (YYYY-MM-DDTHH:MM[:SS]) or null; ordered on parsed dates."""
from nanterino.vartypes import VarType, generic_compare


class DateTime(VarType):
    id = "datetime"
    order = 80
    label = "Date et heure"
    control = "datetime"
    default = None
    ordered = textlike = nullable = True

    def validate(self, v, choices=()):
        from nanterino.graph import parse_iso
        return v is None or parse_iso(v) is not None

    def compare(self, a, op, b):
        """Compare parsed dates; an unparsable side makes the order operators false (= / != stay literal)."""
        from nanterino.graph import ORDER_OPS, parse_iso
        da, db = parse_iso(a), parse_iso(b)
        if da is not None and db is not None:
            a, b = da, db
        elif op in ORDER_OPS:
            return False
        return generic_compare(a, op, b)
