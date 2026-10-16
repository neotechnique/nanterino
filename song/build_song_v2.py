#!/usr/bin/env python3
"""Voice-first Nanterino song: the VOICE sets the timing, the music is built around it.

User priority (2026-10-16): "c'est la chansonnette qui suit la voix et pas l'inverse".
  1. Each lyric line is spoken by Piper at its NATURAL speed (best articulation), with each
     syllable region tuned to its melody note (sung-spoken) and the last vowel held briefly.
  2. Each line then gets as many whole bars as it needs; chords follow the line, and the
     vibraphone doubles exactly the syllables Nanterino sings (onsets measured on the voice).
  3. The backing is rendered with the user's soundgen tool, mixed under the voice (ducked).

Usage (Jetson): PYTHONPATH=/opt/robot/nanterino .venv/bin/python song/build_song_v2.py [spec.json]
Writes media/chanson-nanterino.wav + .json (lyric timings for the face subtitles).
logging: robotlog via nanterino.log.
"""
import json
import math
import os
import subprocess
import sys
import wave

import numpy as np
import pyworld
from piper import PiperVoice
from piper.config import SynthesisConfig

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_song import CHORDS, FRAME_MS, SOUNDGEN, midi, nuclei, read_wav, resample  # noqa: E402
from nanterino.log import log  # noqa: E402

ROOT = "/opt/robot/nanterino"
VOCAL_RMS, MUSIC_GAIN, DUCK = 0.30, 0.8, 0.45  # v3: gentler ducking (less "flat")
# Warm voicings: (piano/strings voicing with 7ths, guitar arpeggio notes, bass root).
WARM = {
    "C": ("C3+G3+E4+B4", "C3 G3 E4 B4 C5", "C2"), "Am": ("A2+E3+C4+G4", "A2 E3 C4 G4 A4", "A1"),
    "F": ("F2+C3+A3+E4", "F2 C3 A3 E4 F4", "F1"), "G": ("G2+D3+B3+F4", "G2 D3 B3 F4 G4", "G1"),
    "Em": ("E2+B2+G3+D4", "E2 B2 G3 D4 E4", "E2"), "Dm": ("D2+A2+F3+C4", "D2 A2 F3 C4 D4", "D2"),
}
TAKES = 4  # max takes per distinct line (best one by Whisper word error rate)
HOLD_S = 0.45  # final vowel held this long (sung feel) when the bar leaves room


class Singer:
    """Piper voice (any model/speaker) -> WORLD parameters."""

    def __init__(self, model: str, speaker=None):
        self.voice = PiperVoice.load(model)
        ids = self.voice.config.speaker_id_map or {}
        self.sid = ids.get(str(speaker)) if speaker is not None else None
        self.cfg = SynthesisConfig(speaker_id=self.sid) if self.sid is not None else None
        self.rate = self.voice.config.sample_rate

    def analyse(self, text):
        pcm = np.concatenate([c.audio_int16_array for c in self.voice.synthesize(text, syn_config=self.cfg)])
        x = pcm.astype(np.float64) / 32768
        f0, t = pyworld.harvest(x, self.rate, frame_period=FRAME_MS, f0_floor=70, f0_ceil=700)
        return f0, pyworld.cheaptrick(x, f0, t, self.rate), pyworld.d4c(x, f0, t, self.rate)


def sing(singer, text, pitches, transpose):
    """-> (float32 audio, lead_s, syllable events [(t_s, midi)]) ; t=0 = first nucleus - 40 ms."""
    f0, sp, ap = singer.analyse(text)
    fr = FRAME_MS / 1000
    voiced = np.flatnonzero(f0 > 0)
    first = max(0, voiced[0] - int(0.18 / fr))  # keep unvoiced onsets ("Tr" of "Triez")
    last = min(len(f0) - 1, voiced[-1] + int(0.08 / fr))
    p = np.round(nuclei(f0, sp, len(pitches)) / fr).astype(int)
    seg = np.arange(first, last + 1)  # natural timing: no stretch at all
    log_sp = np.log(sp + 1e-12)
    sp_o, ap_o, vo_o = log_sp[seg], ap[seg], f0[seg] > 0
    bounds = np.concatenate([[first], (p[:-1] + p[1:]) / 2, [last + 1]])
    k_of = np.clip(np.searchsorted(bounds, seg, side="right") - 1, 0, len(pitches) - 1)
    # Short steady hold of the last vowel (one averaged timbre: no warble), soft release.
    n_hold = int(HOLD_S / fr)
    pk = p[-1]
    cut = min(len(seg), int(pk + 4 - first))
    v0, v1 = max(first, pk - 3), min(last + 1, pk + 4)
    vowel_sp, vowel_ap = log_sp[v0:v1].mean(axis=0), ap[v0:v1].mean(axis=0)
    ramp = np.clip(np.arange(n_hold) / 6.0, 0, 1)[:, None]
    fade = np.clip((n_hold - np.arange(n_hold)) / 25.0, 0.02, 1)
    hold_sp = (1 - ramp) * sp_o[cut - 1] + ramp * vowel_sp + np.log(fade)[:, None]
    tail = np.arange(cut, len(seg))  # consonants after the last vowel, played after the hold
    sp_o = np.concatenate([sp_o[:cut], hold_sp, sp_o[tail]])
    ap_o = np.concatenate([ap_o[:cut], np.repeat(vowel_ap[None], n_hold, 0), ap_o[tail]])
    vo_o = np.concatenate([vo_o[:cut], np.ones(n_hold, bool), vo_o[tail]])
    k_of = np.concatenate([k_of[:cut], np.full(n_hold, len(pitches) - 1), k_of[tail]])
    target = 440 * 2 ** ((np.array([pitches[k] for k in k_of]) + transpose - 69) / 12)
    glide, g, a = np.empty_like(target), target[0], 1 - np.exp(-FRAME_MS / 35.0)
    for i, v in enumerate(target):
        g += a * (v - g)
        glide[i] = g
    y = pyworld.synthesize(np.ascontiguousarray(np.where(vo_o, glide, 0.0)), np.ascontiguousarray(np.exp(sp_o)),
                           np.ascontiguousarray(np.clip(ap_o, 0, 1)), singer.rate, FRAME_MS)
    lead = (p[0] - first) * fr - 0.04
    # Syllable onsets on the OUTPUT timeline (relative to the first nucleus - 40 ms).
    starts = [int(np.searchsorted(k_of, k)) for k in range(len(pitches))]
    events = [(s * fr - lead, pitches[k] + transpose) for k, s in enumerate(starts)]
    return y.astype(np.float32), lead, events


def _biquad(kind, f0, gain_db, q, rate):
    """RBJ cookbook peaking / low-shelf coefficients (b, a)."""
    A, w = 10 ** (gain_db / 40), 2 * np.pi * f0 / rate
    cw, sw = np.cos(w), np.sin(w)
    if kind == "peak":
        al = sw / (2 * q)
        b = [1 + al * A, -2 * cw, 1 - al * A]; a = [1 + al / A, -2 * cw, 1 - al / A]
    else:  # low shelf, slope 1
        al = sw / 2 * np.sqrt(2)
        b = [A * ((A + 1) - (A - 1) * cw + 2 * np.sqrt(A) * al), 2 * A * ((A - 1) - (A + 1) * cw),
             A * ((A + 1) - (A - 1) * cw - 2 * np.sqrt(A) * al)]
        a = [(A + 1) + (A - 1) * cw + 2 * np.sqrt(A) * al, -2 * ((A - 1) + (A + 1) * cw),
             (A + 1) + (A - 1) * cw - 2 * np.sqrt(A) * al]
    return np.array(b) / a[0], np.array(a) / a[0]


def warm_voice(x, rate):
    """Make the WORLD voice less hollow/thin (user v3: "trop creux, pas assez chaleureux").

    Body (+4 dB low shelf 280 Hz), less nasal box (-2.5 dB at 1 kHz), softer edge (-3 dB at
    4 kHz), a quiet 22 ms double (fuller, chorus-like) and a short warm room (0.9 s tail).
    """
    from scipy.signal import fftconvolve, lfilter
    for kind, f0, g, q in (("shelf", 280, 4.0, 0.7), ("peak", 1000, -2.5, 1.0), ("peak", 4000, -3.0, 1.2)):
        b, a = _biquad(kind, f0, g, q, rate)
        x = lfilter(b, a, x)
    d = int(0.022 * rate)
    double = np.concatenate([np.zeros(d), x[:-d]]) * 0.28
    rng = np.random.default_rng(3)
    t = np.arange(int(0.9 * rate)) / rate
    ir = rng.standard_normal(len(t)) * np.exp(-t / 0.22)
    b, a = _biquad("peak", 3000, -9, 0.5, rate)  # dark reverb tail
    ir = lfilter(b, a, ir)
    ir /= np.sqrt((ir ** 2).sum())
    wet = fftconvolve(x, ir)[: len(x)] * 0.16
    return (x + double + wet).astype(np.float32)


def auto_transpose(singer, lines):
    f0, _, _ = singer.analyse(lines[0]["say"])
    voice_midi = 69 + 12 * np.log2(np.median(f0[f0 > 0]) / 440)
    melody_midi = np.median([m for ln in lines for m in ln["pitches"]])
    shift = int(12 * round((voice_midi + 3 - melody_midi) / 12))
    log.info("song v2 transpose voice_midi=%.1f melody_midi=%.1f shift=%d", voice_midi, melody_midi, shift)
    return shift


def main():
    spec_path = sys.argv[1] if len(sys.argv) > 1 else f"{ROOT}/song/chanson.json"
    spec = json.load(open(spec_path, encoding="utf-8"))
    bpm = spec["bpm"]
    spb = 60 / bpm
    bar_s = 4 * spb
    v = spec.get("voice", {})
    singer = Singer(f"{ROOT}/models/piper/{v.get('model', 'fr_FR-siwis-medium.onnx')}", v.get("speaker"))
    lines = [{"text": ln["text"], "say": ln.get("say") or ln["text"].replace("-", ""),
              "pitches": [midi(t.split(":")[0]) for t in ln["notes"].split()], "section": si, "idx": li}
             for si, sec in enumerate(spec["sections"]) for li, ln in enumerate(sec.get("lines", []))]
    transpose = auto_transpose(singer, lines) if spec.get("vocal_transpose", "auto") == "auto" else spec["vocal_transpose"]

    # 1) Voice first: render every line at its natural speed. Piper is random (noise sampling),
    # so each distinct line is sung TAKES times and the take Whisper understands best is kept;
    # repeated lines (refrains) reuse that same best take (2026-10-16: refrain 1 perfect,
    # refrain 2 garbled with the same text).
    from listen_song import wer
    from nanterino.engines import STT
    stt = STT("http://127.0.0.1:8178/inference")
    best = {}
    for ln in lines:
        key = (ln["say"], tuple(ln["pitches"]))
        if key not in best:
            takes = []
            for _ in range(TAKES):
                y, lead, ev = sing(singer, ln["say"], ln["pitches"], transpose)
                x16 = y[np.linspace(0, len(y), int(len(y) * 16000 / singer.rate), endpoint=False).astype(int)]
                heard = stt.transcribe((np.clip(x16, -1, 1) * 32767).astype(np.int16), 16000)
                takes.append((wer(ln["text"].replace("-", ""), heard), y, lead, ev))
                if takes[-1][0] == 0:
                    break  # perfect take: no need for more
            takes.sort(key=lambda t: t[0])
            best[key] = takes[0][1:]
            log.info("song take chosen wer=%.2f of %d takes", takes[0][0], len(takes))
        ln["audio"], ln["lead"], ln["events"] = best[key]
        ln["dur"] = len(ln["audio"]) / singer.rate - ln["lead"]

    # 2) Arrangement around the voice: whole bars per line, chords follow the line.
    bars, placed, bar = [], [], 0
    for si, sec in enumerate(spec["sections"]):
        chords, sec_lines = sec["chords"], [ln for ln in lines if ln["section"] == si]
        drums = sec.get("drums", True)
        # Section energy drives the arrangement (v3 "pas tout au même niveau"):
        # intro/end soft, couplet light, refrain full.
        kind = "chorus" if "refrain" in sec["name"] else ("verse" if "couplet" in sec["name"] else "soft")
        if not sec_lines:  # instrumental section (intro)
            bars += [{"chord": c, "drums": drums, "kind": kind} for c in chords]
            bar += len(chords)
            continue
        for ln in sec_lines:
            n = max(1, math.ceil((ln["dur"] + 0.25) / bar_s))
            own = chords[2 * ln["idx"] % len(chords): 2 * ln["idx"] % len(chords) + 2] or chords[:2]
            bars += [{"chord": own[min(i, len(own) - 1)] if n <= len(own) else own[i % len(own)], "drums": drums, "kind": kind} for i in range(n)]
            placed.append((bar, ln))
            bar += n
        bars.append({"chord": chords[-1], "drums": drums, "kind": kind})  # one breathing bar between sections
        bar += 1
    bars += [{"chord": "C", "drums": False, "kind": "soft"}, {"chord": "C", "drums": False, "kind": "soft"}]  # ending

    # Vibraphone doubling = the measured syllable onsets of the voice.
    notes = []
    for b0, ln in placed:
        if bars[b0]["kind"] != "chorus":
            continue  # melody doubling only in the refrains (lighter verses)
        for i, (t, m) in enumerate(ln["events"]):
            t_next = ln["events"][i + 1][0] if i + 1 < len(ln["events"]) else ln["dur"]
            notes.append((b0 * 4 + t / spb, max(0.25, (t_next - t) / spb), m + 12))  # an octave above the voice
    mel, cursor = [], 0.0
    for beat, dur, m in sorted(notes):
        if beat > cursor + 1e-3:
            mel.append(f"r:{beat - cursor:.4f}")
        elif beat < cursor:
            continue
        mel.append(f"{440 * 2 ** ((m - 69) / 12):.3f}:{dur:.4f}")
        cursor = beat + dur
    # v3 arrangement (user: "tout au même niveau, trop creux, pas assez chaleureux"):
    # warm 7th chords, acoustic piano + nylon guitar arpeggios, sustained bass in verses,
    # strings + soft "ooh" choir + full drums only in the refrains -> real dynamics.
    piano, guitar, bass, drums, strings, choir = [], [], [], [], [], []
    for b in bars:
        root_name, kind = b["chord"], b["kind"]
        voicing, arp, root = WARM[root_name]
        vel = {"soft": 0.6, "verse": 0.8, "chorus": 1.0}[kind]
        piano.append(f"{voicing}:2!{vel:.2f} {voicing}:2!{vel * 0.7:.2f}")
        a = arp.split()
        guitar.append(" ".join(f"{n}:1/2!{0.55 if kind == 'chorus' else 0.75}" for n in (a + a[-2:0:-1])[:8])
                      if kind != "soft" else "r:4")
        bass.append(f"{root}:4!{vel:.2f}" if kind != "chorus" else f"{root}:2 {root[0]}{int(root[-1]) + 1}:1 {root}:1")
        if not b["drums"] or kind == "soft":
            drums.append("r:4")
        elif kind == "verse":  # light: kick + soft hats, no snare
            drums.append("C2+F#2:1!0.7 F#2:1!0.4 F#2:1!0.5 F#2:1!0.4")
        else:
            drums.append("C2+F#2:1 F#2:1!0.6 D2+F#2:1 F#2:1/2!0.6 C2:1/2!0.8")
        strings.append(f"{voicing}:4" if kind == "chorus" else "r:4")
        choir.append(f"{CHORDS[root_name][0]}:4" if kind == "chorus" else "r:4")
    music = {
        "mode": "song", "name": "chanson-nanterino-v3", "bpm": bpm, "gain": 0.6, "seed": 7,
        "eq": {"bass": 2.5, "bassFreq": 200, "treble": -4, "trebleFreq": 6500},  # warmer, less harsh
        "space": {"reverb": {"mix": 0.24, "size": 0.6, "damp": 0.6, "width": 1}, "width": 1.15},
        "tracks": [
            {"instrument": "kit-lofi", "volume": 0.4, "notes": " ".join(drums)},
            {"instrument": "pno-grand", "volume": 0.34, "notes": " ".join(piano)},
            {"instrument": "gtr-nylon", "volume": 0.3, "pan": 0.3, "notes": " ".join(guitar)},
            {"instrument": "gtr-bass", "volume": 0.6, "notes": " ".join(bass)},
            {"instrument": "str-ensemble", "volume": 0.16, "pan": -0.3, "notes": " ".join(strings)},
            {"instrument": "vox-ooh", "volume": 0.1, "pan": -0.15, "notes": " ".join(choir)},
            {"instrument": "mal-vibraphone", "volume": 0.09, "pan": 0.25, "notes": " ".join(mel)},
        ],
    }
    work = f"{ROOT}/song/build"
    os.makedirs(work, exist_ok=True)
    json.dump(music, open(f"{work}/music_v2.json", "w"), indent=1)
    subprocess.run([sys.executable, SOUNDGEN, "render", f"{work}/music_v2.json", "-o", f"{work}/music_v2.wav"],
                   check=True, cwd=os.path.dirname(SOUNDGEN), stdout=subprocess.DEVNULL)
    rate, music_pcm = read_wav(f"{work}/music_v2.wav")

    # 3) Mix: voice placed so its first nucleus lands on the line's downbeat; music ducks.
    voice = np.zeros(len(music_pcm), dtype=np.float32)
    timings = []
    for b0, ln in placed:
        y = resample(ln["audio"], singer.rate, rate)
        start = int(round((b0 * bar_s - ln["lead"]) * rate))
        if start < 0:
            y, start = y[-start:], 0
        n = min(len(y), len(voice) - start)
        voice[start:start + n] += y[:n]
        timings.append({"t": round(b0 * bar_s, 3), "text": ln["text"].replace("-", "")})
    voice = warm_voice(voice, rate)
    voice *= VOCAL_RMS / max(1e-6, np.sqrt(np.mean(voice[np.abs(voice) > 1e-4] ** 2)))
    env, level = np.abs(voice), 0.0
    att, rel = 1 - np.exp(-1 / (0.02 * rate)), 1 - np.exp(-1 / (0.35 * rate))
    smooth = np.empty_like(env)
    for i, x in enumerate(env):
        level += (att if x > level else rel) * (x - level)
        smooth[i] = level
    duck = 1 - DUCK * np.clip(smooth / (0.5 * VOCAL_RMS), 0, 1)
    mix = (music_pcm * (MUSIC_GAIN * duck)[:, None]).mean(axis=1) + voice
    # Section dynamics on the whole mix (measured v3: refrain came out 2.5 dB QUIETER than the
    # verse because of ducking): intro/end -3 dB, verse 0 dB, refrain +3.5 dB, 0.6 s ramps.
    level_db = {"soft": -3.0, "verse": 0.0, "chorus": 3.5}
    curve = np.zeros(len(mix), dtype=np.float32)
    for i, b in enumerate(bars):
        curve[int(i * bar_s * rate):int((i + 1) * bar_s * rate)] = level_db[b["kind"]]
    curve[int(len(bars) * bar_s * rate):] = level_db["soft"]
    k = int(0.6 * rate)
    curve = np.convolve(curve, np.ones(k) / k, mode="same")
    mix *= 10 ** (curve / 20)
    mix *= 0.89 / max(1e-6, np.abs(mix).max())
    out = f"{ROOT}/media/chanson-nanterino.wav"
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())
    json.dump({"title": spec["title"], "duration_s": round(len(mix) / rate, 2), "voice": v, "lines": timings},
              open(out.replace(".wav", ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log.info("song v2 built s=%.1f bars=%d voice=%s", len(mix) / rate, len(bars), v)
    print(out, round(len(mix) / rate, 1), "s", len(bars), "bars")


if __name__ == "__main__":
    main()

