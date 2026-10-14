"""Audio input/output.

logging: robotlog via nanterino.log.

Output: ONE stream stays open for the whole process and plays silence when idle, so neither
PipeWire nor the speaker suspends and clips the first syllable (Pi lesson, persistent player).
Input: 16 kHz mono capture, webrtcvad end-of-speech detection. Captured audio exists in RAM
only and is dropped right after transcription (privacy, cahier §7).
"""
import collections
import io
import itertools
import queue
import threading
import time
import wave

import numpy as np
import sounddevice as sd
import webrtcvad

from .log import log


def list_devices() -> list[dict]:
    devs = []
    for i, d in enumerate(sd.query_devices()):
        devs.append({"index": i, "name": d["name"], "inputs": d["max_input_channels"],
                     "outputs": d["max_output_channels"], "rate": int(d["default_samplerate"])})
    return devs


def find_device(name: str | None, kind: str):
    """Match a device by name substring; None keeps the PipeWire default."""
    if not name:
        return None
    key = "inputs" if kind == "input" else "outputs"
    for d in list_devices():
        if name.lower() in d["name"].lower() and d[key] > 0:
            return d["index"]
    log.warning("audio device not found kind=%s name=%s, using default", kind, name)
    return None


class AudioOut:
    """Persistent, interruptible player. `level` drives the mouth animation."""

    def __init__(self, device=None, rate: int = 22050, volume: float = 0.8):
        self.device, self.rate, self.volume = device, rate, volume
        self._chunks: queue.Queue = queue.Queue()
        self._buf = np.zeros(0, dtype=np.float32)
        self._lock = threading.Lock()
        self.level = 0.0
        self.stream = None
        # Remote monitor (Pi "casque PC" equivalent): last clips as WAV bytes, RAM only, never on disk.
        self.monitor = collections.deque(maxlen=10)
        self._clip_ids = itertools.count(1)

    def start(self):
        self.close()
        self.stream = sd.OutputStream(samplerate=self.rate, channels=1, dtype="float32",
                                      device=self.device, blocksize=1024, callback=self._callback)
        self.stream.start()
        log.info("audio out open device=%s rate=%s", self.device, self.rate)

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None

    def _callback(self, outdata, frames, _time, status):
        if status:
            log.warning("audio out status=%s", status)
        with self._lock:
            while len(self._buf) < frames and not self._chunks.empty():
                self._buf = np.concatenate([self._buf, self._chunks.get_nowait()])
            n = min(frames, len(self._buf))
            block = np.zeros(frames, dtype=np.float32)
            block[:n] = self._buf[:n] * self.volume
            self._buf = self._buf[n:]
        outdata[:, 0] = block
        self.level = float(np.abs(block).mean()) * 8 if n else 0.0

    def play(self, pcm: np.ndarray, rate: int):
        """Queue int16 PCM; resampled linearly if the voice rate differs from the stream."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm.astype(np.int16).tobytes())
        self.monitor.append((next(self._clip_ids), buf.getvalue()))
        x = pcm.astype(np.float32) / 32768.0
        if rate != self.rate and len(x):
            t = np.linspace(0, len(x), int(len(x) * self.rate / rate), endpoint=False)
            x = np.interp(t, np.arange(len(x)), x).astype(np.float32)
        self._chunks.put(x)

    def stop(self):
        """Barge-in / emergency stop: drop everything not yet played (< 1 block of latency)."""
        with self._lock:
            while not self._chunks.empty():
                self._chunks.get_nowait()
            self._buf = np.zeros(0, dtype=np.float32)

    @property
    def busy(self) -> bool:
        return len(self._buf) > 0 or not self._chunks.empty()


class AudioIn:
    """Microphone -> VAD -> complete utterances (int16 @16 kHz) via callbacks. Starts OFF."""

    RATE, FRAME_MS = 16000, 30

    def __init__(self, on_utterance, on_speech_start=None, device=None,
                 silence_ms: int = 800, max_s: int = 10, aggressiveness: int = 2):
        self.on_utterance, self.on_speech_start = on_utterance, on_speech_start
        self.device, self.silence_ms, self.max_s = device, silence_ms, max_s
        self.vad = webrtcvad.Vad(aggressiveness)
        self.frame_len = self.RATE * self.FRAME_MS // 1000
        self.stream = None
        self.level = 0.0
        self._out: queue.Queue = queue.Queue()
        self._reset()
        threading.Thread(target=self._worker, daemon=True, name="stt-dispatch").start()

    def _reset(self):
        self._speech: list[bytes] = []
        self._pre = collections.deque(maxlen=10)  # 300 ms kept before speech onset
        self._silent_ms = 0
        self._in_speech = False

    @property
    def active(self) -> bool:
        return self.stream is not None

    def start(self):
        if self.stream:
            return
        self._reset()
        self.stream = sd.RawInputStream(samplerate=self.RATE, channels=1, dtype="int16",
                                        blocksize=self.frame_len, device=self.device,
                                        callback=self._callback)
        self.stream.start()
        log.info("mic open device=%s", self.device)

    def stop(self):
        if self.stream:
            self.stream.close()
            self.stream = None
            self._reset()
            log.info("mic closed")

    def _callback(self, indata, frames, _time, status):
        frame = bytes(indata)
        if len(frame) != self.frame_len * 2:
            return
        self.level = float(np.abs(np.frombuffer(frame, dtype=np.int16)).mean()) / 3000
        speech = self.vad.is_speech(frame, self.RATE)
        if not self._in_speech:
            self._pre.append(frame)
            if speech:
                self._in_speech, self._speech = True, list(self._pre)
                if self.on_speech_start:
                    self.on_speech_start()
            return
        self._speech.append(frame)
        self._silent_ms = 0 if speech else self._silent_ms + self.FRAME_MS
        too_long = len(self._speech) * self.FRAME_MS >= self.max_s * 1000
        if self._silent_ms >= self.silence_ms or too_long:
            pcm = np.frombuffer(b"".join(self._speech), dtype=np.int16)
            self._reset()
            if len(pcm) > self.RATE * 0.4:  # ignore clicks shorter than 400 ms
                self._out.put((pcm, time.monotonic()))

    def _worker(self):
        # Transcription runs outside the audio callback to never block capture.
        while True:
            pcm, t_end = self._out.get()
            try:
                self.on_utterance(pcm, t_end)
            except Exception:
                log.exception("utterance handler failed")
