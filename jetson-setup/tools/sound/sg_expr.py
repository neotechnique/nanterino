"""Expression language for soundgen (modes `expr` and `bytebeat`).

Contract: docs/format.md ("Expression language"). The JS twin (web/engine.js) must
produce the same values, so this module deliberately emulates JavaScript double
semantics instead of Python's:

* Python raises where JS returns Infinity/NaN (division by zero, math domain
  errors, pow overflow, math.sin(inf), ...). Every helper below converts those
  exceptions back into the JS result. Evaluating a sample must never raise.
* Bitwise operators and shifts use JS int32 semantics (`to_int32`).
* `%` is C fmod (sign of the dividend), `**` follows Math.pow special cases.
* `mulberry32` is the PRNG shared with the patch engine (`rand()` / noise).

Pipeline: text -> tokens -> AST (`parse_expr`) -> Python source -> `eval` once with a
restricted namespace -> callable `fn(t, i, sr) -> float` (`compile_expr`).
Only whitelisted helper names and numeric literals can appear in the generated
source, and `__builtins__` is empty, so user text can never reach attributes,
imports or builtins.
"""

import math
import re

_INF = math.inf
_NAN = math.nan
_M32 = 0xFFFFFFFF


class ExprError(ValueError):
    """Syntax / name / arity error. `pos` is the 0-based character position."""

    def __init__(self, message, pos):
        # Message shows a 1-based position (same as web/engine.js); `pos` stays 0-based.
        super().__init__("%s (position %d)" % (message, pos + 1))
        self.pos = pos
        self.detail = message


# --------------------------------------------------------------------------
# JS int32 and PRNG emulation
# --------------------------------------------------------------------------

def to_int32(x):
    """JS ToInt32: NaN/inf -> 0, truncate toward zero, wrap modulo 2^32, signed."""
    # Fast path: every double in this open interval truncates into int32 range.
    if -2147483649.0 < x < 2147483648.0:
        return int(x)
    try:
        n = int(x)  # ValueError for NaN, OverflowError for +-inf
    except (ValueError, OverflowError):
        return 0
    n &= _M32
    return n - 0x100000000 if n & 0x80000000 else n


def mulberry32(seed):
    """Return a closure producing floats in [0,1), bit-exact with the JS version.

    JS: a|=0; a=a+0x6D2B79F5|0; t=Math.imul(a^a>>>15,1|a);
        t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296
    We keep the state as an unsigned 32-bit int; Math.imul equals the low 32 bits of
    the product, and `t + imul(...)` followed by `^` is a mod-2^32 sum xor t.
    """
    state = [to_int32(seed) & _M32]

    def rand():
        a = (state[0] + 0x6D2B79F5) & _M32
        state[0] = a
        t = ((a ^ (a >> 15)) * (a | 1)) & _M32
        t = ((t + (((t ^ (t >> 7)) * (t | 61)) & _M32)) & _M32) ^ t
        return (t ^ (t >> 14)) / 4294967296.0

    return rand


# --------------------------------------------------------------------------
# JS-flavoured arithmetic helpers (never raise)
# --------------------------------------------------------------------------

def _div(a, b):
    try:
        return a / b
    except ZeroDivisionError:  # Python raises for b == 0 (also NaN / 0)
        if a != a or a == 0:
            return _NAN
        return -_INF if (a < 0) != (math.copysign(1.0, b) < 0) else _INF


def _mod(a, b):
    try:
        return math.fmod(a, b)
    except ValueError:  # fmod(x, 0) and fmod(inf, y) are NaN in JS too
        return _NAN


def _is_odd_int(y):
    # Beyond 2^53 every double is even, so only smaller finite values can be odd.
    return abs(y) < 9007199254740992.0 and y == math.floor(y) and int(y) % 2 == 1


def _pow(a, b):
    """Math.pow semantics (differs from Python's for NaN exponents and +-1 ** inf)."""
    if b != b:
        return _NAN
    if b == 0:
        return 1.0
    if (a == 1.0 or a == -1.0) and (b == _INF or b == -_INF):
        return _NAN
    try:
        return math.pow(a, b)
    except OverflowError:
        return -_INF if (a < 0 and _is_odd_int(b)) else _INF
    except ValueError:
        if a == 0:  # 0 ** negative -> +-Infinity
            return -_INF if (math.copysign(1.0, a) < 0 and _is_odd_int(b)) else _INF
        return _NAN  # negative base, non-integer exponent


def _or(a, b):
    return float(to_int32(a) | to_int32(b))


def _xor(a, b):
    return float(to_int32(a) ^ to_int32(b))


def _and(a, b):
    return float(to_int32(a) & to_int32(b))


def _shl(a, b):
    n = (to_int32(a) << (to_int32(b) & 31)) & _M32
    return float(n - 0x100000000 if n & 0x80000000 else n)


def _shr(a, b):
    return float(to_int32(a) >> (to_int32(b) & 31))


def _ushr(a, b):
    return float((to_int32(a) & _M32) >> (to_int32(b) & 31))


def _bnot(a):
    return float(~to_int32(a))


# --------------------------------------------------------------------------
# Function library (names from format.md)
# --------------------------------------------------------------------------

def _sin(x):
    try:
        return math.sin(x)
    except ValueError:
        return _NAN


def _cos(x):
    try:
        return math.cos(x)
    except ValueError:
        return _NAN


def _tan(x):
    try:
        return math.tan(x)
    except ValueError:
        return _NAN


def _asin(x):
    try:
        return math.asin(x)
    except ValueError:
        return _NAN


def _acos(x):
    try:
        return math.acos(x)
    except ValueError:
        return _NAN


def _sinh(x):
    try:
        return math.sinh(x)
    except OverflowError:
        return _INF if x > 0 else -_INF


def _cosh(x):
    try:
        return math.cosh(x)
    except OverflowError:
        return _INF


def _finite(x):
    return x - x == 0.0  # False for NaN and +-inf


def _floor(x):
    return float(math.floor(x)) if _finite(x) else x


def _ceil(x):
    return float(math.ceil(x)) if _finite(x) else x


def _round(x):
    return _floor(x + 0.5)  # spec: never banker's rounding


def _trunc(x):
    return float(math.trunc(x)) if _finite(x) else x


def _sqrt(x):
    try:
        return math.sqrt(x)
    except ValueError:
        return _NAN


_HAS_CBRT = hasattr(math, "cbrt")  # math.cbrt exists from Python 3.11


def _cbrt(x):
    if not _finite(x):
        return x
    if _HAS_CBRT:
        return math.cbrt(x)
    return math.copysign(abs(x) ** (1.0 / 3.0), x)


def _exp(x):
    try:
        return math.exp(x)
    except OverflowError:
        return _INF


def _make_log(fn):
    def log_like(x):
        try:
            return fn(x)
        except ValueError:  # x == 0 -> -Infinity, x < 0 -> NaN
            return -_INF if x == 0 else _NAN
    return log_like


_log = _make_log(math.log)
_log2 = _make_log(math.log2)
_log10 = _make_log(math.log10)


def _min(*args):
    r = args[0]
    for v in args:
        if v != v:
            return _NAN  # Math.min propagates NaN regardless of position
        if v < r:
            r = v
    return r


def _max(*args):
    r = args[0]
    for v in args:
        if v != v:
            return _NAN
        if v > r:
            r = v
    return r


def _sign(x):
    if x != x:
        return _NAN
    return 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)


def _frac(x):
    return x - _floor(x)  # inf -> NaN like JS (inf - inf)


def _clamp(x, lo, hi):
    return _min(_max(x, lo), hi)  # lo > hi therefore yields hi


def _mix(a, b, k):
    return a + (b - a) * k


def _step(edge, x):
    return 1.0 if x >= edge else 0.0


def _sq(x):
    return 1.0 if _frac(x) < 0.5 else -1.0


def _saw(x):
    return 2.0 * _frac(x) - 1.0


def _tri(x):
    return 1.0 - 4.0 * abs(_frac(x) - 0.5)


def _osc(x):
    return _sin(2.0 * math.pi * x)


def _mtof(m):
    return 440.0 * _pow(2.0, (m - 69.0) / 12.0)


# name -> (python helper, min args, max args or None for variadic)
FUNCTIONS = {
    "sin": (_sin, 1, 1), "cos": (_cos, 1, 1), "tan": (_tan, 1, 1),
    "asin": (_asin, 1, 1), "acos": (_acos, 1, 1), "atan": (math.atan, 1, 1),
    "atan2": (math.atan2, 2, 2),
    "sinh": (_sinh, 1, 1), "cosh": (_cosh, 1, 1), "tanh": (math.tanh, 1, 1),
    "abs": (math.fabs, 1, 1), "floor": (_floor, 1, 1), "ceil": (_ceil, 1, 1),
    "round": (_round, 1, 1), "trunc": (_trunc, 1, 1),
    "sqrt": (_sqrt, 1, 1), "cbrt": (_cbrt, 1, 1),
    "exp": (_exp, 1, 1), "log": (_log, 1, 1), "log2": (_log2, 1, 1),
    "log10": (_log10, 1, 1),
    "pow": (_pow, 2, 2), "min": (_min, 1, None), "max": (_max, 1, None),
    "sign": (_sign, 1, 1), "frac": (_frac, 1, 1), "clamp": (_clamp, 3, 3),
    "mix": (_mix, 3, 3), "step": (_step, 2, 2),
    "sq": (_sq, 1, 1), "saw": (_saw, 1, 1), "tri": (_tri, 1, 1), "osc": (_osc, 1, 1),
    "mtof": (_mtof, 1, 1),
    "rand": (None, 0, 0), "noise": (None, 0, 0),  # bound per compile (PRNG state)
}
CONSTANTS = {"pi": math.pi, "tau": math.tau, "e": math.e}
VARIABLES = ("t", "i", "sr")


# --------------------------------------------------------------------------
# Tokenizer
# --------------------------------------------------------------------------

_NUM_RE = re.compile(r"0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Longest operators first so `>>>` wins over `>>` over `>`, `**` over `*`, etc.
_OPS = [">>>", "**", "<<", ">>", "<=", ">=", "==", "!=", "&&", "||",
        "+", "-", "*", "/", "%", "&", "|", "^", "~", "!", "<", ">", "?", ":",
        "(", ")", ","]


def tokenize(text):
    """Return [(kind, value, pos)] with kind in num|name|op|end."""
    tokens = []
    pos = 0
    n = len(text)
    while pos < n:
        ch = text[pos]
        if ch.isspace():
            pos += 1
            continue
        if ch.isdigit() or (ch == "." and pos + 1 < n and text[pos + 1].isdigit()):
            m = _NUM_RE.match(text, pos)
            end = m.end()
            if end < n and (text[end].isalnum() or text[end] == "_"):
                raise ExprError("malformed number", pos)
            raw = m.group(0)
            value = float(int(raw, 16)) if raw[:2] in ("0x", "0X") else float(raw)
            tokens.append(("num", value, pos))
            pos = end
            continue
        m = _NAME_RE.match(text, pos)
        if m:
            tokens.append(("name", m.group(0), pos))
            pos = m.end()
            continue
        for op in _OPS:
            if text.startswith(op, pos):
                tokens.append(("op", op, pos))
                pos += len(op)
                break
        else:
            raise ExprError("unexpected character %r" % ch, pos)
    tokens.append(("end", None, n))
    return tokens


# --------------------------------------------------------------------------
# Parser (precedence climbing; keeps Python recursion shallow for nested parens)
# --------------------------------------------------------------------------

# Binary operator precedence, low -> high (format.md levels 2..11). All left assoc.
_BINARY_PREC = {
    "||": 1, "&&": 2, "|": 3, "^": 4, "&": 5,
    "==": 6, "!=": 6, "<": 7, "<=": 7, ">": 7, ">=": 7,
    "<<": 8, ">>": 8, ">>>": 8, "+": 9, "-": 9, "*": 10, "/": 10, "%": 10,
}


class _Parser:
    def __init__(self, text):
        self.tokens = tokenize(text)
        self.k = 0

    def peek(self):
        return self.tokens[self.k]

    def advance(self):
        tok = self.tokens[self.k]
        self.k += 1
        return tok

    def is_op(self, op):
        tok = self.tokens[self.k]
        return tok[0] == "op" and tok[1] == op

    def expect(self, op):
        tok = self.peek()
        if tok[0] == "op" and tok[1] == op:
            return self.advance()
        raise ExprError("expected %r but found %s" % (op, _describe(tok)), tok[2])

    def parse(self):
        if self.peek()[0] == "end":
            raise ExprError("empty expression", 0)
        node = self.ternary()
        tok = self.peek()
        if tok[0] != "end":
            raise ExprError("unexpected %s" % _describe(tok), tok[2])
        return node

    def ternary(self):
        cond = self.binary(1)
        if self.is_op("?"):
            self.advance()
            a = self.ternary()
            self.expect(":")
            b = self.ternary()  # right associative
            return ("cond", cond, a, b)
        return cond

    def binary(self, min_prec):
        left = self.unary()
        while True:
            tok = self.peek()
            prec = _BINARY_PREC.get(tok[1]) if tok[0] == "op" else None
            if prec is None or prec < min_prec:
                return left
            self.advance()
            right = self.binary(prec + 1)  # left associative
            left = ("bin", tok[1], left, right)

    def unary(self):
        tok = self.peek()
        if tok[0] == "op" and tok[1] in ("-", "+", "!", "~"):
            self.advance()
            return ("un", tok[1], self.unary())
        return self.power()

    def power(self):
        base = self.primary()
        if self.is_op("**"):
            self.advance()
            # Right operand may carry a unary (2**-1) and recurses for right assoc.
            return ("bin", "**", base, self.unary())
        return base

    def primary(self):
        tok = self.advance()
        kind, value, pos = tok
        if kind == "num":
            return ("num", value)
        if kind == "op" and value == "(":
            node = self.ternary()
            self.expect(")")
            return node
        if kind == "name":
            nxt = self.peek()
            is_call = nxt[0] == "op" and nxt[1] == "("
            if value in FUNCTIONS:
                if not is_call:
                    raise ExprError("function %r must be called with ()" % value, pos)
                return self.call(value, pos)
            if value in CONSTANTS or value in VARIABLES:
                if is_call:
                    raise ExprError("%r is not a function" % value, pos)
                return ("const", CONSTANTS[value]) if value in CONSTANTS else ("var", value)
            raise ExprError("unknown name %r" % value, pos)
        self.k -= 1  # keep the offending token for the message
        raise ExprError("unexpected %s" % _describe(tok), pos)

    def call(self, name, pos):
        self.expect("(")
        args = []
        if not self.is_op(")"):
            args.append(self.ternary())
            while self.is_op(","):
                self.advance()
                args.append(self.ternary())
        self.expect(")")
        _, lo, hi = FUNCTIONS[name]
        if len(args) < lo or (hi is not None and len(args) > hi):
            want = str(lo) if lo == hi else ("at least %d" % lo if hi is None else "%d to %d" % (lo, hi))
            raise ExprError("%s() takes %s argument(s), got %d" % (name, want, len(args)), pos)
        return ("call", name, args)


def _describe(tok):
    kind, value, _ = tok
    if kind == "end":
        return "end of expression"
    if kind == "num":
        return "number"
    return repr(value)


def parse_expr(text):
    """Parse `text` into an AST of tuples; raises ExprError with the position."""
    if not isinstance(text, str):
        raise ExprError("expression must be a string", 0)
    try:
        return _Parser(text).parse()
    except RecursionError:
        raise ExprError("expression is nested too deeply", 0) from None


# --------------------------------------------------------------------------
# Code generation
# --------------------------------------------------------------------------

_ARITH = {"+", "-", "*"}
_COMPARE = {"<", "<=", ">", ">=", "==", "!="}
_BITWISE = {"|": "_or", "^": "_xor", "&": "_and", "<<": "_shl", ">>": "_shr", ">>>": "_ushr"}


class _Gen:
    def __init__(self):
        self.tmp = 0

    def truth(self, src):
        """Source for 'value != 0 and not NaN'; walrus evaluates `src` once."""
        self.tmp += 1
        v = "_w%d" % self.tmp
        return "((%s := %s) == %s and %s != 0.0)" % (v, src, v, v)

    def lit(self, v):
        return repr(v) if _finite(v) else "_INF"

    def gen(self, node):
        kind = node[0]
        if kind == "num":
            return self.lit(node[1])
        if kind == "const":
            return self.lit(node[1])
        if kind == "var":
            return node[1]
        if kind == "un":
            op, x = node[1], self.gen(node[2])
            if op == "-":
                return "(-%s)" % x
            if op == "+":
                return "(+%s)" % x
            if op == "!":
                return "(0.0 if %s else 1.0)" % self.truth(x)
            return "_bnot(%s)" % x
        if kind == "bin":
            return self.gen_bin(node)
        if kind == "cond":
            c = self.truth(self.gen(node[1]))
            return "(%s if %s else %s)" % (self.gen(node[2]), c, self.gen(node[3]))
        if kind == "call":
            args = ", ".join(self.gen(a) for a in node[2])
            return "_f_%s(%s)" % (node[1], args)
        raise AssertionError("unknown node " + kind)  # parser never emits this

    def gen_bin(self, node):
        op, left, right = node[1], node[2], node[3]
        a = self.gen(left)
        if op == "&&" or op == "||":
            # Short-circuit like JS (matters when rand() has side effects); result is 1/0.
            joiner = " and " if op == "&&" else " or "
            return "(1.0 if (%s%s%s) else 0.0)" % (
                self.truth(a), joiner, self.truth(self.gen(right)))
        b = self.gen(right)
        if op in _ARITH:
            return "(%s %s %s)" % (a, op, b)
        if op == "/":
            # Constant non-zero divisor cannot raise, so skip the helper call.
            if right[0] in ("num", "const") and right[1] != 0 and _finite(right[1]):
                return "(%s / %s)" % (a, b)
            return "_div(%s, %s)" % (a, b)
        if op == "%":
            return "_mod(%s, %s)" % (a, b)
        if op == "**":
            return "_pow(%s, %s)" % (a, b)
        if op in _COMPARE:
            return "(1.0 if %s %s %s else 0.0)" % (a, op, b)
        return "%s(%s, %s)" % (_BITWISE[op], a, b)


def _build_namespace(rng):
    ns = {"__builtins__": {}, "_INF": _INF, "_div": _div, "_mod": _mod, "_pow": _pow,
          "_or": _or, "_xor": _xor, "_and": _and, "_shl": _shl, "_shr": _shr,
          "_ushr": _ushr, "_bnot": _bnot}
    for name, (fn, _, _) in FUNCTIONS.items():
        if fn is not None:
            ns["_f_" + name] = fn
    ns["_f_rand"] = rng
    ns["_f_noise"] = lambda: rng() * 2.0 - 1.0
    return ns


def compile_expr(text, seed=1):
    """Compile `text` to `fn(t, i, sr) -> float`; `rand()` uses mulberry32(seed).

    All arguments and results are floats. The returned callable never raises for
    any numeric input. It carries `.source` (generated Python) for debugging.
    """
    ast = parse_expr(text)
    src = "lambda t, i, sr: " + _Gen().gen(ast)
    try:
        fn = eval(compile(src, "<soundgen-expr>", "eval"), _build_namespace(mulberry32(seed)))
    except (SyntaxError, RecursionError, MemoryError):
        # CPython caps nesting of parentheses / AST depth.
        raise ExprError("expression is too complex", 0) from None
    fn.source = src
    return fn


def evaluate(text, t=0.0, i=0.0, sr=44100.0, seed=1):
    """Convenience for tests and tools: compile and evaluate once."""
    return compile_expr(text, seed)(float(t), float(i), float(sr))
