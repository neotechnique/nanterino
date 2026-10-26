"""Output post-processing for rendered sounds (pure functions on lists of floats).

Invariant: this module runs AFTER the engines have rendered. It never feeds back
into synthesis, so the Python/JS engine parity contract (docs/format.md) is
unaffected. With no option set, `process` returns the input samples untouched,
which keeps default WAV output byte-identical.

Stereo: every step treats the two channels identically so the image never shifts.
trim cuts both channels at the same indexes (silent = max(|L|,|R|) < threshold),
normalize uses the JOINT peak and one gain, fades and resample run per channel.

Fixed order: trim -> normalize -> fades -> resample.
  - trim first so silence does not affect the peak or the fade positions;
  - normalize before fades (fades only lower the level, never the peak target);
  - resample last so fade lengths and trim are expressed at the source rate.
"""

import math

# Samples below this absolute value count as silence for --trim (about -80 dBFS).
TRIM_THRESHOLD = 1e-4


def trim(samples, threshold=TRIM_THRESHOLD):
    """Drop leading/trailing samples with abs < threshold; always keeps >= 1 sample."""
    n = len(samples)
    if n == 0:
        return list(samples)
    start = 0
    while start < n and abs(samples[start]) < threshold:
        start += 1
    if start == n:  # all silent: keep a single sample so the file stays valid
        return [samples[0]]
    end = n
    while end > start and abs(samples[end - 1]) < threshold:
        end -= 1
    return list(samples[start:end])


def peak(samples):
    """Largest absolute sample value (0.0 for an empty list)."""
    return max((abs(x) for x in samples), default=0.0)


def normalize(samples, target_db):
    """Scale so the peak equals target_db dBFS. Silent input stays silent (no divide by 0)."""
    p = peak(samples)
    if p <= 0.0:
        return list(samples)
    gain = (10.0 ** (target_db / 20.0)) / p
    return [x * gain for x in samples]


def fade_in(samples, seconds, rate):
    """Linear ramp 0 -> 1 over `seconds`; the first sample becomes exactly 0."""
    n = min(len(samples), int(round(seconds * rate)))
    if n <= 0:
        return list(samples)
    out = list(samples)
    for i in range(n):
        out[i] *= i / n
    return out


def fade_out(samples, seconds, rate):
    """Linear ramp 1 -> 0 over `seconds`; the last sample becomes exactly 0."""
    n = min(len(samples), int(round(seconds * rate)))
    if n <= 0:
        return list(samples)
    out = list(samples)
    last = len(out) - 1
    for i in range(len(out) - n, len(out)):
        out[i] *= (last - i) / n
    return out


def resample(samples, rate, new_rate):
    """Linear-interpolation resampler (no anti-alias filter).

    Adequate for game assets; when downsampling, content above new_rate/2 can
    alias, which is rarely audible for these synthesized effects.
    """
    if new_rate == rate or not samples:
        return list(samples)
    n = len(samples)
    out_len = max(1, int(round(n * new_rate / rate)))
    step = rate / new_rate
    out = []
    append = out.append
    for j in range(out_len):
        pos = j * step
        i = int(pos)
        if i >= n - 1:
            append(samples[-1])
        else:
            frac = pos - i
            append(samples[i] + (samples[i + 1] - samples[i]) * frac)
    return out


def trim_channels(chans, threshold=TRIM_THRESHOLD):
    """trim() for 1 or 2 equal-length channels: same cut for all, silence = max(|L|,|R|) < threshold."""
    if len(chans) == 1:
        return [trim(chans[0], threshold)]
    n = len(chans[0])
    if n == 0:
        return [list(c) for c in chans]
    start = 0
    while start < n and all(abs(c[start]) < threshold for c in chans):
        start += 1
    if start == n:  # all silent: keep a single frame so the file stays valid
        return [[c[0]] for c in chans]
    end = n
    while end > start and all(abs(c[end - 1]) < threshold for c in chans):
        end -= 1
    return [list(c[start:end]) for c in chans]


def normalize_channels(chans, target_db):
    """normalize() with the joint peak of all channels (one gain keeps the stereo balance)."""
    p = max((peak(c) for c in chans), default=0.0)
    if p <= 0.0:
        return [list(c) for c in chans]
    gain = (10.0 ** (target_db / 20.0)) / p
    return [[x * gain for x in c] for c in chans]


def _process_channels(chans, rate, trim_silence, normalize_db, fade_in_s, fade_out_s, new_rate):
    out = chans
    if trim_silence:
        out = trim_channels(out)
    if normalize_db is not None:
        out = normalize_channels(out, normalize_db)
    if fade_in_s and fade_in_s > 0:
        out = [fade_in(c, fade_in_s, rate) for c in out]
    if fade_out_s and fade_out_s > 0:
        out = [fade_out(c, fade_out_s, rate) for c in out]
    if new_rate and new_rate != rate:
        out = [resample(c, rate, new_rate) for c in out]
        rate = new_rate
    return rate, out


def process(samples, rate, trim_silence=False, normalize_db=None,
            fade_in_s=0.0, fade_out_s=0.0, new_rate=None):
    """Apply the enabled steps in the fixed order; returns (rate, samples)."""
    rate, out = _process_channels([samples], rate, trim_silence, normalize_db,
                                  fade_in_s, fade_out_s, new_rate)
    return rate, out[0]


def process_stereo(left, right, rate, trim_silence=False, normalize_db=None,
                   fade_in_s=0.0, fade_out_s=0.0, new_rate=None):
    """process() for a stereo pair; returns (rate, left, right)."""
    rate, out = _process_channels([left, right], rate, trim_silence, normalize_db,
                                  fade_in_s, fade_out_s, new_rate)
    return rate, out[0], out[1]


def peak_db(samples, right=None):
    """Peak in dBFS (joint peak when `right` is given), or None for silence (JSON-friendly)."""
    p = peak(samples)
    if right is not None:
        p = max(p, peak(right))
    return None if p <= 0.0 else 20.0 * math.log10(p)
