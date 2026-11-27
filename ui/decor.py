"""
Raikō - living themes: ambient effects, ornaments on real elements, and Rai.

One transparent, click-through layer per window (DecorLayer) draws, from the
current theme's `extra`:

  ambient   {"kind": snow|petals|leaves|embers|fireflies|confetti|stars,
             "density": 0-1, "colors": [...]}
  ornaments [{"anchor": "settings_button", "kind": "bats"}, ...]
            kinds: bats · santa_hat · holly · snowcap · lantern · sparkles · party_hat · pumpkin
  mascot    outfit name ("", "santa", "witch", "party", "yukata") -> Rai, the light spirit,
            beside the Home greeting

Anchors are real widgets registered by name (logo, settings_button, hall_nav,
home_greeting, add_button). Everything is drawn with QPainter - crisp at any
size, no image files.

Motion: Settings → Appearance (Full / Calm / Off) and Windows' "Animation
effects" (reduced motion). Off/reduced = no particles, ornaments still and
static. Only the small areas that change are repainted, the timer runs at
25 fps (Calm: 15), and everything pauses while the window is minimised.
"""
from __future__ import annotations

import math
import random
import time
import weakref
from typing import Dict, List, Optional

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor as _Raw, QPainter, QPainterPath, QPen, QRadialGradient, QRegion
from PyQt6.QtWidgets import QWidget

_ANCHORS: Dict[str, "weakref.ref"] = {}


def register(name: str, w: QWidget):
    """Make a widget available to ornaments under `name`."""
    _ANCHORS[name] = weakref.ref(w)


def anchor(name: str) -> Optional[QWidget]:
    r = _ANCHORS.get(name)
    w = r() if r else None
    try:
        if w is not None and w.isVisible():
            return w
    except RuntimeError:
        pass
    return None


def windows_reduced_motion() -> bool:
    try:
        import ctypes
        v = ctypes.c_bool(True)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(v), 0):   # SPI_GETCLIENTAREAANIMATION
            return not v.value
    except Exception:
        pass
    return False


def motion_level() -> str:
    """'on' | 'calm' | 'off' (settings, then Windows reduced motion)."""
    try:
        from core.app_settings import app_settings
        st = app_settings()
        m = str(st.value("motion", "calm") or "calm")      # Calm by default: subtle, ~1% CPU
        follow = str(st.value("motion_follow_windows", "true")).lower() != "false"
    except Exception:
        m, follow = "on", True
    if follow and windows_reduced_motion():
        return "off"
    return m if m in ("on", "calm", "off") else "calm"


def mascot_enabled() -> bool:
    try:
        from core.app_settings import app_settings
        return str(app_settings().value("mascot", "true")).lower() != "false"
    except Exception:
        return True


class _P:
    __slots__ = ("x", "y", "vx", "vy", "size", "rot", "vr", "phase", "color", "life", "zone")


class DecorLayer(QWidget):
    def __init__(self, host: QWidget):
        super().__init__(host)
        self.host = host
        self.zones: List[QRect] = []
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setGeometry(host.rect())
        self.parts: List[_P] = []
        self.cfg: Dict = {}
        self.level = "on"
        self.t0 = time.monotonic()
        self._dirty = QRegion()
        self._last_orn = QRegion()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        host.installEventFilter(self)
        from ui.theme import ThemeManager
        ThemeManager.get().changed.connect(self._on_theme)
        self.refresh()

    def _on_theme(self, _theme):
        from PyQt6 import sip
        if sip.isdeleted(self) or sip.isdeleted(self.host):
            return
        self.refresh()

    # ── configuration ────────────────────────────────────────────────────────

    def refresh(self):
        from ui.theme import ThemeManager
        self.cfg = dict(ThemeManager.get().theme.extra or {})
        self.level = motion_level()
        amb = self.cfg.get("ambient") or {}
        self.setGeometry(self.host.rect())
        self._zones()
        n = 0
        if amb and self.level != "off" and self.zones:
            area = sum(z.width() * z.height() for z in self.zones) / (270 * 900 + 1130 * 96)
            n = int((26 if self.level == "on" else 12) * float(amb.get("density", 0.6)) * area)
        self.parts = [self._spawn(amb, initial=True) for _ in range(n)]
        animated = bool(self.parts) or bool(self.cfg.get("ornaments")) or bool(self.cfg.get("mascot"))
        if animated and self.level != "off":
            self.timer.start(40 if self.level == "on" else 66)
        else:
            self.timer.stop()
        self.setGeometry(self.host.rect())
        self.raise_()
        self.update()

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        t = ev.type()
        if obj is self.host and t == QEvent.Type.Resize:
            self.setGeometry(self.host.rect())
            self._zones()
        return False

    # ── particles ────────────────────────────────────────────────────────────

    def burst(self, seconds: float = 3.5):
        """A short confetti celebration (milestones). Nothing with motion off."""
        if motion_level() == "off":
            return
        self._zones()
        amb = {"kind": "confetti", "density": 1.0}
        saved = (self.cfg, self.parts)
        self.cfg = {**self.cfg, "ambient": amb}
        self.parts = [self._spawn(amb, initial=True) for _ in range(45)]
        self.timer.start(40)

        def restore():
            from PyQt6 import sip
            if sip.isdeleted(self):
                return
            self.cfg, self.parts = saved
            self.refresh()
        QTimer.singleShot(int(seconds * 1000), restore)

    def _zones(self):
        """Where ambient effects live: the sidebar and the band across the top
        of the page - never over artwork, cards or text you're reading."""
        zones = []
        sb = anchor("sidebar")
        if sb is not None:
            try:
                tl = sb.mapTo(self.host, sb.rect().topLeft())
                zones.append(QRect(tl, sb.size()))
                band_left = tl.x() + sb.width()
            except RuntimeError:
                band_left = 0
        else:
            band_left = 0
        zones.append(QRect(band_left, 0, max(0, self.width() - band_left), 96))
        self.zones = [z for z in zones if z.width() > 20 and z.height() > 20]

    def _spawn(self, amb: Dict, initial: bool = False) -> _P:
        p = _P()
        kind = amb.get("kind", "snow")
        z = random.choices(self.zones, weights=[r.width() * r.height() for r in self.zones])[0] \
            if self.zones else QRect(0, 0, self.width(), self.height())
        p.zone = z
        W, H = max(1, self.width()), max(1, self.height())
        colors = amb.get("colors") or {"snow": ["#ffffff"], "petals": ["#ffc0d9", "#ffd6e6", "#ff9ec4"],
                                       "leaves": ["#e8742a", "#c2410c", "#f4a259", "#b45309"],
                                       "embers": ["#ffb347", "#ff7a1a"], "fireflies": ["#fff3a0"],
                                       "confetti": ["#f472b6", "#38bdf8", "#f5c451", "#34d399", "#8b7bff"],
                                       "stars": ["#ffffff", "#fff3c4"]}.get(kind, ["#ffffff"])
        p.color = random.choice(colors)
        p.x = random.uniform(z.left(), z.right())
        p.y = random.uniform(z.top(), z.bottom()) if initial else \
            (z.top() - 8 if kind != "embers" else z.bottom() + 8)
        del W, H
        p.size = {"snow": random.uniform(1.5, 4.2), "petals": random.uniform(4, 8), "leaves": random.uniform(6, 11),
                  "embers": random.uniform(1.5, 3), "fireflies": random.uniform(2, 3.5),
                  "confetti": random.uniform(4, 7), "stars": random.uniform(1, 2.6)}.get(kind, 3)
        speed = 0.55 if self.level == "calm" else 1.0
        p.vy = {"snow": random.uniform(0.4, 1.2), "petals": random.uniform(0.6, 1.3), "leaves": random.uniform(0.8, 1.6),
                "embers": -random.uniform(0.4, 1.0), "fireflies": random.uniform(-0.2, 0.2),
                "confetti": random.uniform(1.2, 2.4), "stars": 0.0}.get(kind, 1) * speed
        p.vx = random.uniform(-0.3, 0.3) * speed
        p.rot = random.uniform(0, 360)
        p.vr = random.uniform(-2.5, 2.5) * speed
        p.phase = random.uniform(0, 6.28)
        p.life = 0
        return p

    def _rect(self, p: _P) -> QRect:
        s = p.size * 2 + 6
        return QRect(int(p.x - s), int(p.y - s), int(s * 2), int(s * 2))

    def _tick(self):
        try:
            win = self.host.window()
            if win.isMinimized() or not win.isVisible():
                return
        except RuntimeError:
            return
        amb = self.cfg.get("ambient") or {}
        kind = amb.get("kind", "snow")
        W, H = self.width(), self.height()
        t = time.monotonic() - self.t0
        region = QRegion()
        for i, p in enumerate(self.parts):
            region += self._rect(p)
            sway = math.sin(t * 1.3 + p.phase) * (0.6 if kind in ("snow", "petals", "leaves") else 0.2)
            p.x += p.vx + sway
            p.y += p.vy
            p.rot += p.vr
            p.life += 1
            if kind == "fireflies":
                p.x += math.sin(t * 0.7 + p.phase * 3) * 0.5
                p.y += math.cos(t * 0.6 + p.phase * 2) * 0.4
            z = p.zone
            if p.y > z.bottom() + 6 or p.y < z.top() - 10 or p.x < z.left() - 8 or p.x > z.right() + 8:
                self.parts[i] = self._spawn(amb)
                p = self.parts[i]
            region += self._rect(p)
        del W, H
        orn = self._ornament_region()
        region += orn + self._last_orn
        self._last_orn = orn
        if not region.isEmpty():
            self.update(region)

    def _ornament_region(self) -> QRegion:
        reg = QRegion()
        for o in self.cfg.get("ornaments") or []:
            r = self._anchor_rect(o.get("anchor"))
            if r is not None:
                reg += r.adjusted(-46, -46, 46, 46)
        if self.cfg.get("mascot") and mascot_enabled():
            r = self._mascot_rect()
            if r is not None:
                reg += r.adjusted(-6, -6, 6, 6)
        return reg

    def _anchor_rect(self, name: Optional[str]) -> Optional[QRect]:
        w = anchor(name or "")
        if w is None:
            return None
        try:
            if w.window() is not self.host.window():
                return None
            tl = w.mapTo(self.host, w.rect().topLeft())
            return QRect(tl, w.size())
        except RuntimeError:
            return None

    def _mascot_rect(self) -> Optional[QRect]:
        r = self._anchor_rect("home_greeting")
        if r is None:
            return None
        w = anchor("home_greeting")
        tw = w.fontMetrics().horizontalAdvance(w.text()) if w is not None else 200
        return QRect(r.left() + tw + 18, r.top() - 8, 58, 58)

    # ── painting ─────────────────────────────────────────────────────────────

    def paintEvent(self, ev):
        if not self.parts and not self.cfg.get("ornaments") and not self.cfg.get("mascot"):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = (time.monotonic() - self.t0) if self.level != "off" else 0.0
        kind = (self.cfg.get("ambient") or {}).get("kind", "snow")
        for q in self.parts:
            z = q.zone
            p.save()
            p.setClipRect(z)
            # fade out near the bottom of the header band
            if z.top() == 0 and z.height() < 200:
                p.setOpacity(max(0.0, min(1.0, (z.bottom() - q.y) / 30)))
            self._draw_particle(p, q, kind, t)
            p.restore()
        for o in self.cfg.get("ornaments") or []:
            r = self._anchor_rect(o.get("anchor"))
            if r is not None:
                self._draw_ornament(p, o.get("kind", ""), QRectF(r), t)
        if self.cfg.get("mascot") is not None and self.cfg.get("mascot") is not False and mascot_enabled():
            r = self._mascot_rect()
            if r is not None:
                draw_rai(p, QRectF(r), t, str(self.cfg.get("mascot") or ""), still=self.level == "off")
        p.end()

    def _draw_particle(self, p: QPainter, q: _P, kind: str, t: float):
        c = _Raw(q.color)
        p.setPen(Qt.PenStyle.NoPen)
        if kind == "snow":
            c.setAlpha(170)
            p.setBrush(c)
            p.drawEllipse(QPointF(q.x, q.y), q.size, q.size)
        elif kind in ("petals", "leaves", "confetti"):
            p.save()
            p.translate(q.x, q.y)
            p.rotate(q.rot)
            c.setAlpha(200 if kind != "petals" else 170)
            p.setBrush(c)
            if kind == "petals":
                path = QPainterPath()
                path.moveTo(0, -q.size)
                path.cubicTo(q.size, -q.size * 0.5, q.size * 0.6, q.size, 0, q.size * 0.8)
                path.cubicTo(-q.size * 0.6, q.size, -q.size, -q.size * 0.5, 0, -q.size)
                p.drawPath(path)
            elif kind == "leaves":
                path = QPainterPath()
                path.moveTo(0, -q.size)
                path.quadTo(q.size * 0.9, 0, 0, q.size)
                path.quadTo(-q.size * 0.9, 0, 0, -q.size)
                p.drawPath(path)
            else:
                p.drawRect(QRectF(-q.size / 2, -q.size / 4, q.size, q.size / 2))
            p.restore()
        elif kind in ("embers", "fireflies", "stars"):
            blink = 0.5 + 0.5 * math.sin(t * (3 if kind == "fireflies" else 2) + q.phase)
            g = QRadialGradient(QPointF(q.x, q.y), q.size * 3)
            c.setAlpha(int(200 * (0.4 + 0.6 * blink)))
            g.setColorAt(0, c)
            c2 = _Raw(c)
            c2.setAlpha(0)
            g.setColorAt(1, c2)
            p.setBrush(g)
            p.drawEllipse(QPointF(q.x, q.y), q.size * 3, q.size * 3)

    def _draw_ornament(self, p: QPainter, kind: str, r: QRectF, t: float):
        cx, cy = r.center().x(), r.center().y()
        if kind == "bats":
            rad = max(r.width(), r.height()) / 2 + 16
            for i in range(3):
                a = t * 0.9 + i * 2.1
                x = cx + math.cos(a) * rad * 1.15
                y = cy + math.sin(a) * rad * 0.55
                flap = math.sin(t * 9 + i) if t else 0.6
                draw_bat(p, x, y, 9, flap)
        elif kind == "santa_hat":
            draw_santa_hat(p, r.right() - r.width() * 0.32, r.top() - 4, r.width() * 0.62, math.sin(t * 1.5) * 4)
        elif kind == "party_hat":
            draw_party_hat(p, r.right() - r.width() * 0.3, r.top() - 2, r.width() * 0.45, math.sin(t * 2) * 5)
        elif kind == "holly":
            draw_holly(p, r.left() + 6, r.top() + 4, 1.0)
        elif kind == "snowcap":
            path = QPainterPath()
            path.moveTo(r.left() + 6, r.top() + 2)
            steps = 8
            for k in range(steps + 1):
                x = r.left() + 6 + (r.width() - 12) * k / steps
                path.lineTo(x, r.top() + 2 - (3 + 3 * math.sin(k * 1.7)))
            path.lineTo(r.right() - 6, r.top() + 4)
            path.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_Raw(255, 255, 255, 235))
            p.drawPath(path)
        elif kind == "lantern":
            draw_lantern(p, r.right() - 6, r.top() - 4, math.sin(t * 1.6) * 8)
        elif kind == "pumpkin":
            draw_pumpkin(p, r.right() - 18, r.center().y(), 11, (math.sin(t * 4) + 1) / 2)
        elif kind == "sparkles":
            for i in range(4):
                a = i * 1.57 + 0.6
                x = cx + math.cos(a) * (r.width() / 2 + 10)
                y = cy + math.sin(a) * (r.height() / 2 + 8)
                s = 3 + 2.5 * (0.5 + 0.5 * math.sin(t * 3 + i * 1.3))
                draw_sparkle(p, x, y, s, _Raw("#fff3c4"))


# ── vector ornaments ──────────────────────────────────────────────────────────

def draw_bat(p: QPainter, x: float, y: float, s: float, flap: float):
    p.save()
    p.translate(x, y)
    lift = flap * s * 0.55
    path = QPainterPath()
    path.moveTo(0, 0)
    path.cubicTo(-s * 0.6, -s * 0.2 - lift, -s * 1.3, -s * 0.5 - lift, -s * 1.8, -s * 0.1 - lift * 0.6)
    path.cubicTo(-s * 1.4, s * 0.1, -s * 1.1, s * 0.05, -s * 0.9, s * 0.35)
    path.cubicTo(-s * 0.6, s * 0.15, -s * 0.4, s * 0.3, 0, s * 0.45)
    path.cubicTo(s * 0.4, s * 0.3, s * 0.6, s * 0.15, s * 0.9, s * 0.35)
    path.cubicTo(s * 1.1, s * 0.05, s * 1.4, s * 0.1, s * 1.8, -s * 0.1 - lift * 0.6)
    path.cubicTo(s * 1.3, -s * 0.5 - lift, s * 0.6, -s * 0.2 - lift, 0, 0)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_Raw(18, 12, 28, 235))
    p.drawPath(path)
    p.setBrush(_Raw(255, 140, 40, 230))
    p.drawEllipse(QPointF(-s * 0.18, s * 0.12), s * 0.08, s * 0.08)
    p.drawEllipse(QPointF(s * 0.18, s * 0.12), s * 0.08, s * 0.08)
    p.restore()


def draw_santa_hat(p: QPainter, x: float, y: float, w: float, sway: float):
    p.save()
    p.translate(x, y)
    p.rotate(18 + sway)
    h = w * 0.85
    body = QPainterPath()
    body.moveTo(-w / 2, 0)
    body.cubicTo(-w * 0.3, -h * 0.6, w * 0.1, -h * 1.05, w * 0.55, -h * 0.75)
    body.cubicTo(w * 0.35, -h * 0.55, w * 0.25, -h * 0.25, w / 2, 0)
    body.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_Raw("#d62839"))
    p.drawPath(body)
    p.setBrush(_Raw(255, 255, 255, 245))
    p.drawRoundedRect(QRectF(-w / 2 - 2, -w * 0.08, w + 4, w * 0.2), w * 0.1, w * 0.1)
    p.drawEllipse(QPointF(w * 0.55, -h * 0.75), w * 0.12, w * 0.12)
    p.restore()


def draw_party_hat(p: QPainter, x: float, y: float, w: float, sway: float):
    p.save()
    p.translate(x, y)
    p.rotate(14 + sway)
    path = QPainterPath()
    path.moveTo(-w / 2, 0)
    path.lineTo(0, -w * 1.2)
    path.lineTo(w / 2, 0)
    path.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_Raw("#8b7bff"))
    p.drawPath(path)
    p.setBrush(_Raw("#f5c451"))
    for k in range(3):
        p.drawEllipse(QPointF(-w * 0.15 + k * w * 0.15, -w * (0.25 + 0.28 * k)), w * 0.07, w * 0.07)
    p.setBrush(_Raw("#f472b6"))
    p.drawEllipse(QPointF(0, -w * 1.22), w * 0.13, w * 0.13)
    p.restore()


def draw_holly(p: QPainter, x: float, y: float, s: float):
    p.save()
    p.translate(x, y)
    p.setPen(Qt.PenStyle.NoPen)
    for ang in (-35, 35):
        p.save()
        p.rotate(ang)
        leaf = QPainterPath()
        leaf.moveTo(0, 0)
        leaf.cubicTo(5 * s, -4 * s, 11 * s, -3 * s, 14 * s, 0)
        leaf.cubicTo(11 * s, 3 * s, 5 * s, 4 * s, 0, 0)
        p.setBrush(_Raw("#1f7a3a"))
        p.drawPath(leaf)
        p.restore()
    p.setBrush(_Raw("#e0263b"))
    for dx, dy in ((0, 0), (4, 2), (-1, 4)):
        p.drawEllipse(QPointF(dx * s, dy * s), 2.6 * s, 2.6 * s)
    p.restore()


def draw_lantern(p: QPainter, x: float, y: float, swing: float):
    p.save()
    p.translate(x, y)
    p.rotate(swing)
    p.setPen(QPen(_Raw(120, 90, 60), 1))
    p.drawLine(QPointF(0, 0), QPointF(0, 10))
    g = QRadialGradient(QPointF(0, 20), 16)
    g.setColorAt(0, _Raw(255, 200, 120, 200))
    g.setColorAt(1, _Raw(255, 120, 40, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(QPointF(0, 20), 16, 16)
    p.setBrush(_Raw("#e63946"))
    p.drawRoundedRect(QRectF(-7, 10, 14, 18), 6, 6)
    p.setBrush(_Raw("#3a2a1a"))
    p.drawRect(QRectF(-5, 9, 10, 2))
    p.drawRect(QRectF(-5, 27, 10, 2))
    p.restore()


def draw_pumpkin(p: QPainter, x: float, y: float, s: float, glow: float):
    p.save()
    p.translate(x, y)
    p.setPen(Qt.PenStyle.NoPen)
    g = QRadialGradient(QPointF(0, 0), s * 1.8)
    g.setColorAt(0, _Raw(255, 150, 40, int(90 * glow)))
    g.setColorAt(1, _Raw(255, 150, 40, 0))
    p.setBrush(g)
    p.drawEllipse(QPointF(0, 0), s * 1.8, s * 1.8)
    p.setBrush(_Raw("#f07a1a"))
    for dx in (-0.45, 0, 0.45):
        p.drawEllipse(QPointF(dx * s, 0), s * 0.62, s * 0.8)
    p.setBrush(_Raw("#3f7a2a"))
    p.drawRoundedRect(QRectF(-s * 0.1, -s * 1.05, s * 0.2, s * 0.35), 2, 2)
    p.setBrush(_Raw(255, 230, 120, int(150 + 100 * glow)))
    for dx in (-0.3, 0.3):
        tri = QPainterPath()
        tri.moveTo(dx * s - s * 0.15, -s * 0.1)
        tri.lineTo(dx * s + s * 0.15, -s * 0.1)
        tri.lineTo(dx * s, -s * 0.35)
        tri.closeSubpath()
        p.drawPath(tri)
    p.drawRoundedRect(QRectF(-s * 0.35, s * 0.15, s * 0.7, s * 0.18), 3, 3)
    p.restore()


def draw_sparkle(p: QPainter, x: float, y: float, s: float, c: _Raw):
    path = QPainterPath()
    path.moveTo(x, y - s)
    path.quadTo(x, y, x + s, y)
    path.quadTo(x, y, x, y + s)
    path.quadTo(x, y, x - s, y)
    path.quadTo(x, y, x, y - s)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPath(path)


def draw_rai(p: QPainter, r: QRectF, t: float, outfit: str = "", still: bool = False):
    """Rai - a small spirit of light (original Raikō mascot)."""
    from ui.theme import ThemeManager
    accent = _Raw(ThemeManager.get().hex("#8b7bff"))
    bob = 0 if still else math.sin(t * 2.2) * 3
    cx, cy = r.center().x(), r.center().y() + bob
    rad = min(r.width(), r.height()) * 0.32
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    halo = QRadialGradient(QPointF(cx, cy), rad * 2.1)
    a = _Raw(accent)
    a.setAlpha(90)
    halo.setColorAt(0, a)
    a2 = _Raw(accent)
    a2.setAlpha(0)
    halo.setColorAt(1, a2)
    p.setBrush(halo)
    p.drawEllipse(QPointF(cx, cy), rad * 2.1, rad * 2.1)
    # wisp tail
    tail = QPainterPath()
    tail.moveTo(cx - rad * 0.7, cy + rad * 0.3)
    sw = 0 if still else math.sin(t * 3) * rad * 0.3
    tail.cubicTo(cx - rad * 1.2, cy + rad * 1.2, cx - rad * 0.1 + sw, cy + rad * 1.5, cx + rad * 0.2 + sw, cy + rad * 1.9)
    tail.cubicTo(cx + rad * 0.2, cy + rad * 1.1, cx + rad * 0.7, cy + rad * 0.8, cx + rad * 0.7, cy + rad * 0.3)
    tail.closeSubpath()
    tb = _Raw(accent)
    tb.setAlpha(150)
    p.setBrush(tb)
    p.drawPath(tail)
    body = QRadialGradient(QPointF(cx - rad * 0.3, cy - rad * 0.35), rad * 1.3)
    body.setColorAt(0, _Raw(255, 255, 255))
    body.setColorAt(0.55, accent.lighter(140))
    body.setColorAt(1, accent)
    p.setBrush(body)
    p.drawEllipse(QPointF(cx, cy), rad, rad)
    blink = (not still) and (t % 4.2) < 0.13
    p.setBrush(_Raw(20, 18, 40))
    for dx in (-0.34, 0.34):
        if blink:
            p.drawRoundedRect(QRectF(cx + dx * rad - rad * 0.12, cy - rad * 0.02, rad * 0.24, rad * 0.06), 1, 1)
        else:
            p.drawEllipse(QPointF(cx + dx * rad, cy), rad * 0.11, rad * 0.16)
    p.setBrush(_Raw(255, 140, 170, 120))
    p.drawEllipse(QPointF(cx - rad * 0.55, cy + rad * 0.3), rad * 0.14, rad * 0.08)
    p.drawEllipse(QPointF(cx + rad * 0.55, cy + rad * 0.3), rad * 0.14, rad * 0.08)
    p.restore()
    if outfit == "santa":
        draw_santa_hat(p, cx + rad * 0.15, cy - rad * 0.75, rad * 1.5, 0 if still else math.sin(t * 1.5) * 4)
    elif outfit == "party":
        draw_party_hat(p, cx + rad * 0.1, cy - rad * 0.8, rad * 1.0, 0 if still else math.sin(t * 2) * 5)
    elif outfit == "witch":
        p.save()
        p.translate(cx, cy - rad * 0.8)
        p.rotate(-8)
        hat = QPainterPath()
        hat.moveTo(-rad * 1.1, 0)
        hat.lineTo(rad * 1.1, 0)
        hat.lineTo(rad * 0.25, -rad * 0.2)
        hat.lineTo(rad * 0.4, -rad * 1.4)
        hat.lineTo(-rad * 0.35, -rad * 0.2)
        hat.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_Raw("#2b1a3d"))
        p.drawPath(hat)
        p.setBrush(_Raw("#f07a1a"))
        p.drawRect(QRectF(-rad * 0.38, -rad * 0.28, rad * 0.72, rad * 0.12))
        p.restore()


# ── event spotlight centrepieces ──────────────────────────────────────────────

def draw_portraits(p: QPainter, r: QRectF, t: float, pix: list, color: str = "#8b7bff"):
    """The show's characters floating in a gentle arc (premieres / farewells)."""
    n = len(pix)
    if not n:
        return
    ring = _Raw(color)
    size = min(r.height() * 0.42, r.width() / max(2.2, n * 0.62))
    cx, cy = r.center().x(), r.center().y()
    for i, pm in enumerate(pix):
        a = (i - (n - 1) / 2) * 0.55
        x = cx + math.sin(a) * r.width() * 0.36
        y = cy + (1 - math.cos(a)) * r.height() * 0.55 - r.height() * 0.08 + math.sin(t * 1.6 + i) * 5
        s = size * (1.0 if i == (n - 1) // 2 else 0.78)
        rect = QRectF(x - s / 2, y - s / 2, s, s)
        p.save()
        glow = QRadialGradient(rect.center(), s * 0.75)
        g = _Raw(ring)
        g.setAlpha(90)
        glow.setColorAt(0.6, g)
        g2 = _Raw(ring)
        g2.setAlpha(0)
        glow.setColorAt(1, g2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(rect.center(), s * 0.75, s * 0.75)
        path = QPainterPath()
        path.addEllipse(rect)
        p.setClipPath(path)
        if pm is not None and not pm.isNull():
            sc = pm.scaled(int(s), int(s), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int(rect.x()), int(rect.y()), sc, (sc.width() - int(s)) // 2, 0, int(s), int(s))
        else:
            p.fillRect(rect, _Raw(30, 32, 46))
        p.setClipping(False)
        p.setPen(QPen(ring, 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)
        p.restore()


def draw_hero(p: QPainter, r: QRectF, t: float, event_id: str, pix: Optional[list] = None, color: str = ""):
    """The animated centrepiece on the event spotlight slide."""
    if pix:
        draw_portraits(p, r, t, pix, color or "#8b7bff")
        return
    if event_id == "christmas":
        draw_tree(p, r, t)
    elif event_id == "halloween":
        draw_pumpkin(p, r.center().x(), r.center().y() + r.height() * 0.12, r.height() * 0.3,
                     0.55 + 0.45 * abs(math.sin(t * 3.1) * math.sin(t * 1.7)))
    elif event_id == "new_year":
        draw_fireworks(p, r, t)
    else:
        for i in range(9):
            a = i * 0.7 + t * 0.4
            rad = r.height() * (0.15 + 0.25 * ((i * 37) % 10) / 10)
            s = 4 + 6 * (0.5 + 0.5 * math.sin(t * 2.4 + i))
            draw_sparkle(p, r.center().x() + math.cos(a) * rad, r.center().y() + math.sin(a) * rad, s,
                         _Raw("#fff3c4"))


def draw_tree(p: QPainter, r: QRectF, t: float):
    cx = r.center().x()
    top = r.top() + r.height() * 0.12
    h = r.height() * 0.72
    w = h * 0.62
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    glow = QRadialGradient(QPointF(cx, top + h * 0.55), h * 0.75)
    glow.setColorAt(0, _Raw(255, 214, 120, 60))
    glow.setColorAt(1, _Raw(255, 214, 120, 0))
    p.setBrush(glow)
    p.drawEllipse(QPointF(cx, top + h * 0.55), h * 0.75, h * 0.75)
    p.setBrush(_Raw("#5b3a22"))
    p.drawRect(QRectF(cx - w * 0.07, top + h * 0.9, w * 0.14, h * 0.12))
    tiers = 4
    for i in range(tiers):
        y0 = top + h * (0.08 + i * 0.2)
        tw = w * (0.38 + 0.2 * i)
        path = QPainterPath()
        path.moveTo(cx, y0)
        path.lineTo(cx + tw / 2, y0 + h * 0.32)
        path.quadTo(cx, y0 + h * 0.37, cx - tw / 2, y0 + h * 0.32)
        path.closeSubpath()
        g = QRadialGradient(QPointF(cx - tw * 0.15, y0 + h * 0.12), tw * 0.8)
        g.setColorAt(0, _Raw("#3fb56a"))
        g.setColorAt(1, _Raw("#14532d"))
        p.setBrush(g)
        p.drawPath(path)
    colors = ["#ff5a6a", "#ffd166", "#7cc4ff", "#f472b6", "#ffffff"]
    rnd = random.Random(7)
    for k in range(26):
        fy = rnd.uniform(0.2, 0.86)
        spread = w * (0.12 + 0.5 * fy) / 2
        x = cx + rnd.uniform(-spread, spread)
        y = top + h * fy + rnd.uniform(0, h * 0.04)
        on = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 2.6 + k * 1.9))
        c = _Raw(colors[k % len(colors)])
        g = QRadialGradient(QPointF(x, y), 7)
        c.setAlpha(int(255 * on))
        g.setColorAt(0, c)
        c2 = _Raw(c)
        c2.setAlpha(0)
        g.setColorAt(1, c2)
        p.setBrush(g)
        p.drawEllipse(QPointF(x, y), 7, 7)
    p.restore()
    s = 13 + 3 * math.sin(t * 2)
    draw_sparkle(p, cx, top + h * 0.06, s, _Raw("#ffd166"))
    draw_sparkle(p, cx, top + h * 0.06, s * 0.5, _Raw("#fff6d5"))


def draw_fireworks(p: QPainter, r: QRectF, t: float):
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    colors = ["#ffd36e", "#b18cff", "#ff7ac6", "#7fd8ff"]
    for b in range(3):
        period = 2.6
        tt = (t + b * 0.9) % period
        rnd = random.Random(int((t + b * 0.9) // period) * 13 + b)
        cx = r.left() + r.width() * rnd.uniform(0.2, 0.8)
        cy = r.top() + r.height() * rnd.uniform(0.2, 0.55)
        prog = min(1.0, tt / 1.6)
        alpha = max(0.0, 1.0 - tt / period)
        rad = r.height() * 0.32 * (1 - (1 - prog) ** 3)
        c = _Raw(colors[(b + int(t // period)) % len(colors)])
        for k in range(18):
            a = k / 18 * 6.283
            x = cx + math.cos(a) * rad
            y = cy + math.sin(a) * rad + (tt ** 2) * 6
            c.setAlpha(int(230 * alpha))
            p.setBrush(c)
            p.drawEllipse(QPointF(x, y), 2.6, 2.6)
    p.restore()
