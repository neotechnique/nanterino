#!/usr/bin/env python3
"""A/B listening file: for each sung line, the OLD voice then the NEW voice, separated by short
silences and a soft beep between lines, so the user can compare quickly by ear.
Usage: make_ab.py old_voice.wav old.json new_voice.wav new.json out.wav
logging: robotlog via nanterino.log
"""
import json
import sys
import wave

import numpy as np


def load(p):
    with wave.open(p) as w:
        r = w.getframerate()
        return r, np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def lines(js):
    L = json.load(open(js, encoding="utf-8"))["lines"]
    return [(L[i]["text"], L[i]["t"], L[i + 1]["t"] if i + 1 < len(L) else L[i]["t"] + 5.0) for i in range(len(L))]


ro, xo = load(sys.argv[1]); rn, xn = load(sys.argv[3])
assert ro == rn
r = ro
lo, ln = lines(sys.argv[2]), lines(sys.argv[4])
sil = lambda s: np.zeros(int(s * r), np.float32)  # noqa: E731
t = np.arange(int(0.12 * r)) / r
beep = 0.15 * np.sin(2 * np.pi * 880 * t) * np.hanning(len(t))
out, seen = [], set()
for (txt, a0, a1), (_, b0, b1) in zip(lo, ln):
    if txt in seen:
        continue  # refrains: compare each distinct line once
    seen.add(txt)
    old = xo[int(max(0, a0 - 0.3) * r):int(min(a1, a0 + 5.5) * r)]
    new = xn[int(max(0, b0 - 0.3) * r):int(min(b1, b0 + 5.5) * r)]
    out += [beep.astype(np.float32), sil(0.3), old, sil(0.7), new, sil(1.2)]
y = np.concatenate(out)
y = y / max(1e-6, np.abs(y).max()) * 0.89
with wave.open(sys.argv[5], "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(r); w.writeframes((y * 32767).astype(np.int16).tobytes())
print("A/B lines:", len(seen), "->", sys.argv[5])
