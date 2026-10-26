#!/usr/bin/env python3
"""Find the quietest keep-alive level that keeps the current speaker awake (mic against the speaker), through the running Nanterino service

Logs: /var/log/robot/speaker-calibrate.log (WARNING+ also in errors.log)
"""
import sys
sys.path.insert(0, "/opt/robot/lib")
from robotlog import get_logger

log = get_logger("speaker-calibrate")

import argparse
import json
import os
import time
import urllib.request

try:
    import numpy as np
    import sounddevice as sd
except ImportError:  # re-run once inside the Nanterino venv (argv[0] must be the venv python)
    VENV_PY = "/opt/robot/nanterino/.venv/bin/python"
    if os.environ.get("ROBOT_REEXEC"):
        raise
    os.environ["ROBOT_REEXEC"] = "1"
    os.execv(VENV_PY, [VENV_PY, *sys.argv])

API = "http://127.0.0.1:8080/api"
RATE = 48000


def ctl(**body):
    req = urllib.request.Request(API + "/control", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=10))


def status():
    return json.load(urllib.request.urlopen(API + "/status", timeout=10))


def mic_device():
    for i, d in enumerate(sd.query_devices()):  # through PipeWire, shared with the service's own mic
        if d["name"] == "pipewire" and d["max_input_channels"] > 0:
            return i
    return None


def tone_ms(rec: np.ndarray) -> dict:
    """Duration and onset of the 1 kHz tone in a recording (10 ms frames, FFT bin around 1 kHz)."""
    frame = 480
    n = len(rec) // frame
    spec = np.abs(np.fft.rfft(rec[: n * frame].reshape(n, frame) * np.hanning(frame), axis=1))
    k = int(1000 * frame / RATE)
    env = spec[:, k - 1:k + 2].max(axis=1)
    floor = np.median(env[:15]) + 1e-9
    on = np.where(env > floor * 8)[0]
    return {"heard": bool(len(on)), "onset_ms": int(on[0] * 10) if len(on) else None, "dur_ms": int(len(on) * 10)}


def shot(dev) -> dict:
    """Record 2 s while the service plays one calibration tone through its real output path."""
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", device=dev) as mic:
        mic.read(int(RATE * 0.2))
        pre = mic.read(int(RATE * 0.15))[0][:, 0]
        ctl(action="test_tone")
        post = mic.read(int(RATE * 1.8))[0][:, 0]
    return tone_ms(np.concatenate([pre, post]))


ap = argparse.ArgumentParser()
ap.add_argument("--levels", default="off,-90,-80,-70,-60,-50", help="keep-alive levels, quietest first")
ap.add_argument("--idle", type=float, default=30, help="silence before each test tone (s)")
ap.add_argument("--reps", type=int, default=2)
a = ap.parse_args()

dev = mic_device()
st = status()
sink, original = st["speaker"]["sink"], st["speaker"]["keepalive_noise_db"]
log.info("calibration start sink=%s levels=%s idle=%s reps=%s", sink, a.levels, a.idle, a.reps)
print("enceinte:", sink)

# Reference: two tones back to back, the second one is played with the amp surely awake.
shot(dev); time.sleep(0.8)
ref = shot(dev)
print("référence (ampli éveillé):", ref)
if not ref["heard"]:
    log.error("reference tone not heard: put the mic against the speaker and check the volume")
    sys.exit(2)

results, chosen = {}, None
for level in a.levels.split(","):
    ctl(action="keepalive_db", value=level)
    rows = []
    for _ in range(a.reps):
        time.sleep(a.idle)
        r = shot(dev)
        r["clipped_ms"] = max(0, ref["dur_ms"] - r["dur_ms"]) if r["heard"] else None
        rows.append(r)
    ok = all(r["heard"] and r["clipped_ms"] <= 40 for r in rows)
    results[level] = {"ok": ok, "shots": rows}
    print(f"niveau {level:>4}: {'OK' if ok else 'COUPÉ'}  {rows}", flush=True)
    log.info("level=%s ok=%s clipped=%s", level, ok, [r["clipped_ms"] for r in rows])
    if ok:
        chosen = level
        break

if chosen is None:
    ctl(action="keepalive_db", value="off" if original is None else original)
    log.warning("no level kept the speaker awake; profile restored to %s", original)
    print("Aucun niveau ne suffit : profil d'origine restauré.")
else:
    print(f"==> niveau retenu : {chosen} (enregistré dans le profil de l'enceinte)")
    log.info("calibration done sink=%s chosen=%s", sink, chosen)

os.makedirs("/opt/robot/nanterino/tests/results", exist_ok=True)
path = time.strftime("/opt/robot/nanterino/tests/results/speaker-calibrate-%Y%m%dT%H%M%SZ.json", time.gmtime())
with open(path, "w") as f:
    json.dump({"sink": sink, "reference": ref, "results": results, "chosen": chosen}, f, indent=2)
print("rapport:", path)
