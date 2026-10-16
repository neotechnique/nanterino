#!/usr/bin/env python3
"""Build "Nanterino, le petit robot": soundgen music + Nanterino's sung voice, beat-aligned.

Usage (on the Jetson, Nanterino venv):
    PYTHONPATH=/opt/robot/nanterino .venv/bin/python song/build_song.py [song/chanson.json]
Writes media/chanson-nanterino.wav (+ .json with the lyric timings for the face subtitles).

How the voice "sings" (no singing model exists for this voice):
  1. Piper says each lyric line (normal TTS, same voice as the robot);
  2. WORLD (pyworld) splits it into pitch (f0), spectral envelope and aperiodicity;
  3. syllable nuclei = energy peaks of the voiced frames; the line is time-warped so nucleus k
     lands on note k's onset (rhythm), and f0 is replaced by the melody (pitch);
  4. WORLD resynthesises; lines are placed on the beat grid over the soundgen backing track,
     which also doubles the melody softly (music and words share ONE timeline).
logging: robotlog via nanterino.log (component "nanterino").
"""
import json
import os
import subprocess
import sys
import wave
from fractions import Fraction

import numpy as np
import pyworld

from nanterino import config
from nanterino.engines import TTS
from nanterino.log import log

ROOT = "/opt/robot/nanterino"
SOUNDGEN = "/opt/robot/tools/sound/soundgen.py"
FRAME_MS = 5.0
# Mix balance: vocal RMS level, music gain, and how much the music ducks under the voice
# (0.6 = -8 dB). Tuned so the lyrics stay intelligible on the small robot speaker.
VOCAL_RMS = 0.30
MUSIC_GAIN = 0.75
DUCK = 0.6

CHORDS = {  # voicing (piano/pad) and bass root
    "C": ("C4+E4+G4", "C2"), "Am": ("A3+C4+E4", "A1"), "F": ("F3+A3+C4", "F1"),
    "G": ("G3+B3+D4", "G1"), "Em": ("E3+G3+B3", "E2"), "Dm": ("D3+F3+A3", "D2"),
}
NOTE_INDEX = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi(note: str) -> int:
    letter, rest = note[0].upper(), note[1:]
    acc = 0
    while rest and rest[0] in "#b":
        acc += 1 if rest[0] == "#" else -1
        rest = rest[1:]
    return 12 * (int(rest) + 1) + NOTE_INDEX[letter] + acc


def parse_notes(s: str):
    """'E4 G4:2 A4:1/2' -> [(midi, beats)]  (same token syntax as soundgen)."""
    out = []
    for tok in s.split():
        name, _, beats = tok.partition(":")
        out.append((midi(name), float(Fraction(beats)) if beats else 1.0))
    return out


def build_timeline(spec):
    """Absolute beats for chords and sung lines."""
    bars, lines, beat = [], [], 0.0
    for sec in spec["sections"]:
        for i, ch in enumerate(sec["chords"]):
            bars.append({"chord": ch, "beat": beat + 4 * i, "drums": sec.get("drums", True)})
        for i, ln in enumerate(sec.get("lines", [])):
            notes = parse_notes(ln["notes"])
            if abs(sum(b for _, b in notes) - 8) > 1e-6:
                sys.exit(f"line '{ln['text']}' does not last 8 beats")
            lines.append({"text": ln["text"], "notes": notes, "beat": beat + 8 * i})
        beat += 4 * len(sec["chords"])
    return bars, lines, beat


def music_spec(spec, bars, lines, total_beats):
    """soundgen 'song' JSON: soft lo-fi drums, e-piano, bass, string pad, vibraphone melody."""
    drums, keys, bass, pad, mel = [], [], [], [], []
    for b in bars:
        voicing, root = CHORDS[b["chord"]]
        keys.append(f"{voicing}:4")
        pad.append(f"{voicing}:4")
        fifth = root[0]  # simple root - root(octave up) pattern
        bass.append(f"{root}:2 {fifth}{int(root[-1]) + 1}:2")
        drums.append("C2+F#2:1 F#2:1 D2+F#2:1 F#2:1/2 C2:1/2" if b["drums"] else "r:4")
    # Melody doubling on the same timeline as the voice (rests between lines).
    cursor = 0.0
    for ln in lines:
        if ln["beat"] > cursor:
            mel.append(f"r:{ln['beat'] - cursor}")
        for m, beats in ln["notes"]:
            mel.append(f"{440 * 2 ** ((m - 69) / 12):.3f}:{beats}")
        cursor = ln["beat"] + 8
    keys.append("C4+E4+G4:4")  # final chord ring-out
    pad.append("C4+E4+G4:4")
    return {
        "mode": "song", "name": "chanson-nanterino", "bpm": spec["bpm"], "gain": 0.6, "seed": 7,
        "eq": {"treble": -3, "trebleFreq": 7000},
        "space": {"reverb": {"mix": 0.2, "size": 0.55, "damp": 0.55, "width": 1}, "width": 1.1},
        "tracks": [
            {"instrument": "kit-lofi", "volume": 0.5, "notes": " ".join(drums)},
            {"instrument": "pno-epiano", "volume": 0.32, "notes": " ".join(keys)},
            {"instrument": "gtr-bass", "volume": 0.55, "notes": " ".join(bass)},
            {"instrument": "str-slow", "volume": 0.16, "pan": -0.2, "notes": " ".join(pad)},
            # Melody doubling kept quiet: it guides the ear without masking the words.
            {"instrument": "mal-vibraphone", "volume": 0.1, "pan": 0.25, "notes": " ".join(mel)},
        ],
    }


def read_wav(path):
    with wave.open(path) as w:
        rate, ch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return rate, x.reshape(-1, ch) if ch > 1 else x[:, None]


def nuclei(f0, sp, n):
    """Times (s) of the n strongest syllable nuclei: energy peaks of voiced frames."""
    energy = np.log(sp.sum(axis=1) + 1e-10)
    energy = np.where(f0 > 0, energy - energy.min(), 0.0)
    k = 7  # ~35 ms smoothing
    e = np.convolve(energy, np.ones(k) / k, mode="same")
    peaks = [i for i in range(1, len(e) - 1) if e[i] > 0 and e[i] >= e[i - 1] and e[i] > e[i + 1]]
    peaks.sort(key=lambda i: -e[i])
    chosen, min_gap = [], int(70 / FRAME_MS)
    for i in peaks:
        if all(abs(i - j) >= min_gap for j in chosen):
            chosen.append(i)
        if len(chosen) == n:
            break
    chosen.sort()
    voiced = np.flatnonzero(f0 > 0)
    if len(chosen) < n and len(voiced):  # fallback: evenly spread over the voiced span
        chosen = list(np.linspace(voiced[0], voiced[-1], n).astype(int))
    return np.array(chosen) * FRAME_MS / 1000


def analyse(tts, text):
    """Piper speech of `text` -> WORLD parameters (f0, spectral envelope, aperiodicity)."""
    pcm = tts.synth(text.replace("-", "")).astype(np.float64) / 32768
    fs = tts.rate
    f0, t = pyworld.harvest(pcm, fs, frame_period=FRAME_MS, f0_floor=70, f0_ceil=600)
    return fs, f0, pyworld.cheaptrick(pcm, f0, t, fs), pyworld.d4c(pcm, f0, t, fs)


def sing_line(tts, text, notes, spb, transpose):
    """Return (rate, float32 mono, lead_s): `text` sung on `notes` (beats).

    lead_s = audio before the first note onset (the consonant before the first vowel), so the
    caller places the line at onset - lead_s.

    v2 (user feedback 2026-10-16: "voix qui se pince le nez, lente, shootée"): the whole line is
    no longer stretched to the notes. Each syllable keeps its NATURAL speed (consonants crisp);
    only its vowel is held (frames looped around the energy peak) to fill a long note, and the
    syllable is sped up only if it is longer than its note. The melody is also transposed near
    the voice's own register (caller), which removes the pinched/nasal sound of a big pitch-up.
    """
    fs, f0, sp, ap = analyse(tts, text)
    n_in, fr = len(f0), FRAME_MS / 1000
    onsets = np.cumsum([0] + [b * spb for _, b in notes])  # note k starts at onsets[k]
    p = np.round(nuclei(f0, sp, len(notes)) / fr).astype(int)  # nucleus frame per syllable
    voiced = np.flatnonzero(f0 > 0)
    first = max(0, (voiced[0] if len(voiced) else 0) - int(0.12 / fr))  # keep leading consonant
    last = min(n_in - 1, (voiced[-1] if len(voiced) else n_in - 1) + int(0.10 / fr))
    bounds = np.concatenate([[first], (p[:-1] + p[1:]) // 2, [last]])  # syllable k = [b_k, b_k+1)
    lead = (p[0] - bounds[0]) * fr + 0.04  # nucleus lands 40 ms after the note onset
    log_sp = np.log(sp + 1e-12)
    voiced_in = f0 > 0
    sp_l, ap_l, vo_l, k_l = [], [], [], []
    for k in range(len(notes)):
        b0, b1, pk = bounds[k], bounds[k + 1], p[k]
        # Output length of syllable k: from its start to the next syllable's start (nucleus-aligned).
        start = onsets[k] + 0.04 - (pk - b0) * fr
        nxt = (onsets[k + 1] + 0.04 - (p[k + 1] - bounds[k + 1]) * fr) if k + 1 < len(notes) else onsets[-1] + 0.15
        target = max(2, int(round((nxt - start) / fr)))
        natural = b1 - b0
        if natural >= target:  # syllable longer than its note: speed it up evenly
            seg = np.linspace(b0, b1 - 1, target).round().astype(int)
            sp_l.append(log_sp[seg]); ap_l.append(ap[seg]); vo_l.append(voiced_in[seg])
        else:
            # Hold the vowel with ONE steady timbre (v4, user 2026-10-16: "la voix barbote, comme
            # sous l'eau"): looping 5 ms frames made the timbre wobble ~9 Hz. Now the vowel is the
            # average envelope around the nucleus, entered/left with short log-domain crossfades.
            h1 = min(b1 - 1, pk + 4)
            v0, v1 = max(b0, pk - 3), min(b1, pk + 4)
            vowel_sp = log_sp[v0:v1].mean(axis=0)
            vowel_ap = ap[v0:v1].mean(axis=0)
            n_hold = target - natural
            ramp = np.clip(np.minimum(np.arange(n_hold) + 1, n_hold - np.arange(n_hold)) / 6.0, 0, 1)[:, None]
            hold_sp = (1 - ramp) * np.where(np.arange(n_hold)[:, None] < n_hold / 2, log_sp[h1], log_sp[min(h1 + 1, b1 - 1)]) + ramp * vowel_sp
            hold_ap = (1 - ramp) * ap[h1] + ramp * vowel_ap
            pre, post = np.arange(b0, h1 + 1), np.arange(h1 + 1, b1)
            sp_l += [log_sp[pre], hold_sp, log_sp[post]]
            ap_l += [ap[pre], hold_ap, ap[post]]
            vo_l += [voiced_in[pre], np.ones(n_hold, bool), voiced_in[post]]
        k_l.append(np.full(sum(len(a) for a in vo_l) - sum(len(a) for a in k_l), k))
    sp_o, ap_o = np.exp(np.concatenate(sp_l)), np.clip(np.concatenate(ap_l), 0, 1)
    voiced_o, k_of = np.concatenate(vo_l), np.concatenate(k_l)
    t_out = np.arange(len(k_of)) * fr - lead  # time relative to the first note onset
    # Melody f0 with a short glide between notes; no vibrato (v4: the vibrato read as "shaky").
    target = np.array([440 * 2 ** ((notes[k][0] + transpose - 69) / 12) for k in k_of])
    glide = np.empty_like(target)
    a = 1 - np.exp(-FRAME_MS / 25.0)  # 25 ms portamento
    g = target[0]
    for i, v in enumerate(target):
        g += a * (v - g)
        glide[i] = g
    f0_o = np.where(voiced_o, glide, 0.0)
    y = pyworld.synthesize(np.ascontiguousarray(f0_o), np.ascontiguousarray(sp_o), np.ascontiguousarray(ap_o), fs, FRAME_MS)
    return fs, y.astype(np.float32), lead


def slam_line(tts, text, notes, spb, transpose):
    """Return (rate, float32 mono, lead_s): `text` SPOKEN in rhythm, gently tuned.

    Measured 2026-10-16 (Whisper on the mix): note-by-note singing was understood at only
    ~15-30 % (68-85 % word errors), because syllable boundaries are guessed. Slam keeps the
    natural speech timing and intonation (intelligible), starts on the line's first beat, is
    sped up only if longer than the 2 bars, and its pitch is moved so the median sits on the
    line's median melody note (so it stays in key with the music).
    """
    fs, f0, sp, ap = analyse(tts, text)
    fr = FRAME_MS / 1000
    voiced = np.flatnonzero(f0 > 0)
    first = max(0, (voiced[0] if len(voiced) else 0) - int(0.10 / fr))
    last = min(len(f0) - 1, (voiced[-1] if len(voiced) else len(f0) - 1) + int(0.12 / fr))
    seg = np.arange(first, last + 1)
    room = int(8 * spb * 0.95 / fr)
    if len(seg) > room:  # too long for its 2 bars: uniform speed-up
        seg = np.linspace(first, last, room).round().astype(int)
    target = 440 * 2 ** ((np.median([m for m, _ in notes]) + transpose - 69) / 12)
    ratio = target / np.median(f0[f0 > 0])
    f0_o = f0[seg] * ratio
    y = pyworld.synthesize(np.ascontiguousarray(f0_o), np.ascontiguousarray(sp[seg]), np.ascontiguousarray(ap[seg]), fs, FRAME_MS)
    return fs, y.astype(np.float32), 0.05


def auto_transpose(tts, lines):
    """Octave shift (multiple of 12) that brings the melody near the voice's speaking pitch.

    A WORLD pitch-up of an octave or more keeps the speech formants and sounds pinched/nasal;
    singing about 3 semitones above the natural speaking pitch sounds natural.
    """
    _, f0, _, _ = analyse(tts, lines[0]["text"])
    voice_midi = 69 + 12 * np.log2(np.median(f0[f0 > 0]) / 440)
    melody_midi = np.median([m for ln in lines for m, _ in ln["notes"]])
    shift = int(12 * round((voice_midi + 3 - melody_midi) / 12))
    log.info("song auto transpose voice_midi=%.1f melody_midi=%.1f shift=%d", voice_midi, melody_midi, shift)
    return shift


def resample(x, src, dst):
    if src == dst:
        return x
    t = np.linspace(0, len(x), int(len(x) * dst / src), endpoint=False)
    return np.interp(t, np.arange(len(x)), x).astype(np.float32)


def main():
    spec_path = sys.argv[1] if len(sys.argv) > 1 else f"{ROOT}/song/chanson.json"
    spec = json.load(open(spec_path, encoding="utf-8"))
    cfg = config.load()
    spb = 60 / spec["bpm"]
    bars, lines, total_beats = build_timeline(spec)
    os.makedirs(f"{ROOT}/media", exist_ok=True)
    work = f"{ROOT}/song/build"
    os.makedirs(work, exist_ok=True)

    # 1) Music with the user's soundgen tool.
    mpath = f"{work}/music.json"
    json.dump(music_spec(spec, bars, lines, total_beats), open(mpath, "w"), indent=1)
    subprocess.run([sys.executable, SOUNDGEN, "render", mpath, "-o", f"{work}/music.wav"], check=True,
                   cwd=os.path.dirname(SOUNDGEN), stdout=subprocess.DEVNULL)
    rate, music = read_wav(f"{work}/music.wav")
    log.info("song music rendered rate=%d s=%.1f", rate, len(music) / rate)

    # 2) Sung voice, line by line, on the same beat grid.
    tts = TTS(cfg["tts_voice"])
    voice = np.zeros(len(music) + rate * 2, dtype=np.float32)
    timings = []
    transpose = spec.get("vocal_transpose", "auto")
    if transpose == "auto":
        transpose = auto_transpose(tts, lines)
    for ln in lines:
        render = slam_line if spec.get("vocal_style", "sing") == "slam" else sing_line
        fs, y, lead = render(tts, ln["text"], ln["notes"], spb, transpose)
        y = resample(y, fs, rate)
        start = int(round((ln["beat"] * spb - lead) * rate))
        if start < 0:  # very first line: drop the part before the song start
            y, start = y[-start:], 0
        voice[start:start + len(y)] += y[: len(voice) - start]
        timings.append({"t": round(ln["beat"] * spb, 3), "text": ln["text"].replace("-", "")})
    voice = voice[: len(music)]
    # Lyrics must be understood (user, 2026-10-16: "paroles et chanson au même niveau"):
    # voice clearly louder, and the music ducks ~8 dB while Nanterino sings.
    voice *= VOCAL_RMS / max(1e-6, np.sqrt(np.mean(voice[np.abs(voice) > 1e-4] ** 2)))
    env = np.abs(voice)
    att, rel = 1 - np.exp(-1 / (0.02 * rate)), 1 - np.exp(-1 / (0.35 * rate))
    smooth = np.empty_like(env)
    level = 0.0
    for i, v in enumerate(env):  # peak follower: fast attack, slow release
        level += (att if v > level else rel) * (v - level)
        smooth[i] = level
    duck = 1 - DUCK * np.clip(smooth / (0.5 * VOCAL_RMS), 0, 1)
    mix = music * (MUSIC_GAIN * duck)[:, None] + voice[:, None]
    mix *= 0.89 / max(1e-6, np.abs(mix).max())  # peak -1 dBFS
    mono = mix.mean(axis=1)  # the robot speaker path is mono
    out = f"{ROOT}/media/chanson-nanterino.wav"
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((mono * 32767).astype(np.int16).tobytes())
    json.dump({"title": spec["title"], "duration_s": round(len(mono) / rate, 2), "lines": timings},
              open(out.replace(".wav", ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log.info("song built path=%s s=%.1f lines=%d", out, len(mono) / rate, len(lines))
    print(out, round(len(mono) / rate, 1), "s")


if __name__ == "__main__":
    main()

