"""Native corpus explorer: browse, preview, edit, create, rename and trash the corpus sheets (fiches/*.md).

logging: robotlog -> /var/log/robot/nanterino-ui.log (`corpus action=..` with the file name only, never content).

Purpose
    Replaces the stock file manager for the corpus (Nautilus CSD windows get stuck under IceWM). A normal
    IceWM-framed Qt window: searchable list on the left, rendered Markdown ("Aperçu") and a plain-text editor
    ("Modifier") on the right, plus new / rename / delete / reload / open-folder actions.
Boundary
    - CorpusStore: pure file logic (no Qt), the only code that touches the disk. It is confined to ONE folder,
      refuses any name that is not a plain `*.md` file name, ignores hidden entries, never unlinks (delete moves
      to `<dir>/.corbeille/`), and writes atomically (tmp + os.replace).
    - CorpusWindow: Qt widgets; the folder is `--dir PATH` or env NANTERINO_FICHES_DIR, default
      /opt/robot/nanterino/fiches. "Recharger le corpus" POSTs {"action":"reload_corpus"} to the server, the same
      call as the dashboard button. No validator exists in nanterino/corpus.py, so no warnings are shown.
    - Single instance role "corpus" (nanterino_ui.single_instance).
Invariants
    - a name given by the user never reaches the filesystem before slugify() / _safe_name().
    - the template (`_MODELE-fiche.md.txt`) is shown read-only and is never written or trashed.
    - unsaved editor text is never dropped without the user's answer (ask_unsaved).
How to test
    .venv/bin/python -m tests.test_ui_corpus     (offscreen, on a temp copy of the sheets)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata

sys.path.insert(0, "/opt/robot/lib")
from robotlog import get_logger  # noqa: E402

from PySide6.QtCore import QByteArray, QUrl, Qt  # noqa: E402
from PySide6.QtGui import QFontDatabase, QKeySequence, QShortcut  # noqa: E402
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest  # noqa: E402
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QInputDialog, QLabel, QLineEdit,  # noqa: E402
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QSplitter, QTabWidget, QVBoxLayout, QWidget)

from nanterino_ui.single_instance import SingleInstance, raise_window  # noqa: E402
from nanterino_ui.viewers import TextPreview, strip_html_comments  # noqa: E402

log = get_logger("nanterino-ui")
ROOT = "/opt/robot/nanterino"
DEFAULT_DIR = f"{ROOT}/fiches"
PY = f"{ROOT}/.venv/bin/python"
API_CONTROL = "http://127.0.0.1:8080/api/control"
TEMPLATE = "_MODELE-fiche.md.txt"
TRASH = ".corbeille"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.md$")


def slugify(text: str) -> str:
    """'Parc André Malraux!' -> 'parc-andre-malraux' (kebab-case ASCII; '' when nothing usable is left)."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def title_of(text: str, fallback: str) -> str:
    """First `#` heading, else the file name. (nanterino/corpus.py takes the first non-empty line instead.)"""
    for line in text.splitlines():
        if line.startswith("#"):
            t = line.lstrip("#").strip()
            if t:
                return t
    return fallback




class StoreError(Exception):
    """User-facing (French) refusal."""


class CorpusStore:
    def __init__(self, folder: str):
        self.dir = os.path.realpath(folder)

    # ---- names -------------------------------------------------------------------------------------------
    def _safe_name(self, name: str) -> str:
        """Accept only a plain existing-style `<kebab>.md` base name: no separators, no dots games, not hidden."""
        if (not isinstance(name, str) or name != os.path.basename(name) or "/" in name or "\\" in name
                or name.startswith(".") or not _NAME_RE.match(name)):
            raise StoreError("Nom de fiche refusé : %r" % name)
        return name

    def path(self, name: str) -> str:
        p = os.path.realpath(os.path.join(self.dir, self._safe_name(name)))
        if os.path.dirname(p) != self.dir:
            raise StoreError("Chemin hors du corpus refusé.")
        return p

    # ---- reading -----------------------------------------------------------------------------------------
    def list_sheets(self) -> list[dict]:
        out = []
        for n in sorted(os.listdir(self.dir)):
            if n.startswith(".") or not _NAME_RE.match(n) or not os.path.isfile(os.path.join(self.dir, n)):
                continue
            text = self.read(n)
            out.append({"file": n, "title": title_of(text, n), "text": text})
        return out

    def read(self, name: str) -> str:
        with open(self.path(name), encoding="utf-8") as f:
            return f.read()

    def has_template(self) -> bool:
        return os.path.isfile(os.path.join(self.dir, TEMPLATE))

    def read_template(self) -> str:
        with open(os.path.join(self.dir, TEMPLATE), encoding="utf-8") as f:
            return f.read()

    # ---- writing -----------------------------------------------------------------------------------------
    def save(self, name: str, text: str) -> None:
        p = self.path(name)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)

    def create(self, display_name: str) -> str:
        slug = slugify(display_name)
        if not slug:
            raise StoreError("Nom vide ou sans lettres.")
        name = slug + ".md"
        if os.path.exists(self.path(name)):
            raise StoreError("La fiche « %s » existe déjà." % name)
        body = strip_html_comments(self.read_template()) if self.has_template() else "# Nom du lieu\n"
        body = body.replace("# Nom du lieu", "# " + display_name.strip(), 1)
        self.save(name, body)
        return name

    def rename(self, old: str, display_name: str) -> str:
        slug = slugify(display_name)
        if not slug:
            raise StoreError("Nom vide ou sans lettres.")
        new = slug + ".md"
        src, dst = self.path(old), self.path(new)
        if new == old:
            return old
        if os.path.exists(dst):
            raise StoreError("La fiche « %s » existe déjà." % new)
        os.rename(src, dst)
        return new

    def trash(self, name: str) -> str:
        """Move to .corbeille/ with a timestamp suffix; returns the trash path. Never unlinks."""
        src = self.path(name)
        tdir = os.path.join(self.dir, TRASH)
        os.makedirs(tdir, exist_ok=True)
        stem = name[:-3]
        dst = os.path.join(tdir, "%s-%s.md" % (stem, time.strftime("%Y%m%d-%H%M%S")))
        n = 1
        while os.path.exists(dst):  # two deletions of the same name in one second
            dst = os.path.join(tdir, "%s-%s-%d.md" % (stem, time.strftime("%Y%m%d-%H%M%S"), n))
            n += 1
        shutil.move(src, dst)
        return dst


def _ask_unsaved_default(parent, name: str) -> str:
    box = QMessageBox(QMessageBox.Question, "Fiches du corpus",
                      "La fiche « %s » a des modifications non enregistrées." % name,
                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, parent)
    box.button(QMessageBox.Save).setText("Enregistrer")
    box.button(QMessageBox.Discard).setText("Abandonner")
    box.button(QMessageBox.Cancel).setText("Annuler")
    box.setDefaultButton(QMessageBox.Save)
    return {QMessageBox.Save: "save", QMessageBox.Discard: "discard"}.get(box.exec(), "cancel")


class CorpusWindow(QWidget):
    def __init__(self, folder: str, ask_unsaved=None, ask_name=None, ask_confirm=None):
        super().__init__()
        self.store = CorpusStore(folder)
        # Dialog seams (stubbed by the tests): ask_unsaved(name)->save|discard|cancel, ask_name(title,label,default)
        # ->str|None, ask_confirm(text)->bool.
        self.ask_unsaved = ask_unsaved or (lambda n: _ask_unsaved_default(self, n))
        self.ask_name = ask_name or self._ask_name_default
        self.ask_confirm = ask_confirm or self._ask_confirm_default
        self.net = QNetworkAccessManager(self)
        self.sheets: list[dict] = []
        self.current: str | None = None   # file name, or TEMPLATE for the read-only model
        self.dirty = False
        self._loading = False

        self.setWindowTitle("Nanterino — Fiches du corpus")
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.btn_new = QPushButton("Nouvelle fiche")
        self.btn_rename = QPushButton("Renommer")
        self.btn_delete = QPushButton("Supprimer")
        self.btn_save = QPushButton("Enregistrer (Ctrl+S)")
        self.btn_reload = QPushButton("Recharger le corpus")
        self.btn_folder = QPushButton("Ouvrir le dossier")
        for b in (self.btn_new, self.btn_rename, self.btn_delete, self.btn_save, self.btn_reload, self.btn_folder):
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)

        split = QSplitter()
        left = QWidget(); lv = QVBoxLayout(left); lv.setContentsMargins(0, 0, 0, 0)
        self.filter = QLineEdit(); self.filter.setPlaceholderText("Filtrer (nom et contenu)…"); self.filter.setClearButtonEnabled(True)
        self.listw = QListWidget()
        self.count = QLabel("")
        lv.addWidget(self.filter); lv.addWidget(self.listw, 1); lv.addWidget(self.count)
        self.tabs = QTabWidget()
        self.preview = TextPreview()
        self.editor = QPlainTextEdit(); self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.tabs.addTab(self.preview, "Aperçu")
        self.tabs.addTab(self.editor, "Modifier")
        split.addWidget(left); split.addWidget(self.tabs)
        split.setStretchFactor(0, 1); split.setStretchFactor(1, 3)
        root.addWidget(split, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.filter.textChanged.connect(self.refresh_list)
        self.listw.currentItemChanged.connect(self._on_select)
        self.editor.textChanged.connect(self._on_edit)
        self.btn_new.clicked.connect(self.new_sheet)
        self.btn_rename.clicked.connect(self.rename_sheet)
        self.btn_delete.clicked.connect(self.delete_sheet)
        self.btn_save.clicked.connect(self.save_current)
        self.btn_reload.clicked.connect(self.reload_corpus)
        self.btn_folder.clicked.connect(self.open_folder)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_current)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)
        self.refresh_list()
        self._update_buttons()

    # ---- helpers -----------------------------------------------------------------------------------------
    def say(self, text: str):
        self.status.setText(text)

    def _ask_name_default(self, title, label, default=""):
        text, ok = QInputDialog.getText(self, title, label, text=default)
        return text if ok else None

    def _ask_confirm_default(self, text):
        return QMessageBox.question(self, "Fiches du corpus", text) == QMessageBox.Yes

    def _is_template(self) -> bool:
        return self.current == TEMPLATE

    def _update_buttons(self):
        real = self.current is not None and not self._is_template()
        self.btn_rename.setEnabled(real)
        self.btn_delete.setEnabled(real)
        self.btn_save.setEnabled(real and self.dirty)
        self.editor.setReadOnly(not real)

    def _set_dirty(self, d: bool):
        self.dirty = d
        shown = self.current or ""
        self.setWindowTitle("Nanterino — Fiches du corpus" + (" — %s%s" % (shown, " *" if d else "") if shown else ""))
        self._update_buttons()

    def confirm_leave(self) -> bool:
        """True when it is fine to drop the current editor state (clean, saved or discarded by the user)."""
        if not self.dirty:
            return True
        ans = self.ask_unsaved(self.current or "")
        if ans == "save":
            return self.save_current()
        return ans == "discard"

    # ---- list --------------------------------------------------------------------------------------------
    def refresh_list(self, *_a, select: str | None = None):
        q = self.filter.text().strip().lower()
        self.sheets = self.store.list_sheets()
        keep = select or self.current
        self._loading = True
        self.listw.clear()
        shown = 0
        for s in self.sheets:
            if q and q not in s["file"].lower() and q not in s["title"].lower() and q not in s["text"].lower():
                continue
            it = QListWidgetItem("%s\n%s" % (s["title"], s["file"]))
            it.setData(Qt.UserRole, s["file"])
            self.listw.addItem(it)
            shown += 1
        if self.store.has_template() and (not q or q in "modèle modele"):
            it = QListWidgetItem("Modèle (lecture seule)\n" + TEMPLATE)
            it.setData(Qt.UserRole, TEMPLATE)
            self.listw.addItem(it)
        self.count.setText("%d fiche(s) affichée(s) sur %d" % (shown, len(self.sheets)))
        for i in range(self.listw.count()):
            if self.listw.item(i).data(Qt.UserRole) == keep:
                self.listw.setCurrentRow(i)
                break
        self._loading = False

    def _on_select(self, item, _prev=None):
        if self._loading or item is None:
            return
        name = item.data(Qt.UserRole)
        if name == self.current:
            return
        if not self.confirm_leave():
            self._loading = True   # put the selection back on the sheet still being edited
            for i in range(self.listw.count()):
                if self.listw.item(i).data(Qt.UserRole) == self.current:
                    self.listw.setCurrentRow(i)
            self._loading = False
            return
        self.open_sheet(name)

    def open_sheet(self, name: str):
        if name == TEMPLATE:
            text = self.store.read_template()
        else:
            text = self.store.read(name)
        self._loading = True
        self.current = name
        for i in range(self.listw.count()):   # keep the list selection in step with the opened sheet
            if self.listw.item(i).data(Qt.UserRole) == name:
                self.listw.setCurrentRow(i)
                break
        self.editor.setPlainText(text)
        self.preview.setMarkdown(strip_html_comments(text))
        self._loading = False
        self._set_dirty(False)

    def _on_edit(self):
        if self._loading or self.current is None or self._is_template():
            return
        self.preview.setMarkdown(strip_html_comments(self.editor.toPlainText()))
        if not self.dirty:
            self._set_dirty(True)

    # ---- actions -----------------------------------------------------------------------------------------
    def save_current(self) -> bool:
        if self.current is None or self._is_template() or not self.dirty:
            return True
        try:
            self.store.save(self.current, self.editor.toPlainText())
        except (StoreError, OSError) as e:
            self.say("Échec de l'enregistrement : %s" % e)
            return False
        log.info("corpus action=save file=%s", self.current)
        self._set_dirty(False)
        self.refresh_list()
        self.say("Enregistré : %s. Pensez à recharger le corpus." % self.current)
        return True

    def new_sheet(self):
        if not self.confirm_leave():
            return
        name = self.ask_name("Nouvelle fiche", "Nom du lieu ou de la pratique :", "")
        if not name:
            return
        try:
            f = self.store.create(name)
        except (StoreError, OSError) as e:
            self.say(str(e))
            return
        log.info("corpus action=new file=%s", f)
        self.current = None
        self._set_dirty(False)
        self.filter.setText("")
        self.refresh_list(select=f)
        self.open_sheet(f)
        self.tabs.setCurrentWidget(self.editor)
        self.say("Fiche créée : %s. Complétez-la puis rechargez le corpus." % f)

    def rename_sheet(self):
        if self.current is None or self._is_template() or not self.confirm_leave():
            return
        name = self.ask_name("Renommer", "Nouveau nom :", self.current[:-3])
        if not name:
            return
        try:
            f = self.store.rename(self.current, name)
        except (StoreError, OSError) as e:
            self.say(str(e))
            return
        log.info("corpus action=rename file=%s", f)
        self.current = f
        self.refresh_list(select=f)
        self.open_sheet(f)
        self.say("Renommée : %s. Pensez à recharger le corpus." % f)

    def delete_sheet(self):
        if self.current is None or self._is_template():
            return
        name = self.current
        if not self.ask_confirm("Mettre la fiche « %s » à la corbeille ?" % name):
            return
        try:
            dst = self.store.trash(name)
        except (StoreError, OSError) as e:
            self.say(str(e))
            return
        log.info("corpus action=trash file=%s", name)
        self.current = None
        self._loading = True
        self.editor.clear(); self.preview.clear()
        self._loading = False
        self._set_dirty(False)
        self.refresh_list()
        self.say("Déplacée dans la corbeille (fiches/%s/%s). Pensez à recharger le corpus." % (TRASH, os.path.basename(dst)))

    def reload_corpus(self):
        req = QNetworkRequest(QUrl(API_CONTROL))
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        reply = self.net.post(req, QByteArray(json.dumps({"action": "reload_corpus"}).encode()))
        log.info("corpus action=reload_corpus")

        def done():
            ok = reply.error() == QNetworkReply.NoError
            reply.deleteLater()
            self.say("Corpus rechargé par le robot." if ok else "Rechargement impossible : le service Nanterino ne répond pas.")
        reply.finished.connect(done)
        self.say("Rechargement du corpus…")

    def open_folder(self):
        subprocess.Popen([PY, "-m", "nanterino_ui.explorer", self.store.dir], cwd=ROOT, start_new_session=True)

    def closeEvent(self, e):
        if self.confirm_leave():
            e.accept()
        else:
            e.ignore()


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")   # IceWM draws the frame; no Wayland / CSD tricks
    folder = os.environ.get("NANTERINO_FICHES_DIR") or DEFAULT_DIR
    if "--dir" in sys.argv:
        folder = sys.argv[sys.argv.index("--dir") + 1]
    app = QApplication(sys.argv)
    si = SingleInstance("corpus")
    if not si.acquire():
        sys.exit(0)
    win = CorpusWindow(folder)
    si.on_raise = lambda: raise_window(win)
    si.on_quit = win.close
    win.resize(1100, 720)
    win.show()
    log.info("corpus started")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
