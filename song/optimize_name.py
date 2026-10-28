#!/usr/bin/env python3
"""Explore the sung name "Nanterino" with a letter-level score (Whisper does not know the word,
so word error rate is always 100 %; letter similarity still separates "Nantérino" from
"Na terrino"). logging: robotlog via nanterino.log
"""
import difflib
import os
import re
import sys
import unicodedata

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_song_v3 as v3  # noqa: E402
from build_song import midi  # noqa: E402
from nanterino.engines import STT  # noqa: E402

TARGET = "nanterinonanterino"


def letters(s):
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z]", "", "".join(c for c in s if unicodedata.category(c) != "Mn"))


def sim(h):
    return difflib.SequenceMatcher(None, letters(h), TARGET).ratio()


singer = v3.DaisySinger("/opt/robot/nanterino/models/piper/fr_FR-siwis-medium.onnx")
stt = STT("http://127.0.0.1:8178/inference")
v3.SPB[0] = 0.6
CUR = "C5:1/2 B4:1/2 A4:1/2 G4:3/2 D5:1/2 C5:1/2 B4:1/2 G4:7/2"
LONG1 = "C5 B4:1/2 A4:1/2 G4 D5 C5:1/2 B4:1/2 G4:3"
EVEN = "C5 B4 A4 G4 D5 C5 B4 G4"
SAYS = ["Nan-té-ri-no, Nan-té-ri-no", "Nantérino, Nantérino", "Nan-té-rino, Nan-té-rino",
        "Nanne-té-ri-no, Nanne-té-ri-no", "Nan, té, ri, no ! Nan, té, ri, no !", "Nanterre-ino, Nanterre-ino"]
rows = []
for say in SAYS:
    for name, notes in (("actuel", CUR), ("1re longue", LONG1), ("régulier", EVEN)):
        toks = notes.split()
        v3.NOTE_BEATS[0] = [eval(t.split(":")[1]) if ":" in t else 1.0 for t in toks]
        p = [midi(t.split(":")[0]) for t in toks]
        hs = []
        for _ in range(3):
            y, _, _ = v3.sing(singer, say, p, -8)
            x16 = y[np.linspace(0, len(y), int(len(y) * 16000 / singer.rate), endpoint=False).astype(int)]
            hs.append(stt.transcribe((np.clip(x16, -1, 1) * 32767).astype(np.int16), 16000))
        s = float(np.mean([sim(h) for h in hs]))
        rows.append((s, say, name, notes, hs[0]))
        print(f"{s:.2f}  {say:<36} {name:<10} | {hs[0]!r}", flush=True)
best = max(rows)
print("BEST", best[:4])
