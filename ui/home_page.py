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
from PyQt6.QtGui import QColor, QCursor, QFont, QLinearGradient, QPainter, QPainterPath, QPixmap
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

class _Hero(QWidget, _Img):
    open = pyqtSignal(int)
    watched = pyqtSignal(dict)
    H = 330

    def __init__(self, parent=None):
        super().__init__(parent)
        self.item: Optional[Dict] = None
        self._pix = None
        self.setFixedHeight(self.H)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 30, 36, 28)
        lay.setSpacing(8)
        self.kicker = QLabel()
        self.kicker.setObjectName("heroKicker")
        lay.addWidget(self.kicker)
        lay.addStretch()
        self.title = QLabel()
        self.title.setObjectName("heroTitle")
        self.title.setWordWrap(True)
        self.next = QLabel()
        self.next.setObjectName("heroNext")
        self.blurb = QLabel()
        self.blurb.setObjectName("heroBlurb")
        self.blurb.setWordWrap(True)
        self.blurb.setMaximumWidth(560)
        for w in (self.title, self.next, self.blurb):
            lay.addWidget(w)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.btn_watched = QPushButton()
        self.btn_watched.setObjectName("heroPrimary")
        self.btn_open = QPushButton("Open details")
        self.btn_open.setObjectName("heroSecondary")
        for b in (self.btn_watched, self.btn_open):
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setMinimumHeight(40)
            row.addWidget(b)
        row.addStretch()
        lay.addSpacing(6)
        lay.addLayout(row)
        self.btn_watched.clicked.connect(lambda: self.item and self.watched.emit(self.item))
        self.btn_open.clicked.connect(lambda: self.item and self.open.emit(self.item["id"]))

    def set_item(self, item: Dict):
        self.item = item
        tag, color = LIB[item["media"]]
        self._color = color
        self.kicker.setText(("NEW EPISODE  ·  " if item.get("new") else "UP NEXT  ·  ") + tag)
        self.kicker.setStyleSheet(f"color:{color};")
        self.title.setText(item["title"])
        self.next.setText(f"{item['label']}   ·   {item['sub']}")
        desc = re.sub(r"<[^>]+>", "", item["row"].get("description") or "").strip()
        desc = re.sub(r"\s+", " ", desc)
        self.blurb.setText(desc if len(desc) < 190 else desc[:185].rsplit(" ", 1)[0] + "…")
        short = item["label"].split(" · ")[0]
        self.btn_watched.setText(f"✓  Watched {short}")
        self.btn_watched.setStyleSheet(
            f"QPushButton#heroPrimary{{background:{color};color:#0b0d12;}}")
        self._load_img(_img_url(item["row"], wide=True))

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
        if self.item:
            prog = max(0.02, min(1.0, self.item["progress"]))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 28))
            p.drawRect(QRectF(0, self.height() - 4, self.width(), 4))
            p.setBrush(QColor(self._color))
            p.drawRect(QRectF(0, self.height() - 4, self.width() * prog, 4))
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


class _ContinueCard(QWidget, _Img):
    """Art on top (16:9), text underneath - clean, nothing over the picture
    except the library tag and a hover Watched button."""
    open = pyqtSignal(int)
    watched = pyqtSignal(dict)
    W, IMG = 264, 148

    def __init__(self, item: Dict, parent=None):
        super().__init__(parent)
        self.item = item
        self._hover = False
        self.setFixedSize(self.W, self.IMG + 66)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn = QPushButton("✓", self)
        self.btn.setObjectName("cardTick")
        self.btn.setFixedSize(34, 34)
        self.btn.setToolTip(f"Mark {item['label'].split(' · ')[0]} watched")
        self.btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn.move(self.W - 44, self.IMG - 44)
        self.btn.clicked.connect(lambda: self.watched.emit(self.item))
        self.btn.setVisible(False)
        self._load_img(_img_url(item["row"], wide=True))

    def enterEvent(self, e):
        self._hover = True
        self.btn.setVisible(True)
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.btn.setVisible(False)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.open.emit(self.item["id"])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        tag, color = LIB[self.item["media"]]
        img = QRectF(0, 0, self.W, self.IMG)
        path = QPainterPath()
        path.addRoundedRect(img, 12, 12)
        p.save()
        p.setClipPath(path)
        self._draw_cover(p, img, 0.3)
        if self._hover:
            p.fillRect(img, QColor(0, 0, 0, 60))
        # progress along the bottom of the art
        p.setPen(Qt.PenStyle.NoPen)
        p.fillRect(QRectF(0, self.IMG - 4, self.W, 4), QColor(0, 0, 0, 150))
        p.fillRect(QRectF(0, self.IMG - 4, self.W * max(0.03, min(1, self.item["progress"])), 4), QColor(color))
        p.restore()
        p.setPen(QColor(255, 255, 255, 30) if not self._hover else QColor(color))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        x = 10
        x += _tag(p, x, 10, tag, color, QColor(8, 9, 14, 215)) + 6
        if self.item.get("new"):
            _tag(p, x, 10, "NEW", "#0b0d12", QColor("#f87171"))
        f = QFont(self.font())
        f.setPointSizeF(10)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#eef0f7"))
        p.drawText(QRectF(2, self.IMG + 8, self.W - 4, 20), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.item["title"], Qt.TextElideMode.ElideRight, self.W - 4))
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(QRectF(2, self.IMG + 29, self.W - 4, 16), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.item["label"], Qt.TextElideMode.ElideRight, self.W - 4))
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor("#7f87a3"))
        p.drawText(QRectF(2, self.IMG + 47, self.W - 4, 16), Qt.AlignmentFlag.AlignLeft, self.item["sub"])
        p.end()


# ── this week ─────────────────────────────────────────────────────────────────

class _MiniItem(QWidget, _Img):
    open = pyqtSignal(int)
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
            self.open.emit(self.item["id"])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        tag, color = LIB[self.item["media"]]
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 12))
            p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 8, 8)
        pr = QRectF(4, 4, self.PW, self.PH)
        path = QPainterPath()
        path.addRoundedRect(pr, 6, 6)
        p.save()
        p.setClipPath(path)
        self._draw_cover(p, pr)
        p.restore()
        x = self.PW + 12
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
        self.setMinimumWidth(150)
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

class HomePage(QWidget):
    open_title = pyqtSignal(int)
    changed = pyqtSignal(int)
    search_online = pyqtSignal(str, str)

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
        self.hero = _Hero()
        self.hero.open.connect(self.open_title.emit)
        self.hero.watched.connect(self._mark)
        sl.addWidget(self.hero)
        self.stats = QHBoxLayout()
        self.stats.setSpacing(12)
        sl.addSpacing(14)
        sl.addLayout(self.stats)
        self.hero_empty = QLabel("Nothing in progress. Find something new in Discover, or press Ctrl+N to add it.")
        self.hero_empty.setObjectName("homeEmpty")
        self.hero_empty.setWordWrap(True)
        sl.addWidget(self.hero_empty)

        self.cw_head = self._head("Continue watching", sl)
        self.cw_rail = _Rail(_ContinueCard.IMG + 70)
        sl.addWidget(self.cw_rail)

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
            return un.continue_watching(self.db), un.coming_up(self.db), un.ready_to_watch(self.db)

        w = Worker(work)
        w.signals.result.connect(self._render)
        run_worker(w, PRIORITY_INTERACTIVE)

    def _render(self, data):
        from PyQt6 import sip
        if sip.isdeleted(self):
            return
        cw, up, ready = data
        # spotlight + stats
        self.hero.setVisible(bool(cw))
        self.hero_empty.setVisible(not cw)
        if cw:
            self.hero.set_item(cw[0])
        self._clear(self.stats)
        now = datetime.now().timestamp()
        new = sum(1 for c in cw if c["new"])
        week = [u for u in up if u["when"] <= now + 7 * 86400]
        for v, label, color in ((len(cw), "in progress", "#f0f1f6"), (new, "new episodes", "#f87171"),
                                (len(week), "airing this week", "#8b7bff"),
                                (len(ready), "movies in HD", "#fbbf24")):
            self.stats.addWidget(_Stat(str(v), label, color))
        self.stats.addStretch()

        # continue rail (everything after the spotlight)
        self.cw_rail.clear()
        rest = cw[1:]
        for item in rest:
            c = _ContinueCard(item)
            c.open.connect(self.open_title.emit)
            c.watched.connect(self._mark)
            self.cw_rail.add(c)
        self.cw_head.setVisible(bool(rest))
        self.cw_rail.setVisible(bool(rest))

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
            mi.open.connect(self.open_title.emit)
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
        host = QWidget()
        online = QHBoxLayout(host)
        online.setContentsMargins(0, 14, 0, 0)
        online.setSpacing(8)
        for text, where in (("Find anime on AniList", "anime"), ("Find movies & shows on TMDB", "kinema")):
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

    def _open_first(self):
        if self._last_results:
            self.open_title.emit(self._last_results[0]["id"])
