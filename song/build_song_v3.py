#!/usr/bin/env python3
"""Daisy-style Nanterino song (v3): a phoneme-level SCORE drives the Siwis voice.

Idea (user 2026-10-27, "comme l'ordi qui chantait Daisy Bell"): the 1961 IBM 7094 sang from a
per-phoneme score - duration, pitch with ramps, loudness. Here the voice stays Piper Siwis, but:
  1. a copy of the voice ONNX exposes the duration predictor (Ceil -> frames of hop 256), so we
     know EXACTLY where each phoneme is in the generated audio (make_dur_model.py);
  2. phonemes are grouped into syllables (vowel nuclei, glides/nasals merged);
  3. score: consonants keep their natural length and end exactly on the note onset; vowels are
     held (natural attack, then one steady averaged timbre) until the next consonant starts;
  4. pitch: note per syllable with smooth ramps (smoothstep glides, small overshoot on rises),
     delayed vibrato on long notes; soft release at the end of the line;
  5. WORLD (pyworld) resynthesis. Arrangement, best-of-N takes and the mix come from v2.
logging: robotlog via nanterino.log
Usage: PYTHONPATH=/opt/robot/nanterino .venv/bin/python song/build_song_v3.py song/chanson-v3.json
"""
import os
import sys

import numpy as np
import onnxruntime as ort
import pyworld
from piper import PiperVoice

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_song_v2 as v2  # noqa: E402
from nanterino.log import log  # noqa: E402

FRAME_MS = v2.FRAME_MS
VOWELS = set("aɑeɛiouyøœəɐɔɪʊʏɜ")  # IPA vowels espeak uses for French
MARKS = set("ˈˌː̃")                # stress / length / nasal tilde: belong to the neighbour
HOLD_POS = 0.5   # where in the vowel the held timbre is sampled (0 = start)
HOLD_WIN = 2     # +/- frames averaged around that point
BREATH_S = 0.45                    # line ends this long before its 2 bars (breath; keeps the line in 2 bars)


class DaisySinger:
    """Piper voice + duration model -> audio, per-phoneme sample spans, WORLD parameters."""

    def __init__(self, model: str, speaker=None):
        self.voice = PiperVoice.load(model)
        self.rate = self.voice.config.sample_rate
        self.hop = self.voice.config.hop_length or 256
        dur_model = model.replace(".onnx", "-durations.onnx")
        self.sess = ort.InferenceSession(dur_model, providers=["CPUExecutionProvider"])
        c = self.voice.config
        self.scales = np.array([c.noise_scale, c.length_scale, c.noise_w_scale], dtype=np.float32)
        self.inv = {i: p for p, ids in c.phoneme_id_map.items() for i in ids}

    def speak(self, text):
        """-> (audio float64, [(symbol, start_sample, end_sample)]) for the whole text."""
        audio, spans, offset = [], [], 0
        for ph in self.voice.phonemize(text):
            ids = self.voice.phonemes_to_ids(ph)
            x = np.array([ids], dtype=np.int64)
            wav, dur = self.sess.run(None, {"input": x, "input_lengths": np.array([x.shape[1]], dtype=np.int64),
                                            "scales": self.scales})
            wav, dur = wav.reshape(-1).astype(np.float64), dur.reshape(-1)
            pos = offset
            for i, d in zip(ids, dur):
                n = int(d) * self.hop
                spans.append((self.inv.get(i, "?"), pos, pos + n))
                pos += n
            audio.append(wav)
            offset += len(wav)
        return np.concatenate(audio), spans

    def analyse(self, text):  # used by v2.auto_transpose
        x, _ = self.speak(text)
        f0, t = pyworld.harvest(x, self.rate, frame_period=FRAME_MS, f0_floor=70, f0_ceil=700)
        return f0, pyworld.cheaptrick(x, f0, t, self.rate), pyworld.d4c(x, f0, t, self.rate)


def normalize(spans):
    """Merge Piper's interleaved pads and marks into real phonemes.

    Piper inserts a pad id ("_") after every phoneme and the duration predictor gives the pad
    part of that phoneme's acoustic time, so a phoneme's real span = its own + following pads.
    Stress marks (ˈ ˌ) join the NEXT phoneme, nasal tilde / length (̃ ː) the PREVIOUS one.
    Separators (space , - .) stay as "sep" spans (pauses), BOS/EOS ("^", "$") too.
    """
    out, pending = [], None  # pending = start of a stress mark waiting for its phoneme
    for sym, s, e in spans:
        if sym == "_" and out:
            out[-1][2] = e
        elif sym in "̃ːʲʷʰ" and out:  # nasal, length, palatalised/labialised/aspirated modify the previous phoneme
            out[-1][2] = e
        elif sym in "ˈˌ":
            pending = s if pending is None else pending
        else:
            kind = "sep" if sym in " ,.-!?;:^$" else sym
            out.append([kind, pending if pending is not None else s, e])
            pending = None
    return [tuple(x) for x in out]


def syllables(spans):
    """Group phoneme spans into syllables: [(onset_start, nucleus_start, nucleus_end)] in samples.

    A nucleus = consecutive vowels (+ marks); a vowel directly followed by another vowel is a
    glide ("suis" = s-y-i -> one syllable). Consonants before a nucleus are its onset.
    """
    spans = normalize(spans)
    out, onset, i, n = [], None, 0, len(spans)
    while i < n:
        sym, s, e = spans[i]
        if sym in VOWELS:
            j, end = i, e
            while j + 1 < n and (spans[j + 1][0] in VOWELS or spans[j + 1][0] in MARKS):
                j += 1
                end = spans[j][2]
            out.append((onset if onset is not None else s, s, end))
            onset, i = None, j + 1
            continue
        if sym != "sep" and e > s and onset is None:
            onset = s  # first real consonant of the next onset
        i += 1
    return out


def sing(singer, text, pitches, transpose):
    """-> (float32 audio, lead_s, events [(t_s, midi)]); t=0 = first note onset (downbeat)."""
    spb = SPB[0]
    x, spans = singer.speak(text)
    rate, fr = singer.rate, FRAME_MS / 1000
    f0, t = pyworld.harvest(x, rate, frame_period=FRAME_MS, f0_floor=70, f0_ceil=700)
    sp, ap = pyworld.cheaptrick(x, f0, t, rate), pyworld.d4c(x, f0, t, rate)
    log_sp = np.log(sp + 1e-12)
    F = lambda samples: min(len(f0) - 1, int(samples / rate / fr))  # noqa: E731
    syl = syllables(spans)
    notes = pitches
    if not syl:
        raise ValueError(f"no vowel found in {text!r}")
    # Map syllables to notes monotonically when counts differ (extra syllables share a note).
    k_of_syl = [min(len(notes) - 1, round(j * (len(notes) - 1) / max(1, len(syl) - 1))) if len(syl) > 1 else 0
                for j in range(len(syl))]
    beats = NOTE_BEATS[0]
    onsets = np.concatenate([[0.0], np.cumsum(beats)]) * spb  # note k starts at onsets[k]
    line_end = onsets[-1] - BREATH_S
    # Desired vowel start per syllable: its note onset (several syllables on one note share it,
    # spread inside the note).
    vstart = []
    for j, k in enumerate(k_of_syl):
        same = [jj for jj, kk in enumerate(k_of_syl) if kk == k]
        pos = same.index(j)
        vstart.append(onsets[k] + pos * (onsets[k + 1] - onsets[k]) / len(same))
    # Layout v2 (2026-10-27 ablation: dropping vowel tails, codas and pauses made words
    # unintelligible). Every input frame is kept. Syllable j = [onset_j, onset_j+1) is split into
    # consonants | vowel first half | vowel second half + rest; it is placed so its consonants END
    # on the note onset. If the slot is longer than natural, a steady averaged vowel is inserted
    # between the two vowel halves (the "held note"); if shorter, the syllable is evenly compressed.
    Fr = lambda samples: min(len(f0), int(round(samples / rate / fr)))  # noqa: E731
    cons_s = [(vs - o) / rate for o, vs, ve in syl]
    starts = [vstart[j] - cons_s[j] for j in range(len(syl))] + [line_end + 0.12]
    seg_bounds = [Fr(o) for o, _, _ in syl] + [len(f0)]
    # 30 ms of the original silence before the first consonant: without it the opening plosive
    # ("T" of "Triez") was lost at the very start of the WORLD resynthesis ("Prie vous...").
    PRE_S = 0.03
    first_cons = cons_s[0] + PRE_S
    frames_sp, frames_ap, frames_vo, frames_k = [], [], [], []
    out_pos = 0  # frames written so far (time = out_pos*fr - first_cons)
    rearticulate = []  # output frames where a vowel follows a vowel ("ici", "oh oh"): soft re-attack
    for j, (o, vs, ve) in enumerate(syl):
        k = k_of_syl[j]
        if j > 0 and cons_s[j] < 0.015:
            rearticulate.append(len(frames_k))
        f_o, f_vs, f_ve, f_end = Fr(o), Fr(vs), max(Fr(vs) + 1, Fr(ve)), max(Fr(ve), seg_bounds[j + 1])
        if j == 0:
            f_o = max(0, f_o - int(round(PRE_S / fr)))
        if j + 1 == len(syl):
            f_end = min(len(f0), f_ve + int(0.15 / fr))  # keep a short natural tail only
        target_len = max(2, int(round((starts[j + 1] + first_cons) / fr)) - out_pos)
        natural = list(range(f_o, f_end))
        mid = (f_vs + f_ve) // 2
        if target_len > len(natural):
            # Held timbre taken at HOLD_POS of the vowel, +/- HOLD_WIN frames (2026-10-28: the
            # vowel middle already moves toward the next consonant, held "o" sounded like "ou").
            hp = f_vs + int(HOLD_POS * max(1, f_ve - f_vs))
            v0, v1 = max(f_vs, hp - HOLD_WIN), min(f_ve, hp + HOLD_WIN + 1)
            v_sp, v_ap = log_sp[v0:max(v1, v0 + 1)].mean(axis=0), ap[v0:max(v1, v0 + 1)].mean(axis=0)
            n_hold = target_len - len(natural)
            first_half = list(range(f_o, mid))
            second = list(range(mid, f_end))
            for c in first_half:
                frames_sp.append(log_sp[c]); frames_ap.append(ap[c]); frames_vo.append(f0[c] > 0 or f_vs <= c < f_ve); frames_k.append(k)
            a_sp = log_sp[max(f_o, mid - 1)]
            b_sp = log_sp[min(len(f0) - 1, mid)]
            for i in range(n_hold):  # crossfade in, steady, crossfade out (log spectrum)
                r_in, r_out = min(1.0, (i + 1) / 6.0), min(1.0, (n_hold - i) / 6.0)
                base = a_sp if i < n_hold / 2 else b_sp
                r = min(r_in, r_out)
                frames_sp.append((1 - r) * base + r * v_sp); frames_ap.append(v_ap); frames_vo.append(True); frames_k.append(k)
            for c in second:
                frames_sp.append(log_sp[c]); frames_ap.append(ap[c]); frames_vo.append(f0[c] > 0 or f_vs <= c < f_ve); frames_k.append(k)
        else:
            idx = np.linspace(f_o, f_end - 1, target_len).round().astype(int) if natural else np.full(target_len, f_vs)
            for c in idx:
                frames_sp.append(log_sp[c]); frames_ap.append(ap[c]); frames_vo.append(f0[c] > 0); frames_k.append(k)
        out_pos = len(frames_k)
    frames_sp = np.array(frames_sp)
    # Re-attack (2026-10-27, user: "ici", "oh oh" sounded stuck/odd): two vowels in a row melt
    # into one; a singer re-articulates with a short dip. -10 dB 25 ms dip, 50 ms recovery.
    dip = np.array([0.32, 0.3, 0.38, 0.5, 0.65, 0.8, 0.92, 1.0])
    for f in rearticulate:
        for i, g in enumerate(dip):
            if 0 <= f - 2 + i < len(frames_sp):
                frames_sp[f - 2 + i] += 2 * np.log(g)
    sp_o, ap_o = np.exp(frames_sp), np.clip(np.array(frames_ap), 0, 1)
    vo_o, k_o = np.array(frames_vo), np.array(frames_k)
    n = len(k_o)
    t_out = np.arange(n) * fr - first_cons
    # Pitch score with ramps: smoothstep glide (70 ms) into each new note, +30 cents overshoot on
    # rises that settles in 120 ms, vibrato 5.2 Hz / 0.22 semitone fading in after 0.35 s held.
    # Pitch follows the SCORE TIME, not the syllable index (2026-10-27: when the voice has fewer
    # syllables than notes, e.g. "chemins" said "ch'mins", a held syllable now sings both notes
    # as a melisma instead of stretching one pitch oddly).
    k_time = np.clip(np.searchsorted(onsets, t_out, side="right") - 1, 0, len(notes) - 1)
    target = np.array([notes[k] + transpose for k in k_time], dtype=float)
    midi_curve = target.copy()
    change = np.flatnonzero(np.diff(target)) + 1
    glide = int(0.07 / fr)
    for c in change:
        a, b = target[c - 1], target[c]
        s0 = max(0, c - glide // 2)
        for i in range(s0, min(n, s0 + glide)):
            u = (i - s0) / glide
            midi_curve[i] = a + (b - a) * (u * u * (3 - 2 * u))
        if b > a:  # small overshoot on rising intervals
            for i in range(s0 + glide, min(n, s0 + glide + int(0.12 / fr))):
                u = (i - s0 - glide) / (0.12 / fr)
                midi_curve[i] += 0.3 * (1 - u) * np.sin(np.pi * u)
    since = np.zeros(n)
    for i in range(1, n):
        since[i] = since[i - 1] + fr if target[i] == target[i - 1] else 0.0
    vib_amp = np.clip((since - 0.35) / 0.25, 0, 1) * 0.22
    midi_curve += vib_amp * np.sin(2 * np.pi * 5.2 * t_out)
    f0_o = np.where(vo_o, 440 * 2 ** ((midi_curve - 69) / 12), 0.0)
    y = pyworld.synthesize(np.ascontiguousarray(f0_o), np.ascontiguousarray(sp_o), np.ascontiguousarray(ap_o), rate, FRAME_MS)
    rel = int(0.08 * rate)  # soft release
    y[-rel:] *= np.linspace(1, 0, min(rel, len(y)))
    events = [(onsets[k], notes[k] + transpose) for k in range(len(notes))]
    return y.astype(np.float32), first_cons, events


SPB = [0.6]          # seconds per beat, set from the spec in main()
NOTE_BEATS = [None]  # current line's note durations (beats); set per line by the patched loop


def main():
    import json
    spec_path = sys.argv[1]
    spec = json.load(open(spec_path, encoding="utf-8"))
    SPB[0] = 60 / spec["bpm"]
    beats_by_line = {}
    from fractions import Fraction
    for sec in spec["sections"]:
        for ln in sec.get("lines", []):
            say = ln.get("say") or ln["text"].replace("-", "")
            beats_by_line[say] = [float(Fraction(t.split(":")[1])) if ":" in t else 1.0 for t in ln["notes"].split()]

    def sing_line(singer, text, pitches, transpose):
        NOTE_BEATS[0] = beats_by_line[text]
        return sing(singer, text, pitches, transpose)

    v2.Singer = DaisySinger
    v2.sing = sing_line
    if "--inmix" in sys.argv:
        # In-mix take selection (2026-10-28): words clear when sung alone were masked under the
        # refrain music. The Daisy score fixes every line's length, so the arrangement and the
        # music of the previous build are valid: each candidate take is mixed with the music
        # under its line (same ducking idea) and the take Whisper understands best IN the mix wins.
        n_takes = int(sys.argv[sys.argv.index("--inmix") + 1])
        sys.argv = [a for a in sys.argv if a not in ("--inmix", str(n_takes))]
        import wave as _wave
        from listen_song import letter_err
        from nanterino.engines import STT
        stt = STT("http://127.0.0.1:8178/inference")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        prev = json.load(open(os.path.join(root, "media", "chanson-nanterino-daisy-final.json"), encoding="utf-8"))["lines"]
        first_t = {}
        for L in prev:
            first_t.setdefault(L["text"], L["t"])
        mrate, music = v2.read_wav(os.path.join(root, "song", "build", "music_v2.wav"))
        music = music.mean(axis=1)
        text_of_say = {}
        for sec in spec["sections"]:
            for ln in sec.get("lines", []):
                text_of_say[ln.get("say") or ln["text"].replace("-", "")] = ln["text"].replace("-", "")

        def sing_inmix(singer, text, pitches, transpose):
            ref = text_of_say.get(text, text)
            t0 = first_t.get(ref)
            best = None
            for _ in range(n_takes):
                y, lead, ev = sing_line(singer, text, pitches, transpose)
                if t0 is None:
                    return y, lead, ev
                v = v2.resample(y, singer.rate, mrate)
                # same vocal chain as the final mix (compressor + warm EQ/double/room)
                v = v2.warm_voice(v2.compress(v / max(1e-6, np.abs(v).max()), mrate), mrate)
                v = v * (v2.VOCAL_RMS / max(1e-6, np.sqrt(np.mean(v[np.abs(v) > 1e-4] ** 2))))
                st = max(0, int((t0 - lead) * mrate))
                seg = music[st:st + len(v)]
                mix = v[: len(seg)] + seg * v2.MUSIC_GAIN * (1 - v2.DUCK)
                mix = mix / max(1e-6, np.abs(mix).max()) * 0.9
                x16 = mix[np.linspace(0, len(mix), int(len(mix) * 16000 / mrate), endpoint=False).astype(int)]
                h = stt.transcribe((x16 * 32767).astype(np.int16), 16000)
                e = letter_err(ref, h)
                if best is None or e < best[0]:
                    best = (e, y, lead, ev)
                if e < 0.02:
                    break
            log.info("song inmix take chosen line=%r letter_err=%.2f", ref[:30], best[0])
            return best[1], best[2], best[3]

        v2.sing = sing_inmix
        v2.TAKES = 1
    log.info("song v3 (daisy score) start spec=%s", spec_path)
    v2.main()


if __name__ == "__main__":
    main()
