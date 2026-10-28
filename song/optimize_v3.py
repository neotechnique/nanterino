#!/usr/bin/env python3
"""Per-line optimiser for the Daisy song (v3): try variants, keep what Whisper understands best.

For every distinct sung line, candidates = the current spec + generated variants:
  - "speech rhythm": note durations proportional to the syllables' NATURAL durations (Piper
    duration predictor), quantised to 1/2 beat, total kept at 8 beats, last syllable >= 1.5 beat
    (the melody follows the voice's own rhythm: user priority "la chansonnette suit la voix");
  - "long first": first syllable on a full beat (opening consonant clusters, "Tr", "Nan");
  - optional pronunciation variants listed in SAY_VARIANTS.
Each candidate is sung TAKES times (Piper is random) and scored by mean Whisper word error rate
on the isolated vocal. The best candidate (ties keep the current spec) is written to
song/chanson-v3-opt.json and a Markdown report to song/build/optimize-report.md.
logging: robotlog via nanterino.log
Usage: PYTHONPATH=/opt/robot/nanterino .venv/bin/python song/optimize_v3.py song/chanson-v3.json
"""
import copy
import json
import os
import sys
from fractions import Fraction

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_song_v3 as v3  # noqa: E402
from build_song import midi  # noqa: E402
from listen_song import wer  # noqa: E402
from nanterino.engines import STT  # noqa: E402
from nanterino.log import log  # noqa: E402

TAKES = 3
SAY_VARIANTS = {
    "Nan-te-ri-no, Nan-te-ri-no": ["Nan-té-ri-no, Nan-té-ri-no", "Nanne-té-ri-no, Nanne-té-ri-no",
                                   "Nan-té-ri-no ! Nan-té-ri-no !", "Nantérino, Nantérino"],
    "Triez bien vos dé-chets, pre-nez le vé-lo": ["Triez bien vos déchets, prenez le vélo",
                                                  "Triez bien vos déchets ! Prenez le vélo !",
                                                  "Triez bien vôs déchets, prenez le vélo"],
}


def beats_of(notes):
    return [float(Fraction(t.split(":")[1])) if ":" in t else 1.0 for t in notes.split()]


def with_beats(notes, beats):
    toks = [t.split(":")[0] for t in notes.split()]
    return " ".join(t if b == 1 else f"{t}:{Fraction(b).limit_denominator(4)}" for t, b in zip(toks, beats))


def speech_rhythm(singer, say, n_notes):
    """Beats per note proportional to natural syllable lengths (1/2-beat grid, sum 8)."""
    _, spans = singer.speak(say)
    syl = v3.syllables(spans)
    if len(syl) != n_notes:
        return None
    lens = [(syl[j + 1][0] if j + 1 < len(syl) else syl[j][2]) - syl[j][0] for j in range(len(syl))]
    lens = np.maximum(np.array(lens, float), 1.0)
    body = lens[:-1] / lens[:-1].sum() * 6.5 if len(lens) > 1 else np.array([])
    q = [max(0.5, round(b * 2) / 2) for b in body]
    last = 8 - sum(q)
    while last < 1.5 and max(q, default=0) > 0.5:  # give the line end room to breathe
        i = int(np.argmax(q)); q[i] -= 0.5; last += 0.5
    return q + [last] if last >= 0.5 else None


def score(singer, stt, text, say, notes, transpose):
    toks = notes.split()
    v3.NOTE_BEATS[0] = beats_of(notes)
    pitches = [midi(t.split(":")[0]) for t in toks]
    errs, heard = [], []
    for _ in range(TAKES):
        y, _, _ = v3.sing(singer, say, pitches, transpose)
        x16 = y[np.linspace(0, len(y), int(len(y) * 16000 / singer.rate), endpoint=False).astype(int)]
        h = stt.transcribe((np.clip(x16, -1, 1) * 32767).astype(np.int16), 16000)
        heard.append(h)
        errs.append(wer(text.replace("-", ""), h))
    return float(np.mean(errs)), heard


def main():
    spec_path = sys.argv[1]
    spec = json.load(open(spec_path, encoding="utf-8"))
    v3.SPB[0] = 60 / spec["bpm"]
    singer = v3.DaisySinger("/opt/robot/nanterino/models/piper/" + spec.get("voice", {}).get("model", "fr_FR-siwis-medium.onnx"))
    stt = STT("http://127.0.0.1:8178/inference")
    transpose = -8  # measured auto-transpose for Siwis on this melody (v2/v3 logs)
    best_by_text, report = {}, ["# Optimiseur ligne par ligne (Daisy v3)", "",
                                f"{TAKES} prises par candidat, score = erreur Whisper moyenne sur la voix seule.", ""]
    for sec in spec["sections"]:
        for ln in sec.get("lines", []):
            key = ln["text"]
            if key in best_by_text:
                continue
            base_say = ln.get("say") or ln["text"].replace("-", "")
            cands = [("actuel", base_say, ln["notes"])]
            r = speech_rhythm(singer, base_say, len(ln["notes"].split()))
            if r:
                cands.append(("rythme de la voix", base_say, with_beats(ln["notes"], r)))
            b = beats_of(ln["notes"])
            if b[0] < 1 and len(b) > 1:
                b2 = b[:]; b2[0] = 1.0; b2[-1] = max(0.5, b2[-1] - 0.5)
                cands.append(("1re syllabe longue", base_say, with_beats(ln["notes"], b2)))
            for say in SAY_VARIANTS.get(key, []):
                if say != base_say:
                    cands.append((f"prononciation « {say} »", say, ln["notes"]))
                    if r:
                        cands.append((f"prononciation « {say} » + rythme voix", say, with_beats(ln["notes"], r)))
            results = []
            for label, say, notes in cands:
                s, heard = score(singer, stt, ln["text"], say, notes, transpose)
                results.append((s, label, say, notes, heard))
                log.info("optimize line=%r cand=%r wer=%.2f", key[:30], label, s)
            best = min(results, key=lambda x: (round(x[0], 3), x[1] != "actuel"))
            best_by_text[key] = best
            report.append(f"## {ln['text'].replace('-', '')}")
            for s, label, say, notes, heard in sorted(results, key=lambda x: x[0]):
                mark = " **← retenu**" if (label, say, notes) == best[1:4] else ""
                report.append(f"- {s:.0%} — {label} — `{notes}`{mark}  \n  entendu : {heard[0]!r}")
            report.append("")
    out = copy.deepcopy(spec)
    for sec in out["sections"]:
        for ln in sec.get("lines", []):
            s, label, say, notes, _ = best_by_text[ln["text"]]
            ln["notes"] = notes
            if say != ln["text"].replace("-", ""):
                ln["say"] = say
    out["_doc_opt"] = "Generated by optimize_v3.py (2026-10-28): best Whisper-scored variant per line."
    dst = spec_path.replace(".json", "-opt.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.makedirs(os.path.join(os.path.dirname(spec_path), "build"), exist_ok=True)
    open(os.path.join(os.path.dirname(spec_path), "build", "optimize-report.md"), "w", encoding="utf-8").write("\n".join(report))
    print("written", dst)


if __name__ == "__main__":
    main()
