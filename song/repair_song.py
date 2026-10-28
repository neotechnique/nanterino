#!/usr/bin/env python3
"""Repair loop for the Daisy song: build -> listen to the REAL final mix line by line -> freeze
the lines Whisper understands, re-sing only the others -> rebuild; keep the best round.

Why (2026-10-28): take selection on an approximate mix still let random regressions through
("Et le cœur tout vert" -> "cœur ouvert" in one build, perfect in the previous one). Judging the
actual final mix and freezing good takes makes every round monotonic for the frozen lines.
logging: robotlog via nanterino.log
Usage: PYTHONPATH=/opt/robot/nanterino .venv/bin/python song/repair_song.py song/chanson-v3-final.json [rounds]
"""
import json
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from listen_song import letter_err  # noqa: E402
from nanterino.engines import STT  # noqa: E402
from nanterino.log import log  # noqa: E402

ROOT = "/opt/robot/nanterino"
BAD_LIMIT = 0.08  # letter error above which a line is re-sung
TAKES_DIR = f"{ROOT}/song/build/takes"


def evaluate(stt):
    path = f"{ROOT}/media/chanson-nanterino.wav"
    with wave.open(path) as w:
        rate = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    lines = json.load(open(path.replace(".wav", ".json"), encoding="utf-8"))["lines"]
    res = []
    for i, ln in enumerate(lines):
        t0 = max(0.0, ln["t"] - 0.3)
        t1 = lines[i + 1]["t"] - 0.1 if i + 1 < len(lines) else t0 + 5.5
        seg = x[int(t0 * rate):int(min(t1, t0 + 5.5) * rate)]
        idx = np.linspace(0, len(seg), int(len(seg) * 16000 / rate), endpoint=False).astype(int)
        h = stt.transcribe(seg[idx].astype(np.int16), 16000)
        res.append((ln["text"], letter_err(ln["text"], h), h))
    return res


def main():
    spec = sys.argv[1]
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    stt = STT("http://127.0.0.1:8178/inference")
    os.makedirs(TAKES_DIR, exist_ok=True)
    for f in os.listdir(TAKES_DIR):  # fresh start: no stale takes from older specs
        os.unlink(os.path.join(TAKES_DIR, f))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=ROOT)
    best = None
    for r in range(rounds + 1):
        subprocess.run([sys.executable, f"{ROOT}/song/build_song_v3.py", spec, "--inmix", "8"], check=True,
                       env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        res = evaluate(stt)
        mean = float(np.mean([e for _, e, _ in res]))
        bad = sorted({t for t, e, _ in res if e > BAD_LIMIT})
        print(f"round {r}: mean letter error {mean:.3f}, bad lines {len(bad)}", flush=True)
        for t, e, h in res:
            print(f"   {e:4.2f}  {t:<40} | {h!r}", flush=True)
        log.info("song repair round=%d mean_letter_err=%.3f bad=%d", r, mean, len(bad))
        if best is None or mean < best[0]:
            best = (mean, r)
            shutil.copy(f"{ROOT}/media/chanson-nanterino.wav", f"{ROOT}/media/chanson-nanterino-daisy-final.wav")
            shutil.copy(f"{ROOT}/media/chanson-nanterino.json", f"{ROOT}/media/chanson-nanterino-daisy-final.json")
        if not bad:
            break
        json.dump(bad, open(f"{TAKES_DIR}/bad.json", "w"), ensure_ascii=False)
    # The robot keeps playing the validated v4 until the user picks the Daisy version.
    shutil.copy(f"{ROOT}/media/chanson-nanterino-v4.wav", f"{ROOT}/media/chanson-nanterino.wav")
    shutil.copy(f"{ROOT}/media/chanson-nanterino-v4.json", f"{ROOT}/media/chanson-nanterino.json")
    print(f"best round {best[1]} mean letter error {best[0]:.3f} -> media/chanson-nanterino-daisy-final.wav")


if __name__ == "__main__":
    main()
