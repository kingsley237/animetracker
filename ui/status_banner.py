"""
Raikō - service status banners (no internet / AniList down / TMDB down).

One design for all three, themed by what's affected:
  offline  red, pulsing dot      - your connection; your library still works
  anilist  Miroku indigo         - AniList's API, not you; anime updates pause
  tmdb     Kinema amber          - TMDB, not you; movie & TV updates pause

They live INSIDE the window (child overlays, not floating tool windows), so
they move with it and never drift. They sit bottom-centre of the content
area, stacked, above the status bar - never over the sidebar.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Dict, Optional

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

THEMES: Dict[str, Dict[str, str]] = {
    "offline": {"accent": "#f87171", "soft": "#fecaca", "bg": "#1a0f13", "icon": "⚡",
                "title": "You're offline",
                "body": "Your library still works. Live updates resume as soon as you're back."},
    "anilist": {"accent": "#8b7bff", "soft": "#d7d2ff", "bg": "#120f24", "icon": "◆",
                "title": "AniList is down — not you",
                "body": "Anime updates, Discover and search are paused until AniList is back."},
    "tmdb": {"accent": "#fbbf24", "soft": "#fde68a", "bg": "#1a1406", "icon": "▶",
             "title": "TMDB is down — not you",
             "body": "Movie & TV updates, Discover and search are paused until TMDB is back."},
}
ORDER = ("offline", "anilist", "tmdb")


class StatusBanner(QWidget):
    WIDTH = 440

    def __init__(self, kind: str, parent: QWidget, on_retry: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.kind = kind
        self.t = THEMES[kind]
        self._on_retry = on_retry
        self._shown = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFixedWidth(self.WIDTH)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 14, 16, 14)
        lay.setSpacing(14)
        self.icon = QLabel(self.t["icon"])
        self.icon.setFixedSize(34, 34)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setStyleSheet(
            f"background:rgba(255,255,255,0.06);border-radius:17px;color:{self.t['accent']};"
            "font-size:16px;font-weight:800;")
        icon_col = QVBoxLayout()
        icon_col.setContentsMargins(0, 0, 0, 0)
        icon_col.addWidget(self.icon)
        icon_col.addStretch()
        lay.addLayout(icon_col)

        col = QVBoxLayout()
        col.setSpacing(3)
        self.title = QLabel(self.t["title"])
        self.title.setStyleSheet(f"color:{self.t['soft']};font-size:13px;font-weight:700;background:transparent;")
        self.body = QLabel(self.t["body"])
        self.body.setWordWrap(True)
        self.body.setStyleSheet("color:#a3a9c2;font-size:11px;background:transparent;")
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color:#7f86a1;font-size:10px;font-style:italic;background:transparent;")
        self.detail.setVisible(False)
        self.meta = QLabel("")
        self.meta.setStyleSheet("color:#646b86;font-size:10px;background:transparent;")
        for w in (self.title, self.body, self.detail, self.meta):
            col.addWidget(w)
        lay.addLayout(col, 1)

        self.retry = QPushButton("Check now")
        self.retry.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.retry.setStyleSheet(
            f"QPushButton{{background:transparent;color:{self.t['soft']};border:1px solid {self.t['accent']};"
            "border-radius:8px;padding:5px 12px;font-size:11px;font-weight:700;}"
            f"QPushButton:hover{{background:rgba(255,255,255,0.06);}}"
            "QPushButton:disabled{color:#646b86;border-color:#2a2e40;}")
        self.retry.clicked.connect(self._retry_clicked)
        self.retry.setVisible(on_retry is not None)
        lay.addWidget(self.retry, alignment=Qt.AlignmentFlag.AlignVCenter)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(shadow)

        self._pulse_on = True
        self._pulse = QTimer(self)
        self._pulse.timeout.connect(self._tick)
        if kind == "offline":
            self._pulse.start(800)
        self.hide()

    # ── look ──────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.fillPath(path, QColor(self.t["bg"]))
        p.setPen(QColor(255, 255, 255, 22))
        p.drawPath(path)
        p.setClipPath(path)
        accent = QColor(self.t["accent"])
        if self.kind == "offline" and not self._pulse_on:
            accent.setAlpha(110)
        p.fillRect(QRectF(0, 0, 4, self.height()), accent)
        p.end()

    def _tick(self):
        self._pulse_on = not self._pulse_on
        self.icon.setStyleSheet(
            f"background:rgba(255,255,255,{0.10 if self._pulse_on else 0.04});border-radius:17px;"
            f"color:{self.t['accent']};font-size:16px;font-weight:800;")
        self.update()

    # ── state ─────────────────────────────────────────────────────────────────

    def _retry_clicked(self):
        self.retry.setEnabled(False)
        self.retry.setText("Checking…")
        self.meta.setText("Checking now…")
        if self._on_retry:
            self._on_retry()

    def set_message(self, message: str = ""):
        self.retry.setEnabled(True)
        self.retry.setText("Check now")
        if self.kind == "offline":
            if not self._shown:
                self.meta.setText(f"Since {datetime.now().strftime('%H:%M')}")
        else:
            generic = not message or message.lower().startswith(("couldn't reach", "anilist api is operating"))
            self.detail.setText("" if generic else f"“{message}”")
            self.detail.setVisible(not generic)
            self.meta.setText(f"Last checked {datetime.now().strftime('%H:%M')}")
        self.adjustSize()
        _layout_banners(self.parentWidget())

    def show_banner(self, message: str = ""):
        self.set_message(message)
        if self._shown:
            return
        self._shown = True
        self.adjustSize()
        self.show()
        self.raise_()
        _layout_banners(self.parentWidget())

    def hide_banner(self):
        if not self._shown:
            return
        self._shown = False
        self.hide()
        _layout_banners(self.parentWidget())

    def is_shown(self) -> bool:
        return self._shown


def _layout_banners(host: Optional[QWidget]):
    """Stack visible banners bottom-centre of the content area."""
    if host is None:
        return
    win = host.window()
    left = 0
    sidebar = getattr(win, "sidebar", None)
    try:
        if sidebar is not None and sidebar.isVisible():
            left = sidebar.mapTo(host, sidebar.rect().topRight()).x()
    except Exception:
        left = 0
    banners = [b for b in host.findChildren(StatusBanner) if b.is_shown()]
    banners.sort(key=lambda b: ORDER.index(b.kind))
    y = host.height() - 18
    for b in reversed(banners):
        b.adjustSize()
        y -= b.height()
        x = left + max(16, (host.width() - left - b.width()) // 2)
        b.move(x, y)
        b.raise_()
        y -= 10


def relayout(host: Optional[QWidget]):
    _layout_banners(host)
