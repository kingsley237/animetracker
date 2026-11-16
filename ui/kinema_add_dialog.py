"""
Kinema - browse movies and add them to your library.

One browser, two homes:
  - the "Add a movie" dialog (sidebar button / Ctrl+N)
  - the Kinema Discover page

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

ACCENT = "#fbbf24"   # Kinema (movies) accent


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
        p.setPen(QColor(ACCENT) if self._sel else QColor(255, 255, 255, 30))
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
            p.setPen(QColor(ACCENT))
            sub = "Out " + _nice_date(rd)
        else:
            p.setPen(QColor("#7b84a3"))
            sub = " · ".join(x for x in (str(self.hit.get("year") or ""),
                                         f"★ {self.hit['score'] / 10:.1f}" if self.hit.get("score") else "") if x)
        p.drawText(QRectF(0, self.H + 22, self.W, 18), Qt.AlignmentFlag.AlignLeft, sub)
        p.end()


class MovieBrowser(QWidget):
    added = pyqtSignal(int, str)        # library id, title

    def __init__(self, db, heading: str = "", start_source: str = "for_you",
                 close_on_add: bool = False, parent=None):
        super().__init__(parent)
        self.db = db
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
        from core.kinema_discover import SORTS, SOURCES
        from ui.layout_helpers import FitWidthScroll, FlowLayout
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(24, 22, 16, 18)
        lv.setSpacing(12)
        if self._heading:
            title = QLabel(self._heading)
            title.setObjectName("pageTitle")
            lv.addWidget(title)
        self.search = QLineEdit()
        self.search.setObjectName("searchBar")
        self.search.setPlaceholderText("Search any movie: title, franchise…")
        self.search.setFixedHeight(40)
        self.search.textChanged.connect(lambda _t: self._timer.start(350))
        lv.addWidget(self.search)

        # list chips
        chips_host = QWidget()
        chips = FlowLayout(chips_host, h_spacing=6, v_spacing=6)
        self._chips: Dict[str, QPushButton] = {}
        for key, label in SOURCES:
            b = QPushButton(label)
            b.setObjectName("filterPill")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _=False, k=key: self.select_source(k))
            chips.addWidget(b)
            self._chips[key] = b
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
            body.addWidget(w)
        self.p_reason.setVisible(False)
        body.addStretch()
        self.btn_watchlist = QPushButton("＋  Add to Watchlist")
        self.btn_watchlist.setObjectName("primaryBtn")
        self.btn_watched = QPushButton("✓  I've watched it")
        self.btn_watched.setObjectName("secondaryBtn")
        for b, st in ((self.btn_watchlist, "planned"), (self.btn_watched, "completed")):
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setMinimumHeight(38)
            b.setEnabled(False)
            b.clicked.connect(lambda _=False, st=st: self._add(st))
            body.addWidget(b)
        self.p_note = QLabel("")
        self.p_note.setObjectName("plannedReleaseHint")
        self.p_note.setWordWrap(True)
        body.addWidget(self.p_note)
        pv.addLayout(body, 1)
        root.addWidget(self.preview)

    # ── lists ─────────────────────────────────────────────────────────────────

    def _load_genres(self):
        def work():
            from core.kinema_discover import genres
            return genres()

        def done(gs):
            if self._gone():
                return
            for g in gs or []:
                self.genre.addItem(g["name"], g["id"])

        w = Worker(work)
        w.signals.result.connect(done)
        run_worker(w, PRIORITY_INTERACTIVE)

    def select_source(self, key: str):
        from core.kinema_discover import SOURCES
        self._source = key
        if self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        for k, b in self._chips.items():
            b.setProperty("active", "true" if k == key else "false")
            b.style().unpolish(b)
            b.style().polish(b)
        self.section.setText(dict(SOURCES).get(key, "").upper())
        if key in self._cache:
            self._show(self._cache[key], self._next_token())
            return
        self.status.setText("Finding films for you…" if key == "for_you" else "Loading…")
        tok = self._next_token()

        def work():
            from core.kinema_discover import load_source
            return load_source(key, self.db)

        def done(hits, t=tok, k=key):
            if self._gone():
                return
            self._cache[k] = hits or []
            self._show(self._cache[k], t)

        w = Worker(work)
        w.signals.result.connect(done)
        run_worker(w, PRIORITY_INTERACTIVE)

    def refresh(self):
        """Drop cached lists (e.g. For you after the library changed)."""
        self._cache.pop("for_you", None)
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
        self.status.setText("Searching…")
        tok = self._next_token()

        def work():
            from core.providers import get_provider
            hits = get_provider("movie").search(q)
            for h in hits:
                raw = h.get("raw") or {}
                h["release_date"] = raw.get("release_date") or ""
                h["popularity"] = raw.get("popularity") or 0
                h["genre_ids"] = raw.get("genre_ids") or []
            return hits

        w = Worker(work)
        w.signals.result.connect(lambda hits, t=tok: self._show(hits, t))
        run_worker(w, PRIORITY_INTERACTIVE)

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
        from core.kinema_discover import apply
        self.grid.clear()
        self._tiles = []
        hits = apply(self._raw, self.genre.currentData() or 0, self.sort.currentData() or "default",
                     "" if self.search.text() else self._source)
        if not hits:
            if not tmdb.has_credentials():
                self.status.setText("TV & movie search needs a TMDB key: Settings → TV shows & movies.")
            elif self._raw:
                self.status.setText("Nothing in this list matches that genre.")
            else:
                self.status.setText("No movies found.")
            return
        self.status.setText("")
        for h in hits[:60]:
            in_lib = bool(self.db.get_title_by_tmdb("movie", h["provider_id"]))
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
        self.p_title.setText(hit.get("title") or "")
        self.p_meta.setText(" · ".join(x for x in (str(hit.get("year") or ""),
                                                  f"★ {hit['score'] / 10:.1f}" if hit.get("score") else "") if x))
        ov = hit.get("overview") or ""
        self.p_overview.setText(ov if len(ov) < 420 else ov[:410].rsplit(" ", 1)[0] + "…")
        existing = self.db.get_title_by_tmdb("movie", hit["provider_id"])
        self._existing = existing
        self.btn_watchlist.setEnabled(not existing)
        # Only enabled once details confirm the film is actually out
        self.btn_watched.setEnabled(False)
        self.p_note.setText("Already in your library." if existing else "")
        self.p_backdrop.clear()
        raw = hit.get("raw") or {}
        from core import tmdb
        url = tmdb.image_url(raw.get("backdrop_path"), "w780") or hit.get("poster_url")
        if url:
            w = ImageWorker(url, hit["provider_id"])
            w.signals.result.connect(self._on_backdrop)
            run_worker(w, PRIORITY_INTERACTIVE)
        pid = hit["provider_id"]

        def work():
            from core.providers import get_provider
            return get_provider("movie").details(pid)

        w2 = Worker(work)
        w2.signals.result.connect(lambda row, pid=pid: self._on_details(row, pid))
        run_worker(w2, PRIORITY_INTERACTIVE)

    def _on_details(self, row: Optional[Dict], pid: int):
        if self._gone() or not row or not self._selected or self._selected["provider_id"] != pid:
            return
        self._selected["_row"] = row
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
        self.btn_watchlist.setEnabled(False)
        self.btn_watched.setEnabled(False)
        self.p_note.setText("Adding…")
        pid = hit["provider_id"]

        def work():
            row = hit.get("_row")
            if not row:
                from core.providers import get_provider
                row = get_provider("movie").details(pid)
            return row

        def done(row):
            if self._gone():
                return
            if not row:
                self.p_note.setText("Couldn't reach TMDB. Check your connection and try again.")
                self.btn_watchlist.setEnabled(True)
                return
            lib_id = self.db.save_tmdb_title(row, watch_status)
            self._existing = self.db.get_anime_by_id(lib_id)
            for t in self._tiles:
                if t.hit.get("provider_id") == pid:
                    t.set_in_library(True)
            self.p_note.setText("Added to your Watchlist." if watch_status == "planned"
                                else "Logged as watched.")
            self._cache.pop("for_you", None)
            self.added.emit(lib_id, row.get("romaji_title") or "")

        w = Worker(work)
        w.signals.result.connect(done)
        run_worker(w, PRIORITY_INTERACTIVE)


class MovieAddDialog(QDialog):
    """The browser in a dialog: closes after a film is added."""
    added = pyqtSignal(int, str)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add a movie")
        self.setObjectName("kinemaAddDialog")
        self.setStyleSheet("QDialog#kinemaAddDialog{background:#0f1118;}")
        self.resize(1120, 720)
        has_movies = bool(db.get_all_anime(media_type="movie"))
        self.browser = MovieBrowser(db, heading="Add a movie",
                                    start_source="for_you" if has_movies else "trending")
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
