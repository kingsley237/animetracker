"""
Raikō - Home: one place for everything you watch.

  Header          greeting + date, and a compact "Search everything" pill (Ctrl+K)
  Spotlight       your most pressing title, full backdrop: what's next, a line
                  of synopsis, one-click Watched, Open; stat chips
  Continue        the rest of what you're in the middle of (anime + TV)
  This week       a 7-day schedule (+ Later): small posters, what airs, when
  Ready to watch  Watchlist movies already out in HD
Search results (anime, shows, movies in your library, grouped) replace the
sections while you type; online fallbacks open the matching Discover.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from workers.workers import PRIORITY_INTERACTIVE, ImageWorker, Worker, run_worker

LIB = {"anime": ("MIROKU", "#8b7bff"), "tv": ("KINEMA · TV", "#38bdf8"),
       "movie": ("KINEMA · MOVIE", "#fbbf24")}


def _img_url(row: Dict, wide: bool) -> str:
    if wide:
        return row.get("banner_url") or row.get("cover_url") or ""
    return row.get("cover_url") or ""


class _Img:
    """Mixin: load one image into self._pix and repaint."""

    def _load_img(self, url: str):
        self._pix: Optional[QPixmap] = None
        if url:
            w = ImageWorker(url, url)
            w.signals.result.connect(self._on_img)
            run_worker(w)

    def _on_img(self, result):
        try:
            _k, _s, path = result
            if path:
                self._pix = QPixmap(str(path))
                self.update()
        except RuntimeError:
            pass

    def _draw_cover(self, p: QPainter, r: QRectF, y_bias: float = 0.5):
        if self._pix and not self._pix.isNull():
            sc = self._pix.scaled(int(r.width()), int(r.height()), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int(r.x()), int(r.y()), sc, int((sc.width() - r.width()) / 2),
                         int((sc.height() - r.height()) * y_bias), int(r.width()), int(r.height()))
        else:
            p.fillRect(r, QColor("#161a2a"))


def _tag(p: QPainter, x: float, y: float, text: str, fg: str, bg: QColor) -> float:
    f = QFont(p.font())
    f.setPointSizeF(7)
    f.setBold(True)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.9)
    p.setFont(f)
    w = p.fontMetrics().horizontalAdvance(text) + 16
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(QRectF(x, y, w, 20), 6, 6)
    p.setPen(QColor(fg))
    p.drawText(QRectF(x, y, w, 20), Qt.AlignmentFlag.AlignCenter, text)
    return w


# ── spotlight ─────────────────────────────────────────────────────────────────

class _Spotlight(QWidget, _Img):
    """Rotating spotlight. Two kinds of slide, told apart at a glance:
      update  news about YOUR library: solid badge (NEW EPISODE, OUT IN HD,
              IN CINEMAS, NEW SEASON, NEW TRAILER, NEXT TO AIR)
      pick    something you don't have yet: outlined FOR YOU badge + reason
    Auto-advances every 9 s, pauses while hovered; dots and arrows to browse."""
    H = 340

    def __init__(self, parent=None):
        super().__init__(parent)
        self.slides: List[Dict] = []
        self.idx = 0
        self._pix = None
        self._hover = False
        self.setFixedHeight(self.H)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 28, 36, 28)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.badge = QLabel()
        self.badge.setObjectName("spotBadge")
        self.lib = QLabel()
        self.lib.setObjectName("spotLib")
        top.addWidget(self.badge)
        top.addWidget(self.lib)
        top.addStretch()
        lay.addLayout(top)
        self.reason = QLabel()
        self.reason.setObjectName("spotReason")
        rrow = QHBoxLayout()
        rrow.addWidget(self.reason)
        rrow.addStretch()
        lay.addLayout(rrow)
        lay.addStretch()
        self.title = QLabel()
        self.title.setObjectName("heroTitle")
        self.title.setWordWrap(True)
        self.line = QLabel()
        self.line.setObjectName("heroNext")
        self.blurb = QLabel()
        self.blurb.setObjectName("heroBlurb")
        self.blurb.setWordWrap(True)
        self.blurb.setMaximumWidth(600)
        for w in (self.title, self.line, self.blurb):
            lay.addWidget(w)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.btn1 = QPushButton()
        self.btn1.setObjectName("spotPrimary")
        self.btn2 = QPushButton()
        self.btn2.setObjectName("heroSecondary")
        for b in (self.btn1, self.btn2):
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setMinimumHeight(40)
            row.addWidget(b)
        row.addStretch()
        self.prev = QPushButton("‹")
        self.next = QPushButton("›")
        for b in (self.prev, self.next):
            b.setObjectName("spotArrow")
            b.setFixedSize(36, 36)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            row.addWidget(b)
        self.prev.clicked.connect(lambda: self.show_slide(self.idx - 1))
        self.next.clicked.connect(lambda: self.show_slide(self.idx + 1))
        lay.addSpacing(6)
        lay.addLayout(row)
        self.btn1.clicked.connect(lambda: self._run(1))
        self.btn2.clicked.connect(lambda: self._run(2))
        self._auto = QTimer(self)
        self._auto.timeout.connect(lambda: self.show_slide(self.idx + 1) if not self._hover else None)
        self._auto.start(9000)
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick)
        self._clock.start(30_000)

    # compat with the previous single-item hero
    @property
    def item(self) -> Optional[Dict]:
        return self.slides[self.idx].get("item") if self.slides else None

    def set_slides(self, slides: List[Dict], keep: bool = False):
        cur = self.slides[self.idx].get("key") if (keep and self.slides) else None
        self.slides = slides
        idx = next((k for k, sl in enumerate(slides) if cur and sl.get("key") == cur), 0)
        self.show_slide(idx)

    def show_slide(self, idx: int):
        if not self.slides:
            return
        self.idx = idx % len(self.slides)
        sl = self.slides[self.idx]
        tag, color = LIB[sl["media"]]
        self._color = color
        pick = sl["kind"] == "pick"
        self.badge.setText(sl["badge"])
        self.badge.setStyleSheet(
            (f"color:{color};background:transparent;border:1.5px solid {color};" if pick else
             f"color:#0b0d12;background:{sl.get('badge_color') or color};border:none;")
            + "border-radius:8px;padding:3px 10px;font-size:10px;font-weight:900;letter-spacing:1.4px;")
        self.lib.setText(tag)
        self.lib.setStyleSheet(f"color:{color};font-size:10px;font-weight:800;letter-spacing:1.4px;"
                               "background:rgba(8,9,14,0.6);border-radius:8px;padding:3px 9px;")
        self.reason.setText(sl.get("reason") or "")
        self.reason.setVisible(bool(sl.get("reason")))
        self.title.setText(sl["title"])
        self.line.setText(sl.get("line") or "")
        self.blurb.setText(sl.get("blurb") or "")
        for b, key in ((self.btn1, "primary"), (self.btn2, "secondary")):
            spec = sl.get(key)
            b.setVisible(bool(spec))
            if spec:
                b.setText(spec[0])
        self.btn1.setStyleSheet(f"QPushButton#spotPrimary{{background:{color};color:#0b0d12;border:none;"
                                "border-radius:11px;padding:0 20px;font-size:13px;font-weight:800;}}")
        many = len(self.slides) > 1
        self.prev.setVisible(many)
        self.next.setVisible(many)
        self._load_img(sl.get("img") or "")
        self._tick()
        self.update()

    def _run(self, which: int):
        sl = self.slides[self.idx] if self.slides else None
        spec = sl and sl.get("primary" if which == 1 else "secondary")
        if spec:
            spec[1]()

    def _tick(self):
        sl = self.slides[self.idx] if self.slides else None
        t = sl and sl.get("countdown_to")
        if not t:
            return
        secs = int(t - datetime.now().timestamp())
        if secs <= 0:
            self.line.setText(f"{sl['line_base']}   ·   out now")
            return
        d, rem = divmod(secs, 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        self.line.setText(f"{sl['line_base']}   ·   in " + (f"{d}d {h}h {m:02d}m" if d else f"{h}h {m:02d}m"))

    def enterEvent(self, e):
        self._hover = True

    def leaveEvent(self, e):
        self._hover = False

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(r, 18, 18)
        p.setClipPath(path)
        self._draw_cover(p, r, 0.3)
        g = QLinearGradient(0, 0, self.width(), 0)
        g.setColorAt(0, QColor(9, 10, 16, 250))
        g.setColorAt(0.42, QColor(9, 10, 16, 215))
        g.setColorAt(0.75, QColor(9, 10, 16, 70))
        g.setColorAt(1, QColor(9, 10, 16, 20))
        p.fillRect(r, g)
        v = QLinearGradient(0, self.height() * 0.55, 0, self.height())
        v.setColorAt(0, QColor(9, 10, 16, 0))
        v.setColorAt(1, QColor(9, 10, 16, 170))
        p.fillRect(r, v)
        p.setPen(QColor(255, 255, 255, 18))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        if not self.slides:
            p.end()
            return
        sl = self.slides[self.idx]
        prog = sl.get("progress")
        if prog is not None and sl["kind"] == "update":
            p.setPen(Qt.PenStyle.NoPen)
            p.fillRect(QRectF(0, self.height() - 4, self.width(), 4), QColor(255, 255, 255, 28))
            p.fillRect(QRectF(0, self.height() - 4, self.width() * max(0.02, min(1.0, prog)), 4),
                       QColor(self._color))
        # dots: solid = your library, ring = picked for you
        n = len(self.slides)
        if n > 1:
            x = self.width() - 36 - n * 14
            y = 34
            for k, s2 in enumerate(self.slides):
                c = QColor(LIB[s2["media"]][1])
                if k != self.idx:
                    c.setAlpha(110)
                if s2["kind"] == "pick":
                    p.setPen(QPen(c, 1.6))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                else:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(c)
                rad = 4.5 if k == self.idx else 3.5
                p.drawEllipse(QRectF(x + k * 14 - rad, y - rad, rad * 2, rad * 2))
        p.end()


class _Stat(QWidget):
    def __init__(self, value: str, label: str, color: str, parent=None):
        super().__init__(parent)
        self.setObjectName("homeStat")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        l = QVBoxLayout(self)
        l.setContentsMargins(16, 10, 16, 10)
        l.setSpacing(0)
        v = QLabel(value)
        v.setObjectName("homeStatValue")
        v.setStyleSheet(f"color:{color};")
        t = QLabel(label.upper())
        t.setObjectName("homeStatLabel")
        l.addWidget(v)
        l.addWidget(t)


# ── continue rail ─────────────────────────────────────────────────────────────

class _Rail(QScrollArea):
    def __init__(self, height: int, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFixedHeight(height)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        host = QWidget()
        host.setStyleSheet("background:transparent;")
        self.row = QHBoxLayout(host)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(16)
        self.row.addStretch()
        self.setWidget(host)

    def wheelEvent(self, e):
        bar = self.horizontalScrollBar()
        if bar.maximum() > 0:
            bar.setValue(bar.value() - e.angleDelta().y())
            e.accept()
        else:
            super().wheelEvent(e)

    def clear(self):
        while self.row.count() > 1:
            it = self.row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def add(self, w: QWidget):
        self.row.insertWidget(self.row.count() - 1, w)


# ── this week ─────────────────────────────────────────────────────────────────

class _MiniItem(QWidget, _Img):
    open = pyqtSignal(int)
    picked = pyqtSignal(object)            # the item widget itself: the popover anchors to it
    PW, PH = 40, 58

    def __init__(self, item: Dict, parent=None):
        super().__init__(parent)
        self.item = item
        self._hover = False
        self.setFixedHeight(self.PH + 8)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(f"{item['title']} — {item['label']}")
        self._load_img(_img_url(item["row"], wide=False))

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        tag, color = LIB[self.item["media"]]
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 12))
            p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 8, 8)
        if self.width() >= 150:
            pr = QRectF(4, 4, self.PW, self.PH)
            path = QPainterPath()
            path.addRoundedRect(pr, 6, 6)
            p.save()
            p.setClipPath(path)
            self._draw_cover(p, pr)
            p.restore()
            x = self.PW + 12
        else:
            # narrow column (small screens): a colour bar instead of the poster
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(3, 8, 3, self.PH - 8), 1.5, 1.5)
            x = 12
        w = self.width() - x - 4
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#e8eaf2"))
        title = p.fontMetrics().elidedText(self.item["title"], Qt.TextElideMode.ElideRight, int(w))
        p.drawText(QRectF(x, 6, w, 16), Qt.AlignmentFlag.AlignLeft, title)
        f.setPointSizeF(8)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(QRectF(x, 24, w, 16), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.item["label"], Qt.TextElideMode.ElideRight, int(w)))
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor("#7f87a3"))
        when = datetime.fromtimestamp(self.item["when"])
        sub = when.strftime("%H:%M") if self.item.get("exact") else (
            "Movie" if self.item["media"] == "movie" else "TV")
        if self.item.get("later"):
            sub = when.strftime("%a %b ") + str(when.day)
        p.drawText(QRectF(x, 42, w, 16), Qt.AlignmentFlag.AlignLeft, sub)
        p.end()


class _DayColumn(QWidget):
    def __init__(self, title: str, sub: str, today: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("homeDayColToday" if today else "homeDayCol")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(96)       # shrinks on small screens; text elides
        l = QVBoxLayout(self)
        l.setContentsMargins(10, 12, 10, 12)
        l.setSpacing(4)
        h = QLabel(title)
        h.setObjectName("homeDayTitle")
        s = QLabel(sub)
        s.setObjectName("homeDaySub")
        l.addWidget(h)
        l.addWidget(s)
        l.addSpacing(6)
        self.items = l

    def add(self, w: QWidget):
        self.items.addWidget(w)

    def finish(self, empty: bool):
        if empty:
            e = QLabel("Nothing")
            e.setObjectName("homeDayEmpty")
            self.items.addWidget(e)
        self.items.addStretch()


class _PosterCard(QWidget, _Img):
    open = pyqtSignal(int)
    W, H = 132, 198

    def __init__(self, item: Dict, parent=None):
        super().__init__(parent)
        self.item = item
        self._hover = False
        self.setFixedSize(self.W, self.H + 42)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._load_img(_img_url(item["row"], wide=False))

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.open.emit(self.item["id"])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(0, 0, self.W, self.H)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.save()
        p.setClipPath(path)
        self._draw_cover(p, r)
        p.restore()
        p.setPen(QColor("#fbbf24") if self._hover else QColor(255, 255, 255, 30))
        p.drawPath(path)
        _tag(p, 8, 8, "IN HD", "#062016", QColor("#34d399"))
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#e8eaf2"))
        p.drawText(QRectF(0, self.H + 5, self.W, 18), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.item["title"], Qt.TextElideMode.ElideRight, self.W))
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor("#7f87a3"))
        p.drawText(QRectF(0, self.H + 23, self.W, 16), Qt.AlignmentFlag.AlignLeft, self.item.get("label") or "")
        p.end()


class _SuggestRow(QWidget, _Img):
    """A title you don't have yet: opens its Discover preview to add it."""
    open = pyqtSignal(dict)

    def __init__(self, hit: Dict, parent=None):
        super().__init__(parent)
        self.hit = hit
        self._hover = False
        self.setFixedHeight(64)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._load_img(hit.get("poster_url") or "")

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.open.emit(self.hit)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        tag, color = LIB[self.hit["media_type"]]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 14 if self._hover else 6))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 10, 10)
        pr = QRectF(10, 6, 36, 52)
        path = QPainterPath()
        path.addRoundedRect(pr, 5, 5)
        p.save()
        p.setClipPath(path)
        self._draw_cover(p, pr)
        p.restore()
        f = QFont(self.font())
        f.setPointSizeF(10)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#eef0f7"))
        p.drawText(QRectF(58, 12, self.width() - 260, 20), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.hit.get("title") or "", Qt.TextElideMode.ElideRight,
                                              self.width() - 260))
        f.setPointSizeF(8)
        p.setFont(f)
        p.setPen(QColor(color))
        year = self.hit.get("year")
        p.drawText(QRectF(58, 34, 320, 16), Qt.AlignmentFlag.AlignLeft, tag + (f"  ·  {year}" if year else ""))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(QRectF(self.width() - 190, 0, 176, self.height()),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "Preview & add  →")
        p.end()


class _SearchRow(QWidget, _Img):
    open = pyqtSignal(int)

    def __init__(self, row: Dict, parent=None):
        super().__init__(parent)
        self.row = row
        self.lib_id = row["id"]
        self._hover = False
        self.setFixedHeight(64)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._load_img(row.get("cover_url") or "")

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.open.emit(self.lib_id)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        media = self.row.get("media_type") or "anime"
        tag, color = LIB[media]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 14 if self._hover else 6))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 10, 10)
        pr = QRectF(10, 6, 36, 52)
        path = QPainterPath()
        path.addRoundedRect(pr, 5, 5)
        p.save()
        p.setClipPath(path)
        self._draw_cover(p, pr)
        p.restore()
        f = QFont(self.font())
        f.setPointSizeF(10)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#eef0f7"))
        name = self.row.get("english_title") or self.row.get("romaji_title") or ""
        p.drawText(QRectF(58, 12, self.width() - 240, 20), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, self.width() - 240))
        f.setPointSizeF(8)
        p.setFont(f)
        p.setPen(QColor(color))
        year = self.row.get("season_year")
        p.drawText(QRectF(58, 34, 300, 16), Qt.AlignmentFlag.AlignLeft,
                   tag + (f"  ·  {year}" if year else ""))
        ws = {"watching": "Watching", "planned": "Plan to Watch" if media == "anime" else "Watchlist",
              "completed": "Completed" if media != "movie" else "Watched",
              "dropped": "Dropped"}.get(self.row.get("watch_status"), "")
        f.setBold(False)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor("#9da5c0"))
        p.drawText(QRectF(self.width() - 170, 0, 156, self.height()),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, ws)
        p.end()


# ── page ──────────────────────────────────────────────────────────────────────

class _PantheonStrip(QWidget):
    """Your four Pantheon picks, small, beside the stats. Click: the Hall."""
    open_hall = pyqtSignal()
    PW, PH = 40, 60

    def __init__(self, entries: List[Dict], parent=None):
        super().__init__(parent)
        self.entries = entries
        self.pix: Dict[str, QPixmap] = {}
        self._hover = False
        self.setFixedSize(16 + 4 * (self.PW + 8) + 88, self.PH + 16)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("Your Pantheon — open the Hall of Fame")
        for e in entries:
            u = (e or {}).get("row", {}).get("cover_url") if e else None
            if u:
                w = ImageWorker(u, u)
                w.signals.result.connect(self._on_img)
                run_worker(w)

    def _on_img(self, res):
        try:
            k, _s, path = res
            if path:
                self.pix[k] = QPixmap(str(path))
                self.update()
        except RuntimeError:
            pass

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.open_hall.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        box = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QColor("#f5c451") if self._hover else QColor("#23273a"))
        p.setBrush(QColor("#12141d"))
        p.drawRoundedRect(box, 12, 12)
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(9)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        p.setFont(f)
        p.setPen(QColor("#f5c451"))
        p.drawText(QRectF(14, 12, 80, 14), Qt.AlignmentFlag.AlignLeft, "★ YOUR")
        p.drawText(QRectF(14, 26, 80, 14), Qt.AlignmentFlag.AlignLeft, "PANTHEON")
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0)
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor("#7f87a3"))
        p.drawText(QRectF(14, 44, 80, 16), Qt.AlignmentFlag.AlignLeft, "Hall of Fame →")
        x = 96
        for e in self.entries:
            r = QRectF(x, 8, self.PW, self.PH)
            path = QPainterPath()
            path.addRoundedRect(r, 6, 6)
            u = (e or {}).get("row", {}).get("cover_url") if e else None
            pm = self.pix.get(u) if u else None
            p.setBrush(Qt.BrushStyle.NoBrush)
            if pm and not pm.isNull():
                p.save()
                p.setClipPath(path)
                sc = pm.scaled(self.PW, self.PH, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
                p.drawPixmap(int(r.x()), int(r.y()), sc, (sc.width() - self.PW) // 2, 0, self.PW, self.PH)
                p.restore()
                p.setPen(QColor(245, 196, 81, 150))
                p.drawPath(path)
            else:
                p.setPen(QPen(QColor("#2e3348"), 1, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)
            x += self.PW + 8
        p.end()


class HomePage(QWidget):
    open_title = pyqtSignal(int)
    changed = pyqtSignal(int)
    search_online = pyqtSignal(str, str)
    open_pick = pyqtSignal(dict)           # a recommendation -> its Discover preview
    play_trailer = pyqtSignal(str, str, str)
    open_hall = pyqtSignal()
    _PICKS: Dict = {"at": 0, "hits": []}   # shared cache: picks are slow (network)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("contentArea")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        from ui.layout_helpers import FitWidthScroll
        self.scroll = FitWidthScroll()
        body = QWidget()
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(36, 26, 36, 36)
        self.lay.setSpacing(0)
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        self.hello = QLabel()
        self.hello.setObjectName("homeHello")
        self.date = QLabel()
        self.date.setObjectName("homeDate")
        col.addWidget(self.hello)
        col.addWidget(self.date)
        head.addLayout(col)
        head.addStretch()
        self.search = QLineEdit()
        self.search.setObjectName("homeSearch")
        self.search.setPlaceholderText("🔎  Search everything     Ctrl+K")
        self.search.setFixedSize(340, 40)
        self.search.setClearButtonEnabled(True)
        head.addWidget(self.search, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.lay.addLayout(head)
        self.lay.addSpacing(20)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._run_search)
        self.search.textChanged.connect(lambda _t: self._timer.start(200))
        self.search.returnPressed.connect(self._open_first)

        self.results = QWidget()
        self.res_lay = QVBoxLayout(self.results)
        self.res_lay.setContentsMargins(0, 0, 0, 0)
        self.res_lay.setSpacing(6)
        self.results.setVisible(False)
        self.lay.addWidget(self.results)

        self.sections = QWidget()
        sl = QVBoxLayout(self.sections)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        self.hero = _Spotlight()
        sl.addWidget(self.hero)
        self.stats = QHBoxLayout()
        self.stats.setSpacing(12)
        sl.addSpacing(14)
        sl.addLayout(self.stats)
        self.hero_empty = QLabel("Nothing in progress. Find something new in Discover, or press Ctrl+N to add it.")
        self.hero_empty.setObjectName("homeEmpty")
        self.hero_empty.setWordWrap(True)
        sl.addWidget(self.hero_empty)

        self.wk_head = self._head("This week", sl)
        self.week = QHBoxLayout()
        self.week.setSpacing(10)
        sl.addLayout(self.week)

        self.rd_head = self._head("Ready to watch  ·  out in HD", sl)
        self.rd_rail = _Rail(_PosterCard.H + 50)
        sl.addWidget(self.rd_rail)

        sl.addStretch()
        self.lay.addWidget(self.sections)
        self.lay.addStretch()
        self._last_results: List[Dict] = []
        # left open for hours: pick up the next rotation without leaving Home
        self._rot_timer = QTimer(self)
        self._rot_timer.timeout.connect(
            lambda: getattr(self, "_picks", None) and self._render_spotlight(keep=True))
        self._rot_timer.start(20 * 60 * 1000)

    @staticmethod
    def _head(text: str, lay: QVBoxLayout) -> QLabel:
        lay.addSpacing(30)
        l = QLabel(text)
        l.setObjectName("homeSection")
        lay.addWidget(l)
        lay.addSpacing(12)
        return l

    @staticmethod
    def _muted(text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("homeEmpty")
        l.setWordWrap(True)
        return l

    @staticmethod
    def _clear(layout):
        while layout.count():
            it = layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                HomePage._clear(it.layout())

    # ── load ──────────────────────────────────────────────────────────────────

    def load(self):
        h = datetime.now().hour
        self.hello.setText("Good morning" if 5 <= h < 12 else "Good afternoon" if h < 18 else "Good evening")
        d = datetime.now()
        self.date.setText(d.strftime("%A, %B ") + str(d.day))

        def work():
            from core import up_next as un
            return (un.continue_watching(self.db), un.coming_up(self.db), un.ready_to_watch(self.db),
                    un.library_updates(self.db))

        w = Worker(work)
        w.signals.result.connect(self._render)
        run_worker(w, PRIORITY_INTERACTIVE)
        self._load_picks()

    def _load_picks(self, force: bool = False):
        import time as _t
        cache = HomePage._PICKS
        if cache["hits"] and not force and _t.time() - cache["at"] < 15 * 60:
            self._picks = cache["hits"]
            return

        def work():
            from core import up_next as un
            return un.picks(self.db)

        def done(hits):
            from PyQt6 import sip
            cache.update(at=_t.time(), hits=hits or [])
            if sip.isdeleted(self):
                return
            self._picks = cache["hits"]
            self._render_picks()

        w = Worker(work)
        w.signals.result.connect(done)
        run_worker(w)

    def _render(self, data):
        from PyQt6 import sip
        if sip.isdeleted(self):
            return
        cw, up, ready, updates = data
        self._data = data
        # spotlight: never empty - a new episode, else what airs next from what
        # you watch, else something from your Plan to Watch / Watchlist
        self._updates = updates
        self._up = up
        self._render_spotlight()
        self._clear(self.stats)
        now = datetime.now().timestamp()
        new = sum(1 for c in cw if c["new"])
        week = [u for u in up if u["when"] <= now + 7 * 86400]
        watching = sum(len(self.db.get_all_anime(watch_status="watching", media_type=m)) for m in ("anime", "tv"))
        for v, label, color in ((watching, "watching", "#f0f1f6"), (new, "new episodes", "#f87171"),
                                (len(week), "airing this week", "#8b7bff"),
                                (len(ready), "movies in HD", "#fbbf24")):
            self.stats.addWidget(_Stat(str(v), label, color))
        self.stats.addStretch()
        self._pantheon_strip = None
        self.refresh_pantheon()

        # this week: 7 day columns + Later
        self._clear(self.week)
        today = datetime.now().date()
        cols = []
        for i in range(7):
            d = today + timedelta(days=i)
            title = "Today" if i == 0 else "Tomorrow" if i == 1 else d.strftime("%A")
            cols.append((d, _DayColumn(title, d.strftime("%b ") + str(d.day), i == 0)))
        later = _DayColumn("Later", "next 2 weeks", False)
        placed = {id(c): 0 for _d, c in cols}
        placed[id(later)] = 0
        for item in up:
            d = datetime.fromtimestamp(item["when"]).date()
            col = next((c for dd, c in cols if dd == d), None)
            if col is None:
                if d < today:
                    col = cols[0][1]
                else:
                    col = later
                    item = {**item, "later": True}
            if placed[id(col)] >= 5:
                continue
            mi = _MiniItem(item)
            mi.picked.connect(self._show_popover)
            col.add(mi)
            placed[id(col)] += 1
        for _d, c in cols + [(None, later)]:
            c.finish(placed[id(c)] == 0)
            self.week.addWidget(c, 1)
        self.wk_head.setVisible(True)

        # ready to watch
        self.rd_rail.clear()
        for item in ready:
            c = _PosterCard(item)
            c.open.connect(self.open_title.emit)
            self.rd_rail.add(c)
        self.rd_head.setVisible(bool(ready))
        self.rd_rail.setVisible(bool(ready))

    # ── spotlight slides ──────────────────────────────────────────────────────

    def _render_spotlight(self, keep: bool = False):
        updates = getattr(self, "_updates", [])
        slides = [self._update_slide(u) for u in updates]
        if not any(u["update"] == "episode" for u in updates):
            # caught up: what airs next from what you watch (or something to start)
            nxt = self._fallback_hero(getattr(self, "_up", []))
            if nxt and not (nxt["mode"] == "planned" and slides):
                s2 = self._airing_slide(nxt) if nxt["mode"] == "airing" else self._planned_slide(nxt)
                slides.insert(0, s2)
        slides += [self._pick_slide(h) for h in self._rotated_picks()]
        self.hero.setVisible(bool(slides))
        self.hero_empty.setVisible(not slides)
        if slides:
            self.hero.set_slides(slides, keep=keep)

    # A new mix every few hours and every app start; recently shown picks rest.
    _ROTATE_EVERY = 4 * 3600
    _SESSION_SEED = None

    def _rotated_picks(self) -> List[Dict]:
        import random
        import time as _t
        pool = getattr(self, "_picks", []) or []
        if not pool:
            return []
        if HomePage._SESSION_SEED is None:
            HomePage._SESSION_SEED = random.randrange(1 << 30)      # new mix on each start
        seed = HomePage._SESSION_SEED + int(_t.time() // self._ROTATE_EVERY)
        cached = getattr(self, "_rot", None)
        ids = tuple(sorted(f"{h.get('media_type')}:{h.get('provider_id')}" for h in pool))
        if cached and cached[0] == seed and cached[1] == ids:
            return cached[2]
        from core import up_next as un
        from core.app_settings import app_settings
        st = app_settings()
        import json
        try:
            recent = json.loads(st.value("spotlight_recent_picks", "{}") or "{}")
        except (TypeError, ValueError):
            recent = {}
        now = _t.time()
        recent = {k: v for k, v in recent.items() if now - float(v) < 24 * 3600}
        chosen = un.rotate_picks(pool, recent, seed)
        for h in chosen:
            recent[f"{h.get('media_type')}:{h.get('provider_id')}"] = now
        st.setValue("spotlight_recent_picks", json.dumps(recent))
        self._rot = (seed, ids, chosen)
        return chosen

    def _render_picks(self):
        self._render_spotlight(keep=True)

    @staticmethod
    def _blurb(text: str) -> str:
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()
        return t if len(t) < 190 else t[:185].rsplit(" ", 1)[0] + "…"

    def _update_slide(self, u: Dict) -> Dict:
        row, kind = u["row"], u["update"]
        sl = {"kind": "update", "key": f"u{u['id']}{kind}", "badge": u["badge"], "media": u["media"],
              "title": u["title"], "img": _img_url(row, wide=True), "blurb": self._blurb(row.get("description")),
              "progress": u.get("progress"), "item": u if kind == "episode" else None,
              "badge_color": {"episode": "#f87171", "hd": "#34d399", "cinema": "#fbbf24",
                              "season": "#f472b6", "trailer": "#38bdf8"}.get(kind)}
        if kind == "episode":
            short = u["label"].split(" · ")[0]
            sl.update(line=f"{u['label']}   ·   {u['sub']}",
                      primary=(f"✓  Watched {short}", lambda u=u: self._mark(u)),
                      secondary=("Open details", lambda i=u["id"]: self.open_title.emit(i)))
        elif kind == "trailer" and (u.get("payload") or {}).get("trailer_id"):
            pl = u["payload"]
            sl.update(line=u["sub"],
                      primary=("▶  Play trailer", lambda pl=pl, t=u["title"]: self.play_trailer.emit(
                          pl["trailer_id"], pl.get("trailer_site") or "youtube", t)),
                      secondary=("Open details", lambda i=u["id"]: self.open_title.emit(i)))
        else:
            sl.update(line=f"{u['label']}   ·   {u['sub']}" if u.get("sub") else u["label"],
                      primary=("Open details", lambda i=u["id"]: self.open_title.emit(i)))
        return sl

    def _airing_slide(self, it: Dict) -> Dict:
        return {"kind": "update", "key": f"a{it['id']}", "badge": "NEXT TO AIR", "media": it["media"],
                "title": it["title"], "img": _img_url(it["row"], wide=True),
                "blurb": self._blurb(it["row"].get("description")), "progress": it.get("progress"),
                "line": it["label"], "line_base": it["label"], "countdown_to": it.get("when"),
                "badge_color": "#c7cbe0", "item": it,
                "primary": ("See the episodes", lambda i=it["id"]: self.open_title.emit(i))}

    def _planned_slide(self, it: Dict) -> Dict:
        return {"kind": "update", "key": f"p{it['id']}", "badge": "READY WHEN YOU ARE", "media": it["media"],
                "title": it["title"], "img": _img_url(it["row"], wide=True),
                "blurb": self._blurb(it["row"].get("description")), "progress": None,
                "line": f"{it['label']}   ·   {it['sub']}" if it.get("sub") else it["label"],
                "badge_color": "#c7cbe0", "item": it,
                "primary": ("Start watching", lambda i=it["id"]: self.open_title.emit(i))}

    def _pick_slide(self, h: Dict) -> Dict:
        from core import tmdb
        raw = h.get("raw") or {}
        if h["media_type"] == "anime":
            img = raw.get("bannerImage") or h.get("poster_url")
        else:
            img = tmdb.image_url(raw.get("backdrop_path"), "w1280") or h.get("poster_url")
        kind = {"anime": "Anime", "tv": "TV show", "movie": "Movie"}[h["media_type"]]
        bits = [kind] + ([str(h["year"])] if h.get("year") else []) + \
            ([f"★ {h['score'] / 10:.1f}"] if h.get("score") else [])
        return {"kind": "pick", "key": f"k{h['media_type']}{h['provider_id']}", "badge": "FOR YOU",
                "media": h["media_type"], "title": h.get("title") or "", "img": img,
                "reason": h.get("reason") or "", "line": "   ·   ".join(bits),
                "blurb": self._blurb(h.get("overview")), "progress": None,
                "primary": ("Preview && add", lambda h=h: self.open_pick.emit(h))}

    def _fallback_hero(self, up: List[Dict]) -> Optional[Dict]:
        mine = [u for u in up if u["media"] in ("anime", "tv")
                and (u["row"].get("watch_status") == "watching")]
        pick = mine[0] if mine else (up[0] if up else None)
        if pick:
            when = datetime.fromtimestamp(pick["when"])
            day = ("today" if when.date() == datetime.now().date() else
                   "tomorrow" if when.date() == (datetime.now() + timedelta(days=1)).date()
                   else when.strftime("%A"))
            at = f" at {when.strftime('%H:%M')}" if pick.get("exact") else ""
            return {**pick, "mode": "airing", "label": f"{pick['label']} · {day}{at}", "sub": "",
                    "progress": self._progress(pick["row"])}
        for media in ("anime", "tv", "movie"):
            rows = self.db.get_all_anime(watch_status="planned", media_type=media, sort_by="top_rated")
            rows = [r for r in rows if (r.get("status") or "") != "NOT_YET_RELEASED"]
            if rows:
                r = rows[0]
                return {"id": r["id"], "media": media, "row": r, "mode": "planned",
                        "title": r.get("english_title") or r.get("romaji_title") or "",
                        "label": "On your " + ("Plan to Watch" if media == "anime" else "Watchlist"),
                        "sub": f"★ {r['average_score'] / 10:.1f}" if r.get("average_score") else "",
                        "progress": 0}
        return None

    def _progress(self, row: Dict) -> float:
        if (row.get("media_type") or "anime") == "tv":
            p = self.db.tv_progress(row["id"])
            return p["watched"] / p["aired"] if p["aired"] else 0
        total = row.get("total_episodes") or 0
        return self.db.get_watched_count(row["id"]) / total if total else 0

    # ── This week popover ─────────────────────────────────────────────────────

    def _show_popover(self, mini):
        from ui.home_popover import EpisodePopover
        old = getattr(self, "_popover", None)
        if old is not None:
            from PyQt6 import sip
            same = not sip.isdeleted(old) and old.item is mini.item
            if not sip.isdeleted(old):
                old.close_popover()
            if same:
                return                                  # clicking the same entry again closes it
        pop = EpisodePopover(mini.item, self.db, self)
        pop.open_details.connect(self.open_title.emit)
        pop.play_trailer.connect(self.play_trailer.emit)
        pop.closed.connect(lambda: setattr(self, "_popover", None))
        self._popover = pop
        pop.show_at(mini)
        if not getattr(self, "_pop_filter", False):
            self.scroll.viewport().installEventFilter(self)
            self.installEventFilter(self)
            self._pop_filter = True

    def eventFilter(self, obj, ev):
        """Close the popover on scroll or a click outside it."""
        from PyQt6.QtCore import QEvent
        pop = getattr(self, "_popover", None)
        if pop is not None:
            t = ev.type()
            if t == QEvent.Type.Wheel:
                pop.close_popover()
            elif t == QEvent.Type.MouseButtonPress:
                gp = ev.globalPosition().toPoint()
                if not pop.geometry().contains(self.mapFromGlobal(gp)):
                    # let a click on another entry reopen it there
                    QTimer.singleShot(0, lambda p=pop: p.isVisible() and p.close_popover()
                                      if getattr(self, "_popover", None) is p else None)
        return False

    def refresh_pantheon(self):
        """The Pantheon strip at the end of the stats row (hidden when empty)."""
        old = getattr(self, "_pantheon_strip", None)
        if old is not None:
            try:
                old.deleteLater()
            except RuntimeError:
                pass
            self._pantheon_strip = None
        try:
            from core.hall import Hall
            h = Hall(self.db)
            h.auto_pantheon()
            slots = h.pantheon()
        except Exception:
            return
        if not any(slots):
            return
        strip = _PantheonStrip(slots)
        strip.open_hall.connect(self.open_hall.emit)
        self.stats.addWidget(strip)
        self._pantheon_strip = strip

    def _mark(self, item: Dict):
        from core import up_next as un
        un.mark_next(self.db, item)
        from ui.toast import Toast
        Toast.show(self.window(), f"{item['title']}: {item['label'].split(' · ')[0]} watched.", kind="success")
        self.changed.emit(item["id"])
        self.load()

    # ── unified search ────────────────────────────────────────────────────────

    def focus_search(self):
        self.scroll.verticalScrollBar().setValue(0)
        self.search.setFocus()
        self.search.selectAll()

    def _run_search(self):
        q = self.search.text().strip()
        self.sections.setVisible(not q)
        self.results.setVisible(bool(q))
        self._clear(self.res_lay)
        if not q:
            return
        rows = self.find(self.db, q)
        self._last_results = rows
        for media, label in (("anime", "Miroku · Anime"), ("tv", "Kinema · TV shows"), ("movie", "Kinema · Movies")):
            hits = [r for r in rows if (r.get("media_type") or "anime") == media]
            if not hits:
                continue
            h = QLabel(f"{label}   {len(hits)}")
            h.setObjectName("homeSection")
            self.res_lay.addSpacing(10)
            self.res_lay.addWidget(h)
            for r in hits[:12]:
                sr = _SearchRow(r)
                sr.open.connect(self.open_title.emit)
                self.res_lay.addWidget(sr)
        if not rows:
            self.res_lay.addWidget(self._muted(f"Nothing called “{q}” in your library yet."))
        # suggestions you don't have yet (local catalogue: instant, partial words work)
        sugg = self.suggest(self.db, q)
        if sugg:
            h = QLabel(f"Not in your library yet   {len(sugg)}")
            h.setObjectName("homeSection")
            self.res_lay.addSpacing(10)
            self.res_lay.addWidget(h)
            for hit in sugg:
                sr = _SuggestRow(hit)
                sr.open.connect(self.open_pick.emit)
                self.res_lay.addWidget(sr)
        host = QWidget()
        online = QHBoxLayout(host)
        online.setContentsMargins(0, 14, 0, 0)
        online.setSpacing(8)
        for text, where in (("Find anime on AniList", "anime"), ("Find movies && shows on TMDB", "kinema")):
            b = QPushButton(text + "  →")
            b.setObjectName("secondaryBtn")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _=False, w=where: self.search_online.emit(w, self.search.text().strip()))
            online.addWidget(b)
        online.addStretch()
        self.res_lay.addWidget(host)

    @staticmethod
    def find(db, q: str) -> List[Dict]:
        out, seen = [], set()
        try:
            out += db.search_anime(q) or []
        except Exception:
            pass
        for m in ("tv", "movie"):
            out += db.search_titles(q, m) or []
        ql = q.lower()
        rows = []
        for r in out:
            if r["id"] in seen or (r.get("id") or 0) <= 0:
                continue
            seen.add(r["id"])
            rows.append(r)
        rows.sort(key=lambda r: (not any((r.get(k) or "").lower().startswith(ql)
                                          for k in ("english_title", "romaji_title")),
                                 (r.get("english_title") or r.get("romaji_title") or "").lower()))
        return rows

    @staticmethod
    def suggest(db, q: str, limit: int = 8) -> List[Dict]:
        """Popular titles matching what's typed that aren't in your library."""
        from core import catalog
        out = []
        for kind in ("anime", "tv", "movie"):
            for h in catalog.search(kind, q, limit=6):
                pid = h.get("provider_id")
                mine = (db.get_anime_by_anilist_id(pid) if kind == "anime"
                        else db.get_title_by_tmdb(kind, pid))
                if not mine:
                    out.append(dict(h, media_type=kind))
        return catalog.rank(out, q)[:limit]

    def _open_first(self):
        if self._last_results:
            self.open_title.emit(self._last_results[0]["id"])
