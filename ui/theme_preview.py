"""
Raikō - theme preview walkthrough.

Previewing a theme applies it to the real app *without saving*, shows a
floating pill (Previewing <name> · ‹ 1/4 › · Apply · Cancel) and walks
through four stops, each highlighted with a glowing ring and a caption:

  1. Home spotlight      2. Library cards
  3. A detail panel      4. The Settings button (where themes live)

← / → move, Esc cancels. Cancel (or 2 minutes without interaction)
restores exactly what you had; Apply saves it.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from PyQt6.QtCore import QEvent, QObject, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor as _RawColor, QCursor, QKeySequence, QPainter, QPen, QShortcut
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ui.theme import ThemeManager
from ui.themes_catalog import build, info

IDLE_MS = 120_000


class _Ring(QWidget):
    """Glowing outline around the current stop (mouse-transparent)."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.target = QRect()
        self.setGeometry(host.rect())

    def set_target(self, r: QRect):
        self.target = r
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.update()

    def paintEvent(self, _):
        if self.target.isNull():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = _RawColor(ThemeManager.get().hex("#8b7bff"))
        r = QRectF(self.target).adjusted(-6, -6, 6, 6)
        for i, a in ((10, 30), (6, 60), (3, 120)):
            cc = _RawColor(c)
            cc.setAlpha(a)
            p.setPen(QPen(cc, i))
            p.drawRoundedRect(r, 14, 14)
        p.setPen(QPen(c, 2))
        p.drawRoundedRect(r, 14, 14)
        p.end()


class _Pill(QWidget):
    def __init__(self, host: QWidget):
        super().__init__(host)
        self.setObjectName("previewPill")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 10, 10, 10)
        h.setSpacing(10)
        self.kicker = QLabel("PREVIEW")
        self.kicker.setObjectName("previewKicker")
        h.addWidget(self.kicker)
        self.name = QLabel()
        self.name.setObjectName("previewName")
        h.addWidget(self.name)
        self.prev = QPushButton("‹")
        self.next = QPushButton("›")
        for b in (self.prev, self.next):
            b.setObjectName("previewNav")
            b.setFixedSize(30, 30)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.step = QLabel()
        self.step.setObjectName("previewStep")
        h.addWidget(self.prev)
        h.addWidget(self.step)
        h.addWidget(self.next)
        self.caption = QLabel()
        self.caption.setObjectName("previewCaption")
        h.addWidget(self.caption, 1)
        self.apply = QPushButton("Apply")
        self.apply.setObjectName("primaryBtn")
        self.cancel = QPushButton("Cancel")
        self.cancel.setObjectName("secondaryBtn")
        for b in (self.apply, self.cancel):
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setFixedHeight(34)
            h.addWidget(b)


class ThemePreview(QObject):
    finished = pyqtSignal(bool)          # applied?

    def __init__(self, window, tid: str, accent: str = ""):
        super().__init__(window)
        self.win = window
        self.tid, self.accent = tid, accent
        tm = ThemeManager.get()
        self._before = (tm.theme, tm.font_scale)
        self.i = 0
        self.stops: List[Tuple[str, Callable[[], Optional[QWidget]]]] = [
            ("Your Home spotlight and week", self._stop_home),
            ("Library cards", self._stop_library),
            ("A detail panel", self._stop_detail),
            ("Themes live in Settings → Appearance", self._stop_settings),
        ]
        host = window.centralWidget() or window
        self.ring = _Ring(host)
        self.pill = _Pill(host)
        self.pill.prev.clicked.connect(lambda: self.go(self.i - 1))
        self.pill.next.clicked.connect(lambda: self.go(self.i + 1))
        self.pill.apply.clicked.connect(lambda: self.end(True))
        self.pill.cancel.clicked.connect(lambda: self.end(False))
        self._keys = [QShortcut(QKeySequence(k), window, f) for k, f in (
            (Qt.Key.Key_Escape, lambda: self.end(False)), (Qt.Key.Key_Left, lambda: self.go(self.i - 1)),
            (Qt.Key.Key_Right, lambda: self.go(self.i + 1)))]
        self.idle = QTimer(self)
        self.idle.setSingleShot(True)
        self.idle.timeout.connect(lambda: self.end(False))
        host.installEventFilter(self)
        self._host = host
        self._done = False

    def start(self):
        tm = ThemeManager.get()
        tm.apply(build(self.tid, self.accent), tm.font_scale)
        meta = info(self.tid)
        self.pill.name.setText(meta["name"])
        self.pill.show()
        self.ring.show()
        self.go(0)

    # ── stops ────────────────────────────────────────────────────────────────

    def _stop_home(self):
        self.win._navigate("home")
        hp = getattr(self.win, "_home_page", None)
        return getattr(hp, "hero", None)

    def _stop_library(self):
        self.win._navigate("library")
        cards = list(getattr(self.win, "_cards", {}).values())
        return cards[0] if cards else getattr(self.win, "library_page", None)

    def _stop_detail(self):
        cards = list(getattr(self.win, "_cards", {}).keys())
        if cards:
            self.win._open_title(cards[0])
        return getattr(self.win, "detail_panel", None)

    def _stop_settings(self):
        if hasattr(self.win, "_close_detail_panel"):
            self.win._close_detail_panel()
        return getattr(self.win, "_settings_btn", None)

    def go(self, i: int):
        if self._done:
            return
        self.i = max(0, min(len(self.stops) - 1, i))
        caption, fn = self.stops[self.i]
        target = fn()
        self.pill.step.setText(f"{self.i + 1} / {len(self.stops)}")
        self.pill.caption.setText(caption)
        self.pill.prev.setEnabled(self.i > 0)
        self.pill.next.setEnabled(self.i < len(self.stops) - 1)
        self.idle.start(IDLE_MS)
        self._target = target
        QTimer.singleShot(250, lambda t=target: self._ring_on(t))
        self._place_pill()

    def _ring_on(self, target: Optional[QWidget]):
        if self._done:
            return
        try:
            if target is not None and target.isVisible():
                tl = target.mapTo(self._host, target.rect().topLeft())
                self.ring.set_target(QRect(tl, target.size()).intersected(self._host.rect().adjusted(8, 8, -8, -8)))
            else:
                self.ring.set_target(QRect())
        except RuntimeError:
            self.ring.set_target(QRect())
        self.pill.raise_()

    def _place_pill(self):
        self.pill.adjustSize()
        w = min(max(self.pill.sizeHint().width(), 640), self._host.width() - 40)
        self.pill.resize(w, self.pill.sizeHint().height())
        self.pill.move((self._host.width() - w) // 2, self._host.height() - self.pill.height() - 44)
        self.pill.raise_()

    def eventFilter(self, obj, ev):
        if obj is self._host and ev.type() == QEvent.Type.Resize and not self._done:
            self._place_pill()
            QTimer.singleShot(0, lambda: self._ring_on(getattr(self, "_target", None)))
        return False

    def end(self, apply: bool):
        if self._done:
            return
        self._done = True
        tm = ThemeManager.get()
        if apply:
            tm.save(self.tid, self.accent, tm.font_scale)
        else:
            theme, scale = self._before
            tm.apply(theme, scale)
        for k in self._keys:
            k.setEnabled(False)
            k.deleteLater()
        self._host.removeEventFilter(self)
        self.ring.deleteLater()
        self.pill.deleteLater()
        self.idle.stop()
        if hasattr(self.win, "_close_detail_panel"):
            self.win._close_detail_panel()
        from ui.toast import Toast
        Toast.show(self.win, f"{info(self.tid)['name']} is on — change it any time in Settings → Appearance."
                   if apply else "Preview closed — nothing changed.", kind="success" if apply else "info")
        self.finished.emit(apply)
