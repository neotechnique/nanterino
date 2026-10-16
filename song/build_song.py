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


def sing_line(tts, text, notes, spb, transpose):
    """Return (rate, float32 mono) of `text` sung on `notes` (beats), starting at t=0."""
    pcm = tts.synth(text.replace("-", "")).astype(np.float64) / 32768
    fs = tts.rate
    f0, t = pyworld.harvest(pcm, fs, frame_period=FRAME_MS, f0_floor=70, f0_ceil=600)
    sp = pyworld.cheaptrick(pcm, f0, t, fs)
    ap = pyworld.d4c(pcm, f0, t, fs)
    t_in_end = len(f0) * FRAME_MS / 1000
    onsets = np.cumsum([0] + [b * spb for _, b in notes])  # note k starts at onsets[k]
    total = onsets[-1] + 0.25
    p = nuclei(f0, sp, len(notes))
    q = onsets[:-1] + 0.06  # vowel nucleus slightly after the note onset
    # Piecewise-linear time map output -> input through (q_k, p_k), monotonic.
    anchors_out = np.concatenate([[0.0], q, [total]])
    anchors_in = np.concatenate([[max(0.0, p[0] - 0.08)], p, [min(t_in_end, p[-1] + 0.35)]])
    anchors_in = np.maximum.accumulate(anchors_in + np.arange(len(anchors_in)) * 1e-6)
    n_out = int(total * 1000 / FRAME_MS)
    t_out = np.arange(n_out) * FRAME_MS / 1000
    idx = np.clip(np.round(np.interp(t_out, anchors_out, anchors_in) * 1000 / FRAME_MS).astype(int), 0, len(f0) - 1)
    sp_o, ap_o, voiced = sp[idx], ap[idx], f0[idx] > 0
    # Melody f0 with short glide between notes and gentle vibrato on long notes.
    k_of = np.clip(np.searchsorted(onsets, t_out, side="right") - 1, 0, len(notes) - 1)
    target = np.array([440 * 2 ** ((notes[k][0] + transpose - 69) / 12) for k in k_of])
    since = t_out - onsets[k_of]
    vib = np.where(since > 0.25, 0.35 * np.sin(2 * np.pi * 5.5 * since), 0.0)  # semitones
    target = target * 2 ** (vib / 12)
    glide = np.empty_like(target)
    a = 1 - np.exp(-FRAME_MS / 25.0)  # 25 ms portamento
    g = target[0]
    for i, v in enumerate(target):
        g += a * (v - g)
        glide[i] = g
    f0_o = np.where(voiced, glide, 0.0)
    y = pyworld.synthesize(np.ascontiguousarray(f0_o), np.ascontiguousarray(sp_o), np.ascontiguousarray(ap_o), fs, FRAME_MS)
    return fs, y.astype(np.float32)


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
    for ln in lines:
        fs, y = sing_line(tts, ln["text"], ln["notes"], spb, spec.get("vocal_transpose", 0))
        y = resample(y, fs, rate)
        start = int(round(ln["beat"] * spb * rate))
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

