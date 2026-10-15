"""Friendly robot face (companion-robot style): two glowing rounded eyes, no pupils, no brows.

logging: robotlog via nanterino_ui.app (this module only draws; it logs nothing itself).
Design notes (user feedback 2026-10-15: the first face with slanted brows and small fixed pupils
looked angry and "staring"): no brows, no pupils, soft cyan glow, happy "^ ^" eyes when greeting,
pink cheeks, a small smile that opens with the audio level actually played.
"""
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

BG = QColor("#0a1220")
EYE = QColor("#6ff5dc")
CHEEK = QColor(255, 143, 177, 55)
TEXT = QColor("#eafffa")

# Per state: eye height factor, happy arcs, eye scale, mouth smile amount.
STATES = {
    "veille":  {"h": 0.55, "happy": False, "scale": 0.95, "smile": 0.25},
    "accueil": {"h": 1.0,  "happy": True,  "scale": 1.0,  "smile": 1.0},
    "ecoute":  {"h": 1.0,  "happy": False, "scale": 1.08, "smile": 0.4},
    "reponse": {"h": 0.95, "happy": False, "scale": 1.0,  "smile": 0.5},
    "relance": {"h": 1.0,  "happy": False, "scale": 1.0,  "smile": 0.3},
    "cloture": {"h": 1.0,  "happy": True,  "scale": 1.0,  "smile": 1.0},
}


class FaceWidget(QWidget):
    def __init__(self, on_click):
        super().__init__()
        self.on_click = on_click
        self.s = {"state": "veille", "subtitle": "", "out_level": 0, "mic_level": 0, "speaking": False}
        self.online = False
        self.mouth = self.look = 0.0
        self.eye_h = 0.55  # smoothed, so state changes morph instead of jumping
        self.t0 = time.monotonic()
        QTimer(self, timeout=self.update, interval=16).start()
        self.setCursor(Qt.BlankCursor)

    def mousePressEvent(self, _event):
        self.on_click()

    # ------------------------------------------------------------------ drawing helpers
    def _glow_rect(self, p: QPainter, rect: QRectF, radius: float):
        for i, alpha in ((3, 18), (2, 30), (1, 55)):  # soft halo, then the solid eye
            g = QColor(EYE); g.setAlpha(alpha)
            p.setBrush(g)
            p.drawRoundedRect(rect.adjusted(-i * radius * 0.18, -i * radius * 0.18, i * radius * 0.18, i * radius * 0.18),
                              radius * 1.1, radius * 1.1)
        p.setBrush(EYE)
        p.drawRoundedRect(rect, radius, radius)
        hl = QColor(255, 255, 255, 170)  # small highlight: makes the eye look alive, not empty
        p.setBrush(hl)
        p.drawEllipse(QPointF(rect.left() + rect.width() * 0.3, rect.top() + min(rect.height(), rect.width()) * 0.28),
                      rect.width() * 0.09, rect.width() * 0.09)

    def _happy_eye(self, p: QPainter, cx: float, cy: float, u: float):
        p.setBrush(Qt.NoBrush)  # stroke only: a leftover brush would fill the arc (pink artifact seen in review)
        path = QPainterPath(QPointF(cx - 1.0 * u, cy + 0.35 * u))
        path.quadTo(QPointF(cx, cy - 1.0 * u), QPointF(cx + 1.0 * u, cy + 0.35 * u))
        for w, a in ((0.75, 40), (0.5, 255)):
            c = QColor(EYE); c.setAlpha(a)
            p.setPen(QPen(c, w * u, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(path)
        p.setPen(Qt.NoPen)

    # ------------------------------------------------------------------ paint
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), BG)
        face_h = h * 0.78
        t = time.monotonic() - self.t0
        st = self.s.get("state", "veille")
        cfg = STATES.get(st, STATES["veille"])
        u = min(w, face_h) / 10
        cx, cy = w / 2, face_h * 0.45

        target_h = cfg["h"] + (0.04 * math.sin(t * 1.3) if st == "veille" else 0)  # breathing while idle
        self.eye_h += (target_h - self.eye_h) * 0.15
        period = 5.0 if st == "veille" else 3.8
        blink = 0.12 if (t % period) < 0.13 else 1.0
        self.look += ((math.sin(t * 0.9) * 0.25 if st == "ecoute" else 0.0) - self.look) * 0.05
        speaking = st == "reponse" or self.s.get("speaking")
        target_m = min(1.0, self.s.get("out_level", 0) * 1.6) if speaking else 0.0
        self.mouth += (target_m - self.mouth) * 0.35

        ew, eh_full = 2.1 * u * cfg["scale"], 2.6 * u * cfg["scale"]
        for side in (-1, 1):
            ex = cx + side * 2.3 * u + self.look * u
            if cfg["happy"]:
                self._happy_eye(p, ex, cy, u * cfg["scale"])
            else:
                tilt = 0.85 if (st == "relance" and side > 0) else 1.0  # curious look when prompting
                eh = max(eh_full * self.eye_h * blink * tilt, 0.18 * u)
                self._glow_rect(p, QRectF(ex - ew / 2, cy - eh / 2, ew, eh), min(ew, eh) * 0.42)
            p.setBrush(CHEEK)
            p.drawEllipse(QPointF(cx + side * 3.5 * u, cy + 2.15 * u), 0.75 * u, 0.42 * u)

        my = cy + 2.5 * u
        if self.mouth > 0.06:  # talking: rounded capsule opening with the sound
            mh = 0.25 * u + self.mouth * 0.9 * u
            p.setBrush(EYE)
            p.drawRoundedRect(QRectF(cx - 0.8 * u, my - mh / 2, 1.6 * u, mh), mh / 2, mh / 2)
        else:  # resting: small smile
            sm = cfg["smile"] * 0.45 * u
            path = QPainterPath(QPointF(cx - 0.75 * u, my))
            path.quadTo(QPointF(cx, my + sm), QPointF(cx + 0.75 * u, my))
            p.setPen(QPen(EYE, 0.22 * u, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            p.setPen(Qt.NoPen)

        if st == "ecoute":  # three dots pulsing with the microphone level
            lvl = min(1.0, self.s.get("mic_level", 0) * 2)
            for i in (-1, 0, 1):
                r = 0.12 * u + 0.12 * u * abs(math.sin(t * 4 + i)) + lvl * 0.15 * u
                c = QColor(EYE); c.setAlpha(150)
                p.setBrush(c)
                p.drawEllipse(QPointF(cx + i * 0.85 * u, my + 1.1 * u), r, r)

        if self.s.get("muted"):  # discreet indicator so a silent robot is not mistaken for a broken one
            p.setPen(QColor(255, 255, 255, 120)); p.setFont(QFont("Sans", max(10, int(h * 0.025))))
            p.drawText(QRectF(0, 8, w - 16, h * 0.05), Qt.AlignRight, "🔇 muet")

        p.setPen(TEXT)
        p.setFont(QFont("Sans", max(12, int(h * 0.042))))
        text = self.s.get("subtitle", "") if self.online else "Nanterino démarre…"
        p.drawText(QRectF(w * 0.05, face_h, w * 0.9, h - face_h), Qt.AlignCenter | Qt.TextWordWrap, text)
        p.end()
