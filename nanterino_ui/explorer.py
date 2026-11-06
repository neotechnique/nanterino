"""Nanterino native file explorer (whole computer): navigate, view text, open, new folder, rename, trash.

logging: robotlog -> /var/log/robot/nanterino-ui.log (`explorer action=..` with base names only, never content).

Purpose
    Replaces Nautilus (client-side decorations get stuck in move mode under IceWM) as the folder opener.
    Plain IceWM-framed Qt window: path bar + back / up, places sidebar, file table (name, size, date), read-only
    text panel for .md/.log/.txt/.json/.yaml/.py..., buttons Ouvrir / Nouveau dossier / Renommer / Supprimer /
    Copier le chemin. Entry: `python -m nanterino_ui.explorer [path]`. Several windows are allowed (no single
    instance); the corpus window is the single-instance one (nanterino_ui/corpus.py).
Boundary
    - ExplorerStore: pure disk logic. Delete NEVER unlinks: it moves to the freedesktop trash
      (<trash>/files + <trash>/info/*.trashinfo, default ~/.local/share/Trash, `trash_dir` overridable for tests).
    - Names given by the user must be a single path component (no "/", not "." / "..", not empty).
    - Files open through `xdg-open` (seam `opener`); folders open inside the explorer itself.
Invariants
    - an existing target is never overwritten by rename / new folder.
    - the viewer never writes; hidden files are shown only when the checkbox is on.
How to test
    .venv/bin/python -m tests.test_ui_explorer     (offscreen, temp dirs only)
"""
import os
import shutil
import subprocess
import sys
import time
from urllib.parse import quote

sys.path.insert(0, "/opt/robot/lib")
from robotlog import get_logger  # noqa: E402

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeySequence, QShortcut  # noqa: E402
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QHBoxLayout, QInputDialog,  # noqa: E402
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from nanterino_ui.viewers import TextPreview, human_date, human_size, is_text_name  # noqa: E402

log = get_logger("nanterino-ui")
HOME = os.path.expanduser("~")
DEFAULT_TRASH = os.path.join(HOME, ".local", "share", "Trash")
PLACES = [
    ("Dossier personnel", HOME),
    ("Bureau", os.path.join(HOME, "Desktop")),
    ("/opt/robot", "/opt/robot"),
    ("/var/log/robot", "/var/log/robot"),
    ("Fiches du corpus", "/opt/robot/nanterino/fiches"),
    ("Racine", "/"),
]


class ExplorerError(Exception):
    """User-facing (French) refusal."""


class ExplorerStore:
    def __init__(self, trash_dir: str | None = None):
        self.trash_dir = trash_dir or DEFAULT_TRASH

    @staticmethod
    def check_name(name: str) -> str:
        n = (name or "").strip()
        if not n or n in (".", "..") or "/" in n or "\x00" in n:
            raise ExplorerError("Nom refusé : %r" % name)
        return n

    def list_dir(self, path: str, show_hidden: bool = False) -> list[dict]:
        out = []
        with os.scandir(path) as it:
            for e in it:
                if e.name.startswith(".") and not show_hidden:
                    continue
                try:
                    st = e.stat()
                    is_dir = e.is_dir()
                except OSError:
                    continue   # dangling link / vanished entry: skip, never crash the list
                out.append({"name": e.name, "path": e.path, "is_dir": is_dir,
                            "size": 0 if is_dir else st.st_size, "mtime": st.st_mtime})
        out.sort(key=lambda d: (not d["is_dir"], d["name"].lower()))
        return out

    def new_folder(self, parent: str, name: str) -> str:
        p = os.path.join(parent, self.check_name(name))
        if os.path.lexists(p):
            raise ExplorerError("« %s » existe déjà." % os.path.basename(p))
        os.mkdir(p)
        return p

    def rename(self, path: str, new_name: str) -> str:
        dst = os.path.join(os.path.dirname(path), self.check_name(new_name))
        if dst == path:
            return path
        if os.path.lexists(dst):
            raise ExplorerError("« %s » existe déjà." % os.path.basename(dst))
        os.rename(path, dst)
        return dst

    def trash(self, path: str) -> str:
        """Freedesktop trash: move into files/, write info/<name>.trashinfo. Returns the trashed path."""
        path = os.path.abspath(path)
        if path == "/" or not os.path.lexists(path):
            raise ExplorerError("Rien à supprimer.")
        files, info = os.path.join(self.trash_dir, "files"), os.path.join(self.trash_dir, "info")
        os.makedirs(files, exist_ok=True)
        os.makedirs(info, exist_ok=True)
        base = os.path.basename(path)
        name, n = base, 1
        while os.path.lexists(os.path.join(files, name)) or os.path.lexists(os.path.join(info, name + ".trashinfo")):
            n += 1
            name = "%s.%d" % (base, n)
        with open(os.path.join(info, name + ".trashinfo"), "w", encoding="utf-8") as f:
            f.write("[Trash Info]\nPath=%s\nDeletionDate=%s\n" % (quote(path, safe="/"), time.strftime("%Y-%m-%dT%H:%M:%S")))
        dst = os.path.join(files, name)
        try:
            shutil.move(path, dst)
        except OSError:
            os.unlink(os.path.join(info, name + ".trashinfo"))   # the info file we just wrote, not user data
            raise
        return dst


def _open_default(path: str) -> None:
    subprocess.Popen(["xdg-open", path], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class ExplorerWindow(QWidget):
    def __init__(self, path: str | None = None, trash_dir: str | None = None, opener=None,
                 ask_name=None, ask_confirm=None, places=None):
        super().__init__()
        self.store = ExplorerStore(trash_dir)
        self.opener = opener or _open_default
        self.ask_name = ask_name or self._ask_name_default
        self.ask_confirm = ask_confirm or self._ask_confirm_default
        self.cwd = HOME
        self.back_stack: list[str] = []
        self.rows: list[dict] = []

        self.setWindowTitle("Nanterino — Explorateur")
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.btn_back = QPushButton("◀ Retour")
        self.btn_up = QPushButton("▲ Dossier parent")
        self.pathbar = QLineEdit()
        self.hidden = QCheckBox("Fichiers cachés")
        for w in (self.btn_back, self.btn_up):
            bar.addWidget(w)
        bar.addWidget(self.pathbar, 1)
        bar.addWidget(self.hidden)
        root.addLayout(bar)

        split = QSplitter()
        self.sidebar = QListWidget()
        for label, p in (places or PLACES):
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, p)
            self.sidebar.addItem(it)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Nom", "Taille", "Modifié"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 320)
        self.preview = TextPreview()
        split.addWidget(self.sidebar); split.addWidget(self.table); split.addWidget(self.preview)
        split.setStretchFactor(0, 1); split.setStretchFactor(1, 4); split.setStretchFactor(2, 3)
        root.addWidget(split, 1)

        acts = QHBoxLayout()
        self.btn_open = QPushButton("Ouvrir")
        self.btn_mkdir = QPushButton("Nouveau dossier")
        self.btn_rename = QPushButton("Renommer")
        self.btn_delete = QPushButton("Supprimer (corbeille)")
        self.btn_copy = QPushButton("Copier le chemin")
        for b in (self.btn_open, self.btn_mkdir, self.btn_rename, self.btn_delete, self.btn_copy):
            acts.addWidget(b)
        acts.addStretch(1)
        root.addLayout(acts)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.btn_back.clicked.connect(self.go_back)
        self.btn_up.clicked.connect(self.go_up)
        self.pathbar.returnPressed.connect(lambda: self.navigate(self.pathbar.text().strip()))
        self.hidden.toggled.connect(lambda _c: self.refresh())
        self.sidebar.itemClicked.connect(lambda it: self.navigate(it.data(Qt.UserRole)))
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.open_row(r))
        self.btn_open.clicked.connect(lambda: self.open_row(self.table.currentRow()))
        self.btn_mkdir.clicked.connect(self.new_folder)
        self.btn_rename.clicked.connect(self.rename_selected)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_copy.clicked.connect(self.copy_path)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)
        self.navigate(path or HOME, push=False)

    # ---- helpers -----------------------------------------------------------------------------------------
    def say(self, t: str):
        self.status.setText(t)

    def _ask_name_default(self, title, label, default=""):
        text, ok = QInputDialog.getText(self, title, label, text=default)
        return text if ok else None

    def _ask_confirm_default(self, text):
        return QMessageBox.question(self, "Explorateur", text) == QMessageBox.Yes

    def selected(self) -> dict | None:
        r = self.table.currentRow()
        return self.rows[r] if 0 <= r < len(self.rows) else None

    # ---- navigation --------------------------------------------------------------------------------------
    def navigate(self, path: str, push: bool = True) -> bool:
        path = os.path.abspath(os.path.expanduser(path or "/"))
        if not os.path.isdir(path):
            self.say("Dossier introuvable : %s" % path)
            self.pathbar.setText(self.cwd)
            return False
        try:
            self.store.list_dir(path, self.hidden.isChecked())
        except OSError as e:
            self.say("Accès refusé : %s (%s)" % (path, e.strerror))
            self.pathbar.setText(self.cwd)
            return False
        if push and path != self.cwd and self.cwd:
            self.back_stack.append(self.cwd)
        self.cwd = path
        self.refresh()
        return True

    def refresh(self, select: str | None = None):
        try:
            self.rows = self.store.list_dir(self.cwd, self.hidden.isChecked())
        except OSError as e:
            self.rows = []
            self.say("Lecture impossible : %s" % e.strerror)
        self.pathbar.setText(self.cwd)
        self.setWindowTitle("Nanterino — Explorateur — %s" % (os.path.basename(self.cwd) or "/"))
        self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            self.table.setItem(i, 0, QTableWidgetItem(("📁 " if r["is_dir"] else "") + r["name"]))
            self.table.setItem(i, 1, QTableWidgetItem("" if r["is_dir"] else human_size(r["size"])))
            self.table.setItem(i, 2, QTableWidgetItem(human_date(r["mtime"])))
            if select and r["name"] == select:
                self.table.setCurrentCell(i, 0)
        if not select:
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
            self.preview.clear()
        self.btn_back.setEnabled(bool(self.back_stack))
        self.btn_up.setEnabled(self.cwd != "/")

    def go_back(self):
        if self.back_stack:
            self.navigate(self.back_stack.pop(), push=False)

    def go_up(self):
        self.navigate(os.path.dirname(self.cwd) or "/")

    def open_row(self, row: int):
        if not (0 <= row < len(self.rows)):
            return
        r = self.rows[row]
        if r["is_dir"]:
            self.navigate(r["path"])
        else:
            log.info("explorer action=open file=%s", r["name"])
            try:
                self.opener(r["path"])
            except OSError as e:
                self.say("Ouverture impossible : %s" % e.strerror)

    def _on_select(self):
        r = self.selected()
        if r is None:
            return
        if r["is_dir"] or not is_text_name(r["name"]):
            self.preview.clear()
            return
        self.say(self.preview.show_file(r["path"]))

    # ---- actions -----------------------------------------------------------------------------------------
    def new_folder(self):
        name = self.ask_name("Nouveau dossier", "Nom du dossier :", "")
        if not name:
            return
        try:
            p = self.store.new_folder(self.cwd, name)
        except (ExplorerError, OSError) as e:
            self.say(str(e))
            return
        log.info("explorer action=mkdir dir=%s", os.path.basename(p))
        self.refresh(select=os.path.basename(p))
        self.say("Dossier créé : %s" % os.path.basename(p))

    def rename_selected(self):
        r = self.selected()
        if r is None:
            return
        name = self.ask_name("Renommer", "Nouveau nom :", r["name"])
        if not name:
            return
        try:
            p = self.store.rename(r["path"], name)
        except (ExplorerError, OSError) as e:
            self.say(str(e))
            return
        log.info("explorer action=rename to=%s", os.path.basename(p))
        self.refresh(select=os.path.basename(p))
        self.say("Renommé : %s" % os.path.basename(p))

    def delete_selected(self):
        r = self.selected()
        if r is None:
            return
        if not self.ask_confirm("Mettre « %s » à la corbeille ?" % r["name"]):
            return
        try:
            self.store.trash(r["path"])
        except (ExplorerError, OSError) as e:
            self.say(str(e))
            return
        log.info("explorer action=trash file=%s", r["name"])
        self.refresh()
        self.say("« %s » déplacé dans la corbeille (%s)." % (r["name"], self.store.trash_dir))

    def copy_path(self):
        r = self.selected()
        p = r["path"] if r else self.cwd
        QApplication.clipboard().setText(p)
        self.say("Chemin copié : %s" % p)


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")   # IceWM draws the frame
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    app = QApplication(sys.argv)
    w = ExplorerWindow(args[0] if args else None)
    w.resize(1250, 740)
    w.show()
    log.info("explorer started")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
