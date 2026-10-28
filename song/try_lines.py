#!/usr/bin/env python3
"""Try say/notes variants for given lines; score = mean letter similarity of Whisper's transcript
to the intended text over 3 takes (robust to unknown words and spacing). Variants come from a
JSON file: [{"text": ..., "say": ..., "notes": ...}, ...]. logging: robotlog via nanterino.log
"""
import difflib
import json
import os
import re
import sys
import unicodedata

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_song_v3 as v3  # noqa: E402
from build_song import midi  # noqa: E402
from nanterino.engines import STT  # noqa: E402


def letters(s):
    s = unicodedata.normalize("NFD", s.lower().replace("œ", "oe"))
    return re.sub(r"[^a-z]", "", "".join(c for c in s if unicodedata.category(c) != "Mn"))


singer = v3.DaisySinger("/opt/robot/nanterino/models/piper/fr_FR-siwis-medium.onnx")
stt = STT("http://127.0.0.1:8178/inference")
v3.SPB[0] = 0.6
for c in json.load(open(sys.argv[1], encoding="utf-8")):
    toks = c["notes"].split()
    v3.NOTE_BEATS[0] = [eval(t.split(":")[1]) if ":" in t else 1.0 for t in toks]
    p = [midi(t.split(":")[0]) for t in toks]
    hs = []
    for _ in range(3):
        y, _, _ = v3.sing(singer, c["say"], p, -8)
        x16 = y[np.linspace(0, len(y), int(len(y) * 16000 / singer.rate), endpoint=False).astype(int)]
        hs.append(stt.transcribe((np.clip(x16, -1, 1) * 32767).astype(np.int16), 16000))
    s = np.mean([difflib.SequenceMatcher(None, letters(h), letters(c["text"])).ratio() for h in hs])
    print(f"{s:.2f}  {c['say']:<44} {c['notes'][:34]:<34} | {hs[0]!r}", flush=True)
