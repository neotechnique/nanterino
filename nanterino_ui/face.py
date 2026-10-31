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
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap
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

# Expressions set by the graph action `set_expression` (snapshot["expression"]): they override the state's
# look while active. smile < 0 draws a frown; eye_scale multiplies the eye height; look = pupil target.
EXPRESSIONS = {
    "content":   {"happy": True,  "smile": 1.0},
    "surpris":   {"happy": False, "smile": 0.0, "eye_scale": 1.3},
    "reflechit": {"happy": False, "smile": 0.1, "look": (0.55, -0.65)},
    "triste":    {"happy": False, "smile": -0.8, "eye_scale": 0.8, "look": (0.0, 0.55)},
    "neutre":    {"happy": False, "smile": 0.0},
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
        self._s = {"state": "veille", "subtitle": "", "out_level": 0, "mic_level": 0, "speaking": False}
        self._online = False
        self.mouth = 0.0
        self.eye_open = 1.0  # smoothed (closing when switched off is animated)
        # Natural gaze = pupil position in [-1, 1] inside the eye; random saccades every 2-5 s.
        self.gaze = [0.0, 0.0]; self.gaze_target = [0.0, 0.0]; self.next_saccade = 0.0
        self.t0 = time.monotonic()
        # Perf (2026-10-29): 30 fps is enough for these slow animations (software rendering made the
        # 60 fps timer cost a full core). Smoothing factors below were tuned per 16 ms frame, so
        # paintEvent rescales them by the real elapsed time to keep the same motion per second.
        self._last_paint = self.t0
        self._anim = QTimer(self, timeout=self.update, interval=33)
        self._anim.start()
        self._fonts = {}        # point size -> QFont, created once instead of per paint
        self._cheek_cache = {}  # side -> (key, QPixmap, QPointF origin): static glow drawn once
        # Kiosk face: cursor hidden, but shown while the mouse moves (remote control, badges),
        # then hidden again after 3 s without movement.
        self.setCursor(Qt.BlankCursor)
        self.setMouseTracking(True)
        self._cursor_timer = QTimer(self, singleShot=True, interval=3000,
                                    timeout=lambda: self.setCursor(Qt.BlankCursor))

    # Anything the face shows that is not animated by the paint loop itself. A change here wakes
    # the timer up again when the robot is switched off and the eyes have settled.
    @staticmethod
    def _view_key(s: dict):
        return (s.get("state"), s.get("subtitle"), s.get("muted"), s.get("deaf"), s.get("face_scale"),
                s.get("speaking"), bool((s.get("face") or {}).get("present")),
                (s.get("expression") or {}).get("name"), s.get("gaze_mode"))

    @property
    def s(self):
        return self._s

    @s.setter
    def s(self, new: dict):
        changed = self._view_key(new) != self._view_key(self._s)
        self._s = new
        if changed:
            self._wake()

    @property
    def online(self):
        return self._online

    @online.setter
    def online(self, value: bool):
        if value != self._online:
            self._online = value
            self._wake()

    def _wake(self):
        if not self._anim.isActive():
            self._anim.start()
        self.update()

    def _settled(self) -> bool:
        """True when 'eteint' and nothing moves any more: the timer can stop until the next change."""
        return (self._s.get("state") == "eteint" and abs(self.eye_open - 0.07) < 0.002
                and abs(self.gaze[0]) < 0.002 and abs(self.gaze[1]) < 0.002 and self.mouth < 0.002)

    def showEvent(self, event):
        self._wake()
        super().showEvent(event)

    def hideEvent(self, event):  # dashboard page shown: nothing to animate
        self._anim.stop()
        super().hideEvent(event)

    def _font(self, size: int) -> QFont:
        f = self._fonts.get(size)
        if f is None:
            f = self._fonts[size] = QFont("Sans", size)
        return f

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
        self._wake()

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

    def _draw_cheek(self, p: QPainter, side: int, cx: float, cy: float, u: float):
        """Cheeks never animate: render the glow once into a QPixmap, re-render only when the
        geometry (size / face scale) changes, then blit it (saves 4 big stroked paths per frame)."""
        centre = QPointF(cx + side * 3.5 * u, cy + 2.15 * u)
        dpr = self.devicePixelRatioF()
        key = (round(u, 3), round(centre.x(), 2), round(centre.y(), 2), dpr)
        hit = self._cheek_cache.get(side)
        if hit is None or hit[0] != key:
            m = GLOW_U * u + 4  # halo half-width + antialiasing margin
            ox, oy = centre.x() - 0.62 * u - m, centre.y() - 0.36 * u - m
            wpx, hpx = 1.24 * u + 2 * m, 0.72 * u + 2 * m
            pm = QPixmap(int(math.ceil(wpx * dpr)), int(math.ceil(hpx * dpr)))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.Antialiasing)
            q.translate(-ox, -oy)
            cheek = QPainterPath(); cheek.addEllipse(centre, 0.62 * u, 0.36 * u)
            self._glow(q, cheek, CHEEK, u)
            q.end()
            hit = self._cheek_cache[side] = (key, pm, QPointF(ox, oy))
        p.drawPixmap(hit[2], hit[1])

    def _happy_eye(self, p: QPainter, cx: float, cy: float, u: float):
        arc = QPainterPath(QPointF(cx - 1.0 * u, cy + 0.35 * u))
        arc.quadTo(QPointF(cx, cy - 1.0 * u), QPointF(cx + 1.0 * u, cy + 0.35 * u))
        self._glow(p, self._stroke(arc, 0.45 * u), EYE, u)

    # ------------------------------------------------------------------ gaze
    def _update_gaze(self, st: str, t: float, steps: float = 1.0, look=None):
        face = self.s.get("face") or {}
        mode = self.s.get("gaze_mode") or "suivre"   # graph action `gaze`: suivre (default) | devant | errer
        if st == "eteint":  # eyes closed: no tracking, no wandering
            self.gaze_target = [0.0, 0.0]; self.next_saccade = t + 1.0
        elif look:  # an active expression (thinking, sad...) steers the pupils
            self.gaze_target = [look[0], look[1]]; self.next_saccade = t + 1.0
        elif mode == "devant":
            self.gaze_target = [0.0, 0.0]; self.next_saccade = t + 1.0
        elif face.get("present") and mode == "suivre":
            # Look AT the person: a person facing the screen appears mirrored in the camera image.
            g = self.s.get("gaze") or {}  # calibration from the dashboard (camera above the screen)
            gx = -face.get("x", 0) * g.get("gain_x", 1.6) + g.get("offset_x", 0.0)
            gy = face.get("y", 0) * g.get("gain_y", 1.4) + g.get("offset_y", 0.0)
            self.gaze_target = [max(-1, min(1, gx)), max(-1, min(1, gy))]
            self.next_saccade = t + 1.5  # resume wandering 1.5 s after the face disappears
        elif t >= self.next_saccade:
            if mode == "errer":
                self.gaze_target = [random.uniform(-0.8, 0.8), random.uniform(-0.5, 0.4)]
            elif st in ("ecoute", "reponse"):  # attending: small drift only
                self.gaze_target = [random.uniform(-0.15, 0.15), random.uniform(-0.1, 0.1)]
            else:
                self.gaze_target = [random.uniform(-0.8, 0.8), random.uniform(-0.5, 0.4)]
            self.next_saccade = t + random.uniform(2.0, 5.0)
        k = 1 - (1 - 0.18) ** steps  # same easing per second whatever the frame rate
        for i in (0, 1):
            self.gaze[i] += (self.gaze_target[i] - self.gaze[i]) * k

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
        expr = EXPRESSIONS.get((self.s.get("expression") or {}).get("name")) if st != "eteint" else None
        if expr:
            cfg = {**cfg, **expr}
        # Face unit; the dashboard "Taille du visage" slider scales the whole face around its centre.
        u = min(w, face_h) / 10 * float(self.s.get("face_scale", 1.0) or 1.0)
        cx, cy = w / 2, face_h * 0.45

        now = time.monotonic()
        steps = max(0.5, min((now - self._last_paint) / 0.016, 12.0))  # elapsed 16 ms frames
        self._last_paint = now
        self.eye_open += ((0.07 if cfg.get("closed") else 1.0) - self.eye_open) * (1 - 0.85 ** steps)
        blink = 0.12 if (t % (5.0 if st == "veille" else 3.8)) < 0.13 else 1.0
        self._update_gaze(st, t, steps, (expr or {}).get("look"))
        speaking = st == "reponse" or self.s.get("speaking")
        target_m = min(1.0, self.s.get("out_level", 0) * 1.6) if speaking else 0.0
        self.mouth += (target_m - self.mouth) * (1 - 0.65 ** steps)

        ew, eh_full = 2.2 * u, 1.45 * u  # wide eyes, constant size
        for side in (-1, 1):
            ex = cx + side * 2.3 * u
            if cfg["happy"]:
                self._happy_eye(p, ex, cy, u)
            else:
                eh = max(eh_full * cfg.get("eye_scale", 1.0) * self.eye_open * blink, 0.18 * u)
                rect = QRectF(ex - ew / 2, cy - eh / 2, ew, eh)
                self._eye(p, rect, min(ew, eh) * 0.42, u, with_pupil=not cfg.get("closed"))
            self._draw_cheek(p, side, cx, cy, u)

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
            font = self._font(max(10, int(h * 0.025))); p.setFont(font)
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
        p.setFont(self._font(max(12, int(h * 0.042))))
        text = self.s.get("subtitle", "") if self.online else "Nanterino démarre…"
        p.drawText(QRectF(w * 0.05, face_h, w * 0.9, h - face_h), Qt.AlignCenter | Qt.TextWordWrap, text)
        p.end()
        if self._settled():  # robot off and eyes closed: stop repainting until state/gaze changes
            self._anim.stop()
