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

    def __init__(self, device=None, rate: int = 22050, volume: float = 0.8, keepalive_noise_db=None):
        self.device, self.rate, self.volume = device, rate, volume
        # None = digital silence when idle; e.g. -70 = inaudible noise that keeps signal-sensing amps awake.
        self.noise_amp = 10 ** (keepalive_noise_db / 20) if keepalive_noise_db is not None else 0.0
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
        try:
            self.stream = sd.OutputStream(samplerate=self.rate, channels=1, dtype="float32",
                                          device=self.device, blocksize=1024, callback=self._callback)
        except sd.PortAudioError:
            # Raw USB DACs often accept only 44.1/48 kHz: use the device rate, play() resamples.
            fallback = int(sd.query_devices(self.device, "output")["default_samplerate"])
            log.warning("audio out rate %s refused, falling back to %s", self.rate, fallback)
            self.rate = fallback
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
        if self.noise_amp and n < frames:  # fill only the idle part, never on top of speech
            block[n:] = np.random.uniform(-self.noise_amp, self.noise_amp, frames - n).astype(np.float32)
        outdata[:, 0] = block
        self.level = float(np.abs(block).mean()) * 8 if n else 0.0

    def set_keepalive_db(self, db):
        """Live change (no restart). None = digital silence; e.g. -70 = inaudible noise."""
        self.noise_amp = 10 ** (db / 20) if db is not None else 0.0

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


def default_sink() -> str | None:
    """PipeWire node.name of the default sink (e.g. alsa_output.usb-Jieli_..._UACDemoV1.0...)."""
    import subprocess
    try:
        out = subprocess.run(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"], capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if "node.name" in line and "=" in line:
            return line.split("=", 1)[1].strip().strip('"')
    return None


class SpeakerProfiles:
    """Dynamic keep-alive: every 3 s, detect the default speaker and apply its profile live.

    Profiles live in config["speaker_profiles"] keyed by PipeWire node.name; an unknown speaker gets
    config["keepalive_noise_db"] (safe default) until calibrated. Survives hot-plug without restart.
    """

    def __init__(self, cfg, out: AudioOut, save):
        self.cfg, self.out, self.save = cfg, out, save
        self.current = None
        threading.Thread(target=self._watch, daemon=True, name="speaker-watch").start()

    def profile(self, sink=None) -> dict:
        sink = sink or self.current
        return {"keepalive_noise_db": self.cfg["keepalive_noise_db"], "volume": self.cfg["volume"],
                **self.cfg.get("speaker_profiles", {}).get(sink or "", {})}

    def update(self, **changes):
        """Store changes for the current speaker and apply them now."""
        if not self.current:
            return
        profiles = self.cfg.setdefault("speaker_profiles", {})
        profiles.setdefault(self.current, {}).update(changes)
        self.save({"speaker_profiles": profiles})
        self._apply()

    def _apply(self):
        p = self.profile()
        self.out.set_keepalive_db(p["keepalive_noise_db"])
        self.out.volume = p["volume"]
        log.info("speaker profile applied sink=%s keepalive_db=%s volume=%s", self.current, p["keepalive_noise_db"], p["volume"])

    def _watch(self):
        while True:
            sink = default_sink()
            if sink and sink != self.current:
                self.current = sink
                self._apply()
            time.sleep(3)
