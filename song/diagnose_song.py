#!/usr/bin/env python3
"""Audible-defect diagnostic of the sung voice (a cappella stem), line by line, timestamped.

Why (2026-10-28): Whisper only measures intelligibility; the user hears level drop-outs, a voice
going too low, rasp/noise and odd timing "un peu partout". This tool measures those defects:
  - dropouts : level dips > DIP_DB inside voiced/held parts (vs the line's median voiced level),
  - pitch    : measured f0 vs the score note (> 1 semitone off, excluding glides), notes < LOW_HZ,
  - rasp     : voiced frames with high aperiodicity (breathy/noisy WORLD output),
  - clicks   : sample-to-sample jumps far above the local signal slope.
Usage: PYTHONPATH=/opt/robot/nanterino .venv/bin/python song/diagnose_song.py <voice.wav> <song.json> <spec.json> [transpose]
Writes song/build/diagnostic.md and prints a summary line "TOTAL ..." (machine-readable).
logging: robotlog via nanterino.log
"""
import json
import os
import sys
import wave
from fractions import Fraction

import numpy as np
import pyworld

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_song import midi  # noqa: E402

DIP_DB, LOW_HZ, OFF_ST, AP_RASP = 8.0, 180.0, 1.0, 0.45
FR = 10.0  # ms analysis frames


def load(path):
    with wave.open(path) as w:
        r = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768
    return r, x


def fmt(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"


def main():
    wav, song_json, spec_json = sys.argv[1:4]
    transpose = int(sys.argv[4]) if len(sys.argv) > 4 else -8
    rate, x = load(wav)
    # analyse at 16 kHz (speed); WORLD f0/aperiodicity on the voice stem
    n16 = int(len(x) * 16000 / rate)
    x16 = np.interp(np.linspace(0, len(x), n16, endpoint=False), np.arange(len(x)), x)
    f0, t = pyworld.harvest(x16, 16000, frame_period=FR, f0_floor=70, f0_ceil=800)
    ap = pyworld.d4c(x16, f0, t, 16000)
    band = ap[:, : ap.shape[1] // 2].mean(axis=1)  # 0-4 kHz aperiodicity
    hop = int(16000 * FR / 1000)
    rms = np.array([np.sqrt(np.mean(x16[i * hop:(i + 1) * hop] ** 2) + 1e-12) for i in range(len(f0))])
    lvl = 20 * np.log10(rms + 1e-9)
    lines = json.load(open(song_json, encoding="utf-8"))["lines"]
    spec = json.load(open(spec_json, encoding="utf-8"))
    spb = 60 / spec["bpm"]
    notes_by_text = {}
    for sec in spec["sections"]:
        for ln in sec.get("lines", []):
            toks = ln["notes"].split()
            notes_by_text[ln["text"].replace("-", "")] = ([midi(tk.split(":")[0]) for tk in toks],
                                                          [float(Fraction(tk.split(":")[1])) if ":" in tk else 1.0 for tk in toks])
    out = ["# Diagnostic de la voix chantée", "", f"Fichier : `{os.path.basename(wav)}` — transposition {transpose}", ""]
    tot = {"creux": 0, "faux": 0, "grave": 0, "souffle": 0, "clic": 0}
    # clicks on the full-rate signal: second difference far above local level
    d2 = np.abs(np.diff(x, 2))
    loc = np.convolve(np.abs(x), np.ones(441) / 441, mode="same")[2:]
    click_idx = np.flatnonzero((d2 > 0.25) & (d2 > 8 * (loc + 1e-3)))
    for i, ln in enumerate(lines):
        t0 = ln["t"]
        t1 = lines[i + 1]["t"] if i + 1 < len(lines) else t0 + 5.0
        a, b = int(t0 * 1000 / FR), min(len(f0), int(t1 * 1000 / FR))
        pitches, beats = notes_by_text.get(ln["text"], ([], []))
        onsets = np.concatenate([[0.0], np.cumsum(beats)]) * spb
        issues = []
        seg_v = [k for k in range(a, b) if f0[k] > 0]
        med = np.median(lvl[seg_v]) if seg_v else -60
        # 1) dropouts: >= 3 consecutive frames (30 ms) inside the sung span far below the median
        sung_end = t0 + (onsets[-1] if len(onsets) else 4.0) - 0.5
        k = a
        while k < b:
            tk = k * FR / 1000
            if tk < sung_end and lvl[k] < med - DIP_DB and any(f0[max(a, k - 5):k] > 0) and any(f0[k + 1:min(b, k + 6)] > 0):
                j = k
                while j < b and lvl[j] < med - DIP_DB:
                    j += 1
                if j - k >= 3:
                    issues.append(("creux", tk, f"niveau −{med - lvl[k:j].min():.0f} dB sur {int((j - k) * FR)} ms"))
                k = j
            k += 1
        # 2) pitch vs score (skip 120 ms after each note onset: glides)
        for n, m in enumerate(pitches):
            ns, ne = t0 + onsets[n] + 0.12, t0 + onsets[n + 1] - 0.05
            target = 440 * 2 ** ((m + transpose - 69) / 12)
            fr_idx = [q for q in range(int(ns * 1000 / FR), min(b, int(ne * 1000 / FR))) if f0[q] > 0]
            if not fr_idx:
                continue
            meas = np.median(f0[fr_idx])
            off = 12 * np.log2(meas / target)
            if abs(off) > OFF_ST:
                issues.append(("faux", ns, f"note {n + 1} : {meas:.0f} Hz au lieu de {target:.0f} ({off:+.1f} demi-ton)"))
            if target < LOW_HZ:
                issues.append(("grave", ns, f"note {n + 1} écrite à {target:.0f} Hz (< {LOW_HZ:.0f})"))
        # 3) rasp: voiced frames with high aperiodicity, in runs >= 50 ms
        run = 0
        for q in seg_v:
            run = run + 1 if band[q] > AP_RASP else 0
            if run == 5:
                issues.append(("souffle", q * FR / 1000, f"voix bruitée (apériodicité {band[q]:.2f})"))
        # 4) clicks
        for c in click_idx[(click_idx >= int(t0 * rate)) & (click_idx < int(t1 * rate))][:5]:
            issues.append(("clic", c / rate, "discontinuité"))
        for kind, _, _ in issues:
            tot[kind] += 1
        out.append(f"## {fmt(t0)} — {ln['text']}")
        out += [f"- {fmt(tt)} **{kind}** : {msg}" for kind, tt, msg in sorted(issues, key=lambda z: z[1])] or ["- aucun défaut mesuré"]
        out.append("")
    out.insert(4, "Total : " + ", ".join(f"{k} {v}" for k, v in tot.items()) + "\n")
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "build"), exist_ok=True)
    open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "diagnostic.md"), "w", encoding="utf-8").write("\n".join(out))
    print("TOTAL " + " ".join(f"{k}={v}" for k, v in tot.items()))


if __name__ == "__main__":
    main()
