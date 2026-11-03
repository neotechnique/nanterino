# Ablation: where does intelligibility get lost? (identity WORLD, melody pitch only, full daisy)
# logging: robotlog via nanterino.log
import sys
import numpy as np, pyworld
sys.path.insert(0, "/opt/robot/nanterino/song")
import build_song_v3 as v3
from build_song import midi
from listen_song import wer
from nanterino.engines import STT

s = v3.DaisySinger("/opt/robot/nanterino/models/piper/fr_FR-siwis-medium.onnx")
stt = STT("http://127.0.0.1:8178/inference")
fr = v3.FRAME_MS / 1000


def hear(y):
    x16 = y[np.linspace(0, len(y), int(len(y) * 16000 / s.rate), endpoint=False).astype(int)]
    return stt.transcribe((np.clip(x16, -1, 1) * 32767).astype(np.int16), 16000)


for text, notes in [("Je suis un petit robot", "E4 E4 G4 G4 A4 G4 E4"), ("Triez vos déchets, prenez le vélo", "E5 E5 D5 C5 D5 D5 C5 B4 G4")]:
    x, spans = s.speak(text)
    f0, t = pyworld.harvest(x, s.rate, frame_period=v3.FRAME_MS, f0_floor=70, f0_ceil=700)
    sp, ap = pyworld.cheaptrick(x, f0, t, s.rate), pyworld.d4c(x, f0, t, s.rate)
    print("raw piper      :", wer(text, hear(x.astype(np.float32))), hear(x.astype(np.float32)))
    y = pyworld.synthesize(f0, sp, ap, s.rate, v3.FRAME_MS)
    print("world identity :", hear(y.astype(np.float32)))
    syl = v3.syllables(spans)
    pitches = [midi(n) - 8 for n in notes.split()]
    bounds = [syl[0][0]] + [syl[j][0] for j in range(1, len(syl))] + [len(x)]
    tgt = np.zeros(len(f0))
    for j in range(len(syl)):
        a, b = int(bounds[j] / s.rate / fr), int(bounds[j + 1] / s.rate / fr)
        tgt[a:b] = 440 * 2 ** ((pitches[min(j, len(pitches) - 1)] - 69) / 12)
    tgt[: int(bounds[0] / s.rate / fr)] = tgt[int(bounds[0] / s.rate / fr)]
    y2 = pyworld.synthesize(np.where(f0 > 0, tgt, 0.0), sp, ap, s.rate, v3.FRAME_MS)
    print("melody pitch   :", hear(y2.astype(np.float32)))
