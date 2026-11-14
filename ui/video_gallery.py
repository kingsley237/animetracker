"""
Miroku - trailer / promo / theme gallery for the detail panel.

A big 16:9 "now selected" thumbnail with a play button, and every other
video as a small tile underneath (wrapping, never scrolling sideways).
Clicking a tile swaps it into the big slot; clicking the big one opens the
player on that video with the whole list as an Up Next playlist, so you can
hop between PVs without closing anything.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QPolygonF,
)
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from ui.layout_helpers import FlowLayout
from workers.workers import ImageWorker, run_worker


class TrailerThumb(QWidget):
    """16:9 thumbnail with a play button; click to play."""
    clicked = pyqtSignal()

    def __init__(self, caption: str = "▶  Watch trailer", parent=None):
        super().__init__(parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._pix: Optional[QPixmap] = None
        self._hover = False
        self._caption = caption
        self.setToolTip("Play")

    def sizeHint(self):
        return QSize(330, 186)

    def resizeEvent(self, e):
        h = max(150, int(self.width() * 9 / 16))
        if self.height() != h:
            self.setFixedHeight(h)
        super().resizeEvent(e)

    def set_caption(self, text: str):
        self._caption = text
        self.update()

    def set_pixmap(self, pix: Optional[QPixmap]):
        self._pix = pix
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.setClipPath(path)
        if self._pix and not self._pix.isNull():
            sc = self._pix.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(0, 0, sc, (sc.width() - self.width()) // 2,
                         (sc.height() - self.height()) // 2, self.width(), self.height())
        else:
            g = QLinearGradient(0, 0, self.width(), self.height())
            g.setColorAt(0, QColor("#1b1840"))
            g.setColorAt(1, QColor("#0f1118"))
            p.fillRect(self.rect(), g)
        shade = QLinearGradient(0, 0, 0, self.height())
        shade.setColorAt(0, QColor(0, 0, 0, 30))
        shade.setColorAt(1, QColor(0, 0, 0, 160 if not self._hover else 115))
        p.fillRect(self.rect(), shade)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 34), 1))
        p.drawPath(path)

        cx, cy = self.width() / 2, self.height() / 2
        rad = 29 if self._hover else 26
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(98, 84, 205, 245) if self._hover else QColor(75, 63, 168, 235))
        p.drawEllipse(QPointF(cx, cy), rad, rad)
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(QPolygonF([QPointF(cx - 7, cy - 11), QPointF(cx - 7, cy + 11),
                                 QPointF(cx + 12, cy)]))
        p.setPen(QColor("#e2e4ec"))
        f = QFont(self.font())
        f.setPointSizeF(9)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(12, self.height() - 28, self.width() - 24, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(self._caption, Qt.TextElideMode.ElideRight,
                                              int(self.width() - 24)))
        p.end()


class _Tile(QWidget):
    """Small thumbnail tile for the 'more videos' grid."""
    clicked = pyqtSignal(int)
    W, H = 104, 58

    def __init__(self, index: int, item: Dict, parent=None):
        super().__init__(parent)
        self.index = index
        self.item = item
        self._pix: Optional[QPixmap] = None
        self._sel = False
        self._hover = False
        self.setFixedSize(self.W, self.H + 30)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(item.get("title") or "Video")

    def set_selected(self, on: bool):
        self._sel = on
        self.update()

    def set_pixmap(self, pix):
        self._pix = pix
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(1, 1, self.W - 2, self.H - 2)
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        p.save()
        p.setClipPath(path)
        if self._pix and not self._pix.isNull():
            sc = self._pix.scaled(self.W, self.H, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(0, 0, sc, (sc.width() - self.W) // 2, (sc.height() - self.H) // 2,
                         self.W, self.H)
        else:
            p.fillRect(r, QColor("#1a1d28"))
        if not self._sel:
            p.fillRect(r, QColor(0, 0, 0, 70 if self._hover else 110))
        p.restore()
        pen = QPen(QColor("#7c6af7") if self._sel else QColor(255, 255, 255, 40), 2 if self._sel else 1)
        p.setPen(pen)
        p.drawPath(path)
        if self.item.get("kind") == "music":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(8, 10, 16, 210))
            p.drawRoundedRect(QRectF(5, 5, 40, 14), 4, 4)
            f = QFont(self.font())
            f.setPointSizeF(6.5)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#fbbf24"))
            p.drawText(QRectF(5, 5, 40, 14), Qt.AlignmentFlag.AlignCenter, "THEME")
        f = QFont(self.font())
        f.setPointSizeF(7.5)
        f.setBold(self._sel)
        p.setFont(f)
        p.setPen(QColor("#e2e4ec") if self._sel else QColor("#9da5c0"))
        rect = QRectF(1, self.H + 3, self.W - 2, 26)
        text = self.item.get("title") or "Video"
        p.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                   p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(self.W * 1.8)))
        p.end()


class VideoGallery(QWidget):
    def __init__(self, empty_text: str = "No videos yet.", parent=None):
        super().__init__(parent)
        self._items: List[Dict] = []
        self._sel = 0
        self._title = ""
        self._token = 0
        self._tiles: List[_Tile] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.hero = TrailerThumb()
        self.hero.clicked.connect(self._play)
        self.caption = QLabel()
        self.caption.setObjectName("galleryCaption")
        self.tiles_host = QWidget()
        self.tiles = FlowLayout(self.tiles_host, h_spacing=8, v_spacing=6)
        self.empty = QLabel(empty_text)
        self.empty.setObjectName("plannedEmpty")
        self.empty.setWordWrap(True)
        for w in (self.hero, self.caption, self.tiles_host, self.empty):
            lay.addWidget(w)

    def load(self, items: List[Dict], anime_title: str = ""):
        self._token += 1
        self._items = list(items or [])
        self._title = anime_title
        self._sel = 0
        has = bool(self._items)
        self.hero.setVisible(has)
        self.caption.setVisible(has)
        self.empty.setVisible(not has)
        self.tiles.clear()
        self._tiles = []
        self.tiles_host.setVisible(len(self._items) > 1)
        if not has:
            return
        if len(self._items) > 1:
            for i, it in enumerate(self._items):
                t = _Tile(i, it)
                t.clicked.connect(self._choose)
                self.tiles.addWidget(t)
                self._tiles.append(t)
                self._fetch(it.get("thumb"), ("tile", self._token, i))
        self._choose(0)

    def _choose(self, i: int):
        self._sel = i
        it = self._items[i]
        n = len(self._items)
        self.hero.set_caption(f"▶  {it.get('title') or 'Trailer'}")
        self.hero.set_pixmap(None)
        self.caption.setText(
            f"{it.get('title') or 'Trailer'}" + (f"   ·   {i + 1} of {n}  ·  click a tile to switch" if n > 1 else ""))
        for t in self._tiles:
            t.set_selected(t.index == i)
        self._fetch(it.get("thumb"), ("hero", self._token, i))

    def _fetch(self, url, key):
        if not url:
            return
        w = ImageWorker(url, key)
        w.signals.result.connect(self._on_img)
        run_worker(w)

    def _on_img(self, result):
        try:
            (slot, token, i), _s, path = result
        except Exception:
            return
        if not path or token != self._token:
            return
        pix = QPixmap(str(path))
        try:
            if slot == "hero" and i == self._sel:
                self.hero.set_pixmap(pix)
            elif slot == "tile" and i < len(self._tiles):
                self._tiles[i].set_pixmap(pix)
        except RuntimeError:
            pass

    def _play(self):
        if not self._items:
            return
        from ui.trailer_player import show_trailer
        it = self._items[self._sel]
        show_trailer(it["id"], it.get("site") or "youtube", self._title, self.window(),
                     playlist=self._items, index=self._sel)
