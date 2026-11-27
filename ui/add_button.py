"""
Raikō - the "add" action, one per library.

A custom-drawn action tile instead of a flat pill: dark surface, a soft glow
along the edge in the library's accent, the library's own icon in a tinted
badge, a two-line label and the keyboard shortcut. Each library gets its own
identity:

    anime  (Miroku)  indigo   four-point sparkle   "Search AniList"
    movie  (Kinema)  amber    film frame           "Search TMDB"
    tv     (Kinema)  sky blue screen on a stand    "Search TMDB"
"""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
)
from ui.theme import QColor  # noqa: E402,F811  (theme-aware colours)
from PyQt6.QtWidgets import QPushButton

LIBRARIES = {
    "anime": {"accent": "#8b7bff", "title": "Add anime", "caption": "Search AniList"},
    "movie": {"accent": "#fbbf24", "title": "Add a movie", "caption": "Search TMDB"},
    "tv":    {"accent": "#38bdf8", "title": "Add a show", "caption": "Search TMDB"},
}


def _icon_path(kind: str, r: QRectF) -> QPainterPath:
    """Vector icon for a library, drawn inside rect r (outline style)."""
    p = QPainterPath()
    cx, cy, w, h = r.center().x(), r.center().y(), r.width(), r.height()
    if kind == "movie":
        # film frame: rounded rect + sprocket holes down both sides
        fr = QRectF(cx - w * 0.42, cy - h * 0.36, w * 0.84, h * 0.72)
        p.addRoundedRect(fr, 2.5, 2.5)
        p.addRect(QRectF(fr.left() + w * 0.2, fr.top(), w * 0.44, fr.height()))
        for i in range(3):
            y = fr.top() + fr.height() * (0.2 + 0.3 * i) - 1.2
            p.addRect(QRectF(fr.left() + 2.2, y, 2.6, 2.4))
            p.addRect(QRectF(fr.right() - 4.8, y, 2.6, 2.4))
    elif kind == "tv":
        sc = QRectF(cx - w * 0.42, cy - h * 0.34, w * 0.84, h * 0.56)
        p.addRoundedRect(sc, 2.5, 2.5)
        p.moveTo(cx - w * 0.16, sc.bottom() + h * 0.16)
        p.lineTo(cx + w * 0.16, sc.bottom() + h * 0.16)
        p.moveTo(cx, sc.bottom())
        p.lineTo(cx, sc.bottom() + h * 0.16)
    else:
        # four-point sparkle
        a, b = w * 0.44, w * 0.12
        p.moveTo(cx, cy - a)
        p.quadTo(cx + b * 0.3, cy - b * 0.3, cx + a, cy)
        p.quadTo(cx + b * 0.3, cy + b * 0.3, cx, cy + a)
        p.quadTo(cx - b * 0.3, cy + b * 0.3, cx - a, cy)
        p.quadTo(cx - b * 0.3, cy - b * 0.3, cx, cy - a)
        p.closeSubpath()
    return p


class AddButton(QPushButton):
    """Library-aware add action. size: 'sidebar' | 'hero'."""

    def __init__(self, media: str = "anime", size: str = "sidebar", parent=None):
        super().__init__(parent)
        self._media = media
        self._size = size
        self._hover = False
        self._down = False
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setObjectName("addActionButton")
        self.setStyleSheet("QPushButton#addActionButton{background:transparent;border:none;}")
        self.setFixedHeight(58 if size == "sidebar" else 64)
        if size == "hero":
            self.setFixedWidth(280)
        self.set_media(media)

    def set_media(self, media: str):
        self._media = media if media in LIBRARIES else "anime"
        info = LIBRARIES[self._media]
        self.setToolTip(f"{info['title']}  (Ctrl+N)")
        self.setAccessibleName(info["title"])
        self.update()

    def media(self) -> str:
        return self._media

    def sizeHint(self):
        return QSize(240, self.height())

    # ── interaction state ──
    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self._down = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self._down = True
        self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._down = False
        self.update()
        super().mouseReleaseEvent(e)

    # ── drawing ──
    def paintEvent(self, _):
        info = LIBRARIES[self._media]
        accent = QColor(info["accent"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self._down:
            r.translate(0, 1)
        radius = 12
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)

        # surface: deep slate with the accent bleeding in from the left
        g = QLinearGradient(r.topLeft(), r.topRight())
        a1 = QColor(accent)
        a1.setAlpha(70 if self._hover else 44)
        a2 = QColor(accent)
        a2.setAlpha(6)
        g.setColorAt(0.0, a1)
        g.setColorAt(0.55, a2)
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillPath(path, QColor("#121522"))
        p.fillPath(path, g)

        # edge: accent hairline, brighter on hover
        edge = QColor(accent)
        edge.setAlpha(170 if self._hover else 90)
        p.setPen(QPen(edge, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # icon badge
        bs = r.height() - 22
        badge = QRectF(r.left() + 11, r.center().y() - bs / 2, bs, bs)
        bpath = QPainterPath()
        bpath.addRoundedRect(badge, 9, 9)
        fill = QColor(accent)
        fill.setAlpha(255 if self._hover else 40)
        p.fillPath(bpath, fill)
        icon_col = QColor("#0d0f14") if self._hover else accent
        p.setPen(QPen(icon_col, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        inner = badge.adjusted(bs * 0.22, bs * 0.22, -bs * 0.22, -bs * 0.22)
        ip = _icon_path(self._media, inner)
        if self._media == "anime":
            p.setBrush(icon_col)
        p.drawPath(ip)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # the "+" that says this adds something
        plus_c = QPointF(badge.right() - 1, badge.bottom() - 1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0d0f14"))
        p.drawEllipse(plus_c, 7.5, 7.5)
        p.setBrush(accent)
        p.drawEllipse(plus_c, 6, 6)
        p.setPen(QPen(QColor("#0d0f14"), 1.6, cap=Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(plus_c.x() - 3, plus_c.y()), QPointF(plus_c.x() + 3, plus_c.y()))
        p.drawLine(QPointF(plus_c.x(), plus_c.y() - 3), QPointF(plus_c.x(), plus_c.y() + 3))

        # labels
        tx = badge.right() + 14
        f = QFont(self.font())
        f.setPointSizeF(10.5 if self._size == "sidebar" else 11.5)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor("#f0f1f5"))
        p.drawText(QRectF(tx, r.top() + 9, r.width() - tx - 40, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, info["title"])
        f2 = QFont(self.font())
        f2.setPointSizeF(8.5)
        p.setFont(f2)
        cap = QColor(accent) if self._hover else QColor("#7b84a3")
        p.setPen(cap)
        p.drawText(QRectF(tx, r.bottom() - 27, r.width() - tx - 40, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, info["caption"])

        # shortcut hint
        f3 = QFont(self.font())
        f3.setPointSizeF(7.5)
        f3.setWeight(QFont.Weight.DemiBold)
        p.setFont(f3)
        hint = "Ctrl N"
        fm = p.fontMetrics()
        hw = fm.horizontalAdvance(hint) + 12
        hr = QRectF(r.right() - hw - 10, r.center().y() - 9, hw, 18)
        hp = QPainterPath()
        hp.addRoundedRect(hr, 5, 5)
        p.fillPath(hp, QColor(255, 255, 255, 14))
        p.setPen(QColor("#7b84a3"))
        p.drawText(hr, Qt.AlignmentFlag.AlignCenter, hint)
        p.end()
