"""Sound engine: defaults, patch voice renderer and mode dispatch.

Contract: docs/format.md (single source of truth shared with web/engine.js).
Operation order, `floor(x + 0.5)` rounding and the PRNG are copied literally so the
two engines agree sample-for-sample (tolerance 1e-6).

Public API:
    resolve_patch(raw)            -> fully defaulted patch dict (all numbers are floats)
    render_patch(resolved)        -> list[float]   (one synth voice, rate = SR)
    render_sound(spec, presets)   -> Rendered, i.e. (sample_rate, left_or_mono_samples)
                                     with an extra `.right` attribute (None for mono sounds)
"""

import copy
import json
import math
import os
from math import ceil, cos, exp, floor, pi, sin

from sg_expr import ExprError, compile_expr, mulberry32, to_int32  # noqa: F401  (re-exported)

SR = 44100
# Safety valve for the CLI only (10 minutes at 44.1 kHz); the format itself has no cap.
MAX_SAMPLES = SR * 600
PRESETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets.json")

# Index order matters: render_patch branches on it (4 = noise, 5 = crackle use the PRNG).
WAVES = ("sine", "square", "saw", "triangle", "noise", "crackle", "pluck", "additive", "sample")
MAX_LAYER_DEPTH = 4

# `None` marks keys whose default is a rule ("use the default rule"): freqEnd = freq,
# indexEnd = index, lowpassEnd = lowpass, bandEnd = band. Resolved in resolve_patch().
# `osc.glideFrom = None` means portamento off (it stays None after resolving).
DEFAULT_PATCH = {
    "mode": "patch", "name": "", "seed": 1, "duration": 0.5, "gain": 0.8,
    "osc": {"wave": "sine", "freq": 440, "freqEnd": None, "sweep": "exp", "duty": 0.5,
            "glideFrom": None, "glide": 0},
    "vibrato": {"rate": 0, "depth": 0, "delay": 0},      # delay: seconds before full depth
    "arp": {"steps": [], "rate": 50},
    "pwm": {"rate": 0, "depth": 0},
    "fm": {"ratio": 1, "index": 0, "indexEnd": None},
    "env": {"a": 0.01, "d": 0.1, "s": 0.7, "r": 0.2},
    "filter": {"lowpass": 20000, "lowpassEnd": None, "highpass": 0, "band": 0, "bandEnd": None, "q": 1},
    "unison": {"voices": 1, "detune": 0},                # stacked detuned oscillators (cents)
    "pluck": {"decay": 0.996, "damping": 0.5, "bright": 1},     # wave "pluck" (Karplus-Strong string)
    "additive": {"harmonics": [[1, 1]], "decay": 0},            # wave "additive": [ratio, amp] partials
    "formant": {"vowel": None, "vowelEnd": None, "mix": 1, "q": 8},   # vowel filter (effect 4a)
    "sampler": {"zones": [], "pitched": True},           # wave "sample": [[rootMidi, "file.wav"], ...]
    "breath": {"level": 0, "band": 1500, "q": 0.8},      # bandpassed noise added after the sub
    "sub": {"level": 0, "octave": -1, "wave": "sine"},   # sub-oscillator mixed in before the envelope
    "drive": 0,                                          # tanh soft saturation amount, 0 = off
    "wobble": {"rate": 0, "depth": 0},                   # filter LFO (Hz, octaves): lowpass + bandpass
    "eq": {"bass": 0, "bassFreq": 120, "treble": 0, "trebleFreq": 6000},   # shelves (dB, Hz)
    "crush": {"bits": 16, "hold": 1},
    "echo": {"time": 0, "feedback": 0, "mix": 0},
}
_SECTIONS = ("osc", "vibrato", "arp", "pwm", "fm", "env", "filter", "unison", "pluck", "additive", "formant", "sampler", "breath", "sub", "wobble", "eq", "crush", "echo")
SUB_WAVES = ("sine", "square", "triangle")
# Vowel table of the formant filter: vowel -> ((F1, F2, F3) Hz, (g1, g2, g3)); docs/format.md effect 4a.
VOWELS = {
    "a": ((800.0, 1150.0, 2900.0), (1.0, 0.5, 0.25)),
    "e": ((400.0, 1600.0, 2700.0), (1.0, 0.35, 0.2)),
    "i": ((300.0, 2300.0, 3000.0), (1.0, 0.2, 0.15)),
    "o": ((450.0, 800.0, 2830.0), (1.0, 0.6, 0.15)),
    "u": ((325.0, 700.0, 2530.0), (1.0, 0.3, 0.1)),
}


class SoundError(ValueError):
    """Invalid sound spec (bad type, unknown wave/mode/preset, absurd length...)."""


class Rendered(tuple):
    """Result of a render: behaves exactly like the historic `(sample_rate, samples)` pair.

    `samples` is the mono signal, or the LEFT channel of a stereo sound; the RIGHT channel
    lives in the `right` attribute and is None for mono sounds (same shape as the JS
    engine's `{sampleRate, samples, right}`). Keeping a 2-tuple means every existing
    `rate, samples = render_sound(...)` caller and equality check keeps working; stereo-aware
    code reads `.right` / `.channels` explicitly.
    """

    def __new__(cls, rate, samples, right=None):
        self = super().__new__(cls, (rate, samples))
        self.right = right
        return self

    @property
    def channels(self):
        return 1 if self.right is None else 2


# --------------------------------------------------------------------------
# Defaults and merging
# --------------------------------------------------------------------------

def deep_merge(base, over):
    """Return a new dict: `over` recursively merged on top of `base`.

    An explicit `None` in `over` replaces the value ("use the default rule"); it is
    interpreted later by resolve_patch(), so a song instrument can reset a preset's
    freqEnd back to the default rule with `"freqEnd": null`.
    """
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _num(value, path):
    # bool is an int subclass in Python; JSON true/false is almost surely a mistake.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SoundError("%s must be a number, got %r" % (path, value))
    value = float(value)
    if value - value != 0.0:
        raise SoundError("%s must be finite" % path)
    return value


def resolve_patch(raw):
    """Merge `raw` (partial patch) over DEFAULT_PATCH and normalise types."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SoundError("patch must be a JSON object")
    for sec in _SECTIONS:
        if raw.get(sec) is not None and not isinstance(raw[sec], dict):
            raise SoundError("%r must be an object" % sec)
    m = deep_merge(DEFAULT_PATCH, raw)
    p = {"mode": "patch", "name": str(m.get("name") or "")}
    p["seed"] = _num(1 if m.get("seed") is None else m["seed"], "seed")
    p["duration"] = _num(_default(m, "duration"), "duration")
    p["gain"] = _num(_default(m, "gain"), "gain")
    p["drive"] = _num(_default(m, "drive"), "drive")
    for sec in _SECTIONS:
        s = m.get(sec) or {}
        p[sec] = {}
        for key, dflt in DEFAULT_PATCH[sec].items():
            v = s.get(key)
            if key == "steps":
                p[sec][key] = _steps(v)
            elif key == "harmonics":
                p[sec][key] = _harmonics(v)
            elif key == "zones":
                p[sec][key] = _zones(v)
            elif key == "pitched":
                p[sec][key] = _pitched(v)
            elif key in ("vowel", "vowelEnd"):
                p[sec][key] = _vowel(v, "%s.%s" % (sec, key))
            elif key in ("wave", "sweep"):  # sub.wave is checked below
                p[sec][key] = dflt if v is None else v
            elif v is not None:
                p[sec][key] = _num(v, "%s.%s" % (sec, key))
            elif dflt is not None:
                p[sec][key] = float(dflt)
            else:
                p[sec][key] = None
    osc, fm, flt = p["osc"], p["fm"], p["filter"]
    if p["sub"]["wave"] not in SUB_WAVES:
        raise SoundError("sub.wave must be one of %s, got %r" % (", ".join(SUB_WAVES), p["sub"]["wave"]))
    if osc["wave"] not in WAVES:
        raise SoundError("osc.wave must be one of %s, got %r" % (", ".join(WAVES), osc["wave"]))
    if osc["freqEnd"] is None:
        osc["freqEnd"] = osc["freq"]
    if fm["indexEnd"] is None:
        fm["indexEnd"] = fm["index"]
    if flt["lowpassEnd"] is None:
        flt["lowpassEnd"] = flt["lowpass"]
    if flt["bandEnd"] is None:
        flt["bandEnd"] = flt["band"]
    return p


def _steps(v):
    """arp.steps: a list of finite numbers (semitone offsets); None -> empty."""
    if v is None:
        return []
    if not isinstance(v, list):
        raise SoundError("arp.steps must be a list of finite numbers, got %r" % (v,))
    return [_num(x, "arp.steps[%d]" % i) for i, x in enumerate(v)]


def _harmonics(v):
    """additive.harmonics: a list of [ratio, amp] finite-number pairs; None -> the default [[1, 1]]."""
    if v is None:
        return [[1.0, 1.0]]
    if not isinstance(v, list):
        raise SoundError("additive.harmonics must be a list of [ratio, amp] pairs, got %r" % (v,))
    out = []
    for i, pair in enumerate(v):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise SoundError("additive.harmonics[%d] must be a [ratio, amp] pair, got %r" % (i, pair))
        out.append([_num(pair[0], "additive.harmonics[%d] ratio" % i), _num(pair[1], "additive.harmonics[%d] amp" % i)])
    return out


def _zones(v):
    """sampler.zones: a list of [rootMidi, "file.wav"] pairs (file names relative to samples/)."""
    if v is None:
        return []
    if not isinstance(v, list):
        raise SoundError("sampler.zones must be a list of [rootMidi, \"file.wav\"] pairs, got %r" % (v,))
    out = []
    for i, pair in enumerate(v):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2 or not isinstance(pair[1], str):
            raise SoundError("sampler.zones[%d] must be a [rootMidi, \"file.wav\"] pair, got %r" % (i, pair))
        out.append([_num(pair[0], "sampler.zones[%d] root" % i), pair[1]])
    return out


def _pitched(v):
    if v is None:
        return True
    if not isinstance(v, bool):
        raise SoundError("sampler.pitched must be true or false, got %r" % (v,))
    return v


# --------------------------------------------------------------------------
# Samples (wave "sample"): 16-bit PCM mono WAVs in samples/ next to presets.json
# --------------------------------------------------------------------------

SAMPLES_DIR = os.path.join(os.path.dirname(PRESETS_PATH), "samples")
_SAMPLE_CACHE = {}


def load_sample(name):
    """Decode samples/<name> -> (sample_rate, [int16 / 32768 floats]); cached, errors are SoundErrors."""
    hit = _SAMPLE_CACHE.get(name)
    if hit is not None:
        return hit
    # Plain file names only: the sampler must not reach outside the samples folder.
    if not name or os.path.basename(name) != name or name in (".", ".."):
        raise SoundError("sample file name must be a plain file name inside samples/, got %r" % (name,))
    path = os.path.join(SAMPLES_DIR, name)
    if not os.path.isfile(path):
        raise SoundError("sample file %r not found in %s" % (name, SAMPLES_DIR))
    import sys
    import wave
    from array import array
    try:
        with wave.open(path, "rb") as w:
            if w.getsampwidth() != 2 or w.getnchannels() != 1 or w.getcomptype() != "NONE":
                raise SoundError("sample %r must be 16-bit PCM mono" % name)
            rate = w.getframerate()
            raw = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as exc:
        raise SoundError("sample %r is not a readable WAV: %s" % (name, exc)) from None
    pcm = array("h")
    pcm.frombytes(raw)
    if sys.byteorder == "big":
        pcm.byteswap()
    data = [v / 32768 for v in pcm]
    _SAMPLE_CACHE[name] = (rate, data)
    return rate, data


def pick_zone(zones, freq):
    """Zone whose root is nearest to m = 69 + 12*log2(freq/440); tie -> lower root; freq <= 0 -> first."""
    if freq <= 0:
        return zones[0]
    m = 69 + 12 * math.log2(freq / 440)
    return min(zones, key=lambda z: (abs(z[0] - m), z[0]))


def _vowel(v, path):
    """formant.vowel / vowelEnd: one of a e i o u, otherwise None.

    Like web/engine.js, an unknown vowel is not an error: formant.vowel unknown/null leaves the
    filter OFF, and an unknown vowelEnd means "same vowel" (no morph).
    """
    return v if isinstance(v, str) and v in VOWELS else None


def _default(m, key):
    v = m.get(key)
    return DEFAULT_PATCH[key] if v is None else v


def load_presets(path=None):
    """Load presets.json (name -> sound object: partial patch, or e.g. a layers spec)."""
    with open(path or PRESETS_PATH, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# EQ shelves (RBJ cookbook, slope S = 1) shared by the patch effect 4b and the master eq
# --------------------------------------------------------------------------

def shelf_coefs(kind, gain_db, fc):
    """Biquad (n0, n1, n2, d1, d2) of a low/high shelf; formulas copied from docs/format.md.

    Constant for a whole render, so callers compute it once. `fc` is clamped to [10, 0.49*sr].
    """
    a = 10.0 ** (gain_db / 40)
    fc = min(max(fc, 10), 0.49 * SR)
    w0 = 2 * pi * fc / SR
    c = cos(w0)
    alpha = sin(w0) / 2 * math.sqrt(2)
    k = 2 * math.sqrt(a) * alpha
    if kind == "low":
        b0 = a * ((a + 1) - (a - 1) * c + k)
        b1 = 2 * a * ((a - 1) - (a + 1) * c)
        b2 = a * ((a + 1) - (a - 1) * c - k)
        a0 = (a + 1) + (a - 1) * c + k
        a1 = -2 * ((a - 1) + (a + 1) * c)
        a2 = (a + 1) + (a - 1) * c - k
    else:
        b0 = a * ((a + 1) + (a - 1) * c + k)
        b1 = -2 * a * ((a - 1) + (a + 1) * c)
        b2 = a * ((a + 1) + (a - 1) * c - k)
        a0 = (a + 1) - (a - 1) * c + k
        a1 = 2 * ((a - 1) - (a + 1) * c)
        a2 = (a + 1) - (a - 1) * c - k
    return b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0


def eq_stages(eq):
    """Active shelf stages [(n0, n1, n2, d1, d2)] of an eq dict: low shelf first, then high."""
    stages = []
    if eq["bass"] != 0:
        stages.append(shelf_coefs("low", eq["bass"], eq["bassFreq"]))
    if eq["treble"] != 0:
        stages.append(shelf_coefs("high", eq["treble"], eq["trebleFreq"]))
    return stages


def resolve_eq(raw, what="eq"):
    """Master eq object (song / layers top level) -> defaulted floats; None -> all off."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SoundError("%s must be an object" % what)
    out = {}
    for key, dflt in DEFAULT_PATCH["eq"].items():
        v = raw.get(key)
        out[key] = float(dflt) if v is None else _num(v, "%s.%s" % (what, key))
    return out


def apply_master_eq(channel, eq):
    """Run the eq shelves over one summed channel in place (own filter state per call).

    Same biquad evaluation order as the patch effect 4b. No-op when both gains are 0.
    """
    for n0, n1, n2, d1, d2 in eq_stages(eq):
        x1 = x2 = y1 = y2 = 0.0
        for k, x in enumerate(channel):
            y = n0 * x + n1 * x1 + n2 * x2 - d1 * y1 - d2 * y2
            x2 = x1
            x1 = x
            y2 = y1
            y1 = y
            channel[k] = y
    return channel


# --------------------------------------------------------------------------
# Patch voice
# --------------------------------------------------------------------------

def _check_length(n, what):
    if n > MAX_SAMPLES:
        raise SoundError("%s would be %d samples long (limit %d, about 10 minutes)"
                         % (what, n, MAX_SAMPLES))
    return max(n, 0)


def _pow2(x):
    """2 ** x with JS overflow semantics (Infinity instead of OverflowError)."""
    try:
        return 2.0 ** x
    except OverflowError:
        return math.inf


MAX_UNISON = 16


def unison_voice_count(voices):
    """V = min(16, max(1, floor(unison.voices))) (format.md)."""
    return min(MAX_UNISON, max(1, floor(voices)))


def unison_multipliers(count, detune):
    """Per-voice frequency multipliers 2 ** (detune * (2k/(V-1) - 1) / 1200): cents spread
    -detune..+detune, so the set is symmetric (mk[k] * mk[V-1-k] == 1 up to rounding)."""
    return [_pow2(detune * (2 * k / (count - 1) - 1) / 1200) for k in range(count)]


def patch_length(p):
    """N from the format's "Length" section: gate + release + echo tail."""
    echo = p["echo"]
    tail = 0.0
    if echo["mix"] > 0 and echo["time"] > 0:
        fb = min(echo["feedback"], 0.95)
        repeats = 1 if fb <= 0 else 1 + ceil(math.log(0.001) / math.log(fb))
        tail = min(4.0, echo["time"] * repeats)
    total = (p["duration"] + p["env"]["r"] + tail) * SR
    return _check_length(ceil(total), "patch")


def render_patch(p):
    """Render a resolved patch (see resolve_patch) to a list of floats.

    The loop is hand-tuned (locals, hoisted constants, stages skipped when they are
    provably identity ops). Each shortcut is bit-exact with the generic formula:
      * constant frequency: freq*(freq/freq)**p == freq
      * no vibrato: f*(1+0*sin()) == f;  no FM: frac(phase + 0) == phase
      * frac(x) is written `x % 1.0`, equal to x - floor(x) for every double and
        NaN (not an exception) for +-inf, like JS.
    """
    sr = float(SR)
    n = patch_length(p)
    out = [0.0] * n
    if n == 0:
        return out

    osc, vib, fm, env, flt, crush, echo = (p[k] for k in
                                           ("osc", "vibrato", "fm", "env", "filter", "crush", "echo"))
    sub, wob, uni = p["sub"], p["wobble"], p["unison"]
    duration, gain = p["duration"], p["gain"]
    two_pi = 2.0 * pi

    # --- oscillator / pitch ---------------------------------------------------
    # 0 sine 1 square 2 saw 3 triangle 4 noise 5 crackle 6 pluck 7 additive
    wave_id = WAVES.index(osc["wave"])
    freq, freq_end, duty = osc["freq"], osc["freqEnd"], osc["duty"]
    linear = osc["sweep"] == "linear" or freq <= 0 or freq_end <= 0
    ratio = 1.0 if linear else freq_end / freq
    const_f = freq == freq_end
    # Portamento (format.md): from `glideFrom` Hz down/up to the pitch over `glide` seconds,
    # applied right after the sweep and before arp/vibrato. Inactive (the common case) means
    # zero extra work per sample. It is exponential in frequency: f * (from/freq) ** (1 - t/glide).
    glide_from, glide_t = osc["glideFrom"], osc["glide"]
    glide_on = glide_from is not None and glide_from > 0 and glide_t > 0 and freq > 0
    glide_ratio = glide_from / freq if glide_on else 1.0
    vib_depth, vib_w = vib["depth"], two_pi * vib["rate"]
    vib_delay = vib["delay"]  # > 0: depth ramps linearly from 0 to full over this many seconds
    vib_on = vib_depth != 0.0
    # Arpeggio: per-step frequency multipliers 2 ** (step / 12), precomputed (same values).
    arp_steps = p["arp"]["steps"]
    arp_on = len(arp_steps) > 0
    arp_rate = p["arp"]["rate"]
    arp_mult = [_pow2(st / 12) for st in arp_steps]
    arp_n = len(arp_mult)
    # PWM only touches the square wave and only when depth != 0 (else duty, unclamped).
    pwm_depth, pwm_w = p["pwm"]["depth"], two_pi * p["pwm"]["rate"]
    pwm_on = wave_id == 1 and pwm_depth != 0.0
    fm_i0, fm_i1, fm_ratio = fm["index"], fm["indexEnd"], fm["ratio"]
    fm_on = wave_id < 4 and not (fm_i0 == 0.0 and fm_i1 == 0.0)  # noise/crackle ignore FM
    breath = p["breath"]
    breath_on = breath["level"] != 0.0
    # PRNG: noise / crackle / pluck excitation, and breath (which draws AFTER the oscillator's own draws)
    rand = mulberry32(p["seed"]) if 4 <= wave_id <= 6 or breath_on else None
    # Karplus-Strong string: the delay line length and the excitation are fixed per voice (the
    # string is NOT retuned by sweep / glide / arp / vibrato). Excitation: seeded noise run through
    # a one-pole lowpass whose `bright` coefficient goes from dull (0) to raw noise (1).
    if wave_id == 6:
        pl = p["pluck"]
        pl_decay, pl_damp, pl_bright = pl["decay"], pl["damping"], pl["bright"]
        pl_omd = 1 - pl_damp
        pl_len = max(2, floor(sr / freq + 0.5)) if freq > 0 else 2
        pl_buf = []
        pl_lp = 0.0
        for _ in range(pl_len):
            e = rand() * 2 - 1
            pl_lp = pl_lp + pl_bright * (e - pl_lp)
            pl_buf.append(pl_lp)
        pl_r = 0
        pl_last = 0.0
    # Sampler: nearest-root zone chosen once per voice from osc.freq; read position advances per
    # sample by (pitched ? f / rootF : 1) * srS / sr with the per-sample f (sweep / glide / arp / vibrato).
    if wave_id == 8:
        zones = p["sampler"]["zones"]
        if not zones:
            raise SoundError("wave \"sample\" needs sampler.zones, e.g. [[60, \"cellos_A3.wav\"]]")
        zone_root, zone_file = pick_zone(zones, freq)
        smp_rate, smp_data = load_sample(zone_file)
        smp_n = len(smp_data)
        smp_root_f = 440 * _pow2((zone_root - 69) / 12)
        smp_step = smp_rate / sr
        smp_pitched = p["sampler"]["pitched"]
        smp_pos = 0.0
    # Breath: fixed RBJ bandpass (effect-4 formula) with its own state, fed by rand() * 2 - 1.
    if breath_on:
        br_level = breath["level"]
        br_fc = min(max(breath["band"], 10), 0.49 * sr)
        br_w0 = two_pi * br_fc / sr
        br_alpha = sin(br_w0) / (2 * max(breath["q"], 0.1))
        br_a0 = 1 + br_alpha
        br_n0, br_n2 = br_alpha / br_a0, -br_alpha / br_a0
        br_d1, br_d2 = -2 * cos(br_w0) / br_a0, (1 - br_alpha) / br_a0
        br_x1 = br_x2 = br_y1 = br_y2 = 0.0
    # Additive: own phase per partial, optional per-partial exponential decay, normalised by sum |amp|.
    if wave_id == 7:
        add_h = p["additive"]["harmonics"]
        add_decay = p["additive"]["decay"]
        add_norm = 0.0
        for _, amp in add_h:
            add_norm = add_norm + abs(amp)
        add_ph = [0.0] * len(add_h)
    # Unison: V stacked detuned copies of tonal waves (noise/crackle ignore it). The fast path
    # below is untouched when V == 1. Voice k starts at phase k / V; multipliers are constant.
    uni_n = unison_voice_count(uni["voices"])
    uni_on = uni_n > 1 and wave_id < 4
    if uni_on:
        uni_mult = unison_multipliers(uni_n, uni["detune"])
        uni_ph = [k / uni_n for k in range(uni_n)]
    # Sub-oscillator: own phase, no FM, mixed into v before the envelope (all waves, noise too).
    sub_on = sub["level"] != 0.0
    sub_level, sub_wave = sub["level"], SUB_WAVES.index(sub["wave"])  # 0 sine 1 square 2 triangle
    sub_mult = _pow2(sub["octave"]) if sub_on else 1.0
    sph = 0.0
    # Drive (effect 0) and wobble: both skipped entirely when off.
    drive = p["drive"]
    drive_on = drive > 0
    drive_norm = math.tanh(drive) if drive_on else 1.0
    wob_depth, wob_w = wob["depth"], two_pi * wob["rate"]
    wob_on = wob_depth != 0.0

    # --- envelope ---------------------------------------------------------------
    a, d, s, r = env["a"], env["d"], env["s"], env["r"]
    a_plus_d = a + d

    def adsr(t):
        if a > 0 and t < a:
            return t / a
        if d > 0 and t < a_plus_d:
            return 1 - (1 - s) * (t - a) / d
        return s

    release_level = adsr(duration)

    # --- effects ------------------------------------------------------------------
    bits, hold = crush["bits"], crush["hold"]
    crush_on = bits < 16
    q = 2.0 ** (bits - 1) if crush_on else 1.0
    hold_on = hold > 1
    hold_int = int(hold) if hold == int(hold) else 0  # 0 -> non-integer, use fmod
    lp0, lp1 = flt["lowpass"], flt["lowpassEnd"]
    lp_on = not (lp0 >= 20000 and lp1 >= 20000)
    lp_const = lp0 == lp1
    lp_linear = lp0 <= 0 or lp1 <= 0
    lp_ratio = 1.0 if lp_linear else lp1 / lp0
    nyq = sr / 2

    def lp_alpha(c):
        try:
            return 1 - exp(-two_pi * min(c, nyq) / sr)
        except OverflowError:  # only reachable with a negative cutoff (invalid input)
            return -math.inf

    alpha_const = lp_alpha(lp0) if lp_on and lp_const and not wob_on else 0.0
    hp_on = flt["highpass"] > 0
    beta = 1 - exp(-two_pi * flt["highpass"] / sr) if hp_on else 0.0
    # Resonant bandpass (RBJ biquad, constant 0 dB peak). Coefficients are computed per
    # sample only when the centre frequency sweeps; otherwise once (same formula).
    band0, band1 = flt["band"], flt["bandEnd"]
    band_on = band0 > 0
    band_lin = band1 <= 0
    band_ratio = 1.0 if band_lin else band1 / band0
    band_q = max(flt["q"], 0.1)

    def band_coef(fc):
        fc = min(max(fc, 10), 0.49 * sr)
        w0 = two_pi * fc / sr
        alpha = sin(w0) / (2 * band_q)
        a0 = 1 + alpha
        return alpha / a0, -alpha / a0, -2 * cos(w0) / a0, (1 - alpha) / a0

    band_fixed = band_on and band0 == band1 and not wob_on  # wobble moves fc every sample
    bn0, bn2, bd1c, bd2c = band_coef(band0) if band_fixed else (0.0, 0.0, 0.0, 0.0)
    bx1 = bx2 = by1 = by2 = 0.0
    # Formant (4a): 3 parallel bandpasses from the vowel table, linear morph over p. When the vowel
    # does not morph the centre frequencies are constant, so the coefficients are computed once.
    fmt = p["formant"]
    fmt_on = fmt["vowel"] is not None
    if fmt_on:
        f_start, g_start = VOWELS[fmt["vowel"]]
        f_end, g_end = VOWELS[fmt["vowelEnd"] or fmt["vowel"]]
        fmt_morph = fmt["vowelEnd"] is not None and fmt["vowelEnd"] != fmt["vowel"]
        fmt_q = max(fmt["q"], 0.1)
        fmt_mix = fmt["mix"]

        def fmt_coef(fc):
            # same bandpass as effect 4 with the formant Q (centre frequency clamped identically)
            fc = min(max(fc, 10), 0.49 * sr)
            w0 = two_pi * fc / sr
            alpha = sin(w0) / (2 * fmt_q)
            a0 = 1 + alpha
            return alpha / a0, -alpha / a0, -2 * cos(w0) / a0, (1 - alpha) / a0

        fmt_fixed = [fmt_coef(fc) for fc in f_start]
        fmt_state = [[0.0, 0.0, 0.0, 0.0] for _ in range(3)]  # x1 x2 y1 y2 per bandpass
    # EQ shelves (4b): coefficients are constant, so computed once; each stage owns its state.
    eq_st = eq_stages(p["eq"])
    eq_state = [[0.0, 0.0, 0.0, 0.0] for _ in eq_st]  # x1 x2 y1 y2 per stage
    echo_on = echo["mix"] > 0 and echo["time"] > 0
    echo_mix = echo["mix"]
    echo_fb = min(echo["feedback"], 0.95)
    echo_d = max(1, floor(echo["time"] * sr + 0.5)) if echo_on else 0
    w = [0.0] * n if echo_on else None

    phase = mphase = nph = nval = lp = hp_low = held = 0.0
    inf = math.inf

    try:
        for i in range(n):
            t = i / sr
            if duration > 0:
                p_ = t / duration
                if p_ > 1.0:
                    p_ = 1.0
            else:
                p_ = 1.0

            # pitch
            if const_f:
                f = freq
            elif linear:
                f = freq + (freq_end - freq) * p_
            else:
                f = freq * ratio ** p_
            if glide_on and t < glide_t:
                f = f * glide_ratio ** (1 - t / glide_t)
            if arp_on:
                f = f * arp_mult[int(t * arp_rate) % arp_n if arp_rate > 0 else 0]
            if vib_on:
                if vib_delay > 0:
                    f = f * (1 + vib_depth * (t / vib_delay if t < vib_delay else 1) * sin(vib_w * t))
                else:
                    f = f * (1 + vib_depth * sin(vib_w * t))

            # oscillator value from current phases, then advance
            if wave_id == 4:
                v = nval
                nph += f * 2 / sr
                if nph >= 1:
                    nph -= floor(nph)
                    nval = rand() * 2 - 1
            elif wave_id == 5:
                # crackle: f is a density (hits/s); the 2nd draw happens only on a hit
                v = 0.0
                if rand() < f / sr:
                    v = rand() * 2 - 1
            elif wave_id == 6:
                v = pl_buf[pl_r]
                pl_buf[pl_r] = pl_decay * (pl_omd * v + pl_damp * pl_last)
                pl_last = v
                pl_r += 1
                if pl_r == pl_len:
                    pl_r = 0
            elif wave_id == 8:
                j0 = floor(smp_pos)
                fr = smp_pos - j0
                a_s = smp_data[j0] if 0 <= j0 < smp_n else 0.0
                b_s = smp_data[j0 + 1] if 0 <= j0 + 1 < smp_n else 0.0
                v = a_s + (b_s - a_s) * fr
                smp_pos = smp_pos + (f / smp_root_f if smp_pitched else 1) * smp_step
            elif wave_id == 7:
                v = 0.0
                for kk, (ratio_k, amp_k) in enumerate(add_h):
                    a_k = amp_k
                    if add_decay > 0:
                        a_k = amp_k * exp(-t * add_decay * max(0, ratio_k - 1))
                    v = v + a_k * sin(two_pi * add_ph[kk])
                    add_ph[kk] = (add_ph[kk] + f * ratio_k / sr) % 1.0
                v = v / add_norm if add_norm != 0 else 0.0
            elif uni_on:
                # V detuned voices sharing one FM term and this sample's PWM duty, summed in
                # voice order then divided by V (format.md).
                if fm_on:
                    idx = fm_i0 + (fm_i1 - fm_i0) * p_
                    fm_term = idx * sin(two_pi * mphase) / two_pi
                    mphase = (mphase + f * fm_ratio / sr) % 1.0
                if wave_id == 1:
                    if pwm_on:
                        dd = duty + pwm_depth * sin(pwm_w * t)
                        dd = min(max(dd, 0.01), 0.99)
                    else:
                        dd = duty
                v = 0.0
                for kk in range(uni_n):
                    pk = uni_ph[kk]
                    ph = (pk + fm_term) % 1.0 if fm_on else pk
                    if wave_id == 0:
                        v = v + sin(two_pi * ph)
                    elif wave_id == 1:
                        v = v + (1.0 if ph < dd else -1.0)
                    elif wave_id == 2:
                        v = v + (2 * ph - 1)
                    else:
                        v = v + (1 - 4 * abs(ph - 0.5))
                    uni_ph[kk] = (pk + f * uni_mult[kk] / sr) % 1.0
                v = v / uni_n
            else:
                if fm_on:
                    idx = fm_i0 + (fm_i1 - fm_i0) * p_
                    ph = (phase + idx * sin(two_pi * mphase) / two_pi) % 1.0
                    mphase = (mphase + f * fm_ratio / sr) % 1.0
                else:
                    ph = phase
                if wave_id == 0:
                    v = sin(two_pi * ph)
                elif wave_id == 1:
                    if pwm_on:
                        dd = duty + pwm_depth * sin(pwm_w * t)
                        dd = min(max(dd, 0.01), 0.99)
                        v = 1.0 if ph < dd else -1.0
                    else:
                        v = 1.0 if ph < duty else -1.0
                elif wave_id == 2:
                    v = 2 * ph - 1
                else:
                    v = 1 - 4 * abs(ph - 0.5)
                phase = (phase + f / sr) % 1.0

            if sub_on:
                if sub_wave == 0:
                    sv = sin(two_pi * sph)
                elif sub_wave == 1:
                    sv = 1.0 if sph < 0.5 else -1.0
                else:
                    sv = 1 - 4 * abs(sph - 0.5)
                v = v + sub_level * sv
                sph = (sph + f * sub_mult / sr) % 1.0

            if breath_on:
                nb = rand() * 2 - 1
                yb = br_n0 * nb + br_n2 * br_x2 - br_d1 * br_y1 - br_d2 * br_y2
                br_x2 = br_x1
                br_x1 = nb
                br_y2 = br_y1
                br_y1 = yb
                v = v + br_level * yb

            # envelope (gate = duration)
            if t < duration:
                if a > 0 and t < a:
                    e = t / a
                elif d > 0 and t < a_plus_d:
                    e = 1 - (1 - s) * (t - a) / d
                else:
                    e = s
            elif r <= 0:
                e = 0.0
            else:
                e = release_level * (1 - (t - duration) / r)
                if e < 0:  # max(0, .) -- NaN deliberately passes through like JS
                    e = 0.0
            x = v * e

            # 0. drive: tanh soft saturation normalised so +-1 maps to +-1
            if drive_on:
                x = math.tanh(drive * x) / drive_norm
            # 1. crush: quantize first, then hold. Non-finite values pass through
            #    unchanged (JS Math.floor(NaN) is NaN; Python's floor would raise).
            if crush_on and x - x == 0.0:
                x = floor(x * q + 0.5) / q
            if hold_on:
                if (i % hold_int == 0) if hold_int else (math.fmod(i, hold) == 0.0):
                    held = x
                else:
                    x = held
            # 2. one-pole lowpass (cutoff sweeps with p)
            if wob_on:
                m = _pow2(wob_depth * sin(wob_w * t))  # filter LFO multiplier, in octaves
            if lp_on:
                if wob_on:
                    # c = sweep(p) * m; the constant case is lp0 (lp0 * 1.0**p == lp0 exactly)
                    if lp_const:
                        c = lp0
                    elif lp_linear:
                        c = lp0 + (lp1 - lp0) * p_
                    else:
                        c = lp0 * lp_ratio ** p_
                    alpha = lp_alpha(c * m)
                elif lp_const:
                    alpha = alpha_const
                elif lp_linear:
                    alpha = lp_alpha(lp0 + (lp1 - lp0) * p_)
                else:
                    alpha = lp_alpha(lp0 * lp_ratio ** p_)
                lp += alpha * (x - lp)
                x = lp
            # 3. one-pole highpass
            if hp_on:
                hp_low += beta * (x - hp_low)
                x = x - hp_low
            # 4. resonant bandpass, direct form I (evaluation order as in format.md)
            if band_on:
                if band_fixed:
                    n0, n2, d1, d2 = bn0, bn2, bd1c, bd2c
                else:
                    # fc = sweep(p) [* m with wobble], then clamped inside band_coef
                    fc = band0 + (band1 - band0) * p_ if band_lin else band0 * band_ratio ** p_
                    n0, n2, d1, d2 = band_coef(fc * m if wob_on else fc)
                y = n0 * x + n2 * bx2 - d1 * by1 - d2 * by2
                bx2 = bx1
                bx1 = x
                by2 = by1
                by1 = y
                x = y
            # 4a. formant: three parallel bandpasses, sum g1*y1 + g2*y2 + g3*y3, then dry/wet mix
            if fmt_on:
                acc = 0.0
                for ki in range(3):
                    if fmt_morph:
                        fk = f_start[ki] + (f_end[ki] - f_start[ki]) * p_
                        gk = g_start[ki] + (g_end[ki] - g_start[ki]) * p_
                        fn0, fn2, fd1, fd2 = fmt_coef(fk)
                    else:
                        gk = g_start[ki]
                        fn0, fn2, fd1, fd2 = fmt_fixed[ki]
                    st = fmt_state[ki]
                    yk = fn0 * x + fn2 * st[1] - fd1 * st[2] - fd2 * st[3]
                    st[1] = st[0]
                    st[0] = x
                    st[3] = st[2]
                    st[2] = yk
                    acc = yk * gk if ki == 0 else acc + gk * yk
                x = x * (1 - fmt_mix) + fmt_mix * acc
            # 4b. EQ shelves: low then high, direct form I, each with its own state
            for st, (en0, en1, en2, ed1, ed2) in zip(eq_state, eq_st):
                y = en0 * x + en1 * st[0] + en2 * st[1] - ed1 * st[2] - ed2 * st[3]
                st[1] = st[0]
                st[0] = x
                st[3] = st[2]
                st[2] = y
                x = y
            # 5. echo (delay line holds the pre-mix signal plus feedback)
            if echo_on:
                delayed = w[i - echo_d] if i >= echo_d else 0.0
                w[i] = x + echo_fb * delayed
                x = x + echo_mix * delayed
            # 6. gain, non-finite -> 0, clip
            x = x * gain
            if x - x != 0.0:
                x = 0.0
            elif x > 1.0:
                x = 1.0
            elif x < -1.0:
                x = -1.0
            out[i] = x
    except (OverflowError, ValueError, ZeroDivisionError) as exc:
        # Only absurd parameters (e.g. frequency ~1e308) can get here.
        raise SoundError("numeric overflow while rendering patch (%s); check parameters" % exc) from None
    return out


# --------------------------------------------------------------------------
# expr / bytebeat
# --------------------------------------------------------------------------

def _spec_number(spec, key, default):
    v = spec.get(key)
    return default if v is None else _num(v, key)


def render_expr(spec):
    """Mode `expr`: x = expr(t, i, sr) * gain with t = i / sr."""
    sr = float(SR)
    gain = _spec_number(spec, "gain", DEFAULT_PATCH["gain"])
    duration = _spec_number(spec, "duration", 2.0)  # format.md: expr default 2 s
    fn = compile_expr(spec.get("expr"), _spec_number(spec, "seed", 1.0))
    n = _check_length(ceil(duration * sr), "expr sound")
    out = [0.0] * n
    for i in range(n):
        x = fn(i / sr, float(i), sr) * gain
        if x - x != 0.0:
            x = 0.0
        elif x > 1.0:
            x = 1.0
        elif x < -1.0:
            x = -1.0
        out[i] = x
    return SR, out


def render_bytebeat(spec):
    """Mode `bytebeat`: b = toInt32(expr) & 255, x = (b - 128) / 128 * gain, t = i."""
    rate = _spec_number(spec, "rate", 8000.0)
    if rate <= 0:
        raise SoundError("rate must be > 0")
    gain = _spec_number(spec, "gain", DEFAULT_PATCH["gain"])
    duration = _spec_number(spec, "duration", 10.0)  # format.md: bytebeat default 10 s
    fn = compile_expr(spec.get("expr"), _spec_number(spec, "seed", 1.0))
    n = _check_length(ceil(duration * rate), "bytebeat sound")
    out = [0.0] * n
    for i in range(n):
        fi = float(i)
        # A non-finite result gives toInt32 == 0 -> b = 0 -> x = -gain (JS semantics).
        b = to_int32(fn(fi, fi, rate)) & 255
        x = (b - 128) / 128 * gain
        if x - x != 0.0:
            x = 0.0
        elif x > 1.0:
            x = 1.0
        elif x < -1.0:
            x = -1.0
        out[i] = x
    return int(rate) if rate == int(rate) else rate, out


# --------------------------------------------------------------------------
# Sound references (preset name / object with "preset") and mode `layers`
# --------------------------------------------------------------------------

def resolve_sound(sound, presets):
    """Return the raw sound object for a preset name or an object with "preset".

    A string is a preset name; an object with `"preset": "name"` is deep-merged over
    that preset. Any other object is returned as is. The result is a fresh dict that
    may be of any mode (callers check the mode they can accept).
    """
    if sound is None:
        return {}
    if isinstance(sound, str):
        if sound not in presets:
            raise SoundError("unknown preset %r" % sound)
        return copy.deepcopy(presets[sound])
    if not isinstance(sound, dict):
        raise SoundError("a sound must be a preset name or an object, got %r" % (sound,))
    name = sound.get("preset")
    if isinstance(name, str):
        if name not in presets:
            raise SoundError("unknown preset %r" % name)
        return deep_merge(presets[name], {k: v for k, v in sound.items() if k != "preset"})
    return copy.deepcopy(sound)


# Patch fields scaled by the layer pitch factor `kp` (format.md "Mode layers").
_PITCH_FIELDS = (("osc", "freq"), ("osc", "freqEnd"), ("filter", "lowpass"), ("filter", "lowpassEnd"),
                 ("filter", "highpass"), ("filter", "band"), ("filter", "bandEnd"))


def layers_defaults(spec):
    """Top-level defaults of a layers spec (layer entries are left untouched)."""
    vary = spec.get("vary") if isinstance(spec.get("vary"), dict) else {}
    return {"mode": "layers", "name": str(spec.get("name") or ""),
            "seed": 1 if spec.get("seed") is None else spec["seed"],
            "gain": 0.9 if spec.get("gain") is None else spec["gain"],
            "vary": {k: (0 if vary.get(k) is None else vary[k]) for k in ("pitch", "volume", "time")},
            "layers": spec.get("layers") if spec.get("layers") is not None else []}


def render_layers(spec, presets, depth=0):
    """Mode `layers`: stack of sounds with seeded pitch/volume/time variation."""
    if depth > MAX_LAYER_DEPTH:
        raise SoundError("layers nested too deep (max %d)" % MAX_LAYER_DEPTH)
    seed = _spec_number(spec, "seed", 1.0)
    gain = _spec_number(spec, "gain", 0.9)
    vary = spec.get("vary")
    if vary is None:
        vary = {}
    if not isinstance(vary, dict):
        raise SoundError("vary must be an object")
    v_pitch = _spec_number(vary, "pitch", 0.0)
    v_volume = _spec_number(vary, "volume", 0.0)
    v_time = _spec_number(vary, "time", 0.0)
    layers = spec.get("layers")
    if layers is None:
        layers = []
    if not isinstance(layers, list):
        raise SoundError("layers must be a list")
    eq = resolve_eq(spec.get("eq"), "eq")  # master eq on the summed mix
    import sg_space  # lazy: sg_space imports this module
    space = sg_space.resolve_space(spec.get("space"))  # master space effects, after eq
    any_pos = False  # stereo-iff: any entry with `pos`
    drive = _spec_number(spec, "drive", 0.0)  # master drive, after space

    vr = mulberry32(seed)
    seed_offset = 1000 * (seed - 1)  # seed 1 keeps the preset seeds untouched
    parts = []  # (start_index, left_or_mono, right_or_None, volume, pan)
    for li, layer in enumerate(layers):
        if not isinstance(layer, dict):
            raise SoundError("layer %d must be an object" % li)
        # Always three draws per layer, in this order, so variants stay aligned.
        kp = 1 + v_pitch * (2 * vr() - 1)
        kv = 1 + v_volume * (2 * vr() - 1)
        dt = v_time * vr()
        snd = resolve_sound(layer.get("sound"), presets)
        mode = snd.get("mode") or "patch"
        right = None  # only a nested stereo layers/song sound has a right channel
        if mode == "patch":
            p = resolve_patch(snd)
            for sec, key in _PITCH_FIELDS:
                p[sec][key] *= kp
            p["seed"] = p["seed"] + seed_offset
            samples = render_patch(p)
        elif mode == "layers":
            snd["seed"] = _spec_number(snd, "seed", 1.0) + seed_offset
            sub = render_layers(snd, presets, depth + 1)
            samples, right = sub[1], sub.right
        elif mode == "expr":
            samples = render_expr(snd)[1]  # kp ignored, keeps its own seed
        elif mode == "song":
            import sg_song  # lazy: sg_song imports this module
            sub = sg_song.render_song(snd, presets)
            samples, right = sub[1], sub.right
        else:
            raise SoundError("layer %d: sound mode %r cannot be used in layers" % (li, mode))
        at = _spec_number(layer, "at", 0.0)
        volume = _spec_number(layer, "volume", 1.0)
        pan = clamp_pan(_spec_number(layer, "pan", 0.0))
        start = floor((at + dt) * SR + 0.5)
        pos = sg_space.resolve_pos(layer.get("pos"), "layer %d pos" % li)
        if pos is not None:
            # 3D placement overrides pan; a stereo sub-sound enters as (L + R) / 2
            any_pos = True
            out_l, out_r = sg_space.place(sg_space.mono_of(samples, right), start, pos)
            parts.append((start, out_l, out_r, volume * kv, 0.0))
        else:
            parts.append((start, samples, right, volume * kv, pan))
    return mix_any(parts, gain, stereo=any_pos, eq=eq, space=space, drive=drive)


def clamp_pan(pan):
    """`pan` clamped to [-1, 1] (format.md "Stereo")."""
    return max(-1.0, min(1.0, pan))


def pan_gains(pan):
    """Balance law: pan 0 -> (1, 1), so a centred mono part is unchanged; -1 = full left."""
    pan = clamp_pan(pan)
    return min(1.0, 1.0 - pan), min(1.0, 1.0 + pan)


def mix_any(parts, gain, stereo=False, eq=None, space=None, automation=None, drive=0.0):
    """Mix (start, left, right_or_None, volume, pan[, duck_gains]) parts into a Rendered result.

    Stereo-iff rule (format.md): the result is stereo when any track/entry has pan != 0
    (after clamping) or any part is itself stereo; otherwise it is mono and goes through
    the unchanged mono mixer, so mono output stays bit-identical to the pre-stereo engine.
    `stereo=True` is for callers whose pan sources are not all visible as parts (a song
    track with pan but no voices, e.g. only rests, or `mute`) -- the rule is about tracks.
    The optional 6th part field is a per-sample sidechain gain list (None = no duck).

    Master chain (format.md): sum -> eq -> automation.lowpass -> space -> drive -> gain/clip.
    """
    stereo = stereo or (space is not None and space["active"])  # an active space makes it stereo
    if not stereo and all(p[2] is None and p[4] == 0 for p in parts):
        mono = [(p[0], p[1], p[3], p[5] if len(p) > 5 else None) for p in parts]
        return Rendered(SR, mix_parts(mono, gain, eq, automation, drive))
    left, right = mix_stereo(parts, gain, eq, space, automation, drive)
    return Rendered(SR, left, right)


def _finish_channel(mix, gain):
    """Apply gain, non-finite -> 0 and clip, in place."""
    for k, x in enumerate(mix):
        x = x * gain
        if x - x != 0.0:
            x = 0.0
        elif x > 1.0:
            x = 1.0
        elif x < -1.0:
            x = -1.0
        mix[k] = x
    return mix


def apply_master_drive(channel, drive):
    """Master drive (after space, before gain): x = tanh(drive*x) / tanh(drive) when drive > 0."""
    if drive > 0:
        norm = math.tanh(drive)
        tanh = math.tanh
        for k, x in enumerate(channel):
            channel[k] = tanh(drive * x) / norm
    return channel


def resolve_automation(raw, bpm):
    """Master `automation` -> {"points": [(beat, hz)...], "beat": 60/bpm} or None when it does nothing.

    Only `lowpass` exists: a list of [beat, hz] points sorted by beat with hz > 0.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SoundError("automation must be an object like {\"lowpass\": [[0, 400], [8, 12000]]}")
    pts = raw.get("lowpass")
    if pts is None:
        return None
    if not isinstance(pts, list):
        raise SoundError("automation.lowpass must be a list of [beat, hz] points")
    points = []
    for i, pt in enumerate(pts):
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            raise SoundError("automation.lowpass[%d] must be a [beat, hz] pair" % i)
        beat = _num(pt[0], "automation.lowpass[%d] beat" % i)
        hz = _num(pt[1], "automation.lowpass[%d] hz" % i)
        if hz <= 0:
            raise SoundError("automation.lowpass[%d] hz must be > 0, got %r" % (i, hz))
        if points and beat < points[-1][0]:
            raise SoundError("automation.lowpass points must be sorted by beat (point %d goes backwards)" % i)
        points.append((beat, hz))
    if not points:
        return None
    return {"points": points, "beat": 60 / bpm}


def _automation_alphas(auto, n):
    """One-pole coefficient per mix sample for the lowpass automation (shared by both channels).

    b = n / (beat * sr); before the first point the first hz, after the last the last hz,
    between two points hz0 * (hz1/hz0) ** ((b - b0) / (b1 - b0)).
    """
    points = auto["points"]
    beat_sr = auto["beat"] * SR
    two_pi = 2 * pi
    nyq = SR / 2

    def alpha(fc):
        return 1 - exp(-two_pi * min(fc, nyq) / SR)

    a_first, a_last = alpha(points[0][1]), alpha(points[-1][1])
    b_first, b_last = points[0][0], points[-1][0]
    out = [0.0] * n
    seg = 0  # segment index: points[seg] .. points[seg + 1]
    for i in range(n):
        b = i / beat_sr
        if b <= b_first:
            out[i] = a_first
        elif b >= b_last:
            out[i] = a_last
        else:
            while b >= points[seg + 1][0]:
                seg += 1
            b0, hz0 = points[seg]
            b1, hz1 = points[seg + 1]
            out[i] = alpha(hz0 * (hz1 / hz0) ** ((b - b0) / (b1 - b0)))
    return out


def apply_automation(channels, auto):
    """Two cascaded one-pole lowpasses per channel with the automated cutoff (in place)."""
    if auto is None:
        return
    alphas = _automation_alphas(auto, len(channels[0]))
    for ch in channels:
        s1 = s2 = 0.0
        for k, (x, a) in enumerate(zip(ch, alphas)):
            s1 += a * (x - s1)
            s2 += a * (s1 - s2)
            ch[k] = s2


def duck_gains(start, length, triggers, amount, release):
    """Per-sample sidechain gain for a part occupying mix samples start .. start + length - 1.

    `triggers` is the sorted list of trigger start samples. With tk the latest trigger <= n:
    g = 1 - amount * max(0, 1 - (n - tk) / (release * sr)); g = 1 before the first trigger or
    when release <= 0. Returns None when the gain is 1 over the whole range.
    """
    if release <= 0 or not triggers or amount == 0:
        return None
    from bisect import bisect_right
    span = release * SR
    end = start + length
    gains = None
    # triggers that can affect [start, end): the latest one <= start, then any inside the range
    i = bisect_right(triggers, start) - 1
    if i < 0:
        i = 0
    while i < len(triggers):
        tk = triggers[i]
        if tk >= end:
            break
        nxt = triggers[i + 1] if i + 1 < len(triggers) else end
        lo, hi = max(tk, start), min(nxt, end)
        for n in range(lo, hi):
            w = 1 - (n - tk) / span
            if w <= 0:  # max(0, .) -> g == 1 for the rest of this trigger's stretch
                break
            if gains is None:
                gains = [1.0] * length
            gains[n - start] = 1 - amount * w
        i += 1
    return gains


def mix_parts(parts, gain, eq=None, automation=None, drive=0.0):
    """Sum (start, samples, volume[, duck_gains]) parts, apply the master chain, gain and clip.

    A negative start drops the samples before index 0 (JS ignores writes to negative
    typed-array indexes), but still counts toward the length like `start + len`.
    Ducked parts are mixed as `s * vol * g(n)`.
    """
    total = max((p[0] + len(p[1]) for p in parts), default=0)
    total = _check_length(total, "mix")
    mix = [0.0] * total
    for part in parts:
        start, smp, vol = part[0], part[1], part[2]
        gains = part[3] if len(part) > 3 else None
        if start < 0:
            smp = smp[-start:]
            if gains is not None:
                gains = gains[-start:]
            start = 0
        if gains is None:
            for k, v in enumerate(smp, start):
                mix[k] += v * vol
        else:
            for k, (v, g) in enumerate(zip(smp, gains), start):
                mix[k] += v * vol * g
    if eq is not None:
        apply_master_eq(mix, eq)  # on the summed mix, BEFORE gain
    apply_automation([mix], automation)
    apply_master_drive(mix, drive)
    return _finish_channel(mix, gain)


def mix_stereo(parts, gain, eq=None, space=None, automation=None, drive=0.0):
    """Stereo mix of (start, left_or_mono, right_or_None, volume, pan[, duck_gains]) parts.

    Each part adds `left * vol * gL` to L and `(right or left) * vol * gR` to R: a mono part
    (right is None) feeds both sides from the same samples; a ducked part multiplies by g(n)
    last (`s * vol * gSide * g`). Length = max part end, then the master chain
    (eq -> automation -> space -> drive), gain / non-finite -> 0 / clip per channel.
    Same negative-start rule as mix_parts.
    """
    total = max((p[0] + len(p[1]) for p in parts), default=0)
    total = _check_length(total, "mix")
    out_l = [0.0] * total
    out_r = [0.0] * total
    for part in parts:
        start, left, right, vol, pan = part[:5]
        gains = part[5] if len(part) > 5 else None
        g_l, g_r = pan_gains(pan)
        if right is None:
            right = left
        if start < 0:
            left, right = left[-start:], right[-start:]
            if gains is not None:
                gains = gains[-start:]
            start = 0
        if gains is None:
            for k, v in enumerate(left, start):
                out_l[k] += v * vol * g_l
            for k, v in enumerate(right, start):
                out_r[k] += v * vol * g_r
        else:
            for k, (v, g) in enumerate(zip(left, gains), start):
                out_l[k] += v * vol * g_l * g
            for k, (v, g) in enumerate(zip(right, gains), start):
                out_r[k] += v * vol * g_r * g
    if eq is not None:  # separate filter state per channel, left first
        apply_master_eq(out_l, eq)
        apply_master_eq(out_r, eq)
    apply_automation([out_l, out_r], automation)
    if space is not None and space["active"]:  # after eq/automation, before drive and gain
        import sg_space  # lazy: sg_space imports this module
        out_l, out_r = sg_space.apply_space(out_l, out_r, space, lambda n: _check_length(n, "space"))
    apply_master_drive(out_l, drive)
    apply_master_drive(out_r, drive)
    return _finish_channel(out_l, gain), _finish_channel(out_r, gain)


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------

def render_sound(spec, presets=None):
    """Render a spec dict; returns a Rendered: (sample_rate, samples) plus `.right`.

    `samples` is mono, or the left channel when `.right` is not None (stereo song/layers).
    """
    if not isinstance(spec, dict):
        raise SoundError("sound spec must be a JSON object")
    if presets is None:
        presets = load_presets()
    mode = spec.get("mode") or "patch"
    if mode == "patch":
        return Rendered(SR, render_patch(resolve_patch(spec)))
    if mode == "expr":
        return Rendered(*render_expr(spec))
    if mode == "bytebeat":
        return Rendered(*render_bytebeat(spec))
    if mode == "song":
        import sg_song  # lazy: sg_song imports this module
        return sg_song.render_song(spec, presets)
    if mode == "layers":
        return render_layers(spec, presets)
    if mode == "kit":
        raise SoundError("a kit is only valid as a song instrument (use it as the instrument of a song track)")
    raise SoundError("unknown mode %r (expected patch, expr, bytebeat, song or layers)" % (mode,))
