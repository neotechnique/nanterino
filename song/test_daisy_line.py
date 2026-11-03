# Quick check of the Daisy singer on a few lines (syllables vs notes, timing, Whisper).
# logging: robotlog via nanterino.log
import sys, wave
import numpy as np
sys.path.insert(0, "/opt/robot/nanterino/song")
import build_song_v3 as v3
from build_song import midi
from listen_song import wer
from nanterino.engines import STT

s = v3.DaisySinger("/opt/robot/nanterino/models/piper/fr_FR-siwis-medium.onnx")
v3.SPB[0] = 0.6
stt = STT("http://127.0.0.1:8178/inference")
LINES = [("Je suis un petit robot", "E4 E4 G4 G4 A4 G4 E4:2"),
         ("Nan-té-ri-no, Nan-té-ri-no", "C5 B4 A4 G4 D5 C5 B4 G4"),
         ("Triez vos déchets, prenez le vélo", "E5:1/2 E5:1/2 D5 C5 D5 D5 C5 B4 G4"),
         ("Et le cœur tout vert", "A4 G4 F4 F4 E4:4")]
out = []
for text, notes in LINES:
    toks = notes.split()
    v3.NOTE_BEATS[0] = [eval(t.split(":")[1]) if ":" in t else 1.0 for t in toks]
    pitches = [midi(t.split(":")[0]) for t in toks]
    x, spans = s.speak(text)
    syl = v3.syllables(spans)
    y, lead, ev = v3.sing(s, text, pitches, -8)
    x16 = y[np.linspace(0, len(y), int(len(y) * 16000 / s.rate), endpoint=False).astype(int)]
    heard = stt.transcribe((np.clip(x16, -1, 1) * 32767).astype(np.int16), 16000)
    print(f"{text:<36} syl={len(syl)} notes={len(toks)} dur={len(y)/s.rate:.2f}s lead={lead:.2f} WER={wer(text.replace('-', ''), heard):.0%} | {heard}")
    out.append(y); out.append(np.zeros(int(0.5 * s.rate), np.float32))
w = wave.open("/opt/robot/nanterino/song/build/daisy_test.wav", "wb")
w.setnchannels(1); w.setsampwidth(2); w.setframerate(s.rate)
w.writeframes((np.clip(np.concatenate(out), -1, 1) * 32767).astype(np.int16).tobytes()); w.close()
print("wrote song/build/daisy_test.wav")
