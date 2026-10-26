"""16-bit mono/stereo PCM WAV helpers and basic signal statistics (stdlib `wave` only)."""

import math
import sys
import wave
from array import array


def to_pcm16(samples):
    """Float samples -> list of int16 using the contract: floor(clip(x)*32767 + 0.5)."""
    out = []
    append = out.append
    floor = math.floor
    for x in samples:
        if x != x:  # NaN guard: engines already zero non-finite samples
            x = 0.0
        elif x > 1.0:
            x = 1.0
        elif x < -1.0:
            x = -1.0
        append(floor(x * 32767.0 + 0.5))
    return out


def write_wav(path, rate, samples, right=None):
    """Write PCM16 little-endian; returns the number of frames written.

    Mono by default (byte-identical to the historic writer). With `right`, `samples` is the
    left channel and the file gets 2 interleaved channels (L, R, L, R...).
    """
    if right is None:
        pcm = array("h", to_pcm16(samples))
        channels = 1
    else:
        if len(right) != len(samples):
            raise ValueError("left and right channels must have the same length")
        pcm = array("h", bytes(4 * len(samples)))
        pcm[0::2] = array("h", to_pcm16(samples))
        pcm[1::2] = array("h", to_pcm16(right))
        channels = 2
    frames = len(samples)
    if sys.byteorder == "big":  # WAV data is little endian regardless of host
        pcm.byteswap()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm.tobytes())
    return frames


def read_wav(path):
    """Read a mono/stereo 16-bit WAV; returns (rate, floats in [-1, 1], channels).

    Multi-channel files are returned interleaved so stats still make sense.
    """
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("only 16-bit PCM WAV files are supported")
        rate, channels = w.getframerate(), w.getnchannels()
        raw = w.readframes(w.getnframes())
    pcm = array("h")
    pcm.frombytes(raw)
    if sys.byteorder == "big":
        pcm.byteswap()
    return rate, [v / 32767.0 for v in pcm], channels


def split_channels(samples, channels):
    """De-interleave read_wav() output into one list per channel."""
    return [samples[c::channels] for c in range(channels)]


def stats(samples, rate, right=None):
    """Peak / RMS (linear, 0..1) and length for a list of float samples.

    With `right` (stereo), `samples` is the left channel: the peak is the joint peak, the RMS
    is taken over both channels, and `samples` / `seconds` count frames (not values).
    """
    n = len(samples)
    if n == 0:
        return {"samples": 0, "seconds": 0.0, "peak": 0.0, "rms": 0.0}
    chans = [samples] if right is None else [samples, right]
    peak = max(max(max(c), -min(c)) for c in chans)
    rms = math.sqrt(sum(x * x for c in chans for x in c) / (n * len(chans)))
    return {"samples": n, "seconds": n / rate, "peak": peak, "rms": rms}


def format_stats(rate, st):
    """One-line human summary used by the CLI."""
    def db(v):
        return "-inf" if v <= 0 else "%.1f" % (20.0 * math.log10(v))
    return "%d Hz, %d samples, %.3f s, peak %.3f (%s dBFS), rms %.3f (%s dBFS)" % (
        rate, st["samples"], st["seconds"], st["peak"], db(st["peak"]),
        st["rms"], db(st["rms"]))
