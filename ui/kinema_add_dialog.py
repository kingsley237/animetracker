"""
Kinema - find a movie and add it to your library.

Opens on this week's trending films so it's never an empty box, searches
TMDB as you type, and shows a preview (backdrop, runtime, genres, plot) with
two clear actions: add to Watchlist, or log it as already watched.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from workers.workers import PRIORITY_INTERACTIVE, ImageWorker, Worker, run_worker

ACCENT = "#fbbf24"   # Kinema (movies) accent


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
        self.setToolTip(hit.get("title") or "")
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
            p.drawText(r, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       self.hit.get("title") or "")
        if self._hover and not self._sel:
            p.fillRect(r, QColor(255, 255, 255, 18))
        p.restore()
        pen = QColor(ACCENT) if self._sel else QColor(255, 255, 255, 30)
        p.setPen(pen)
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
        p.setPen(QColor("#7b84a3"))
        sub = " · ".join(x for x in (str(self.hit.get("year") or ""),
                                     f"★ {self.hit['score'] / 10:.1f}" if self.hit.get("score") else "") if x)
        p.drawText(QRectF(0, self.H + 22, self.W, 18), Qt.AlignmentFlag.AlignLeft, sub)
        p.end()


class MovieAddDialog(QDialog):
    added = pyqtSignal(int, str)   # library id, title

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._tiles: List[_PosterTile] = []
        self._selected: Optional[Dict] = None
        self._token = 0
        self.setWindowTitle("Add a movie")
        self.setObjectName("kinemaAddDialog")
        self.setStyleSheet("QDialog#kinemaAddDialog{background:#0f1118;}")
        self.resize(1040, 680)
        self._build()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._search)
        QTimer.singleShot(0, self._load_trending)

    # ── layout ────────────────────────────────────────────────────────────────

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(24, 22, 16, 18)
        lv.setSpacing(12)
        title = QLabel("Add a movie")
        title.setObjectName("pageTitle")
        lv.addWidget(title)
        self.search = QLineEdit()
        self.search.setObjectName("searchBar")
        self.search.setPlaceholderText("Search any movie: title, franchise…")
        self.search.setFixedHeight(40)
        self.search.textChanged.connect(lambda _t: self._timer.start(350))
        lv.addWidget(self.search)
        self.section = QLabel("TRENDING THIS WEEK")
        self.section.setObjectName("detailSectionLabel")
        lv.addWidget(self.section)
        # Wrapping layout: as many poster columns as fit, never clipped
        from ui.layout_helpers import FitWidthScroll, FlowLayout
        self.scroll = FitWidthScroll()
        self.grid_host = QWidget()
        self.grid = FlowLayout(self.grid_host, h_spacing=14, v_spacing=16)
        self.scroll.setWidget(self.grid_host)
        lv.addWidget(self.scroll, 1)
        self.status = QLabel("")
        self.status.setObjectName("plannedReleaseHint")
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
        self.p_title = QLabel("Pick a movie")
        self.p_title.setObjectName("spotlightTitle")
        self.p_title.setWordWrap(True)
        self.p_meta = QLabel("Search on the left or start from what's trending.")
        self.p_meta.setObjectName("spotlightMeta")
        self.p_meta.setWordWrap(True)
        self.p_overview = QLabel("")
        self.p_overview.setObjectName("spotlightSynopsis")
        self.p_overview.setWordWrap(True)
        self.p_overview.setAlignment(Qt.AlignmentFlag.AlignTop)
        for w in (self.p_title, self.p_meta, self.p_overview):
            body.addWidget(w)
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

    # ── data ──────────────────────────────────────────────────────────────────

    def _load_trending(self):
        self.status.setText("Loading…")
        tok = self._next_token()

        def work():
            from core import tmdb
            from core.providers import _hit
            return [_hit(r, "movie") for r in tmdb.trending("movie", "week")]

        w = Worker(work)
        w.signals.result.connect(lambda hits, t=tok: self._show(hits, t, "TRENDING THIS WEEK"))
        run_worker(w, PRIORITY_INTERACTIVE)

    def _search(self):
        q = self.search.text().strip()
        if not q:
            self._load_trending()
            return
        self.status.setText("Searching…")
        tok = self._next_token()

        def work():
            from core.providers import get_provider
            return get_provider("movie").search(q)

        w = Worker(work)
        w.signals.result.connect(lambda hits, t=tok: self._show(hits, t, f"RESULTS FOR “{q.upper()}”"))
        run_worker(w, PRIORITY_INTERACTIVE)

    def _next_token(self) -> int:
        self._token += 1
        return self._token

    def _show(self, hits: List[Dict], token: int, heading: str):
        if token != self._token:
            return                      # an older search finished late
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._tiles = []
        self.section.setText(heading)
        from core import tmdb
        if not hits:
            self.status.setText("No movies found." if tmdb.has_credentials()
                                else "TV & movie search needs a TMDB key: Settings → TV shows & movies.")
            return
        self.status.setText("")
        for h in hits[:30]:
            in_lib = bool(self.db.get_title_by_tmdb("movie", h["provider_id"]))
            t = _PosterTile(h, in_lib)
            t.clicked.connect(self._select)
            self.grid.addWidget(t)
            self._tiles.append(t)

    def _select(self, hit: Dict):
        self._selected = hit
        for t in self._tiles:
            t.set_selected(t.hit is hit)
        self.p_title.setText(hit.get("title") or "")
        self.p_meta.setText(" · ".join(x for x in (str(hit.get("year") or ""),
                                                  f"★ {hit['score'] / 10:.1f}" if hit.get("score") else "") if x))
        ov = hit.get("overview") or ""
        self.p_overview.setText(ov if len(ov) < 420 else ov[:410].rsplit(" ", 1)[0] + "…")
        existing = self.db.get_title_by_tmdb("movie", hit["provider_id"])
        self.btn_watchlist.setEnabled(not existing)
        # Only enabled once details confirm the film is actually out
        self.btn_watched.setEnabled(False)
        self._existing = existing
        self.p_note.setText("Already in your library." if existing else "")
        self.p_backdrop.clear()
        raw = hit.get("raw") or {}
        from core import tmdb
        url = tmdb.image_url(raw.get("backdrop_path"), "w780") or hit.get("poster_url")
        if url:
            w = ImageWorker(url, hit["provider_id"])
            w.signals.result.connect(self._on_backdrop)
            run_worker(w)

        # details for runtime + genres
        pid = hit["provider_id"]

        def work():
            from core.providers import get_provider
            return get_provider("movie").details(pid)

        w2 = Worker(work)
        w2.signals.result.connect(lambda row, pid=pid: self._on_details(row, pid))
        run_worker(w2, PRIORITY_INTERACTIVE)

    def _on_details(self, row: Optional[Dict], pid: int):
        if not row or not self._selected or self._selected["provider_id"] != pid:
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
            d = row.get("digital_date")
            self.p_note.setText("In cinemas now. " + (f"Out in HD {d}." if d else "HD date not announced yet."))
        else:
            self.p_note.setText("Out in HD: ready to watch.")

    def _on_backdrop(self, result):
        try:
            _id, _s, path = result
        except Exception:
            return
        if not path or not self._selected or _id != self._selected.get("provider_id"):
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
            if not row:
                self.p_note.setText("Couldn't reach TMDB. Check your connection and try again.")
                self.btn_watchlist.setEnabled(True)
                self.btn_watched.setEnabled(True)
                return
            lib_id = self.db.save_tmdb_title(row, watch_status)
            self.added.emit(lib_id, row.get("romaji_title") or "")
            self.accept()

        w = Worker(work)
        w.signals.result.connect(done)
        run_worker(w, PRIORITY_INTERACTIVE)
