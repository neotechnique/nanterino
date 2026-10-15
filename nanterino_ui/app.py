"""Nanterino native UI (PySide6). Run: python -m nanterino_ui.app [--dash] [--windowed]

logging: robotlog -> /var/log/robot/nanterino-ui.log (actions and errors only, never dialogue text).

Keys: Tab = switch face / dashboard · F11 = toggle full screen · Esc = leave full screen.
A click on the face starts a conversation (same as the "Démarrer" button).
Data: /api/live polled at 10 Hz (state, subtitle, audio levels), /api/status every 2 s.
"""
import json
import math
import sys
import time

sys.path.insert(0, "/opt/robot/lib")
from robotlog import get_logger  # noqa: E402

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen  # noqa: E402
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest  # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox, QFormLayout, QGridLayout, QGroupBox,  # noqa: E402
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPlainTextEdit,
                               QProgressBar, QPushButton, QSlider, QStackedWidget, QVBoxLayout, QWidget)

log = get_logger("nanterino-ui")
API = "http://127.0.0.1:8080/api"

# Expression per dialogue state (cahier des charges §2): eye openness, smile, raised brows.
EXPR = {
    "veille": (0.75, 0.15, 0.0), "accueil": (1.0, 0.9, 0.2), "ecoute": (1.0, 0.3, 0.1),
    "reponse": (1.0, 0.45, 0.1), "relance": (1.1, 0.35, 0.8), "cloture": (0.9, 1.0, 0.2),
}
BG, FACE, ACCENT, MOUTH = QColor("#0b1d16"), QColor("#e8fff4"), QColor("#3ddc97"), QColor("#123d2c")


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


class FaceWidget(QWidget):
    """Animated face drawn with QPainter at 60 fps; mouth follows the audio actually played."""

    def __init__(self, on_click):
        super().__init__()
        self.on_click = on_click
        self.s = {"state": "veille", "subtitle": "", "out_level": 0, "mic_level": 0, "speaking": False}
        self.online = False
        self.mouth = self.look = 0.0
        self.t0 = time.monotonic()
        timer = QTimer(self, timeout=self.update)
        timer.start(16)
        self.setCursor(Qt.BlankCursor)

    def mousePressEvent(self, _event):
        self.on_click()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), BG)
        face_h = h * 0.78
        t = (time.monotonic() - self.t0) * 1000
        st = self.s.get("state", "veille")
        eye, smile, brow = EXPR.get(st, EXPR["veille"])
        u = min(w, face_h) / 10
        cx, cy = w / 2, face_h * 0.48
        period = 5000 if st == "veille" else 3500
        blink = 0.08 if (t % period) < 140 else 1.0
        self.look += ((math.sin(t / 900) * 0.15 if st == "ecoute" else 0) - self.look) * 0.05
        target = min(1.0, self.s.get("out_level", 0) * 1.5) if (st == "reponse" or self.s.get("speaking")) else 0
        self.mouth += (target - self.mouth) * 0.35
        for side in (-1, 1):  # eyes, pupils, brows
            ex = cx + side * 2.4 * u + self.look * u
            eh = max(1.3 * u * eye * blink, 0.06 * u)
            p.setPen(Qt.NoPen); p.setBrush(FACE)
            p.drawEllipse(QPointF(ex, cy - 0.6 * u), 0.85 * u, eh)
            p.setBrush(BG)
            r = 0.32 * u * min(1, blink * 2)
            p.drawEllipse(QPointF(ex + self.look * u * 0.6, cy - 0.5 * u), r, r)
            p.setPen(QPen(FACE, 0.18 * u, Qt.SolidLine, Qt.RoundCap))
            by = cy - 2.2 * u - brow * 0.6 * u
            p.drawLine(QPointF(ex - 0.8 * u, by + side * 0.1 * u), QPointF(ex + 0.8 * u, by - side * 0.1 * u))
        mw, my, opening, sm = 2.2 * u, cy + 2.2 * u, self.mouth * 1.1 * u, smile * 0.8 * u
        path = QPainterPath(QPointF(cx - mw, my))
        path.quadTo(QPointF(cx, my + sm + opening), QPointF(cx + mw, my))
        if opening > 0.05 * u:
            path.quadTo(QPointF(cx, my + sm - opening * 0.3), QPointF(cx - mw, my))
            p.setBrush(MOUTH)
        else:
            p.setBrush(Qt.NoBrush)
        p.setPen(QPen(ACCENT, 0.22 * u, Qt.SolidLine, Qt.RoundCap))
        p.drawPath(path)
        if st == "ecoute":  # listening cue
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(61, 220, 151, 128), 0.08 * u))
            rr = 0.4 * u + self.s.get("mic_level", 0) * 1.2 * u
            p.drawEllipse(QPointF(cx, my + 2.4 * u), rr, rr)
        p.setPen(FACE)
        f = QFont("Sans", max(12, int(h * 0.042)))
        p.setFont(f)
        text = self.s.get("subtitle", "") if self.online else "Nanterino démarre…"
        p.drawText(QRectF(w * 0.05, face_h, w * 0.9, h - face_h), Qt.AlignCenter | Qt.TextWordWrap, text)
        p.end()


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
        self.ask = QLineEdit(placeholderText="Poser une question (test sans micro) puis Entrée")
        self.ask.returnPressed.connect(lambda: self._send("ask", self.ask))
        self.say = QLineEdit(placeholderText="Faire parler le robot puis Entrée")
        self.say.returnPressed.connect(lambda: self._send("say", self.say))
        for wdg in (self.state, self.sub):
            v.addWidget(wdg)
        v.addLayout(row); v.addWidget(self.ask); v.addWidget(self.say)
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
        hint = QLabel("Tab : visage / tableau · F11 : plein écran · Échap : quitter le plein écran")
        hint.setStyleSheet("color:gray"); grid.addWidget(hint, 3, 0, 1, 2)

    def _send(self, action, field: QLineEdit):
        if field.text().strip():
            self.api.post({"action": action, "text": field.text().strip()})
            field.clear()

    def live(self, s):
        self.state.setText(s.get("state", "?"))
        self.sub.setText(s.get("subtitle", ""))
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
        self.face = FaceWidget(lambda: self.api.post({"action": "start"}))
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
        elif e.key() == Qt.Key_F11:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()
        elif e.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
        else:
            super().keyPressEvent(e)


def main():
    app = QApplication(sys.argv)
    win = Main(start_dash="--dash" in sys.argv)
    if "--windowed" in sys.argv or "--dash" in sys.argv:
        win.resize(1100, 760); win.show()
    else:
        win.showFullScreen()
    log.info("ui started mode=%s", "dash" if "--dash" in sys.argv else "face")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
