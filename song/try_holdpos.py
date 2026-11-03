# Compare held-vowel sampling positions on "o"-heavy lines (letter similarity, 3 takes).
# logging: robotlog via nanterino.log
import difflib, os, re, sys, unicodedata
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_song_v3 as v3
from build_song import midi
from nanterino.engines import STT

def letters(s):
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z]", "", "".join(c for c in s if unicodedata.category(c) != "Mn"))

singer = v3.DaisySinger("/opt/robot/nanterino/models/piper/fr_FR-siwis-medium.onnx")
stt = STT("http://127.0.0.1:8178/inference")
v3.SPB[0] = 0.6
LINES = [("Le petit robot rigolo", "Le pe-tit ro-bot, ri-go-lo !", "A4:1/2 A4:1/2 C5:1/2 C5:1/2 E5 D5:1/2 C5:1/2 A4:4"),
         ("Triez bien vos déchets, prenez le vélo", "Tri-ez bien vos dé-chets, pre-nez le vé-lo", "E5 E5:1/2 E5:1/2 D5:1/2 C5:3/2 D5:1/2 D5:1/2 C5 B4:1/2 G4:3/2"),
         ("Je suis un petit robot", "Je suis un petit robot", "E4 E4 G4 G4 A4 G4 E4:2")]
for pos, win in ((0.5, 2), (0.3, 1), (0.35, 2), (0.2, 1)):
    v3.HOLD_POS, v3.HOLD_WIN = pos, win
    tot = []
    for text, say, notes in LINES:
        toks = notes.split()
        v3.NOTE_BEATS[0] = [eval(t.split(":")[1]) if ":" in t else 1.0 for t in toks]
        p = [midi(t.split(":")[0]) for t in toks]
        hs = []
        for _ in range(3):
            y, _, _ = v3.sing(singer, say, p, -8)
            x16 = y[np.linspace(0, len(y), int(len(y) * 16000 / singer.rate), endpoint=False).astype(int)]
            hs.append(stt.transcribe((np.clip(x16, -1, 1) * 32767).astype(np.int16), 16000))
        s = np.mean([difflib.SequenceMatcher(None, letters(h), letters(text)).ratio() for h in hs])
        tot.append(s)
        print(f"pos={pos} win={win} {s:.2f} {text[:26]:<26} | {hs[0]!r}", flush=True)
    print(f"pos={pos} win={win} MEAN {np.mean(tot):.3f}", flush=True)
