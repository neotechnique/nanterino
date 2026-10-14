"""Clients for the local AI engines (all on the Jetson, no Internet).

logging: robotlog via nanterino.log. Only durations/sizes are logged, never text content.
- STT: whisper.cpp `whisper-server` (CUDA) on 127.0.0.1:8178
- LLM: llama.cpp `llama-server` (CUDA, OpenAI-compatible) on 127.0.0.1:8179
- TTS: Piper (CPU), French voice fr_FR-siwis-medium
"""
import io
import json
import re
import time
import wave

import numpy as np
import requests

from .log import log

SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


class STT:
    def __init__(self, url: str):
        self.url = url

    def transcribe(self, pcm: np.ndarray, rate: int = 16000) -> str:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:  # in-memory WAV, never written to disk
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
            w.writeframes(pcm.tobytes())
        t0 = time.monotonic()
        r = requests.post(self.url, files={"file": ("u.wav", buf.getvalue(), "audio/wav")},
                          data={"language": "fr", "temperature": "0", "response_format": "json"},
                          timeout=30)
        r.raise_for_status()
        log.info("stt done audio_s=%.1f took_ms=%d", len(pcm) / rate, (time.monotonic() - t0) * 1000)
        return r.json().get("text", "").strip()

    def ready(self) -> bool:
        try:
            return requests.get(self.url.rsplit("/", 1)[0] + "/", timeout=2).status_code < 500
        except requests.RequestException:
            return False


class LLM:
    def __init__(self, url: str):
        self.url = url

    def stream(self, messages: list[dict], max_tokens: int = 160):
        """Yield text deltas as they arrive (server-sent events)."""
        body = {"messages": messages, "stream": True, "temperature": 0.3, "max_tokens": max_tokens}
        with requests.post(self.url, json=body, stream=True, timeout=60) as r:
            r.raise_for_status()
            r.encoding = "utf-8"  # SSE has no charset header; requests would guess Latin-1
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                delta = json.loads(data)["choices"][0].get("delta", {}).get("content")
                if delta:
                    yield delta

    def sentences(self, messages: list[dict]):
        """Group the stream into complete sentences so TTS can start on the first one."""
        pending = ""
        for delta in self.stream(messages):
            pending += delta
            parts = SENTENCE_END.split(pending)
            for sentence in parts[:-1]:
                if sentence.strip():
                    yield sentence.strip()
            pending = parts[-1]
        if pending.strip():
            yield pending.strip()

    def ready(self) -> bool:
        try:
            return requests.get(self.url.split("/v1/")[0] + "/health", timeout=2).ok
        except requests.RequestException:
            return False


class TTS:
    def __init__(self, voice_path: str):
        from piper import PiperVoice  # heavy import kept local
        t0 = time.monotonic()
        self.voice = PiperVoice.load(voice_path)
        self.rate = self.voice.config.sample_rate
        log.info("tts voice loaded rate=%s took_ms=%d", self.rate, (time.monotonic() - t0) * 1000)
        self.synth("Bonjour.")  # warm-up: the first ONNX run is ~2x slower than the next ones

    def synth(self, text: str) -> np.ndarray:
        t0 = time.monotonic()
        if hasattr(self.voice, "synthesize") and not hasattr(self.voice, "synthesize_stream_raw"):
            # piper-tts >= 1.3: iterable of AudioChunk
            pcm = np.concatenate([c.audio_int16_array for c in self.voice.synthesize(text)])
        else:
            raw = b"".join(self.voice.synthesize_stream_raw(text))
            pcm = np.frombuffer(raw, dtype=np.int16)
        log.info("tts done chars=%d audio_s=%.1f took_ms=%d", len(text), len(pcm) / self.rate,
                 (time.monotonic() - t0) * 1000)
        return pcm
