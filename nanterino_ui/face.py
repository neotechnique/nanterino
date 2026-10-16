"""Friendly robot face (companion-robot style): two glowing rounded eyes with moving round pupils.

logging: robotlog via nanterino_ui.app (this module only draws; it logs nothing itself).

Design decisions (user feedback, 2026-10-15):
- first face (slanted brows, small fixed pupils) looked angry/staring -> no brows;
- fixed white highlight read as pupils staring one way -> no white dot anywhere;
- eyes keep a constant WIDE shape in every state (no breathing / half-closed lids); only the
  blink and the "eteint" state close them; round blue pupils move INSIDE the eyes;
- ONE consistent glow recipe for every element (crisp solid shape + identical soft halo), so
  eyes, pupils, cheeks, mouth and listening dots have the same balance (no element "blurrier").
"""
import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import QWidget

BG = QColor("#0a1220")
EYE = QColor("#6ff5dc")
PUPIL = QColor("#1e90ff")           # saturated luminous blue, no whitish centre
CHEEK = QColor(255, 110, 165, 200)  # crisp pink, same glow as everything else
TEXT = QColor("#eafffa")

# Shared glow recipe: halo width relative to the face unit `u`, three layers (wide -> tight).
GLOW_U = 0.30
GLOW_LAYERS = ((1.0, 22), (0.66, 40), (0.33, 70))

STATES = {  # constant eye size in every state; only blink / eteint close the eyes
    "veille":  {"happy": False, "smile": 0.25},
    "accueil": {"happy": True,  "smile": 1.0},
    "ecoute":  {"happy": False, "smile": 0.4},
    "reponse": {"happy": False, "smile": 0.5},
    "relance": {"happy": False, "smile": 0.3},
    "cloture": {"happy": True,  "smile": 1.0},
    "eteint":  {"happy": False, "smile": 0.0, "closed": True},
}


class FaceWidget(QWidget):
    def __init__(self, on_click, on_toggle=None):
        super().__init__()
        self.on_click = on_click
        # on_toggle("mute" | "deaf"): called when the matching badge (top right) is clicked.
        self.on_toggle = on_toggle
        # Badges can be hidden (key I) for demos; remembered locally across restarts.
        self._settings = QSettings("nanterino", "ui")
        self.show_flags = self._settings.value("show_flags", True, type=bool)
        self._flag_rects = {}  # action -> QRectF of the badge drawn in the last frame
        self.s = {"state": "veille", "subtitle": "", "out_level": 0, "mic_level": 0, "speaking": False}
        self.online = False
        self.mouth = 0.0
        self.eye_open = 1.0  # smoothed (closing when switched off is animated)
        # Natural gaze = pupil position in [-1, 1] inside the eye; random saccades every 2-5 s.
        self.gaze = [0.0, 0.0]; self.gaze_target = [0.0, 0.0]; self.next_saccade = 0.0
        self.t0 = time.monotonic()
        QTimer(self, timeout=self.update, interval=16).start()
        # Kiosk face: cursor hidden, but shown while the mouse moves (remote control, badges),
        # then hidden again after 3 s without movement.
        self.setCursor(Qt.BlankCursor)
        self.setMouseTracking(True)
        self._cursor_timer = QTimer(self, singleShot=True, interval=3000,
                                    timeout=lambda: self.setCursor(Qt.BlankCursor))

    def mouseMoveEvent(self, _event):
        self.setCursor(Qt.ArrowCursor)
        self._cursor_timer.start()

    def mousePressEvent(self, event):
        pos = event.position()
        for action, rect in self._flag_rects.items():
            if rect.contains(pos) and self.on_toggle:
                self.on_toggle(action)
                return
        self.on_click()

    def toggle_flags(self):
        self.show_flags = not self.show_flags
        self._settings.setValue("show_flags", self.show_flags)

    # ------------------------------------------------------------------ one glow recipe for all
    def _glow(self, p: QPainter, path: QPainterPath, color: QColor, u: float):
        """Crisp filled `path` + identical soft halo (strokes centred on its outline)."""
        p.setBrush(Qt.NoBrush)
        for k, alpha in GLOW_LAYERS:
            c = QColor(color); c.setAlpha(int(alpha * color.alphaF()))
            p.setPen(QPen(c, GLOW_U * u * k * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
        p.setPen(Qt.NoPen); p.setBrush(color)
        p.drawPath(path)

    @staticmethod
    def _stroke(path: QPainterPath, width: float) -> QPainterPath:
        """Turn a line (smile, happy-eye arc) into a fillable shape so it uses the same glow."""
        s = QPainterPathStroker(); s.setWidth(width); s.setCapStyle(Qt.RoundCap)
        return s.createStroke(path)

    def _eye(self, p: QPainter, rect: QRectF, radius: float, u: float, with_pupil: bool):
        shape = QPainterPath(); shape.addRoundedRect(rect, radius, radius)
        self._glow(p, shape, EYE, u)
        if not with_pupil or rect.height() < rect.width() * 0.25:
            return  # eye (almost) closed: no pupil
        r = min(rect.width(), rect.height()) * 0.30
        px = rect.center().x() + self.gaze[0] * (rect.width() / 2 - r * 1.15)
        py = rect.center().y() + self.gaze[1] * (rect.height() / 2 - r * 1.15)
        pupil = QPainterPath(); pupil.addEllipse(QPointF(px, py), r, r)
        p.save(); p.setClipPath(shape)  # the pupil (and its halo) never leaves the eye
        self._glow(p, pupil, PUPIL, u * 0.6)  # same recipe, scaled to the pupil size
        p.restore()

    def _happy_eye(self, p: QPainter, cx: float, cy: float, u: float):
        arc = QPainterPath(QPointF(cx - 1.0 * u, cy + 0.35 * u))
        arc.quadTo(QPointF(cx, cy - 1.0 * u), QPointF(cx + 1.0 * u, cy + 0.35 * u))
        self._glow(p, self._stroke(arc, 0.45 * u), EYE, u)

    # ------------------------------------------------------------------ gaze
    def _update_gaze(self, st: str, t: float):
        face = self.s.get("face") or {}
        if st == "eteint":  # eyes closed: no tracking, no wandering
            self.gaze_target = [0.0, 0.0]; self.next_saccade = t + 1.0
        elif face.get("present"):
            # Look AT the person: a person facing the screen appears mirrored in the camera image.
            g = self.s.get("gaze") or {}  # calibration from the dashboard (camera above the screen)
            gx = -face.get("x", 0) * g.get("gain_x", 1.6) + g.get("offset_x", 0.0)
            gy = face.get("y", 0) * g.get("gain_y", 1.4) + g.get("offset_y", 0.0)
            self.gaze_target = [max(-1, min(1, gx)), max(-1, min(1, gy))]
            self.next_saccade = t + 1.5  # resume wandering 1.5 s after the face disappears
        elif t >= self.next_saccade:
            if st in ("ecoute", "reponse"):  # attending: small drift only
                self.gaze_target = [random.uniform(-0.15, 0.15), random.uniform(-0.1, 0.1)]
            else:
                self.gaze_target = [random.uniform(-0.8, 0.8), random.uniform(-0.5, 0.4)]
            self.next_saccade = t + random.uniform(2.0, 5.0)
        for i in (0, 1):
            self.gaze[i] += (self.gaze_target[i] - self.gaze[i]) * 0.18

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
        # Face unit; the dashboard "Taille du visage" slider scales the whole face around its centre.
        u = min(w, face_h) / 10 * float(self.s.get("face_scale", 1.0) or 1.0)
        cx, cy = w / 2, face_h * 0.45

        self.eye_open += ((0.07 if cfg.get("closed") else 1.0) - self.eye_open) * 0.15
        blink = 0.12 if (t % (5.0 if st == "veille" else 3.8)) < 0.13 else 1.0
        self._update_gaze(st, t)
        speaking = st == "reponse" or self.s.get("speaking")
        target_m = min(1.0, self.s.get("out_level", 0) * 1.6) if speaking else 0.0
        self.mouth += (target_m - self.mouth) * 0.35

        ew, eh_full = 2.2 * u, 1.45 * u  # wide eyes, constant size
        for side in (-1, 1):
            ex = cx + side * 2.3 * u
            if cfg["happy"]:
                self._happy_eye(p, ex, cy, u)
            else:
                eh = max(eh_full * self.eye_open * blink, 0.18 * u)
                rect = QRectF(ex - ew / 2, cy - eh / 2, ew, eh)
                self._eye(p, rect, min(ew, eh) * 0.42, u, with_pupil=not cfg.get("closed"))
            cheek = QPainterPath(); cheek.addEllipse(QPointF(cx + side * 3.5 * u, cy + 2.15 * u), 0.62 * u, 0.36 * u)
            self._glow(p, cheek, CHEEK, u)

        my = cy + 2.5 * u
        if self.mouth > 0.06:  # talking: capsule opening with the sound actually played
            mh = 0.25 * u + self.mouth * 0.9 * u
            cap = QPainterPath(); cap.addRoundedRect(QRectF(cx - 0.8 * u, my - mh / 2, 1.6 * u, mh), mh / 2, mh / 2)
            self._glow(p, cap, EYE, u)
        else:  # resting smile
            sm = cfg["smile"] * 0.45 * u
            line = QPainterPath(QPointF(cx - 0.75 * u, my))
            line.quadTo(QPointF(cx, my + sm), QPointF(cx + 0.75 * u, my))
            self._glow(p, self._stroke(line, 0.22 * u), EYE, u)

        if st == "ecoute":  # three dots pulsing with the microphone level
            lvl = min(1.0, self.s.get("mic_level", 0) * 2)
            for i in (-1, 0, 1):
                r = 0.10 * u + 0.08 * u * abs(math.sin(t * 4 + i)) + lvl * 0.10 * u
                dot = QPainterPath(); dot.addEllipse(QPointF(cx + i * 0.85 * u, my + 1.1 * u), r, r)
                self._glow(p, dot, EYE, u * 0.6)

        # Clickable badges, right to left: deaf then mute. Active = bright (so a silent/deaf
        # robot is not mistaken for a broken one), inactive = faint. Hidden with key I.
        self._flag_rects = {}
        if self.show_flags:
            font = QFont("Sans", max(10, int(h * 0.025))); p.setFont(font)
            fm = QFontMetricsF(font)
            x = w - 16.0
            for key, action, on_txt, off_txt in (("deaf", "deaf", "🙉 sourd", "👂 écoute"),
                                                 ("muted", "mute", "🔇 muet", "🔊 son")):
                active = bool(self.s.get(key))
                txt = on_txt if active else off_txt
                tw = fm.horizontalAdvance(txt) + 16
                rect = QRectF(x - tw, 8, tw, fm.height() + 8)
                p.setPen(QColor(255, 255, 255, 200 if active else 70))
                p.drawText(rect, Qt.AlignCenter, txt)
                self._flag_rects[action] = rect
                x -= tw + 12

        p.setPen(TEXT)
        p.setFont(QFont("Sans", max(12, int(h * 0.042))))
        text = self.s.get("subtitle", "") if self.online else "Nanterino démarre…"
        p.drawText(QRectF(w * 0.05, face_h, w * 0.9, h - face_h), Qt.AlignCenter | Qt.TextWordWrap, text)
        p.end()
