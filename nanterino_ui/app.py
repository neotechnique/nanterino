"""Nanterino native UI (PySide6). Run: python -m nanterino_ui.app [--dash] [--windowed]

logging: robotlog -> /var/log/robot/nanterino-ui.log (actions and errors only, never dialogue text).

Options: --dash (start on the dashboard), --kiosk (full screen face for the robot screen).
Keys: Tab = switch face / dashboard · F11 = toggle full screen · Esc = leave full screen.
A click on the face starts a conversation (same as the "Démarrer" button).
Data: /api/live polled at 10 Hz (state, subtitle, audio levels), /api/status every 2 s.
"""
import json
import os
import sys
import time

sys.path.insert(0, "/opt/robot/lib")
from robotlog import get_logger  # noqa: E402

from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest  # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox, QFormLayout, QGridLayout, QGroupBox,  # noqa: E402
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPlainTextEdit,
                               QProgressBar, QPushButton, QSlider, QStackedWidget, QVBoxLayout, QWidget)

from nanterino_ui.face import FaceWidget  # noqa: E402

log = get_logger("nanterino-ui")
API = "http://127.0.0.1:8080/api"



class Api:
    """Async HTTP helper on the Qt event loop (no threads, never blocks the animation)."""

    def __init__(self):
        self.net = QNetworkAccessManager()

    def get(self, path, cb):
        reply = self.net.get(QNetworkRequest(QUrl(API + path)))
        reply.finished.connect(lambda: self._done(reply, cb))

    def post(self, body: dict, cb=None):
        req = QNetworkRequest(QUrl(API + "/control"))
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        reply = self.net.post(req, QByteArray(json.dumps(body).encode()))
        reply.finished.connect(lambda: self._done(reply, cb))
        log.info("ui action=%s", body.get("action"))  # action name only, never typed text

    @staticmethod
    def _done(reply, cb):
        data = bytes(reply.readAll())
        ok = reply.error() == QNetworkReply.NoError
        reply.deleteLater()
        if cb:
            if not ok:
                cb(None)
                return
            try:
                cb(json.loads(data))
            except ValueError:
                cb(data.decode(errors="replace"))


class Dashboard(QWidget):
    """Native technical dashboard (Jetson equivalent of the Pi AI-Orchestrator window)."""

    def __init__(self, api: Api):
        super().__init__()
        self.api = api
        grid = QGridLayout(self)
        # Dialogue
        box = QGroupBox("Dialogue"); v = QVBoxLayout(box)
        self.state = QLabel("…"); self.state.setStyleSheet("font-size:22px;font-weight:700")
        self.sub = QLabel(""); self.sub.setWordWrap(True)
        row = QHBoxLayout()
        for label, action, color in (("Démarrer", "start", "#1f9d63"), ("Stop", "stop", "#c63d3d")):
            b = QPushButton(label); b.setStyleSheet(f"background:{color};color:white;padding:10px;font-weight:700")
            b.clicked.connect(lambda _=False, a=action: self.api.post({"action": a}))
            row.addWidget(b)
        row2 = QHBoxLayout()
        hush = QPushButton("🤫 Tais-toi"); hush.setStyleSheet("padding:10px;font-weight:700")
        hush.clicked.connect(lambda: self.api.post({"action": "hush"}))
        self.mute = QPushButton("🔇 Muet : non"); self.mute.setCheckable(True); self.mute.setStyleSheet("padding:10px;font-weight:700")
        self.mute.clicked.connect(lambda checked: self.api.post({"action": "mute", "value": checked}))
        self.power = QPushButton("⏻ Éteindre"); self.power.setStyleSheet("padding:10px;font-weight:700")
        self.power.clicked.connect(lambda: self.api.post({"action": "on" if self._off else "off"}))
        self._off = False
        self.deaf = QPushButton("🙉 Sourd : non"); self.deaf.setCheckable(True); self.deaf.setStyleSheet("padding:10px;font-weight:700")
        self.deaf.clicked.connect(lambda checked: self.api.post({"action": "deaf", "value": checked}))
        row2.addWidget(hush); row2.addWidget(self.mute); row2.addWidget(self.deaf); row2.addWidget(self.power)
        self.ask = QLineEdit(placeholderText="Poser une question (test sans micro) puis Entrée")
        self.ask.returnPressed.connect(lambda: self._send("ask", self.ask))
        self.say = QLineEdit(placeholderText="Faire parler le robot puis Entrée")
        self.say.returnPressed.connect(lambda: self._send("say", self.say))
        for wdg in (self.state, self.sub):
            v.addWidget(wdg)
        v.addLayout(row); v.addLayout(row2); v.addWidget(self.ask); v.addWidget(self.say)
        grid.addWidget(box, 0, 0)
        # Audio
        box = QGroupBox("Audio"); f = QFormLayout(box)
        self.mic, self.out = QProgressBar(), QProgressBar()
        for bar in (self.mic, self.out):
            bar.setRange(0, 100); bar.setTextVisible(False)
        self.volume = QSlider(Qt.Horizontal); self.volume.setRange(0, 100)
        self.volume.sliderReleased.connect(lambda: self.api.post({"action": "volume", "value": self.volume.value() / 100}))
        self.keep = QComboBox()
        self.keep.addItems(["off", "-90", "-80", "-70", "-60", "-50"])
        self.keep.activated.connect(lambda _i: self.api.post({"action": "keepalive_db", "value": self.keep.currentText()}))
        self.sink = QLabel("–"); self.sink.setWordWrap(True)
        f.addRow("Micro", self.mic); f.addRow("Sortie", self.out); f.addRow("Volume", self.volume)
        f.addRow("Anti-veille (dB)", self.keep); f.addRow("Enceinte", self.sink)
        grid.addWidget(box, 0, 1)
        # Engines + latency
        box = QGroupBox("Moteurs IA"); f = QFormLayout(box)
        self.eng = {k: QLabel("–") for k in ("stt", "llm", "tts")}
        for k, lab in self.eng.items():
            f.addRow(k.upper(), lab)
        self.sheets, self.lat = QLabel("–"), QLabel("–"); self.lat.setWordWrap(True)
        reload_btn = QPushButton("Recharger le corpus")
        reload_btn.clicked.connect(lambda: self.api.post({"action": "reload_corpus"}))
        f.addRow("Fiches", self.sheets); f.addRow("Latence", self.lat); f.addRow(reload_btn)
        grid.addWidget(box, 1, 0)
        # Hardware
        box = QGroupBox("Matériel (tegrastats)"); self.hw = QLabel("–"); QVBoxLayout(box).addWidget(self.hw)
        grid.addWidget(box, 1, 1)
        # Errors
        box = QGroupBox("Erreurs et avertissements récents"); self.err = QPlainTextEdit(readOnly=True)
        QVBoxLayout(box).addWidget(self.err)
        grid.addWidget(box, 2, 0, 1, 2)
        hint = QLabel("Tab : visage / tableau · H : tais-toi · M : muet · D : sourd · I : masquer muet/sourd · F11 : plein écran · Échap : quitter le plein écran")
        hint.setStyleSheet("color:gray"); grid.addWidget(hint, 3, 0, 1, 2)

    def _send(self, action, field: QLineEdit):
        if field.text().strip():
            self.api.post({"action": action, "text": field.text().strip()})
            field.clear()

    def live(self, s):
        self.state.setText(s.get("state", "?"))
        self._off = s.get("state") == "eteint"
        self.power.setText("⏻ Allumer" if self._off else "⏻ Éteindre")
        self.sub.setText(s.get("subtitle", ""))
        self.deaf.setChecked(bool(s.get("deaf"))); self.deaf.setText("🙉 Sourd : " + ("oui" if s.get("deaf") else "non"))
        self.mute.setChecked(bool(s.get("muted"))); self.mute.setText("🔇 Muet : " + ("oui" if s.get("muted") else "non"))
        self.mic.setValue(int(min(1, s.get("mic_level", 0)) * 100))
        self.out.setValue(int(min(1, s.get("out_level", 0)) * 100))
        lat = s.get("latencies_ms", [])
        self.lat.setText(f"dernière {lat[-1]} ms · moy {sum(lat)//len(lat)} ms · max {max(lat)} ms ({len(lat)})" if lat else "aucun échange")

    def status(self, s):
        for k, lab in self.eng.items():
            ok = s.get("engines", {}).get(k)
            lab.setText("prêt" if ok else "indisponible"); lab.setStyleSheet(f"color:{'#1f9d63' if ok else '#c63d3d'}")
        self.sheets.setText(str(s.get("sheets", "–")))
        sp = s.get("speaker", {})
        if not self.volume.isSliderDown():
            self.volume.setValue(int(sp.get("volume", s.get("volume", 0.8)) * 100))
        if not self.keep.view().isVisible():
            k = sp.get("keepalive_noise_db")
            self.keep.setCurrentText("off" if k is None else str(int(k)))
        self.sink.setText((sp.get("sink") or "?").replace("alsa_output.", "")[:50])
        m = s.get("metrics", {})
        lines = [f"CPU {m.get('cpu_pct', '–')} %   GPU {m.get('gpu_pct', '–')} %   {m.get('power_w', '–')} W",
                 f"RAM {m.get('ram_used_mb', '–')} / {m.get('ram_total_mb', '–')} Mo"]
        lines += ["   ".join(f"{k} {v:.0f}°C" for k, v in m.get("temps", {}).items())]
        self.hw.setText("\n".join(lines))


class Main(QMainWindow):
    def __init__(self, start_dash: bool):
        super().__init__()
        self.setWindowTitle("Nanterino")
        self.api = Api()
        self.face = FaceWidget(lambda: self.api.post({"action": "start"}),
                               lambda action: self.api.post({"action": action}))  # toggles
        self.dash = Dashboard(self.api)
        self.stack = QStackedWidget(); self.stack.addWidget(self.face); self.stack.addWidget(self.dash)
        self.setCentralWidget(self.stack)
        if start_dash:
            self.stack.setCurrentWidget(self.dash)
        QTimer(self, timeout=lambda: self.api.get("/live", self._live), interval=100).start()
        QTimer(self, timeout=self._slow, interval=2000).start()
        self._slow()

    def _live(self, s):
        self.face.online = isinstance(s, dict)
        if isinstance(s, dict):
            self.face.s = s
            self.dash.live(s)

    def _slow(self):
        self.api.get("/status", lambda s: isinstance(s, dict) and self.dash.status(s))
        self.api.get("/errors", lambda t: isinstance(t, str) and self.dash.err.setPlainText(t))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Tab:
            self.stack.setCurrentIndex(1 - self.stack.currentIndex())
        elif e.key() == Qt.Key_M:
            self.api.post({"action": "mute"})
        elif e.key() == Qt.Key_D:  # deaf toggle (server toggles when no value is given)
            self.api.post({"action": "deaf"})
        elif e.key() == Qt.Key_I:  # show/hide the mute/deaf badges of the face
            self.face.toggle_flags()
        elif e.key() == Qt.Key_H:
            self.api.post({"action": "hush"})
        elif e.key() == Qt.Key_F11:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()
        elif e.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
        else:
            super().keyPressEvent(e)


def main():
    kiosk = "--kiosk" in sys.argv
    if not kiosk:
        # Normal window: use XWayland so GNOME draws real title bars (move / resize / minimise).
        # Qt's own Wayland decorations were hard to use (user, 2026-10-15). Kiosk keeps Wayland.
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    app = QApplication(sys.argv)
    win = Main(start_dash="--dash" in sys.argv)
    win.setMinimumSize(480, 320)
    if kiosk:
        win.showFullScreen()  # robot screen: full screen face (F11 / Échap still work)
    else:
        win.resize(1100, 760); win.show()
    log.info("ui started mode=%s", "dash" if "--dash" in sys.argv else "face")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
