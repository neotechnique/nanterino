#!/usr/bin/env python3
""""Listen" to the built song: intelligibility (Whisper per line vs lyrics) + spectrogram image.

logging: robotlog via nanterino.log. Usage (Jetson):
    PYTHONPATH=/opt/robot/nanterino .venv/bin/python song/listen_song.py
Outputs a per-line report on stdout and song/build/spectro.png (first 40 s, vocal band).
"""
import json
import re
import unicodedata
import wave

import numpy as np
from PySide6.QtGui import QColor, QImage

from nanterino.engines import STT

ROOT = "/opt/robot/nanterino"


def words(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z]+", s)


def letter_err(ref, hyp):
    """1 - letter similarity (accents/spaces/punctuation ignored): robust to unknown words such
    as "Nanterino" and to word splits ("Nanté Rino"), unlike the word error rate."""
    import difflib
    a = "".join(words(ref.replace("œ", "oe"))); b = "".join(words(hyp.replace("œ", "oe")))
    return 1 - difflib.SequenceMatcher(None, a, b).ratio()


def wer(ref, hyp):
    """Word error rate (Levenshtein on words)."""
    r, h = words(ref), words(hyp)
    d = np.arange(len(h) + 1)
    for i, rw in enumerate(r, 1):
        prev, d[0] = d.copy(), i
        for j, hw in enumerate(h, 1):
            d[j] = min(prev[j] + 1, d[j - 1] + 1, prev[j - 1] + (rw != hw))
    return d[len(h)] / max(1, len(r))


def main():
    path = f"{ROOT}/media/chanson-nanterino.wav"
    with wave.open(path) as w:
        rate = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    meta = json.load(open(path.replace(".wav", ".json"), encoding="utf-8"))
    stt = STT("http://127.0.0.1:8178/inference")
    lines = meta["lines"]
    total = 0.0
    for i, ln in enumerate(lines):
        t0 = max(0.0, ln["t"] - 0.3)
        t1 = lines[i + 1]["t"] - 0.1 if i + 1 < len(lines) else t0 + 5.5
        seg = x[int(t0 * rate):int(min(t1, t0 + 5.5) * rate)]
        idx = np.linspace(0, len(seg), int(len(seg) * 16000 / rate), endpoint=False).astype(int)
        heard = stt.transcribe(seg[idx].astype(np.int16), 16000)
        e = wer(ln["text"], heard)
        total += e
        print(f"{ln['t']:6.1f}s WER={e:4.0%} | {ln['text']:<36} | entendu: {heard}")
    print(f"moyenne WER={total / len(lines):.0%} (0% = tout compris)")

    # Spectrogram 0-40 s, 0-4 kHz (where vowels/formants live), log magnitude.
    seg = x[: rate * 40].astype(np.float32)
    n, hop = 2048, 512
    win = np.hanning(n)
    frames = np.array([np.abs(np.fft.rfft(seg[i:i + n] * win)) for i in range(0, len(seg) - n, hop)])
    fmax = int(4000 * n / rate)
    s = 20 * np.log10(frames[:, :fmax] + 1e-6)
    s = np.clip((s - (s.max() - 70)) / 70, 0, 1)
    img = QImage(s.shape[0], s.shape[1], QImage.Format_RGB32)
    for xi in range(s.shape[0]):
        for yi in range(s.shape[1]):
            v = s[xi, yi]
            img.setPixelColor(xi, s.shape[1] - 1 - yi, QColor(int(255 * v ** 0.7), int(255 * v ** 1.5), int(255 * (1 - v) * v * 2)))
    img.save(f"{ROOT}/song/build/spectro.png")
    print("spectro", s.shape)


if __name__ == "__main__":
    main()

