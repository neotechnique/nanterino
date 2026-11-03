"""Corpus search over validated place sheets (cahier §4): one Markdown file per place.

logging: robotlog via nanterino.log. Keyword scoring first (enough for 30 sheets); embeddings later.
The LLM only rephrases these sheets; a place absent from the corpus must never be invented.
"""
import glob
import os
import re
import unicodedata

from .log import log

STOP = set("le la les un une des de du d l a au aux et ou en dans sur pour par avec est il elle "
           "je tu vous nous on que qui quoi ou y ce cet cette ces mon ma mes son sa ses quel quelle "
           "quels quelles comment faire veux voudrais cherche chercher trouver aller pres proche "
           "bonjour merci svp s il plait".split())


def _stem(w: str) -> str:
    """Crude French plural folding so "piles"/"pile" and "jardins"/"jardin" match."""
    if len(w) > 4 and w.endswith("aux"):
        return w[:-3] + "al"        # animaux -> animal
    if len(w) > 3 and w[-1] in "sx":
        return w[:-1]
    return w


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", text) if len(w) > 2 and w not in STOP]


def _keywords(text: str) -> str:
    """Content of the "- Mots-clés :" line (synonyms visitors may say), weighted like the title."""
    for line in text.splitlines():
        low = line.lower()
        if "mots-cl" in low and ":" in line:
            return line.split(":", 1)[1]
    return ""


class Corpus:
    def __init__(self, folder: str):
        self.folder = folder
        self.sheets: list[dict] = []
        self.reload()

    def reload(self):
        self.sheets = []
        for path in sorted(glob.glob(os.path.join(self.folder, "*.md"))):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.strip()), os.path.basename(path))
            self.sheets.append({"file": os.path.basename(path), "title": title, "text": text,
                                "title_tokens": set(_tokens(title)) | set(_tokens(_keywords(text))),
                                "tokens": set(_tokens(text))})
        log.info("corpus loaded sheets=%d", len(self.sheets))

    def search(self, question: str, k: int = 3, rel_min: float = 0.0) -> list[dict]:
        """Top-k sheets; rel_min drops sheets scoring below rel_min x the best score. Every sheet costs
        ~350 prompt tokens (~0.25 s on the Orin with LFM3), so weak matches are worth dropping."""
        q = set(_tokens(question))
        scored = []
        for s in self.sheets:
            score = 3 * len(q & s["title_tokens"]) + len(q & s["tokens"])
            if score:
                scored.append((score, s))
        scored.sort(key=lambda x: -x[0])
        best = scored[0][0] if scored else 0
        return [s for score, s in scored[:k] if score >= rel_min * best]
