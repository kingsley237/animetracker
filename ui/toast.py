"""
Raikō — toasts: short confirmations ("Episode 7 marked watched").

A solid card, painted in one piece (no see-through gaps): dark surface,
hairline border, soft shadow, a filled round icon in the kind's colour,
the message, and a thin countdown line along the bottom that pauses while
the pointer is over it. Click the card or ✕ to dismiss. Toasts stack
bottom-right inside the window (just above the status bar), newest at the
bottom, at most 3.

API (unchanged): Toast.show(parent, message, kind="info"|"success"|"warning"|"error", duration=ms)
"""
from __future__ import annotations

from typing import ClassVar

from PyQt6.QtCore import QEasingCurve, QElapsedTimer, QEvent, QObject, QPoint, QPropertyAnimation, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen
from ui.theme import QColor  # noqa: E402,F811  (theme-aware colours)
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget

# kind -> (glyph, accent)
_KINDS: dict[str, tuple[str, str]] = {
    "success": ("✓", "#34d399"),
    "error":   ("✕", "#f87171"),
    "warning": ("!", "#fbbf24"),
    "info":    ("i", "#8b7bff"),
}
_DEFAULT_DURATION_MS: int = 3500
_MARGIN:   int = 22          # from the window's edge
_BOTTOM:   int = 34          # clears the status bar
_SPACING:  int = 10
_MAX_TOASTS: int = 3
_SHADOW:   int = 14          # painted shadow around the card
_MAX_W:    int = 420
def _SURFACE():
    return QColor("#161925")


def _BORDER():
    return QColor(255, 255, 255, 22)
_TEXT = "#eef0f7"


class _Follow(QObject):
    """Re-stack when the window is resized."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize:
            _ToastManager.get()._reposition_all(animate=False)
        return False


class _ToastManager:
    """Process-global: owns live toasts and stacks them."""
    _instance: ClassVar["_ToastManager | None"] = None
    _toasts: ClassVar[list["Toast"]] = []

    @classmethod
    def get(cls) -> "_ToastManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _prune(self) -> None:
        """Drop toasts whose window closed before they faded out."""
        from PyQt6 import sip
        self._toasts[:] = [t for t in self._toasts if not sip.isdeleted(t)]

    def add(self, toast: "Toast") -> None:
        self._prune()
        if len(self._toasts) >= _MAX_TOASTS:
            self._toasts[0]._dismiss_immediate()
        self._toasts.append(toast)
        self._reposition_all()

    def remove(self, toast: "Toast") -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._reposition_all()

    def target(self, toast: "Toast") -> QPoint:
        """Where `toast` belongs in its window's stack (window coordinates)."""
        self._prune()
        p = toast.parentWidget()
        if p is None or toast not in self._toasts:
            return toast.pos()
        same = [t for t in self._toasts if t.parentWidget() is p]
        i = same.index(toast)
        below = sum(same[j].height() - 2 * _SHADOW + _SPACING for j in range(i + 1, len(same)))
        return QPoint(p.width() - _MARGIN - toast.width() + _SHADOW,
                      p.height() - _BOTTOM - toast.height() + _SHADOW - below)

    def _reposition_all(self, animate: bool = True) -> None:
        self._prune()
        for t in self._toasts:
            if animate:
                t.glide_to(self.target(t))
            else:
                t.move(self.target(t))


class _Badge(QWidget):
    """Filled round icon in the kind's colour."""

    def __init__(self, glyph: str, color: str, parent=None):
        super().__init__(parent)
        self.glyph, self.color = glyph, QColor(color)
        self.setFixedSize(26, 26)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        glow = QColor(self.color)
        glow.setAlpha(46)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(0, 0, 26, 26))
        p.setBrush(self.color)
        p.drawEllipse(QRectF(3, 3, 20, 20))
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(12 if self.glyph != "i" else 13)
        p.setFont(f)
        p.setPen(QColor("#0b0d12"))
        p.drawText(QRectF(3, 3, 20, 20), Qt.AlignmentFlag.AlignCenter, self.glyph)
        p.end()


class Toast(QWidget):
    """Auto-dismissing toast, stacked by _ToastManager."""

    def __init__(self, parent: QWidget, message: str,
                 kind: str = "info", duration: int = _DEFAULT_DURATION_MS, action=None):
        host = parent.window() if parent is not None else None
        super().__init__(host)        # drawn inside the window: no OS frame, moves with it
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        if host is not None and not getattr(host, "_toast_follow", None):
            host._toast_follow = _Follow(host)
            host.installEventFilter(host._toast_follow)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        glyph, self.accent = _KINDS.get(kind, _KINDS["info"])
        self.kind = kind
        self.duration = max(800, int(duration))
        self._left = float(self.duration)        # ms remaining (pauses on hover)
        self._hover = False
        self._closing = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(_SHADOW + 14, _SHADOW + 12, _SHADOW + 10, _SHADOW + 14)
        lay.setSpacing(12)
        lay.addWidget(_Badge(glyph, self.accent), alignment=Qt.AlignmentFlag.AlignTop)
        self.msg = QLabel(message)
        self.msg.setObjectName("toastText")
        f = QFont(self.font())
        f.setPixelSize(13)
        f.setWeight(QFont.Weight.DemiBold)
        self.msg.setFont(f)
        self.msg.setStyleSheet(f"color:{_TEXT};background:transparent;")
        self.msg.setWordWrap(True)
        from PyQt6.QtGui import QFontMetrics
        one_line = QFontMetrics(f).horizontalAdvance(message) + 12
        room = _MAX_W - 26 - 12 - 24 - 28
        if action:
            from PyQt6.QtWidgets import QPushButton
            self.action_btn = QPushButton(action[0])
            self.action_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.action_btn.setStyleSheet(
                f"QPushButton{{color:{self.accent};background:transparent;border:1px solid {self.accent};"
                "border-radius:8px;padding:3px 12px;font-size:12px;font-weight:700;}"
                "QPushButton:hover{background:rgba(255,255,255,0.06);}")
            self.action_btn.clicked.connect(lambda: (action[1](), self._dismiss()))
            room -= self.action_btn.sizeHint().width() + 12
        self.msg.setFixedWidth(min(one_line, room))
        lay.addWidget(self.msg, 1, Qt.AlignmentFlag.AlignVCenter)
        if action:
            lay.addWidget(self.action_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.close_btn = QLabel("✕")
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.close_btn.setStyleSheet("color:#6b7391;background:transparent;font-size:11px;")
        lay.addWidget(self.close_btn, alignment=Qt.AlignmentFlag.AlignTop)
        self.adjustSize()

        mgr = _ToastManager.get()
        mgr.add(self)
        end = mgr.target(self)
        self.move(end + QPoint(0, 14))
        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)
        QWidget.show(self)          # explicit: not the static Toast.show()
        self.raise_()
        self._in = QPropertyAnimation(self._fx, b"opacity", self)
        self._in.setDuration(200)
        self._in.setStartValue(0.0)
        self._in.setEndValue(1.0)
        self._in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._in.start()
        self.glide_to(end, 260)

        self._clock = QElapsedTimer()
        self._clock.start()
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._step)
        self._tick.start(30)

    # ── life cycle ───────────────────────────────────────────────────────────

    def glide_to(self, pos: QPoint, ms: int = 180) -> None:
        if pos == self.pos():
            return
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(ms)
        self._slide.setStartValue(self.pos())
        self._slide.setEndValue(pos)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide.start()

    def _step(self) -> None:
        dt = self._clock.restart()
        if not self._hover and not self._closing:
            self._left -= dt
            if self._left <= 0:
                self._left = 0
                self._dismiss()
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.close_btn.setStyleSheet("color:#e8eaf2;background:transparent;font-size:11px;")
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.close_btn.setStyleSheet("color:#6b7391;background:transparent;font-size:11px;")
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dismiss()

    def _dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._tick.stop()
        self._out = QPropertyAnimation(self._fx, b"opacity", self)
        self._out.setDuration(220)
        self._out.setStartValue(self._fx.opacity())
        self._out.setEndValue(0.0)
        self._out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._out.finished.connect(self._on_dismissed)
        self._out.start()
        self.glide_to(self.pos() + QPoint(0, 8), 220)

    def _dismiss_immediate(self) -> None:
        self._closing = True
        _ToastManager.get().remove(self)
        self.close()

    def _on_dismissed(self) -> None:
        _ToastManager.get().remove(self)
        self.close()

    # ── look ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(self.rect()).adjusted(_SHADOW, _SHADOW, -_SHADOW, -_SHADOW)
        # soft shadow: stacked translucent rounded rects
        for i in range(_SHADOW, 0, -2):
            a = int(34 * (1 - i / _SHADOW) ** 2) + 2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(card.adjusted(-i, -i + 3, i, i + 3), 14 + i, 14 + i)
        path = QPainterPath()
        path.addRoundedRect(card, 14, 14)
        p.fillPath(path, QColor("#1b1f2d") if self._hover else _SURFACE())
        p.setPen(QPen(_BORDER(), 1))
        p.drawPath(path)
        # countdown line along the bottom, clipped to the card
        frac = self._left / self.duration if self.duration else 0
        p.save()
        p.setClipPath(path)
        track = QRectF(card.left(), card.bottom() - 3, card.width(), 3)
        p.fillRect(track, QColor(255, 255, 255, 10))
        c = QColor(self.accent)
        c.setAlpha(150 if self._hover else 230)
        p.fillRect(QRectF(track.left(), track.top(), track.width() * frac, 3), c)
        p.restore()
        p.end()

    # ── API ──────────────────────────────────────────────────────────────────

    @staticmethod
    def show(parent: QWidget, message: str, kind: str = "info",
             duration: int = _DEFAULT_DURATION_MS, action=None) -> "Toast":
        """action: optional (label, callback), e.g. ("Undo", fn)."""
        return Toast(parent, message, kind, duration, action)

    @staticmethod
    def popup(parent: QWidget, message: str, kind: str = "info",
              duration: int = _DEFAULT_DURATION_MS) -> "Toast":
        return Toast(parent, message, kind, duration)
