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


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return [w for w in re.findall(r"[a-z0-9]+", text) if len(w) > 2 and w not in STOP]


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
                                "title_tokens": set(_tokens(title)), "tokens": set(_tokens(text))})
        log.info("corpus loaded sheets=%d", len(self.sheets))

    def search(self, question: str, k: int = 3) -> list[dict]:
        q = set(_tokens(question))
        scored = []
        for s in self.sheets:
            score = 3 * len(q & s["title_tokens"]) + len(q & s["tokens"])
            if score:
                scored.append((score, s))
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:k]]
