#!/usr/bin/env python3
"""Measure whether a USB speaker sleeps when idle (mic placed against the speaker); compares off / silence / noise keep-alive modes

Logs: /var/log/robot/speaker-sleep-test.log (WARNING+ also in errors.log)
"""
import sys
sys.path.insert(0, "/opt/robot/lib")
from robotlog import get_logger

log = get_logger("speaker-sleep-test")

import argparse
import json
import os
import subprocess
import threading
import time

try:
    import numpy as np
    import sounddevice as sd
except ImportError:  # system python lacks numpy/sounddevice: re-run inside the Nanterino venv
    # argv[0] must be the venv path itself, otherwise Python does not detect the venv (exec loop).
    # The env flag guarantees a single re-exec even if the venv is broken.
    VENV_PY = "/opt/robot/nanterino/.venv/bin/python"
    if os.environ.get("ROBOT_REEXEC"):
        raise
    os.environ["ROBOT_REEXEC"] = "1"
    os.execv(VENV_PY, [VENV_PY, *sys.argv])

RATE = 48000
BEEP_S, PAD_S = 0.4, 1.6  # beep length, recording window after the play command
RESULTS = "/opt/robot/nanterino/tests/results"


def beep() -> np.ndarray:
    t = np.arange(int(RATE * BEEP_S)) / RATE
    x = 0.5 * np.sin(2 * np.pi * 1000 * t)
    fade = int(RATE * 0.005)
    x[:fade] *= np.linspace(0, 1, fade); x[-fade:] *= np.linspace(1, 0, fade)
    return x.astype(np.float32)


def tone_envelope(rec: np.ndarray, frame=480) -> np.ndarray:
    """1 kHz energy per 10 ms frame (FFT bin), robust to room noise at other frequencies."""
    n = len(rec) // frame
    frames = rec[: n * frame].reshape(n, frame) * np.hanning(frame)
    spec = np.abs(np.fft.rfft(frames, axis=1))
    k = int(1000 * frame / RATE)
    return spec[:, k - 1:k + 2].max(axis=1)


def measure(rec: np.ndarray, t_play: float) -> dict:
    env = tone_envelope(rec)
    floor = np.median(env[:10]) + 1e-9  # first 100 ms precede the beep
    on = np.where(env > floor * 8)[0]
    if not len(on):
        return {"heard": False}
    return {"heard": True, "onset_ms": int(on[0] * 10 - t_play * 1000), "duration_ms": int(len(on) * 10)}


class Player:
    """Keep-alive output stream (modes 'silence' and 'noise'); beeps are injected into it."""

    def __init__(self, device, noise_db):
        self.buf = np.zeros(0, dtype=np.float32)
        self.lock = threading.Lock()
        self.noise = 10 ** (noise_db / 20) if noise_db is not None else 0.0
        self.stream = sd.OutputStream(samplerate=RATE, channels=1, dtype="float32", device=device, callback=self.cb)
        self.stream.start()

    def cb(self, out, frames, _t, _s):
        with self.lock:
            n = min(frames, len(self.buf)); blk = np.zeros(frames, dtype=np.float32)
            blk[:n] = self.buf[:n]; self.buf = self.buf[n:]
        if self.noise and n < frames:
            blk[n:] = np.random.uniform(-self.noise, self.noise, frames - n)
        out[:, 0] = blk

    def play(self, x):
        with self.lock:
            self.buf = np.concatenate([self.buf, x])

    def close(self):
        self.stream.close()


def one_shot(mode, player, out_dev, in_dev) -> dict:
    """Record 0.1 s before + window after the beep; play via the keep-alive player or a fresh stream."""
    rec = np.zeros(int(RATE * (PAD_S + 0.1)), dtype=np.float32)
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", device=in_dev) as mic:
        mic.read(int(RATE * 0.1))  # flush
        pre = mic.read(int(RATE * 0.1))[0][:, 0]
        if player:
            player.play(beep())
        else:  # 'off' mode: the output device was fully closed during the idle time
            threading.Thread(target=lambda: sd.play(beep(), RATE, device=out_dev, blocking=True), daemon=True).start()
        post = mic.read(int(RATE * PAD_S))[0][:, 0]
    rec = np.concatenate([pre, post])
    return measure(rec, 0.1)


def run(args):
    out_dev = args.out or None
    in_dev = args.mic or None
    modes = args.modes.split(",")
    idles = [float(x) for x in args.idles.split(",")]
    log.info("start modes=%s idles=%s out=%s mic=%s", modes, idles, out_dev, in_dev)
    # The Nanterino service keeps a stream open, which would hide any sleep: stop it during the test.
    was_active = subprocess.run(["systemctl", "--user", "is-active", "--quiet", "nanterino"]).returncode == 0
    if was_active:
        subprocess.run(["systemctl", "--user", "stop", "nanterino"])
    report = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "out": out_dev, "mic": in_dev, "results": {}}
    try:
        for mode in modes:
            player = None if mode == "off" else Player(out_dev, args.noise_db if mode == "noise" else None)
            time.sleep(1)
            ref = one_shot(mode, player, out_dev, in_dev)  # reference right after warm-up
            rows = [{"idle_s": 0, **ref}]
            print(f"\n== mode {mode}  reference: {ref}", flush=True)
            if not ref.get("heard"):
                log.warning("mode=%s reference beep not heard: mic not close to speaker, wrong devices or volume", mode)
            for idle in idles:
                time.sleep(idle)
                r = one_shot(mode, player, out_dev, in_dev)
                if r.get("heard") and ref.get("heard"):
                    r["clipped_ms"] = max(0, ref["duration_ms"] - r["duration_ms"])
                    r["extra_delay_ms"] = r["onset_ms"] - ref["onset_ms"]
                    r["verdict"] = "OK" if r["clipped_ms"] <= 60 and r["extra_delay_ms"] <= 60 else "COUPÉ/RETARD"
                else:
                    r["verdict"] = "MUET" if ref.get("heard") else "?"
                rows.append({"idle_s": idle, **r})
                print(f"   idle {idle:>5.0f}s -> {r}", flush=True)
                log.info("mode=%s idle_s=%s verdict=%s", mode, idle, r["verdict"])
            report["results"][mode] = rows
            if player:
                player.close()
    finally:
        if was_active:
            subprocess.run(["systemctl", "--user", "start", "nanterino"])
    os.makedirs(RESULTS, exist_ok=True)
    path = f"{RESULTS}/speaker-sleep-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    bad = {m: [r for r in rows if r.get("verdict") not in ("OK", None)] for m, rows in report["results"].items()}
    for m, rows in bad.items():
        print(f"{m}: {'OK partout' if not rows else str(len(rows)) + ' problème(s)'}")
        if rows:
            log.warning("mode=%s problems=%d", m, len(rows))
    print("rapport:", path)


ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--out", help="output device name or index (default: PipeWire default)")
ap.add_argument("--mic", help="mic device name or index (default: PipeWire default)")
ap.add_argument("--modes", default="off,silence,noise")
ap.add_argument("--idles", default="5,30,120,300,600", help="idle durations in seconds")
ap.add_argument("--noise-db", type=float, default=-70.0)
a = ap.parse_args()
a.out = int(a.out) if a.out and a.out.isdigit() else a.out
a.mic = int(a.mic) if a.mic and a.mic.isdigit() else a.mic
run(a)
