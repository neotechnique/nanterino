"""Shared read-only viewing helpers for the native explorers (explorer.py, corpus.py).

logging: robotlog -> /var/log/robot/nanterino-ui.log (unreadable / binary previews: base name only).

Purpose
    TextPreview: a QTextBrowser that shows Markdown rendered and any other text as plain monospace, read-only.
    human_size / human_date: list column formatting. is_text_name: which files the side panel may show.
Boundary
    Qt widgets only, no disk access except TextPreview.show_file (bounded read, never writes).
Invariants
    - a file larger than MAX_BYTES is shown truncated with a French notice; binary-looking content is refused.
How to test
    covered by tests/test_ui_explorer.py and tests/test_ui_corpus.py (offscreen)
"""
import os
import re
import sys
import time

sys.path.insert(0, "/opt/robot/lib")
from robotlog import get_logger  # noqa: E402

from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QTextBrowser  # noqa: E402

log = get_logger("nanterino-ui")
TEXT_EXTS = {".md", ".log", ".txt", ".json", ".yaml", ".yml", ".py", ".sh", ".toml", ".cfg", ".ini", ".csv", ".desktop"}
MAX_BYTES = 200_000


def strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->\s*", "", text, flags=re.S)


def is_text_name(name: str) -> bool:
    low = name.lower()
    return os.path.splitext(low)[1] in TEXT_EXTS or low.endswith(".md.txt")


def human_size(n: float) -> str:
    if n < 1024:
        return "%d o" % n
    for unit in ("Ko", "Mo", "Go"):
        n /= 1024.0
        if n < 1024 or unit == "Go":
            return "%.1f %s" % (n, unit)
    return ""


def human_date(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


class TextPreview(QTextBrowser):
    def __init__(self):
        super().__init__()
        self.setOpenExternalLinks(False)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))

    def show_text(self, name: str, text: str) -> None:
        if name.lower().endswith(".md"):
            self.setMarkdown(strip_html_comments(text))
        else:
            self.setPlainText(text)

    def show_file(self, path: str) -> str:
        """Show a text file read-only; returns "" or a French notice (binary / unreadable / truncated)."""
        try:
            with open(path, "rb") as f:
                raw = f.read(MAX_BYTES + 1)
        except OSError as e:
            self.clear()
            return "Lecture impossible : %s" % e.strerror
        if b"\x00" in raw[:4096]:
            log.info("viewer binary file=%s", os.path.basename(path))
            self.clear()
            return "Fichier binaire : pas d'aperçu."
        notice = ""
        if len(raw) > MAX_BYTES:
            raw = raw[:MAX_BYTES]
            notice = "Aperçu tronqué à %s." % human_size(MAX_BYTES)
        self.show_text(os.path.basename(path), raw.decode("utf-8", "replace"))
        return notice
