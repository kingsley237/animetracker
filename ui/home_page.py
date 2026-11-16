"""
Raikō - Home: one place for everything you watch.

  Search everything (Ctrl+K)   your anime, shows and movies in one box;
                               nothing in your library? find it on AniList /
                               TMDB in the matching Discover
  Continue watching            the next episode of every anime and show
                               you're watching, new episodes first; one click
                               marks it watched
  Coming up                    the next 14 days, grouped by day: episodes,
                               premieres, movies reaching cinemas or HD
  Ready to watch               Watchlist movies out in HD
"""
from __future__ import annotations

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


class _Rail(QScrollArea):
    """Horizontal row of cards; mouse wheel scrolls sideways."""

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
        self.row.setSpacing(14)
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


class _ContinueCard(QWidget):
    """Wide art card: library tag, title, next episode, progress, Watched."""
    open = pyqtSignal(int)
    watched = pyqtSignal(dict)
    W, H = 300, 200

    def __init__(self, item: Dict, parent=None):
        super().__init__(parent)
        self.item = item
        self._pix: Optional[QPixmap] = None
        self._hover = False
        self.setFixedSize(self.W, self.H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn = QPushButton("✓  Watched", self)
        self.btn.setObjectName("homeWatchedBtn")
        self.btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn.setToolTip(f"Mark {item['label'].split(' · ')[0]} watched")
        self.btn.adjustSize()
        self.btn.move(self.W - self.btn.width() - 12, 12)
        self.btn.clicked.connect(lambda: self.watched.emit(self.item))
        url = _img_url(item["row"], wide=True)
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
        path.addRoundedRect(r, 14, 14)
        p.setClipPath(path)
        tag, color = LIB[self.item["media"]]
        if self._pix and not self._pix.isNull():
            sc = self._pix.scaled(self.W, self.H, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(0, 0, sc, (sc.width() - self.W) // 2, (sc.height() - self.H) // 3, self.W, self.H)
        else:
            p.fillRect(r, QColor("#161a2a"))
        g = QLinearGradient(0, self.H * 0.25, 0, self.H)
        g.setColorAt(0, QColor(8, 9, 14, 30))
        g.setColorAt(0.55, QColor(8, 9, 14, 200))
        g.setColorAt(1, QColor(8, 9, 14, 250))
        p.fillRect(r, g)
        if self._hover:
            p.fillRect(r, QColor(255, 255, 255, 10))
        # library tag (+ NEW)
        f = QFont(self.font())
        f.setPointSizeF(7)
        f.setBold(True)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        p.setFont(f)
        x = 14
        for text, fg, bg in ([(tag, color, QColor(8, 9, 14, 210))] +
                             ([("NEW", "#0b0d12", QColor("#f87171"))] if self.item.get("new") else [])):
            tw = p.fontMetrics().horizontalAdvance(text) + 16
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(x, 14, tw, 20), 6, 6)
            p.setPen(QColor(fg))
            p.drawText(QRectF(x, 14, tw, 20), Qt.AlignmentFlag.AlignCenter, text)
            x += tw + 6
        # text
        f = QFont(self.font())
        f.setPointSizeF(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#f4f5fa"))
        p.drawText(QRectF(14, self.H - 82, self.W - 28, 22), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.item["title"], Qt.TextElideMode.ElideRight, self.W - 28))
        f.setPointSizeF(9)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(QRectF(14, self.H - 58, self.W - 28, 18), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.item["label"], Qt.TextElideMode.ElideRight, self.W - 28))
        f.setBold(False)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor("#9da5c0"))
        p.drawText(QRectF(14, self.H - 38, self.W - 28, 16), Qt.AlignmentFlag.AlignLeft, self.item["sub"])
        # progress
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(QRectF(14, self.H - 14, self.W - 28, 4), 2, 2)
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(14, self.H - 14, (self.W - 28) * max(0.02, min(1, self.item["progress"])), 4), 2, 2)
        p.end()


class _PosterCard(QWidget):
    open = pyqtSignal(int)
    W, H = 128, 192

    def __init__(self, item: Dict, parent=None):
        super().__init__(parent)
        self.item = item
        self._pix: Optional[QPixmap] = None
        self.setFixedSize(self.W, self.H + 40)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        url = _img_url(item["row"], wide=False)
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
        if self._pix and not self._pix.isNull():
            sc = self._pix.scaled(self.W, self.H, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(0, 0, sc, (sc.width() - self.W) // 2, (sc.height() - self.H) // 2, self.W, self.H)
        else:
            p.fillRect(r, QColor("#161a2a"))
        p.restore()
        p.setPen(QColor(LIB[self.item["media"]][1]))
        p.drawPath(path)
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#e8eaf2"))
        p.drawText(QRectF(0, self.H + 4, self.W, 18), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.item["title"], Qt.TextElideMode.ElideRight, self.W))
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor("#7b84a3"))
        p.drawText(QRectF(0, self.H + 21, self.W, 16), Qt.AlignmentFlag.AlignLeft, self.item.get("label") or "")
        p.end()


class _UpcomingRow(QWidget):
    open = pyqtSignal(int)

    def __init__(self, item: Dict, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("homeUpRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 8, 14, 8)
        h.setSpacing(12)
        tag, color = LIB[item["media"]]
        bar = QWidget()
        bar.setFixedSize(4, 34)
        bar.setStyleSheet(f"background:{color};border-radius:2px;")
        h.addWidget(bar)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(item["title"])
        t.setObjectName("homeUpTitle")
        s = QLabel(item["label"])
        s.setObjectName("homeUpLabel")
        s.setStyleSheet(f"color:{color};")
        col.addWidget(t)
        col.addWidget(s)
        h.addLayout(col, 1)
        when = datetime.fromtimestamp(item["when"])
        tl = QLabel(when.strftime("%H:%M") if item.get("exact") else tag.title().replace("Kinema · ", ""))
        tl.setObjectName("homeUpWhen")
        h.addWidget(tl)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.open.emit(self.item["id"])


class _SearchRow(QWidget):
    open = pyqtSignal(int)

    def __init__(self, row: Dict, parent=None):
        super().__init__(parent)
        self.lib_id = row["id"]
        media = row.get("media_type") or "anime"
        self.setObjectName("homeUpRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 7, 14, 7)
        h.setSpacing(12)
        tag, color = LIB[media]
        bar = QWidget()
        bar.setFixedSize(4, 30)
        bar.setStyleSheet(f"background:{color};border-radius:2px;")
        h.addWidget(bar)
        t = QLabel(row.get("english_title") or row.get("romaji_title") or "")
        t.setObjectName("homeUpTitle")
        h.addWidget(t, 1)
        ws = {"watching": "Watching", "planned": "Plan to Watch" if media == "anime" else "Watchlist",
              "completed": "Completed" if media != "movie" else "Watched",
              "dropped": "Dropped"}.get(row.get("watch_status"), "")
        s = QLabel(ws)
        s.setObjectName("homeUpWhen")
        h.addWidget(s)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.open.emit(self.lib_id)


class HomePage(QWidget):
    open_title = pyqtSignal(int)
    changed = pyqtSignal(int)                    # a title's progress changed here
    search_online = pyqtSignal(str, str)         # "anime" | "kinema", query

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
        self.lay.setContentsMargins(32, 26, 32, 30)
        self.lay.setSpacing(14)
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll)

        self.hello = QLabel()
        self.hello.setObjectName("pageTitle")
        self.lay.addWidget(self.hello)
        self.summary = QLabel()
        self.summary.setObjectName("homeSummary")
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.lay.addWidget(self.summary)

        self.search = QLineEdit()
        self.search.setObjectName("searchBar")
        self.search.setPlaceholderText("Search everything you track: anime, shows, movies…   Ctrl+K")
        self.search.setFixedHeight(42)
        self.search.setClearButtonEnabled(True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._run_search)
        self.search.textChanged.connect(lambda _t: self._timer.start(200))
        self.search.returnPressed.connect(self._open_first)
        self.lay.addWidget(self.search)

        # search results (replace the sections while typing)
        self.results = QWidget()
        self.res_lay = QVBoxLayout(self.results)
        self.res_lay.setContentsMargins(0, 4, 0, 0)
        self.res_lay.setSpacing(4)
        self.results.setVisible(False)
        self.lay.addWidget(self.results)

        self.sections = QWidget()
        sl = QVBoxLayout(self.sections)
        sl.setContentsMargins(0, 6, 0, 0)
        sl.setSpacing(12)
        self.cw_head = self._head("Continue watching")
        sl.addWidget(self.cw_head)
        self.cw_rail = _Rail(_ContinueCard.H + 16)
        sl.addWidget(self.cw_rail)
        self.cw_empty = self._muted("Nothing waiting. Start something from Discover, or mark where you are in a show.")
        sl.addWidget(self.cw_empty)

        self.up_head = self._head("Coming up")
        sl.addWidget(self.up_head)
        self.up_host = QWidget()
        self.up_lay = QVBoxLayout(self.up_host)
        self.up_lay.setContentsMargins(0, 0, 0, 0)
        self.up_lay.setSpacing(4)
        sl.addWidget(self.up_host)

        self.rd_head = self._head("Ready to watch")
        sl.addWidget(self.rd_head)
        self.rd_rail = _Rail(_PosterCard.H + 56)
        sl.addWidget(self.rd_rail)
        sl.addStretch()
        self.lay.addWidget(self.sections)
        self.lay.addStretch()
        self._last_results: List[Dict] = []

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _head(text: str) -> QLabel:
        l = QLabel(text.upper())
        l.setObjectName("homeSection")
        return l

    @staticmethod
    def _muted(text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("plannedReleaseHint")
        l.setWordWrap(True)
        return l

    # ── load ──────────────────────────────────────────────────────────────────

    def load(self):
        h = datetime.now().hour
        self.hello.setText("Good morning" if 5 <= h < 12 else "Good afternoon" if h < 18 else "Good evening")

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
        new = sum(1 for c in cw if c["new"])
        week = sum(1 for u in up if u["when"] <= datetime.now().timestamp() + 7 * 86400)
        bits = [f"<b style='color:#f0f1f6'>{len(cw)}</b> to continue"]
        if new:
            bits.append(f"<b style='color:#f87171'>{new}</b> new episode{'s' if new != 1 else ''}")
        bits.append(f"<b style='color:#f0f1f6'>{week}</b> coming this week")
        if ready:
            bits.append(f"<b style='color:#fbbf24'>{len(ready)}</b> movie{'s' if len(ready) != 1 else ''} ready")
        self.summary.setText("  ·  ".join(bits))

        self.cw_rail.clear()
        for item in cw:
            c = _ContinueCard(item)
            c.open.connect(self.open_title.emit)
            c.watched.connect(self._mark)
            self.cw_rail.add(c)
        self.cw_rail.setVisible(bool(cw))
        self.cw_empty.setVisible(not cw)

        while self.up_lay.count():
            it = self.up_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        today = datetime.now().date()
        last_day = None
        for item in up:
            d = datetime.fromtimestamp(item["when"]).date()
            if d != last_day:
                last_day = d
                lbl = ("Today" if d == today else "Tomorrow" if d == today + timedelta(days=1)
                       else d.strftime("%A, %b ") + str(d.day))
                day = QLabel(lbl)
                day.setObjectName("homeDay")
                self.up_lay.addWidget(day)
            row = _UpcomingRow(item)
            row.open.connect(self.open_title.emit)
            self.up_lay.addWidget(row)
        if not up:
            self.up_lay.addWidget(self._muted("Nothing scheduled in the next two weeks."))

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
        while self.res_lay.count():
            it = self.res_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if not q:
            return
        rows = self.find(self.db, q)
        self._last_results = rows
        groups = [("anime", "Miroku · Anime"), ("tv", "Kinema · TV shows"), ("movie", "Kinema · Movies")]
        for media, label in groups:
            hits = [r for r in rows if (r.get("media_type") or "anime") == media]
            if not hits:
                continue
            self.res_lay.addWidget(self._head(f"{label}  ·  {len(hits)}"))
            for r in hits[:12]:
                sr = _SearchRow(r)
                sr.open.connect(self.open_title.emit)
                self.res_lay.addWidget(sr)
        if not rows:
            self.res_lay.addWidget(self._muted(f"Nothing called “{q}” in your library."))
        online = QHBoxLayout()
        online.setSpacing(8)
        host = QWidget()
        host.setLayout(online)
        for text, where in (("Find anime on AniList", "anime"), ("Find movies & shows on TMDB", "kinema")):
            b = QPushButton(f"🔎  {text}")
            b.setObjectName("secondaryBtn")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _=False, w=where: self.search_online.emit(w, self.search.text().strip()))
            online.addWidget(b)
        online.addStretch()
        self.res_lay.addSpacing(8)
        self.res_lay.addWidget(host)

    @staticmethod
    def find(db, q: str) -> List[Dict]:
        """Your library, all three types; titles starting with the query first."""
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
