#!/usr/bin/env python3
"""Scan French Piper voices/speakers for a warm, well-articulated FEMALE voice (2026-10-16).

logging: robotlog via nanterino.log. Per candidate: median pitch (female > 165 Hz), Whisper
word error rate on 3 test phrases (articulation), spectral "warmth" = energy 150-1000 Hz vs
2-6 kHz (dB, higher = warmer/less shrill). Writes samples for the best ones to song/voices/.
"""
import os
import re
import unicodedata
import wave

import numpy as np
import pyworld
from piper import PiperVoice
from piper.config import SynthesisConfig

from nanterino.engines import STT

M = "/opt/robot/nanterino/models/piper"
OUT = "/opt/robot/nanterino/song/voices"
PHRASES = ["Bonjour, je suis Nanterino, le petit robot de Nanterre.",
           "Triez vos déchets et prenez soin de la planète.",
           "Le parc André-Malraux est juste à côté de La Défense."]
DEMO = "Bonjour ! Je suis Nanterino. Je connais les parcs de Nanterre et les bons gestes pour la planète."
stt = STT("http://127.0.0.1:8178/inference")


def words(s):
    s = unicodedata.normalize("NFD", s.lower().replace("œ", "oe"))
    return re.findall(r"[a-z]+", "".join(c for c in s if unicodedata.category(c) != "Mn"))


def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    d = np.arange(len(h) + 1)
    for i, rw in enumerate(r, 1):
        prev, d[0] = d.copy(), i
        for j, hw in enumerate(h, 1):
            d[j] = min(prev[j] + 1, d[j - 1] + 1, prev[j - 1] + (rw != hw))
    return d[len(h)] / max(1, len(r))


def synth(voice, text, sid):
    cfg = SynthesisConfig(speaker_id=sid) if sid is not None else None
    return np.concatenate([c.audio_int16_array for c in voice.synthesize(text, syn_config=cfg)]), voice.config.sample_rate


def measure(voice, sid):
    errs, f0s, warm = [], [], []
    for ph in PHRASES:
        pcm, fs = synth(voice, ph, sid)
        x16 = pcm[np.linspace(0, len(pcm), int(len(pcm) * 16000 / fs), endpoint=False).astype(int)]
        errs.append(wer(ph, stt.transcribe(x16.astype(np.int16), 16000)))
        x = pcm.astype(np.float64) / 32768
        f0, _ = pyworld.dio(x, fs, frame_period=10)
        f0s.extend(f0[f0 > 0])
        spec = np.abs(np.fft.rfft(x)) ** 2
        f = np.fft.rfftfreq(len(x), 1 / fs)
        warm.append(10 * np.log10(spec[(f > 150) & (f < 1000)].sum() / spec[(f > 2000) & (f < 6000)].sum()))
    return float(np.mean(errs)), float(np.median(f0s)), float(np.mean(warm))


def save(path, pcm, fs):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fs); w.writeframes(pcm.astype(np.int16).tobytes())


os.makedirs(OUT, exist_ok=True)
rows = []
for model in ("siwis", "upmc", "mls"):
    voice = PiperVoice.load(f"{M}/fr_FR-{model}-medium.onnx")
    ids = voice.config.speaker_id_map or {"-": None}
    for name, sid in ids.items():
        e, f0, w = measure(voice, sid)
        rows.append((model, name, sid, e, f0, w))
        print(f"{model:6} {name:8} wer={e:4.0%} f0={f0:5.0f}Hz warmth={w:5.1f}dB", flush=True)

female = [r for r in rows if r[4] > 165]
# Rank: articulation first (WER), then warmth.
female.sort(key=lambda r: (round(r[3], 2), -r[5]))
print("\nTOP (female, best articulation then warmth):")
for model, name, sid, e, f0, w in female[:8]:
    print(f"{model:6} {name:8} wer={e:4.0%} f0={f0:5.0f}Hz warmth={w:5.1f}dB")
for model, name, sid, e, f0, w in female[:5] + [r for r in rows if r[0] == "siwis"]:
    voice = PiperVoice.load(f"{M}/fr_FR-{model}-medium.onnx")
    pcm, fs = synth(voice, DEMO, sid)
    save(f"{OUT}/voix-{model}-{name}.wav", pcm, fs)
print("samples in", OUT)

