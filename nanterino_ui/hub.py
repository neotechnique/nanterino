"""Nanterino launcher panel: the single desktop icon, acting like a "folder" of Nanterino tools.

logging: robotlog -> /var/log/robot/nanterino-ui.log (which button was used, never content).
Why not a real desktop folder: Nautilus 46 cannot launch .desktop files from a folder window.
"""
import subprocess
import sys

sys.path.insert(0, "/opt/robot/lib")
from robotlog import get_logger  # noqa: E402

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget  # noqa: E402

log = get_logger("nanterino-ui")
PY = "/opt/robot/nanterino/.venv/bin/python"
ROOT = "/opt/robot/nanterino"

ACTIONS = [
    ("🙂  Visage (plein écran)", [PY, "-m", "nanterino_ui.app"]),
    ("📊  Tableau technique", [PY, "-m", "nanterino_ui.app", "--dash"]),
    ("🔄  Redémarrer Nanterino", ["gnome-terminal", "--", "bash", "-c",
                                 "systemctl --user restart nanterino-stt nanterino-llm nanterino; sleep 15; "
                                 "systemctl --user --no-pager status nanterino nanterino-stt nanterino-llm | grep -E '●|Active'; "
                                 "read -p 'Entrée pour fermer'"]),
    ("📁  Fiches du corpus", ["xdg-open", f"{ROOT}/fiches"]),
    ("📜  Logs (/var/log/robot)", ["xdg-open", "/var/log/robot"]),
]


def main():
    app = QApplication(sys.argv)
    w = QWidget()
    w.setWindowTitle("Nanterino")
    lay = QVBoxLayout(w)
    title = QLabel("Nanterino")
    title.setStyleSheet("font-size:24px;font-weight:700;margin-bottom:8px")
    lay.addWidget(title)
    for label, cmd in ACTIONS:
        b = QPushButton(label)
        b.setStyleSheet("text-align:left;padding:12px;font-size:16px")

        def launch(_=False, c=cmd, l=label):
            log.info("hub launch=%s", l.split(maxsplit=1)[-1])
            subprocess.Popen(c, cwd=ROOT, start_new_session=True)
        b.clicked.connect(launch)
        lay.addWidget(b)
    w.resize(380, 340)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
