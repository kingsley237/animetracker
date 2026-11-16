"""
Kinema - browse movies and TV shows and add them to your library.

One browser, two homes:
  - the "Add a movie" / "Add a show" dialog (sidebar button / Ctrl+N)
  - the Kinema Discover page (with a Movies | TV shows switch)

TV: add to Watchlist, "I'm watching it" (once it has aired) or "I've
finished it" (marks every aired episode watched).

Lists: For you (recommendations with a reason), Coming soon (most
anticipated), Trending, Just out in HD, In cinemas, Top rated. Each can be
filtered by genre and sorted. Searching TMDB overrides the list while you
type. A preview shows backdrop, runtime, genres, plot, where it stands, and
two actions: add to Watchlist, or log it as watched (only once it's out).
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from workers.workers import PRIORITY_INTERACTIVE, ImageWorker, Worker, run_worker

ACCENT = "#fbbf24"   # Kinema movies accent
ACCENTS = {"movie": "#fbbf24", "tv": "#38bdf8", "anime": "#8b7bff"}


def _cat(kind: str):
    """The list/recommendation module for a library: AniList for anime,
    TMDB for movies and TV. Both expose sources/genres/load_source/apply."""
    if kind == "anime":
        from core import miroku_discover as m
    else:
        from core import kinema_discover as m
    return m


def _in_library(db, kind: str, pid) -> Optional[Dict]:
    if kind == "anime":
        return db.get_anime_by_anilist_id(pid)
    return db.get_title_by_tmdb(kind, pid)


def _nice_date(s: str) -> str:
    try:
        d = datetime.strptime((s or "")[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    return d.strftime("%b ") + f"{d.day}, {d.year}"


class _PosterTile(QWidget):
    clicked = pyqtSignal(dict)
    W, H = 132, 198

    def __init__(self, hit: Dict, in_library: bool, parent=None):
        super().__init__(parent)
        self.hit = hit
        self._pix: Optional[QPixmap] = None
        self._sel = False
        self._hover = False
        self._in_lib = in_library
        self.setFixedSize(self.W, self.H + 44)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(hit.get("reason") or hit.get("title") or "")
        if hit.get("poster_url"):
            w = ImageWorker(hit["poster_url"], hit.get("provider_id"))
            w.signals.result.connect(self._on_img)
            run_worker(w)

    def _on_img(self, result):
        try:
            _id, _s, path = result
            if path:
                self._pix = QPixmap(str(path))
                self.update()
        except RuntimeError:
            pass

    def set_selected(self, on: bool):
        self._sel = on
        self.update()

    def set_in_library(self, on: bool):
        self._in_lib = on
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.hit)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(1, 1, self.W - 2, self.H - 2)
        path = QPainterPath()
        path.addRoundedRect(r, 9, 9)
        p.save()
        p.setClipPath(path)
        if self._pix and not self._pix.isNull():
            sc = self._pix.scaled(self.W, self.H, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(0, 0, sc, (sc.width() - self.W) // 2, (sc.height() - self.H) // 2, self.W, self.H)
        else:
            p.fillRect(r, QColor("#1a1d28"))
            p.setPen(QColor("#4a5070"))
            p.drawText(r.adjusted(8, 8, -8, -8), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       self.hit.get("title") or "")
        if self._hover and not self._sel:
            p.fillRect(r, QColor(255, 255, 255, 18))
        p.restore()
        accent = ACCENTS.get(self.hit.get("media_type"), ACCENT)
        p.setPen(QColor(accent) if self._sel else QColor(255, 255, 255, 30))
        p.drawPath(path)
        if self._in_lib:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(8, 10, 16, 220))
            p.drawRoundedRect(QRectF(6, 6, 70, 18), 5, 5)
            f = QFont(self.font())
            f.setPointSizeF(7)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#34d399"))
            p.drawText(QRectF(6, 6, 70, 18), Qt.AlignmentFlag.AlignCenter, "IN LIBRARY")
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#e2e4ec"))
        title = p.fontMetrics().elidedText(self.hit.get("title") or "", Qt.TextElideMode.ElideRight, self.W)
        p.drawText(QRectF(0, self.H + 4, self.W, 18), Qt.AlignmentFlag.AlignLeft, title)
        f.setBold(False)
        f.setPointSizeF(8)
        p.setFont(f)
        rd = self.hit.get("release_date") or ""
        if rd and rd > datetime.now().strftime("%Y-%m-%d"):
            p.setPen(QColor(accent))
            sub = ("Premieres " if self.hit.get("media_type") in ("tv", "anime") else "Out ") + _nice_date(rd)
        else:
            p.setPen(QColor("#7b84a3"))
            sub = " · ".join(x for x in (str(self.hit.get("year") or ""),
                                         f"★ {self.hit['score'] / 10:.1f}" if self.hit.get("score") else "") if x)
        p.drawText(QRectF(0, self.H + 22, self.W, 18), Qt.AlignmentFlag.AlignLeft, sub)
        p.end()


class _TrailerThumb(QWidget):
    """16:9 thumbnail of the official trailer with a play button."""
    play = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(168)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._pix: Optional[QPixmap] = None
        self._title = ""
        self._hover = False
        self._url = ""

    def load(self, url: str, title: str):
        self._title = title
        self._pix = None
        self._url = url
        self.update()
        if url:
            w = ImageWorker(url, url)
            w.signals.result.connect(self._on_img)
            run_worker(w, PRIORITY_INTERACTIVE)

    def _on_img(self, result):
        try:
            key, _s, path = result
            if path and key == self._url:
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
            self.play.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.setClipPath(path)
        if self._pix and not self._pix.isNull():
            sc = self._pix.scaled(self.width(), self.height(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(0, 0, sc, (sc.width() - self.width()) // 2, (sc.height() - self.height()) // 2,
                         self.width(), self.height())
        else:
            p.fillRect(r, QColor("#151827"))
        p.fillRect(r, QColor(0, 0, 0, 70 if self._hover else 110))
        c = r.center()
        rad = 26 if self._hover else 24
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 235))
        p.drawEllipse(c, rad, rad)
        tri = QPainterPath()
        tri.moveTo(c.x() - 7, c.y() - 11)
        tri.lineTo(c.x() - 7, c.y() + 11)
        tri.lineTo(c.x() + 12, c.y())
        tri.closeSubpath()
        p.setBrush(QColor("#0b0d12"))
        p.drawPath(tri)
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#f0f1f6"))
        p.drawText(r.adjusted(12, 0, -12, -10), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self._title, Qt.TextElideMode.ElideRight, self.width() - 24))
        p.end()


class _SkeletonTile(QWidget):
    """Placeholder poster with a moving shimmer while a list loads."""
    W, H = _PosterTile.W, _PosterTile.H

    def __init__(self, phase: float, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.W, self.H + 44)
        self._t = phase
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(40)

    def _step(self):
        self._t = (self._t + 0.025) % 1.6
        self.update()

    def paintEvent(self, _):
        from PyQt6.QtGui import QLinearGradient
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        base, hi = QColor("#151826"), QColor("#232842")
        x = (self._t - 0.3) * self.W * 1.6
        g = QLinearGradient(x, 0, x + self.W * 0.6, self.H)
        g.setColorAt(0, base)
        g.setColorAt(0.5, hi)
        g.setColorAt(1, base)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(QRectF(1, 1, self.W - 2, self.H - 2), 9, 9)
        p.setBrush(base)
        p.drawRoundedRect(QRectF(0, self.H + 8, self.W * 0.8, 10), 4, 4)
        p.drawRoundedRect(QRectF(0, self.H + 26, self.W * 0.45, 9), 4, 4)
        p.end()


class MovieBrowser(QWidget):
    added = pyqtSignal(int, str)        # library id, title
    kind_changed = pyqtSignal(str)      # "movie" | "tv"

    def __init__(self, db, heading: str = "", start_source: str = "for_you",
                 close_on_add: bool = False, kind: str = "movie",
                 kind_switch: bool = False, parent=None):
        super().__init__(parent)
        self.db = db
        self.kind = kind
        self._kind_switch = kind_switch
        self._heading = heading
        self._close_on_add = close_on_add
        self._tiles: List[_PosterTile] = []
        self._selected: Optional[Dict] = None
        self._token = 0
        self._source = start_source
        self._cache: Dict[str, List[Dict]] = {}
        self._raw: List[Dict] = []
        self._build()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._search)
        # Bound methods (not lambdas): if this widget is destroyed before the
        # deferred call runs, Qt drops it instead of calling a dead object.
        self._start_source = start_source
        QTimer.singleShot(0, self._load_genres)
        QTimer.singleShot(0, self._initial_load)

    def _initial_load(self):
        self.select_source(self._start_source)

    def _gone(self) -> bool:
        """True once this browser's widgets have been destroyed (e.g. the
        dialog was closed while a list was still loading). Late results are
        dropped instead of touching dead widgets, which would abort the app."""
        from PyQt6 import sip
        return sip.isdeleted(self) or sip.isdeleted(self.grid_host)

    # ── layout ────────────────────────────────────────────────────────────────

    def _build(self):
        from core.kinema_discover import SORTS
        from ui.layout_helpers import FitWidthScroll, FlowLayout
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(24, 22, 16, 18)
        lv.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(12)
        if self._heading:
            self.title_lbl = QLabel(self._heading)
            self.title_lbl.setObjectName("pageTitle")
            head.addWidget(self.title_lbl)
        head.addStretch()
        self._kind_btns: Dict[str, QPushButton] = {}
        if self._kind_switch:
            for k, label in (("movie", "Movies"), ("tv", "TV shows")):
                b = QPushButton(label)
                b.setObjectName("kindSwitch")
                b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                b.clicked.connect(lambda _=False, k=k: self.set_kind(k))
                head.addWidget(b)
                self._kind_btns[k] = b
        if self._heading or self._kind_switch:
            lv.addLayout(head)
        self.search = QLineEdit()
        self.search.setObjectName("searchBar")
        self.search.setFixedHeight(40)
        self.search.textChanged.connect(lambda _t: self._timer.start(350))
        lv.addWidget(self.search)

        # list chips
        chips_host = QWidget()
        self._chip_flow = FlowLayout(chips_host, h_spacing=6, v_spacing=6)
        self._chips: Dict[str, QPushButton] = {}
        lv.addWidget(chips_host)

        # genre + sort
        tools = QHBoxLayout()
        tools.setSpacing(10)
        self.section = QLabel("")
        self.section.setObjectName("detailSectionLabel")
        tools.addWidget(self.section, 1)
        g_lbl = QLabel("Genre")
        g_lbl.setObjectName("plannedFactKey")
        tools.addWidget(g_lbl)
        self.genre = QComboBox()
        self.genre.addItem("All genres", 0)
        self.genre.setFixedWidth(150)
        self.genre.currentIndexChanged.connect(lambda _i: self._render())
        tools.addWidget(self.genre)
        s_lbl = QLabel("Sort")
        s_lbl.setObjectName("plannedFactKey")
        tools.addWidget(s_lbl)
        self.sort = QComboBox()
        self.sort.addItem("Best match", "default")
        for key, label in SORTS:
            self.sort.addItem(label, key)
        self.sort.setFixedWidth(140)
        self.sort.currentIndexChanged.connect(lambda _i: self._render())
        tools.addWidget(self.sort)
        lv.addLayout(tools)

        self.scroll = FitWidthScroll()
        self.grid_host = QWidget()
        self.grid = FlowLayout(self.grid_host, h_spacing=14, v_spacing=16)
        self.scroll.setWidget(self.grid_host)
        lv.addWidget(self.scroll, 1)
        self.status = QLabel("")
        self.status.setObjectName("plannedReleaseHint")
        self.status.setWordWrap(True)
        lv.addWidget(self.status)
        root.addWidget(left, 1)

        # preview pane
        self.preview = QFrame()
        self.preview.setObjectName("kinemaPreview")
        self.preview.setFixedWidth(340)
        self.preview.setStyleSheet(
            "QFrame#kinemaPreview{background:#0a0c10;border-left:1px solid #1a1d28;}")
        pv = QVBoxLayout(self.preview)
        pv.setContentsMargins(0, 0, 0, 18)
        pv.setSpacing(10)
        self.p_backdrop = QLabel()
        self.p_backdrop.setFixedHeight(190)
        self.p_backdrop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.p_backdrop.setStyleSheet("background:#151827;")
        pv.addWidget(self.p_backdrop)
        from ui.layout_helpers import FitWidthScroll as _Scroll
        self.p_scroll = _Scroll()
        info = QWidget()
        info_l = QVBoxLayout(info)
        info_l.setContentsMargins(20, 6, 20, 6)
        info_l.setSpacing(8)
        self.p_scroll.setWidget(info)
        body = QVBoxLayout()
        body.setContentsMargins(20, 6, 20, 0)
        body.setSpacing(8)
        self.p_reason = QLabel("")
        self.p_reason.setObjectName("browserReason")
        self.p_reason.setWordWrap(True)
        self.p_title = QLabel("Pick a movie")
        self.p_title.setObjectName("spotlightTitle")
        self.p_title.setWordWrap(True)
        self.p_meta = QLabel("Browse the lists or search on the left.")
        self.p_meta.setObjectName("spotlightMeta")
        self.p_meta.setWordWrap(True)
        self.p_overview = QLabel("")
        self.p_overview.setObjectName("spotlightSynopsis")
        self.p_overview.setWordWrap(True)
        self.p_overview.setAlignment(Qt.AlignmentFlag.AlignTop)
        for w in (self.p_reason, self.p_title, self.p_meta, self.p_overview):
            info_l.addWidget(w)
        self.p_reason.setVisible(False)
        # the official trailer (one) and the cast / characters
        self.p_trailer_lbl = QLabel("OFFICIAL TRAILER")
        self.p_trailer_lbl.setObjectName("plannedFactKey")
        self.p_trailer = _TrailerThumb()
        self.p_trailer.play.connect(self._play_trailer)
        self.p_cast_lbl = QLabel("CAST")
        self.p_cast_lbl.setObjectName("plannedFactKey")
        self.p_cast_host = QWidget()
        from PyQt6.QtWidgets import QGridLayout
        self.p_cast = QGridLayout(self.p_cast_host)
        self.p_cast.setContentsMargins(0, 0, 0, 0)
        self.p_cast.setHorizontalSpacing(4)
        self.p_cast.setVerticalSpacing(8)
        for w in (self.p_trailer_lbl, self.p_trailer, self.p_cast_lbl, self.p_cast_host):
            info_l.addWidget(w)
            w.setVisible(False)
        info_l.addStretch()
        pv.addWidget(self.p_scroll, 1)
        self.btn_watchlist = QPushButton("＋  Add to Watchlist")
        self.btn_watchlist.setObjectName("primaryBtn")
        self.btn_watching = QPushButton("▶  I'm watching it")
        self.btn_watching.setObjectName("secondaryBtn")
        self.btn_watched = QPushButton("✓  I've watched it")
        self.btn_watched.setObjectName("secondaryBtn")
        for b, st in ((self.btn_watchlist, "planned"), (self.btn_watching, "watching"),
                      (self.btn_watched, "completed")):
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setMinimumHeight(38)
            b.setEnabled(False)
            b.clicked.connect(lambda _=False, st=st: self._add(st))
            body.addWidget(b)
        self.p_note = QLabel("")
        self.p_note.setObjectName("plannedReleaseHint")
        self.p_note.setWordWrap(True)
        body.addWidget(self.p_note)
        pv.addLayout(body)
        root.addWidget(self.preview)
        self._apply_kind()

    # ── movies / TV ───────────────────────────────────────────────────────────

    def _apply_kind(self):
        sources = _cat(self.kind).sources
        tv = self.kind == "tv"
        anime = self.kind == "anime"
        self.search.setPlaceholderText("Search any anime: title, studio, season…" if anime else
                                       "Search any show: title, creator…" if tv
                                       else "Search any movie: title, franchise…")
        self._chip_flow.clear()
        self._chips = {}
        for key, label in sources(self.kind):
            b = QPushButton(label)
            b.setObjectName("filterPill")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _=False, k=key: self.select_source(k))
            self._chip_flow.addWidget(b)
            self._chips[key] = b
        self.btn_watching.setVisible(tv or anime)
        self.btn_watchlist.setText("＋  Plan to Watch" if anime else "＋  Add to Watchlist")
        self.btn_watched.setText("✓  I've finished it" if (tv or anime) else "✓  I've watched it")
        self.p_title.setText("Pick an anime" if anime else "Pick a show" if tv else "Pick a movie")
        self.p_reason.setProperty("kind", self.kind)
        self.p_reason.style().unpolish(self.p_reason)
        self.p_reason.style().polish(self.p_reason)
        for k, b in self._kind_btns.items():
            b.setProperty("active", "true" if k == self.kind else "false")
            b.style().unpolish(b)
            b.style().polish(b)
        while self.genre.count() > 1:
            self.genre.removeItem(1)

    def set_kind(self, kind: str):
        if kind == self.kind:
            return
        self.kind = kind
        self._selected = None
        self._raw = []
        self.grid.clear()
        self._tiles = []
        for b in (self.btn_watchlist, self.btn_watching, self.btn_watched):
            b.setEnabled(False)
        self.p_reason.setVisible(False)
        self.p_meta.setText("Browse the lists or search on the left.")
        self.p_overview.setText("")
        self.p_note.setText("")
        self.p_backdrop.clear()
        self._apply_kind()
        self._load_genres()
        valid = [k for k, _l in _cat(kind).sources(kind)]
        self.select_source(self._source if self._source in valid else "for_you")
        self.kind_changed.emit(kind)

    # ── lists ─────────────────────────────────────────────────────────────────

    def _load_genres(self):
        kind = self.kind

        def work():
            return _cat(kind).genres(kind)

        def done(gs):
            if self._gone() or kind != self.kind:
                return
            for g in gs or []:
                self.genre.addItem(g["name"], g["id"])

        w = Worker(work)
        w.signals.result.connect(done)
        run_worker(w, PRIORITY_INTERACTIVE)

    def select_source(self, key: str):
        sources = _cat(self.kind).sources
        self._source = key
        kind = self.kind
        ck = f"{kind}:{key}"
        if self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        for k, b in self._chips.items():
            b.setProperty("active", "true" if k == key else "false")
            b.style().unpolish(b)
            b.style().polish(b)
        self.section.setText(dict(sources(kind)).get(key, "").upper())
        if ck in self._cache:
            self._show(self._cache[ck], self._next_token())
            return
        self._show_loading(({"tv": "Finding shows for you…", "anime": "Finding anime for you…"}
                             .get(kind, "Finding films for you…"))
                            if key == "for_you" else f"Loading {dict(sources(kind)).get(key, '')}…")
        tok = self._next_token()

        def work():
            return _cat(kind).load_source(key, self.db, kind=kind)

        def done(hits, t=tok, k=ck):
            if self._gone():
                return
            self._cache[k] = hits or []
            self._show(self._cache[k], t)

        w = Worker(work)
        w.signals.result.connect(done)
        run_worker(w, PRIORITY_INTERACTIVE)

    def refresh(self):
        """Drop cached lists (e.g. For you after the library changed)."""
        self._cache.pop(f"{self.kind}:for_you", None)
        if self._source == "for_you" and not self.search.text():
            self.select_source("for_you")

    def _search(self):
        q = self.search.text().strip()
        if not q:
            self.select_source(self._source)
            return
        for b in self._chips.values():
            b.setProperty("active", "false")
            b.style().unpolish(b)
            b.style().polish(b)
        self.section.setText(f"RESULTS FOR “{q.upper()}”")
        self._show_loading(f"Searching for “{q}”…")
        tok = self._next_token()
        kind = self.kind

        def work():
            from core.providers import get_provider
            if kind == "anime":
                from core.miroku_discover import _hits
                from core.api import search_anime
                return _hits(search_anime(q, per_page=30) or [])
            hits = get_provider(kind).search(q)
            for h in hits:
                raw = h.get("raw") or {}
                h["release_date"] = raw.get("release_date") or raw.get("first_air_date") or ""
                h["popularity"] = raw.get("popularity") or 0
                h["genre_ids"] = raw.get("genre_ids") or []
            return hits

        w = Worker(work)
        w.signals.result.connect(lambda hits, t=tok: self._show(hits, t))
        run_worker(w, PRIORITY_INTERACTIVE)

    def _show_loading(self, text: str):
        """Immediate feedback: the old list goes, shimmering placeholders and
        a status line take its place until the new list arrives."""
        self.grid.clear()
        self._tiles = []
        for i in range(12):
            self.grid.addWidget(_SkeletonTile(i * 0.12))
        self.status.setText(text)
        self.scroll.verticalScrollBar().setValue(0)

    def _next_token(self) -> int:
        self._token += 1
        return self._token

    def _show(self, hits: List[Dict], token: int):
        if self._gone() or token != self._token:
            return                      # an older request finished late
        self._raw = hits or []
        self._render()

    def _render(self):
        from core import tmdb
        apply = _cat(self.kind).apply
        self.grid.clear()
        self._tiles = []
        hits = apply(self._raw, self.genre.currentData() or 0, self.sort.currentData() or "default",
                     "" if self.search.text() else self._source)
        if not hits:
            if self.kind != "anime" and not tmdb.has_credentials():
                self.status.setText("TV & movie search needs a TMDB key: Settings → TV shows & movies.")
            elif self._raw:
                self.status.setText("Nothing in this list matches that genre.")
            else:
                self.status.setText({"tv": "No shows found.", "anime": "No anime found."}
                                    .get(self.kind, "No movies found."))
            return
        self.status.setText("")
        for h in hits[:60]:
            in_lib = bool(_in_library(self.db, h.get("media_type") or self.kind, h["provider_id"]))
            t = _PosterTile(h, in_lib)
            t.clicked.connect(self._select)
            t.set_selected(bool(self._selected) and self._selected.get("provider_id") == h["provider_id"])
            self.grid.addWidget(t)
            self._tiles.append(t)

    # ── preview ───────────────────────────────────────────────────────────────

    def _select(self, hit: Dict):
        self._selected = hit
        for t in self._tiles:
            t.set_selected(t.hit is hit)
        self.p_reason.setText(hit.get("reason") or "")
        self.p_reason.setVisible(bool(hit.get("reason")))
        self._clear_extras()
        self.p_title.setText(hit.get("title") or "")
        self.p_meta.setText(" · ".join(x for x in (str(hit.get("year") or ""),
                                                  f"★ {hit['score'] / 10:.1f}" if hit.get("score") else "") if x))
        ov = hit.get("overview") or ""
        self.p_overview.setText(ov if len(ov) < 420 else ov[:410].rsplit(" ", 1)[0] + "…")
        kind = hit.get("media_type") or self.kind
        existing = _in_library(self.db, kind, hit["provider_id"])
        self._existing = existing
        self.btn_watchlist.setEnabled(not existing)
        # Only enabled once details confirm it's actually out
        self.btn_watched.setEnabled(False)
        self.btn_watching.setEnabled(False)
        self.p_note.setText("Already in your library." if existing else "")
        self.p_backdrop.clear()
        raw = hit.get("raw") or {}
        from core import tmdb
        url = (raw.get("bannerImage") if kind == "anime" else
               tmdb.image_url(raw.get("backdrop_path"), "w780")) or hit.get("poster_url")
        if url:
            w = ImageWorker(url, hit["provider_id"])
            w.signals.result.connect(self._on_backdrop)
            run_worker(w, PRIORITY_INTERACTIVE)
        pid = hit["provider_id"]

        def work():
            if kind == "anime":
                from core.api import get_metadata_batch
                from core.metadata_sync import media_to_row
                m = get_metadata_batch([pid]).get(int(pid))
                if not m:
                    return None
                row = media_to_row(m)
                row.update({"media_type": "anime", "anilist_id": int(pid), "_media": m})
                return row
            from core import tmdb
            from core.providers import movie_row, tv_row
            d = tmdb.tv_details(pid) if kind == "tv" else tmdb.movie_details(pid)
            if not d:
                return None
            row = tv_row(d) if kind == "tv" else movie_row(d)
            row["_main_trailer"] = tmdb.main_trailer(d)
            return row

        w2 = Worker(work)
        w2.signals.result.connect(lambda row, pid=pid: self._on_details(row, pid))
        run_worker(w2, PRIORITY_INTERACTIVE)

    def _on_details(self, row: Optional[Dict], pid: int):
        if self._gone() or not row or not self._selected or self._selected["provider_id"] != pid:
            return
        self._selected["_row"] = row
        self._show_extras(row)
        if row.get("media_type") == "tv":
            return self._on_tv_details(row)
        if row.get("media_type") == "anime":
            return self._on_anime_details(row)
        bits = [str(row.get("season_year") or "")]
        if row.get("duration"):
            h, m = divmod(int(row["duration"]), 60)
            bits.append(f"{h}h {m:02d}m" if h else f"{m}m")
        if row.get("genres"):
            bits.append(", ".join(row["genres"][:3]))
        if row.get("average_score"):
            bits.append(f"★ {row['average_score'] / 10:.1f}")
        self.p_meta.setText("  ·  ".join(b for b in bits if b))
        from core.kinema_sync import release_state
        st = release_state(row)["state"]
        existing = getattr(self, "_existing", None)
        self.btn_watched.setEnabled(st != "unreleased" and
                                    (not existing or existing.get("watch_status") != "completed"))
        if existing:
            return
        if st == "unreleased":
            when = f" It's in cinemas {row['start_date']}." if row.get("start_date") else ""
            self.p_note.setText(f"Not out yet, so it can't be marked watched.{when} "
                                "Add it to your Watchlist and you'll be told when it's out in HD.")
        elif st == "cinema":
            d = _nice_date(row.get("digital_date") or "")
            self.p_note.setText("In cinemas now. " + (f"Out in HD {d}." if d else "HD date not announced yet."))
        else:
            self.p_note.setText("Out in HD: ready to watch.")

    # ── trailer + cast ────────────────────────────────────────────────────────

    def _clear_extras(self):
        self._trailer = None
        for w in (self.p_trailer_lbl, self.p_trailer, self.p_cast_lbl, self.p_cast_host):
            w.setVisible(False)
        while self.p_cast.count():
            it = self.p_cast.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._avatars = {}
        self.p_scroll.verticalScrollBar().setValue(0)

    def _show_extras(self, row: Dict):
        if row.get("media_type") == "anime":
            t = ({"id": row["trailer_id"], "site": row.get("trailer_site") or "youtube",
                  "title": "Official Trailer",
                  "thumb": row.get("trailer_thumb") or (
                      f"https://i.ytimg.com/vi/{row['trailer_id']}/hqdefault.jpg"
                      if (row.get("trailer_site") or "youtube") == "youtube" else "")}
                 if row.get("trailer_id") else None)
            self.p_cast_lbl.setText("CHARACTERS")
        else:
            t = row.get("_main_trailer")
            self.p_cast_lbl.setText("CAST")
        self._trailer = t
        if t:
            self.p_trailer.load(t.get("thumb") or "", t.get("title") or "Official Trailer")
        self.p_trailer_lbl.setVisible(bool(t))
        self.p_trailer.setVisible(bool(t))
        people = (row.get("characters") or [])[:6]
        from ui.planned_details import _Avatar
        for i, c in enumerate(people):
            cell = QWidget()
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(2)
            av = _Avatar(48)
            cl.addWidget(av, alignment=Qt.AlignmentFlag.AlignHCenter)
            for text, obj in ((c.get("name") or "", "plannedCharName"), (c.get("role") or "", "plannedCharRole")):
                l = QLabel(text)
                l.setObjectName(obj)
                l.setWordWrap(True)
                l.setFixedWidth(88)
                l.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                cl.addWidget(l, alignment=Qt.AlignmentFlag.AlignHCenter)
            self.p_cast.addWidget(cell, i // 3, i % 3, alignment=Qt.AlignmentFlag.AlignTop)
            if c.get("image"):
                self._avatars[c["image"]] = av
                w = ImageWorker(c["image"], ("cast", self._token, c["image"]))
                w.signals.result.connect(self._on_avatar)
                run_worker(w)
        self.p_cast_lbl.setVisible(bool(people))
        self.p_cast_host.setVisible(bool(people))

    def _on_avatar(self, result):
        try:
            (_k, tok, url), _s, path = result
        except Exception:
            return
        if self._gone() or tok != self._token:
            return
        av = self._avatars.get(url)
        if path and av is not None:
            try:
                av.set_pixmap(QPixmap(str(path)))
            except RuntimeError:
                pass

    def _play_trailer(self):
        t = getattr(self, "_trailer", None)
        if not t:
            return
        from ui.trailer_player import show_trailer
        show_trailer(t["id"], t.get("site") or "youtube",
                     (self._selected or {}).get("title") or t.get("title") or "", self.window())

    def _on_tv_details(self, row: Dict):
        seasons = row.get("_seasons") or []
        today = datetime.now().strftime("%Y-%m-%d")
        aired = bool(row.get("start_date")) and (row.get("start_ts") or 0) <= datetime.now().timestamp()
        bits = [str(row.get("season_year") or "")]
        if seasons:
            bits.append(f"{len(seasons)} season{'s' if len(seasons) != 1 else ''}")
        if row.get("studios"):
            bits.append(row["studios"][0])
        if row.get("genres"):
            bits.append(", ".join(row["genres"][:2]))
        if row.get("average_score"):
            bits.append(f"★ {row['average_score'] / 10:.1f}")
        self.p_meta.setText("  ·  ".join(b for b in bits if b))
        existing = getattr(self, "_existing", None)
        ended = row.get("status") in ("FINISHED", "CANCELLED")
        started = [s for s in seasons if s.get("air_date") and s["air_date"] <= today]
        self._tv_current = started[-1]["season_number"] if started else None
        if ended:
            self.btn_watched.setText("✓  I've finished it")
            self.btn_watched.setToolTip("Marks every episode watched")
            can_done = aired
        else:
            # Running show: you can't have finished it - but you may be up to
            # date on the earlier seasons and want to follow the current one.
            self.btn_watched.setText("✓  Seen earlier seasons")
            cur = self._tv_current
            self.btn_watched.setToolTip(
                f"Marks Seasons 1–{cur - 1} watched and follows Season {cur}" if cur and cur > 1
                else "Only one season so far")
            can_done = bool(cur and cur > 1)
        self.btn_watching.setEnabled(aired and not existing)
        self.btn_watched.setEnabled(can_done and not existing)
        if existing:
            return
        nxt = next((s for s in seasons if s.get("air_date") and s["air_date"] > today), None)
        if not aired:
            first = next((s.get("air_date") for s in seasons if s.get("air_date")), None)
            self.p_note.setText("Hasn't premiered yet" + (f": {_nice_date(first)}." if first else ".")
                                + " Add it to your Watchlist and you'll hear when it starts.")
        elif nxt:
            self.p_note.setText(f"Season {nxt['season_number']} premieres {_nice_date(nxt['air_date'])}.")
        elif row.get("status") == "RELEASING":
            self.p_note.setText("Still running. New episodes get a notification once you're watching.")
        elif row.get("status") in ("FINISHED", "CANCELLED"):
            n = len(seasons)
            self.p_note.setText(("Ended" if row["status"] == "FINISHED" else "Cancelled")
                                + f" after {n} season{'s' if n != 1 else ''}.")
        else:
            self.p_note.setText("")

    def _on_anime_details(self, row: Dict):
        m = row.get("_media") or {}
        api = (m.get("status") or "").upper()
        eps = m.get("episodes")
        bits = [str(m.get("seasonYear") or "")]
        fmt = {"TV": "TV", "TV_SHORT": "TV short", "ONA": "ONA", "MOVIE": "Movie"}.get(m.get("format") or "", "")
        if fmt:
            bits.append(fmt)
        if eps:
            bits.append(f"{eps} episodes" if eps != 1 else "1 episode")
        studios = [n.get("name") for n in ((m.get("studios") or {}).get("nodes") or []) if n.get("name")]
        if studios:
            bits.append(studios[0])
        if m.get("averageScore"):
            bits.append(f"★ {m['averageScore'] / 10:.1f}")
        self.p_meta.setText("  ·  ".join(b for b in bits if b))
        if m.get("description") and not self.p_overview.text():
            from core.miroku_discover import _clean
            ov = _clean(m["description"])
            self.p_overview.setText(ov if len(ov) < 420 else ov[:410].rsplit(" ", 1)[0] + "…")
        existing = getattr(self, "_existing", None)
        aired = api not in ("NOT_YET_RELEASED", "")
        ended = api in ("FINISHED", "CANCELLED")
        self.btn_watching.setEnabled(aired and not existing)
        self.btn_watched.setEnabled(ended and not existing)
        if existing:
            return
        nae = m.get("nextAiringEpisode") or {}
        if api == "NOT_YET_RELEASED":
            when = row.get("start_date") or ""
            self.p_note.setText("Hasn't aired yet" + (f": starts {when}." if when else ".")
                                + " Plan to watch it and you'll hear when it starts.")
        elif api == "RELEASING":
            if nae.get("airingAt"):
                d = datetime.fromtimestamp(nae["airingAt"])
                self.p_note.setText(f"Airing now. Episode {nae.get('episode')} airs "
                                    f"{d.strftime('%a, %b ')}{d.day}.")
            else:
                self.p_note.setText("Airing now.")
        elif ended:
            self.p_note.setText("Finished airing" + (f": all {eps} episodes are out." if eps else "."))
        else:
            self.p_note.setText("")

    def _on_backdrop(self, result):
        try:
            _id, _s, path = result
        except Exception:
            return
        if self._gone() or not path or not self._selected or _id != self._selected.get("provider_id"):
            return
        px = QPixmap(str(path))
        w, h = self.preview.width(), self.p_backdrop.height()
        sc = px.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation)
        self.p_backdrop.setPixmap(sc.copy((sc.width() - w) // 2, (sc.height() - h) // 2, w, h))

    def _add(self, watch_status: str):
        hit = self._selected
        if not hit:
            return
        for b in (self.btn_watchlist, self.btn_watching, self.btn_watched):
            b.setEnabled(False)
        self.p_note.setText("Adding…")
        pid = hit["provider_id"]
        kind = hit.get("media_type") or self.kind

        def work():
            if kind == "anime":
                m = (hit.get("_row") or {}).get("_media")
                if not m:
                    from core.api import get_metadata_batch
                    m = get_metadata_batch([pid]).get(int(pid))
                if not m:
                    return None
                return {"_media": m, "romaji_title": ((m.get("title") or {}).get("english")
                                                      or (m.get("title") or {}).get("romaji") or "")}
            if kind == "tv":
                from core.kinema_sync import fetch_tv_full
                row, eps = fetch_tv_full(pid)
                if row:
                    row["_episodes"] = eps
                return row
            row = hit.get("_row")
            if not row:
                from core.providers import get_provider
                row = get_provider("movie").details(pid)
            return row

        def done(row):
            nonlocal watch_status
            if self._gone():
                return
            if not row:
                self.p_note.setText(("Couldn't reach AniList." if kind == "anime" else "Couldn't reach TMDB.")
                                    + " Check your connection and try again.")
                self.btn_watchlist.setEnabled(True)
                return
            if kind == "anime":
                lib_id = _save_anime(self.db, row["_media"], watch_status)
            elif kind == "tv":
                from core.kinema_sync import save_tv_full
                ended = row.get("status") in ("FINISHED", "CANCELLED")
                earlier = watch_status == "completed" and not ended
                lib_id = save_tv_full(self.db, row, row.get("_episodes") or [],
                                      "watching" if earlier else watch_status)
                eps = row.get("_episodes") or []
                if earlier:
                    cur = getattr(self, "_tv_current", None) or 1
                    last = max(((e["season_number"], e["episode_number"]) for e in eps
                                if e["season_number"] < cur), default=None)
                elif watch_status == "completed":
                    last = max(((e["season_number"], e["episode_number"]) for e in eps), default=None)
                else:
                    last = None
                if last:
                    self.db.set_tv_watched_through(lib_id, *last)
                if earlier:
                    watch_status = "watching"
            else:
                lib_id = self.db.save_tmdb_title(row, watch_status)
            self._existing = self.db.get_anime_by_id(lib_id)
            for t in self._tiles:
                if t.hit.get("provider_id") == pid:
                    t.set_in_library(True)
            self.p_note.setText({"planned": "Added to Plan to Watch." if kind == "anime"
                                 else "Added to your Watchlist.",
                                 "watching": "Added to Watching. Mark episodes as you go.",
                                 }.get(watch_status, "Logged as finished." if kind in ("tv", "anime")
                                       else "Logged as watched."))
            self._cache.pop(f"{kind}:for_you", None)
            self.added.emit(lib_id, row.get("romaji_title") or "")

        w = Worker(work)
        w.signals.result.connect(done)
        run_worker(w, PRIORITY_INTERACTIVE)


def _save_anime(db, media: Dict, watch_status: str) -> int:
    """Add an AniList media to the library with full metadata; finishing it
    marks every episode watched."""
    from core.anime_add import add_media_to_library
    from core.metadata_sync import media_to_row
    add_media_to_library(db, media, watch_status)
    row = db.get_anime_by_anilist_id(media["id"])
    lib_id = row["id"]
    extra = {k: v for k, v in media_to_row(media).items()
             if k in db._anime_columns() and v not in (None, "", [], {})
             and k not in ("watch_status",)}
    import time as _t
    extra["meta_synced_at"] = int(_t.time())      # baseline: nothing here is "new"
    db.update_anime(lib_id, extra)
    if watch_status == "completed" and media.get("episodes"):
        for n in range(1, int(media["episodes"]) + 1):
            db.set_episode_watched(lib_id, n, True)
    return lib_id


class MovieAddDialog(QDialog):
    """The browser in a dialog: closes after a film is added."""
    added = pyqtSignal(int, str)

    def __init__(self, db, parent=None, kind: str = "movie"):
        super().__init__(parent)
        title = {"tv": "Add a show", "anime": "Add anime"}.get(kind, "Add a movie")
        self.setWindowTitle(title)
        self.setObjectName("kinemaAddDialog")
        self.setStyleSheet("QDialog#kinemaAddDialog{background:#0f1118;}")
        self.resize(1120, 720)
        has_any = bool(db.get_all_anime(media_type=kind))
        self.browser = MovieBrowser(db, heading=title, kind=kind,
                                    start_source="for_you" if has_any else "trending")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.browser)
        self.browser.added.connect(self._on_added)

    def _on_added(self, lib_id: int, title: str):
        self.added.emit(lib_id, title)
        self.accept()

    # convenience used by tests / callers
    @property
    def _tiles(self):
        return self.browser._tiles

    def _select(self, hit):
        self.browser._select(hit)

    def _add(self, status):
        self.browser._add(status)
