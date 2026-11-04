"""Generic N-channel microphone array backend (lot C2): capture thread + DOA (doa.py) -> latest Reading.

logging: robotlog via nanterino.log.

Purpose
    `ArraySoundSource(geometry)` captures `geometry.channels` channels through sounddevice (PortAudio: ALSA or
    PipeWire, device matched by `geometry.device` like cfg["mic_device"]), cuts frames of `frame` samples every `hop`
    samples, runs DoaEstimator.analyse() + CircularSmoother on a worker thread and keeps the latest Reading for
    poll(). process_block() is the same path without a device (tests feed synthetic multi-channel signals).
Boundary
    Only start() touches hardware, and only server.py calls start() when cfg["sound_backend"] == "array" (the live
    robot stays on `mono` until the spatial microphone is known). Captured audio stays in RAM (one frame), never on
    disk - the same privacy rule as nanterino/audio.py.
Invariants
    - the PortAudio callback only copies into a bounded queue (a slow analysis drops frames, never blocks audio);
    - stats() reports frames analysed, frames dropped and the CPU time per frame (thread_time, mean / max), the
      figure the CPU budget is checked against;
    - a failing analysis is logged at most once per 5 s and leaves the previous Reading in place.
How to test
    .venv/bin/python -m tests.test_sound   (process_block on synthetic plane waves; no device is opened)
"""
import queue
import threading
import time

import numpy as np

from ..log import log
from .doa import CircularSmoother, DoaEstimator
from .sources import Reading, SoundSource


class ArraySoundSource(SoundSource):
    name = "array"
    gives_direction = True

    def __init__(self, geometry, device_index=None):
        self.geom = geometry
        self.est = DoaEstimator(geometry)
        self.smooth = CircularSmoother(geometry.smoothing)
        self.device_index = device_index
        self._lock = threading.Lock()
        self._latest = None
        self._q = queue.Queue(maxsize=8)
        self._buf = np.zeros((0, geometry.channels), dtype=np.float32)
        self._stream, self._thread, self._stop = None, None, threading.Event()
        self._frames = self._dropped = 0
        self._cpu_sum = self._cpu_max = 0.0
        self._err_at = -1e9

    # ------------------------------------------------------------------ analysis (no device)
    def process_block(self, block, t=None) -> Reading:
        """Analyse one (frame, channels) block now and make it the latest Reading."""
        t = time.monotonic() if t is None else t
        c0 = time.thread_time()
        res = self.est.analyse(block)
        az = self.smooth.update(res["azimuth_deg"], res["confidence"], t)
        r = Reading(t=t, azimuth_deg=az, level_db=res["level_db"], confidence=res["confidence"] if az is not None else 0.0,
                    voice_prob=res["voice_prob"])
        dt = time.thread_time() - c0
        with self._lock:
            self._latest = r
            self._frames += 1
            self._cpu_sum += dt
            self._cpu_max = max(self._cpu_max, dt)
        return r

    def poll(self, now):
        with self._lock:
            return self._latest

    def stats(self) -> dict:
        with self._lock:
            n = self._frames
            return {"frames": n, "dropped": self._dropped, "cpu_ms_mean": round(1000 * self._cpu_sum / n, 3) if n else None,
                    "cpu_ms_max": round(1000 * self._cpu_max, 3) if n else None,
                    "frame_ms": round(1000.0 * self.geom.frame / self.geom.rate, 1),
                    "hop_ms": round(1000.0 * self.geom.hop / self.geom.rate, 1)}

    def info(self):
        g = self.geom
        return {"name": self.name, "gives_direction": True, "detail": "%s : %d micros, %d Hz" % (g.name, len(g.positions), g.rate),
                "geometry": g.source, "stats": self.stats()}

    # ------------------------------------------------------------------ capture (hardware)
    def start(self):
        import sounddevice as sd   # lazy: importing this module must never need audio hardware
        from ..audio import find_device
        dev = self.device_index if self.device_index is not None else find_device(self.geom.device, "input")
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="sound-array")
        self._thread.start()
        self._stream = sd.InputStream(device=dev, channels=self.geom.channels, samplerate=self.geom.rate,
                                      blocksize=self.geom.hop, dtype="float32", callback=self._callback)
        self._stream.start()
        log.info("sound array capture started device=%s channels=%d rate=%d", dev, self.geom.channels, self.geom.rate)

    def stop(self):
        self._stop.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:   # noqa: BLE001
                log.exception("sound array stream close failed")
            self._stream = None

    def _callback(self, indata, frames, _time, status):
        try:
            self._q.put_nowait(indata.copy())
        except queue.Full:
            with self._lock:
                self._dropped += 1

    def _worker(self):
        g = self.geom
        while not self._stop.is_set():
            try:
                chunk = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            self._buf = np.concatenate([self._buf, chunk])[-2 * g.frame:]
            if len(self._buf) >= g.frame:
                try:
                    self.process_block(self._buf[-g.frame:])
                except Exception:   # noqa: BLE001
                    now = time.monotonic()
                    if now - self._err_at > 5:
                        self._err_at = now
                        log.exception("sound array analysis failed")
