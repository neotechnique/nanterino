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
    def __init__(self, url: str, prompt: str = ""):
        self.url = url
        self.prompt = prompt  # optional vocabulary hint (whisper.cpp server "prompt" field)

    def transcribe(self, pcm: np.ndarray, rate: int = 16000) -> str:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:  # in-memory WAV, never written to disk
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
            w.writeframes(pcm.tobytes())
        t0 = time.monotonic()
        r = requests.post(self.url, files={"file": ("u.wav", buf.getvalue(), "audio/wav")},
                          data={"language": "fr", "temperature": "0", "response_format": "json",
                                **({"prompt": self.prompt} if self.prompt else {})},
                          timeout=30)
        r.raise_for_status()
        text = r.json().get("text", "").strip()
        # Privacy (spec §7): word count only, never the text.
        log.info("stt done audio_s=%.1f took_ms=%d words=%d", len(pcm) / rate, (time.monotonic() - t0) * 1000, len(text.split()))
        return text

    def ready(self) -> bool:
        try:
            return requests.get(self.url.rsplit("/", 1)[0] + "/", timeout=2).status_code < 500
        except requests.RequestException:
            return False


class LLM:
    def __init__(self, url: str, options: dict | None = None):
        self.url = url
        # Sampling and template options merged into every request (config "llm_options").
        # LFM3 reasons in a <think> block by default: enable_thinking=false asks the template to skip
        # it, and stream() still drops any <think>...</think> text in case the model ignores that.
        self.options = dict(options or {"temperature": 0.3})

    def stream(self, messages: list[dict], max_tokens: int = 160):
        """Yield answer text deltas as they arrive (server-sent events), reasoning removed."""
        body = {**self.options, "messages": messages, "stream": True, "max_tokens": max_tokens}
        thinking, pending = False, ""
        for delta in self._raw_stream(body):
            pending += delta
            out = ""
            while pending:
                if thinking:
                    end = pending.find("</think>")
                    if end < 0:
                        pending = pending[-len("</think>"):]  # keep a possible split closing tag
                        break
                    pending, thinking = pending[end + len("</think>"):], False
                else:
                    start = pending.find("<think>")
                    if start >= 0:
                        out += pending[:start]
                        pending, thinking = pending[start + len("<think>"):], True
                        continue
                    cut = pending.rfind("<")  # a tag may be split across two deltas
                    if cut >= 0 and "<think>".startswith(pending[cut:]):
                        out, pending = out + pending[:cut], pending[cut:]
                    else:
                        out, pending = out + pending, ""
                    break
            if out:
                yield out
        if pending and not thinking:
            yield pending

    def _raw_stream(self, body: dict):
        """Yield raw content deltas from llama-server."""
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
        # GPU path (CPU front + TensorRT vocoder, ~5x faster, parity corr >= 0.999); CPU fallback.
        self.gpu = None
        try:
            from .tts_trt import PiperTRT
            self.gpu = PiperTRT(self.voice)
        except Exception as e:
            log.warning("piper gpu unavailable (%s): CPU voice", e)
        self.backend = "tensorrt-gpu" if self.gpu else "onnx-cpu"
        log.info("tts voice loaded rate=%s backend=%s took_ms=%d", self.rate, self.backend, (time.monotonic() - t0) * 1000)
        self.synth("Bonjour.")  # warm-up: the first ONNX run is ~2x slower than the next ones

    def synth(self, text: str) -> np.ndarray:
        t0 = time.monotonic()
        if self.gpu is not None:
            try:
                pcm = self.gpu.synth(text)
                log.info("tts done backend=gpu chars=%d audio_s=%.1f took_ms=%d", len(text), len(pcm) / self.rate,
                         (time.monotonic() - t0) * 1000)
                return pcm
            except Exception as e:  # e.g. very long sentence beyond the engine profile
                log.warning("piper gpu failed (%s): CPU for this sentence", e)
        if hasattr(self.voice, "synthesize") and not hasattr(self.voice, "synthesize_stream_raw"):
            # piper-tts >= 1.3: iterable of AudioChunk
            pcm = np.concatenate([c.audio_int16_array for c in self.voice.synthesize(text)])
        else:
            raw = b"".join(self.voice.synthesize_stream_raw(text))
            pcm = np.frombuffer(raw, dtype=np.int16)
        log.info("tts done chars=%d audio_s=%.1f took_ms=%d", len(text), len(pcm) / self.rate,
                 (time.monotonic() - t0) * 1000)
        return pcm
