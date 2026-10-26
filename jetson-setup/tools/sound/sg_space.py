"""3D placement (`pos`) and master `space` effects (docs/format.md, "3D placement" and "Space").

Pure list-of-float processing, stdlib only. Every formula and the per-sample evaluation order are
copied from the contract so the Python and JavaScript engines agree within 1e-6.

Imported lazily by sg_engine (which this module imports), like sg_song.
"""

import math
from math import ceil, cos, exp, floor, pi, sin

from sg_engine import SR, SoundError, _num

# Binaural model constants (format.md): maximum interaural delay and the delay-line padding.
ITD_SECONDS = 0.00066
POS_TAIL = 30          # a placed part is n + 30 samples long (room for the far-ear delay)
MIN_DIST = 0.25

COMB_LENGTHS = (1116, 1188, 1277, 1356)
ALLPASS_LENGTHS = (556, 441)
STEREO_SPREAD = 23     # right channel line lengths = left + 23


# --------------------------------------------------------------------------
# 3D placement
# --------------------------------------------------------------------------

def resolve_pos(raw, what="pos"):
    """`pos` object -> (angle, spin, dist) floats with dist clamped to >= 0.25; None -> None."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SoundError("%s must be an object like {\"angle\": 90, \"spin\": 0, \"dist\": 1}" % what)
    vals = []
    for key, dflt in (("angle", 0.0), ("spin", 0.0), ("dist", 1.0)):
        v = raw.get(key)
        vals.append(dflt if v is None else _num(v, "%s.%s" % (what, key)))
    return vals[0], vals[1], max(vals[2], MIN_DIST)


def mono_of(left, right):
    """Mono signal fed to placement: the part itself, or (L + R) / 2 for a stereo part."""
    if right is None:
        return left
    return [(a + b) / 2 for a, b in zip(left, right)]


def place(x, start, pos):
    """Binaural placement of mono `x` -> (outL, outR), each n + 30 samples.

    `start` is the part's start sample in the mix: the spin angle advances with the mix time
    `k + start`, so a spinning track keeps turning across notes. See format.md for the model
    (interaural delay, level difference, 1/dist, head-shadow one-pole per ear).
    """
    angle, spin, dist = pos
    n = len(x)
    m = n + POS_TAIL
    sr = float(SR)
    two_pi = 2.0 * pi
    nyq = sr / 2
    itd = ITD_SECONDS * sr
    # xp[PAD + j] = x[j] with zeros outside 0..n-1, so read() needs no bounds checks.
    # Delays are at most 0.00066*sr ~ 29.1 samples, j0 >= -30 and j0 + 1 <= n + 29.
    pad = 32
    xp = [0.0] * pad + list(x) + [0.0] * (pad + 2)
    out_l = [0.0] * m
    out_r = [0.0] * m
    lp_l = lp_r = 0.0

    if spin == 0:
        # Static source: everything but the sample position is constant, and one ear always has
        # d == 0 (read(0) is x[k] itself since fr == 0). Same expressions as the general loop.
        th = (angle + spin * (0 + 0) / sr) * pi / 180
        sn, cs = sin(th), cos(th)
        d_l = itd * max(0, sn)
        d_r = itd * max(0, -sn)
        g_l = (1 - 0.5 * max(0, sn)) / dist
        g_r = (1 - 0.5 * max(0, -sn)) / dist
        back = max(0, -cs)
        a_l = 1 - exp(-two_pi * min(20000 * 2 ** (-3 * max(0, sn) - 1.5 * back), nyq) / sr)
        a_r = 1 - exp(-two_pi * min(20000 * 2 ** (-3 * max(0, -sn) - 1.5 * back), nyq) / sr)
        for out, d, g, a in ((out_l, d_l, g_l, a_l), (out_r, d_r, g_r, a_r)):
            lp = 0.0
            if d == 0:
                for k in range(m):
                    lp += a * (xp[pad + k] * g - lp)
                    out[k] = lp
            else:
                for k in range(m):
                    j = k - d
                    j0 = floor(j)
                    fr = j - j0
                    av = xp[pad + j0]
                    bv = xp[pad + j0 + 1]
                    lp += a * ((av + (bv - av) * fr) * g - lp)
                    out[k] = lp
        return out_l, out_r

    for k in range(m):
        th = (angle + spin * (k + start) / sr) * pi / 180
        sn = sin(th)
        cs = cos(th)
        pos_s = sn if sn > 0 else 0   # max(0, sn)
        neg_s = -sn if sn < 0 else 0  # max(0, -sn)
        d_l = itd * pos_s
        d_r = itd * neg_s
        j = k - d_l
        j0 = floor(j)
        fr = j - j0
        av = xp[pad + j0]
        bv = xp[pad + j0 + 1]
        v_l = (av + (bv - av) * fr) * ((1 - 0.5 * pos_s) / dist)
        j = k - d_r
        j0 = floor(j)
        fr = j - j0
        av = xp[pad + j0]
        bv = xp[pad + j0 + 1]
        v_r = (av + (bv - av) * fr) * ((1 - 0.5 * neg_s) / dist)
        back = -cs if cs < 0 else 0   # max(0, -cs)
        fc_l = 20000 * 2 ** (-3 * pos_s - 1.5 * back)
        fc_r = 20000 * 2 ** (-3 * neg_s - 1.5 * back)
        lp_l += (1 - exp(-two_pi * min(fc_l, nyq) / sr)) * (v_l - lp_l)
        lp_r += (1 - exp(-two_pi * min(fc_r, nyq) / sr)) * (v_r - lp_r)
        out_l[k] = lp_l
        out_r[k] = lp_r
    return out_l, out_r


# --------------------------------------------------------------------------
# Space: echo -> reverb -> haas -> width on the summed mix
# --------------------------------------------------------------------------

_ECHO_DEFAULTS = {"time": 0.0, "feedback": 0.0, "mix": 0.0}
_REVERB_DEFAULTS = {"mix": 0.0, "size": 0.5, "damp": 0.5, "width": 1.0}


def _section(raw, key):
    v = raw.get(key)
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise SoundError("space.%s must be an object" % key)
    return v


def resolve_space(raw):
    """`space` block -> defaulted dict with an `active` flag; None -> inactive defaults."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SoundError("space must be an object")
    echo_raw, rev_raw = _section(raw, "echo"), _section(raw, "reverb")
    echo = {k: (d if echo_raw.get(k) is None else _num(echo_raw[k], "space.echo." + k))
            for k, d in _ECHO_DEFAULTS.items()}
    pp = echo_raw.get("pingpong")
    if pp is not None and not isinstance(pp, bool):
        raise SoundError("space.echo.pingpong must be true or false, got %r" % (pp,))
    echo["pingpong"] = bool(pp)
    reverb = {k: (d if rev_raw.get(k) is None else _num(rev_raw[k], "space.reverb." + k))
              for k, d in _REVERB_DEFAULTS.items()}
    haas = 0.0 if raw.get("haas") is None else _num(raw["haas"], "space.haas")
    width = 1.0 if raw.get("width") is None else _num(raw["width"], "space.width")
    echo_on = echo["mix"] > 0 and echo["time"] > 0
    reverb_on = reverb["mix"] > 0
    return {"echo": echo, "reverb": reverb, "haas": haas, "width": width,
            "echo_on": echo_on, "reverb_on": reverb_on, "haas_on": haas > 0, "width_on": width != 1,
            "active": echo_on or reverb_on or haas > 0 or width != 1}


def echo_tail_seconds(echo):
    """Echo tail in seconds: the patch echo tail rule, min(4, time * repeats)."""
    fb = min(echo["feedback"], 0.95)
    repeats = 1 if fb <= 0 else 1 + ceil(math.log(0.001) / math.log(fb))
    return min(4.0, echo["time"] * repeats)


def reverb_tail_seconds(reverb):
    return min(6.0, 0.5 + 3 * reverb["size"])


def apply_space(left, right, space, check_length=None):
    """Run the active space stages on a stereo pair; returns new (left, right) lists.

    Both channels are first extended with ceil((echoTail + reverbTail) * sr) zeros (the SUM of
    the tails in seconds is rounded once, as in the contract), so tails ring out; the haas delay
    then lengthens the right channel (and the left is zero-padded to match).
    """
    tail = 0.0
    if space["echo_on"]:
        tail += echo_tail_seconds(space["echo"])
    if space["reverb_on"]:
        tail += reverb_tail_seconds(space["reverb"])
    extra = ceil(tail * SR)
    h = round_half_up(space["haas"] / 1000 * SR) if space["haas_on"] else 0
    if check_length is not None:
        check_length(len(left) + extra + h)
    pad = [0.0] * extra
    left = list(left) + pad
    right = list(right) + pad
    if space["echo_on"]:
        left, right = _echo(left, right, space["echo"])
    if space["reverb_on"]:
        left, right = _reverb(left, right, space["reverb"])
    if space["haas_on"]:
        right = [0.0] * h + right
        left = left + [0.0] * h
    if space["width_on"]:
        width = space["width"]
        mid = [(a + b) / 2 for a, b in zip(left, right)]
        side = [(a - b) / 2 * width for a, b in zip(left, right)]
        left = [m + s for m, s in zip(mid, side)]
        right = [m - s for m, s in zip(mid, side)]
    return left, right


def round_half_up(x):
    return floor(x + 0.5)


def _echo(left, right, echo):
    """Stereo echo with optional ping-pong, written exactly as in the contract."""
    d = max(1, round_half_up(echo["time"] * SR))
    fb = min(echo["feedback"], 0.95)
    mix = echo["mix"]
    pingpong = echo["pingpong"]
    # bl/br are the delay lines; pre-filled with D zeros so the delayed value of sample i is
    # simply bl[i] (the list keeps growing as new samples are appended).
    bl = [0.0] * d
    br = [0.0] * d
    out_l = [0.0] * len(left)
    out_r = [0.0] * len(left)
    for i, (l, r) in enumerate(zip(left, right)):
        dl = bl[i]
        dr = br[i]
        if pingpong:
            bl.append((l + r) / 2 + fb * dr)
            br.append(fb * dl)
        else:
            bl.append(l + fb * dl)
            br.append(r + fb * dr)
        out_l[i] = l + mix * dl
        out_r[i] = r + mix * dr
    return out_l, out_r


def _reverb(left, right, reverb):
    """Freeverb-style reverb, one fused loop per sample (bit-identical to the contract's order).

    Per sample: inp = (L + R) * 0.015 feeds 4 combs per channel (their outputs are the delayed
    values `o`), the comb sum goes through 2 series allpasses, and the wet pair is mixed with the
    dry L / R of the same sample. Every comb only reads the dry input, so the lines can be kept
    as plain lists pre-filled with `length` zeros: the delayed value of sample i is simply
    line[i], and new values are appended. Because each line is at least `blk` long, a whole block
    of `blk` samples can be sliced out of the lines up front and walked with zip(), which is much
    faster than indexing / modulo arithmetic in CPython (7.0 s -> 5.0 s on a 60 s signal).
    """
    mix, size, dmp, width = reverb["mix"], reverb["size"], reverb["damp"], reverb["width"]
    fbk = 0.7 + 0.28 * size
    omd = 1 - dmp
    w1 = width / 2 + 0.5
    w2 = (1 - width) / 2
    dry = 1 - mix
    n = len(left)
    cl = list(COMB_LENGTHS)
    cr = [ln + STEREO_SPREAD for ln in COMB_LENGTHS]
    al = list(ALLPASS_LENGTHS)
    ar = [ln + STEREO_SPREAD for ln in ALLPASS_LENGTHS]
    c_l0, c_l1, c_l2, c_l3 = ([0.0] * ln for ln in cl)   # left combs
    c_r0, c_r1, c_r2, c_r3 = ([0.0] * ln for ln in cr)   # right combs
    a_l0, a_l1 = ([0.0] * ln for ln in al)               # left allpasses (series)
    a_r0, a_r1 = ([0.0] * ln for ln in ar)               # right allpasses (series)
    cl0, cl1, cl2, cl3 = c_l0.append, c_l1.append, c_l2.append, c_l3.append
    cr0, cr1, cr2, cr3 = c_r0.append, c_r1.append, c_r2.append, c_r3.append
    al0, al1, ar0, ar1 = a_l0.append, a_l1.append, a_r0.append, a_r1.append
    sl0 = sl1 = sl2 = sl3 = sr0 = sr1 = sr2 = sr3 = 0.0   # comb damping stores
    out_l = []
    out_r = []
    emit_l, emit_r = out_l.append, out_r.append
    blk = min(min(cl), min(al))  # shortest line (441): every slice below stays inside written data
    for b in range(0, n, blk):
        e = b + blk
        for x, y, p0, p1, p2, p3, q0, q1, q2, q3, u0, u1, v0, v1 in zip(
                left[b:e], right[b:e], c_l0[b:e], c_l1[b:e], c_l2[b:e], c_l3[b:e],
                c_r0[b:e], c_r1[b:e], c_r2[b:e], c_r3[b:e], a_l0[b:e], a_l1[b:e], a_r0[b:e], a_r1[b:e]):
            inp = (x + y) * 0.015
            sl0 = p0 * omd + sl0 * dmp
            sl1 = p1 * omd + sl1 * dmp
            sl2 = p2 * omd + sl2 * dmp
            sl3 = p3 * omd + sl3 * dmp
            sr0 = q0 * omd + sr0 * dmp
            sr1 = q1 * omd + sr1 * dmp
            sr2 = q2 * omd + sr2 * dmp
            sr3 = q3 * omd + sr3 * dmp
            cl0(inp + sl0 * fbk)
            cl1(inp + sl1 * fbk)
            cl2(inp + sl2 * fbk)
            cl3(inp + sl3 * fbk)
            cr0(inp + sr0 * fbk)
            cr1(inp + sr1 * fbk)
            cr2(inp + sr2 * fbk)
            cr3(inp + sr3 * fbk)
            # channel sum in comb order 0..3, then the two allpasses in series
            c = p0 + p1 + p2 + p3
            al0(c + u0 * 0.5)
            c = -c + u0
            al1(c + u1 * 0.5)
            c_left = -c + u1
            c = q0 + q1 + q2 + q3
            ar0(c + v0 * 0.5)
            c = -c + v0
            ar1(c + v1 * 0.5)
            c_right = -c + v1
            emit_l(x * dry + mix * (c_left * w1 + c_right * w2))
            emit_r(y * dry + mix * (c_right * w1 + c_left * w2))
    return out_l, out_r
