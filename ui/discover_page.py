"""
AnimeTracker — Discover Page
Tabs: Seasonal · Trending · Upcoming · Anticipated
Filter bar: sort by score, popularity, format, genre
Cards: tall enough to always show all content + buttons
Info dialog: full synopsis, studios, score, genres, release date
"""
import re
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QPushButton, QGridLayout, QComboBox, QProgressBar,
    QMessageBox, QSizePolicy, QDialog, QTextEdit, QSpacerItem,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QColor, QCursor, QPainter, QPainterPath

from core.database import DatabaseManager
from core.api import (
    get_seasonal_anime, get_trending_anime, get_upcoming_anime,
    get_current_season, get_genres_list, format_air_date, get_anime_by_id,
    _post, MEDIA_FIELDS_SLIM,
)
from workers.workers import Worker, ImageWorker, run_worker


def _strip_html(txt: str) -> str:
    return re.sub(r"<[^>]+>", "", txt or "")


def _get_classics(page: int = 1, per_page: int = 24, sort: str = "SCORE_DESC") -> List[Dict]:
    """
    Classics = FINISHED anime sorted by score.
    View-only — great anime the user may not have seen.
    """
    gql = f"""
    query ($page: Int, $perPage: Int, $sort: [MediaSort]) {{
        Page(page: $page, perPage: $perPage) {{
            media(
                type: ANIME, isAdult: false,
                status: FINISHED,
                sort: $sort,
                format_in: [TV, TV_SHORT, ONA, MOVIE],
                averageScore_greater: 60
            ) {{
                {MEDIA_FIELDS_SLIM}
            }}
        }}
    }}
    """
    data = _post(gql, {
        "page": page, "perPage": per_page,
        "sort": [sort] if isinstance(sort, str) else sort
    })
    return (data or {}).get("Page", {}).get("media", [])


def _get_trending_sorted(page: int = 1, per_page: int = 24, sort: str = "TRENDING_DESC") -> List[Dict]:
    """Trending with configurable sort."""
    gql = f"""
    query ($page: Int, $perPage: Int, $sort: [MediaSort]) {{
        Page(page: $page, perPage: $perPage) {{
            media(
                type: ANIME, isAdult: false, sort: $sort,
                format_in: [TV, TV_SHORT, ONA, MOVIE]
            ) {{
                {MEDIA_FIELDS_SLIM}
            }}
        }}
    }}
    """
    data = _post(gql, {
        "page": page, "perPage": per_page,
        "sort": [sort] if isinstance(sort, str) else sort
    })
    return (data or {}).get("Page", {}).get("media", [])


def _get_anticipated(page: int = 1, per_page: int = 24) -> List[Dict]:
    """
    Anticipated = NOT_YET_RELEASED anime sorted by popularity DESC.
    These are the most-wanted upcoming shows — high popularity = community hype.
    """
    from core.api import _post, MEDIA_FIELDS_SLIM
    gql = f"""
    query ($page: Int, $perPage: Int) {{
        Page(page: $page, perPage: $perPage) {{
            media(
                type: ANIME, isAdult: false,
                status: NOT_YET_RELEASED,
                sort: POPULARITY_DESC,
                format_in: [TV, TV_SHORT, ONA, MOVIE]
            ) {{
                {MEDIA_FIELDS_SLIM}
            }}
        }}
    }}
    """
    data = _post(gql, {"page": page, "perPage": per_page})
    return (data or {}).get("Page", {}).get("media", [])


SORT_OPTIONS = [
    ("Score (High→Low)",      "SCORE_DESC"),
    ("Score (Low→High)",      "SCORE"),
    ("Popularity (High→Low)", "POPULARITY_DESC"),
    ("Popularity (Low→High)", "POPULARITY"),
    ("Newest First",          "START_DATE_DESC"),
    ("Oldest First",          "START_DATE"),
]


class DiscoverPage(QWidget):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self._loaded       = False
        self._mode         = "seasonal"
        self._season, self._year = get_current_season()
        self._genre: Optional[str] = None
        self._sort_key     = "SCORE_DESC"
        self._cards: List["DiscoverCard"] = []
        self._current_page = 1
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 0)
        lay.setSpacing(0)

        # Title
        hr = QHBoxLayout()
        t = QLabel("Discover")
        t.setObjectName("pageTitle")
        hr.addWidget(t)
        hr.addStretch()
        lay.addLayout(hr)
        lay.addSpacing(14)

        # ── Tab row ──────────────────────────────────────────────────────
        tab_row = QHBoxLayout()
        tab_row.setSpacing(6)
        self._tabs: Dict[str, QPushButton] = {}
        for label, mode in [
            ("Seasonal", "seasonal"),
            ("Trending", "trending"),
            ("Upcoming", "upcoming"),
            ("Classics", "classics"),
        ]:
            b = QPushButton(label)
            b.setObjectName("filterPill")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _, m=mode: self._switch(m))
            self._tabs[mode] = b
            tab_row.addWidget(b)
        tab_row.addStretch()
        lay.addLayout(tab_row)
        lay.addSpacing(10)

        # ── Filter / control bar (changes per tab) ────────────────────────
        self.control_bar = QWidget()
        self.control_bar.setStyleSheet("background:transparent;")
        self.cb_lay = QHBoxLayout(self.control_bar)
        self.cb_lay.setContentsMargins(0, 0, 0, 0)
        self.cb_lay.setSpacing(8)

        # Season selectors — shown only on Seasonal tab
        self.season_w = QWidget()
        self.season_w.setStyleSheet("background:transparent;")
        sw_lay = QHBoxLayout(self.season_w)
        sw_lay.setContentsMargins(0, 0, 0, 0)
        sw_lay.setSpacing(6)

        self.season_combo = QComboBox()
        # Season items with month hints embedded as subtle tooltip
        _SEASON_MONTHS = {
            "Winter": "Winter  (Jan · Feb · Mar)",
            "Spring": "Spring  (Apr · May · Jun)",
            "Summer": "Summer  (Jul · Aug · Sep)",
            "Fall":   "Fall    (Oct · Nov · Dec)",
        }
        for s, hint in _SEASON_MONTHS.items():
            self.season_combo.addItem(hint)
        # Set current season — match by prefix
        cur_season = self._season.title()
        for i in range(self.season_combo.count()):
            if self.season_combo.itemText(i).startswith(cur_season):
                self.season_combo.setCurrentIndex(i)
                break
        self.season_combo.setFixedWidth(200)
        sw_lay.addWidget(self.season_combo)

        # "You are here" badge — current season
        from core.api import get_current_season as _gcs
        _cur_s, _cur_y = _gcs()
        now_badge = QLabel(f"Now: {_cur_s.title()} {_cur_y}")
        now_badge.setStyleSheet(
            "font-size:10px;font-weight:700;color:#34d399;"
            "background:#0e2a1f;border-radius:8px;padding:2px 8px;"
        )
        sw_lay.addWidget(now_badge)

        self.year_combo = QComboBox()
        self.year_combo.addItems([str(y) for y in range(2027, 2018, -1)])
        self.year_combo.setCurrentText(str(self._year))
        self.year_combo.setFixedWidth(78)
        sw_lay.addWidget(self.year_combo)

        self.cb_lay.addWidget(self.season_w)

        # Genre filter — always visible
        genre_lbl = QLabel("Genre:")
        genre_lbl.setStyleSheet("font-size:12px;color:#4a5070;")
        self.cb_lay.addWidget(genre_lbl)
        self.genre_combo = QComboBox()
        self.genre_combo.addItem("All Genres")
        for g in get_genres_list():
            self.genre_combo.addItem(g)
        self.genre_combo.setFixedWidth(130)
        self.cb_lay.addWidget(self.genre_combo)

        # Sort filter
        sort_lbl = QLabel("Sort:")
        sort_lbl.setStyleSheet("font-size:12px;color:#4a5070;")
        self.cb_lay.addWidget(sort_lbl)
        self.sort_combo = QComboBox()
        for label, _ in SORT_OPTIONS:
            self.sort_combo.addItem(label)
        self.sort_combo.setFixedWidth(180)
        self.cb_lay.addWidget(self.sort_combo)

        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("secondaryBtn")
        apply_btn.setFixedHeight(32)
        apply_btn.setMinimumWidth(64)
        apply_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        apply_btn.clicked.connect(self._apply)
        self.cb_lay.addWidget(apply_btn)
        self.cb_lay.addStretch()

        lay.addWidget(self.control_bar)
        lay.addSpacing(12)

        # Loading bar
        self.bar = QProgressBar()
        self.bar.setFixedHeight(2)
        self.bar.setRange(0, 0)
        self.bar.setVisible(False)
        self.bar.setStyleSheet(
            "QProgressBar{background:#1a1d28;border:none;}"
            "QProgressBar::chunk{background:#7c6af7;}"
        )
        lay.addWidget(self.bar)
        lay.addSpacing(4)

        # Scroll area with grid
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.grid_w = QWidget()
        self.grid_w.setStyleSheet("background:transparent;")
        self.grid   = QGridLayout(self.grid_w)
        self.grid.setSpacing(14)
        self.grid.setContentsMargins(0, 4, 0, 4)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.grid_w)
        lay.addWidget(self.scroll)

        # Load More — with top margin so it doesn't touch the grid
        lay.addSpacing(12)
        self.load_more_btn = QPushButton("Load More")
        self.load_more_btn.setObjectName("secondaryBtn")
        self.load_more_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.load_more_btn.setFixedHeight(38)
        self.load_more_btn.setFixedWidth(160)
        self.load_more_btn.setVisible(False)
        self.load_more_btn.clicked.connect(self._load_more)
        lay.addWidget(self.load_more_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(16)

        self._set_active("seasonal")

    def load(self):
        if not self._loaded:
            self._loaded = True
            self._fetch()

    # ── Tab / filter logic ────────────────────────────────────────────────────

    def _switch(self, mode: str):
        self._mode = mode
        self._set_active(mode)
        # Season selectors only relevant for seasonal tab
        self.season_w.setVisible(mode == "seasonal")
        self._fetch()

    def _set_active(self, mode: str):
        for m, b in self._tabs.items():
            b.setProperty("active", "true" if m == mode else "false")
            b.style().unpolish(b)
            b.style().polish(b)
        self.season_w.setVisible(mode == "seasonal")

    def _apply(self):
        raw = self.season_combo.currentText().split("(")[0].strip()
        self._season   = raw.upper()
        self._year     = int(self.year_combo.currentText())
        gt = self.genre_combo.currentText()
        self._genre    = None if gt == "All Genres" else gt
        idx = self.sort_combo.currentIndex()
        self._sort_key = SORT_OPTIONS[idx][1] if 0 <= idx < len(SORT_OPTIONS) else "SCORE_DESC"
        self._fetch()

    # ── Fetch ─────────────────────────────────────────────────────────────────

    def _fetch(self):
        self._current_page = 1
        self.bar.setVisible(True)
        self.load_more_btn.setVisible(False)
        self._clear()
        self._fetch_page(1, append=False)

    def _load_more(self):
        self._current_page += 1
        self.load_more_btn.setText("Loading…")
        self.load_more_btn.setEnabled(False)
        self._fetch_page(self._current_page, append=True)

    def _fetch_page(self, page: int, append: bool):
        self.bar.setVisible(True)
        mode      = self._mode
        season    = self._season
        year      = self._year
        genre     = self._genre
        sort_key  = self._sort_key

        def work():
            if mode == "seasonal":
                return get_seasonal_anime(season, year, sort=sort_key,
                                          genre=genre, page=page)
            elif mode == "trending":
                return _get_trending_sorted(page=page, per_page=24, sort=sort_key)
            elif mode == "upcoming":
                return get_upcoming_anime(page=page, per_page=24)
            else:  # classics — finished anime sorted by score
                return _get_classics(page=page, sort=sort_key)

        def on_done(results):
            self.bar.setVisible(False)
            self.load_more_btn.setText("Load More")
            self.load_more_btn.setEnabled(True)
            self._on_data(results, append=append)

        w = Worker(work)
        w.signals.result.connect(on_done)
        w.signals.error.connect(lambda e: (
            self.bar.setVisible(False),
            self.load_more_btn.setEnabled(True),
        ))
        run_worker(w)

    def _on_data(self, results: List[Dict], append: bool = False):
        if not append:
            self._clear()
        COLS   = max(2, (self.scroll.width() - 20) // (DiscoverCard.W + 14))
        offset = len(self._cards)
        self.load_more_btn.setVisible(len(results) >= 20)

        for i, media in enumerate(results):
            card = DiscoverCard(media, self.db, self)
            card.add_requested.connect(self._do_add)
            card.info_requested.connect(self._show_info)
            idx = offset + i
            self.grid.addWidget(card, idx // COLS, idx % COLS)
            self._cards.append(card)

            url = (media.get("coverImage") or {}).get("large") or \
                  (media.get("coverImage") or {}).get("medium") or ""
            if url:
                iw = ImageWorker(url, i)
                iw.signals.result.connect(
                    lambda r, c=card: c.set_cover(r[2]) if r and r[2] else None
                )
                run_worker(iw)

    def _clear(self):
        for i in reversed(range(self.grid.count())):
            w = self.grid.itemAt(i).widget()
            if w:
                w.setParent(None)
        self._cards = []

    # ── Info dialog ───────────────────────────────────────────────────────────

    def _show_info(self, media: Dict):
        # Fetch full data for complete synopsis/studios
        anilist_id = media.get("id")
        if anilist_id:
            def fetch():
                return get_anime_by_id(anilist_id)
            w = Worker(fetch)
            w.signals.result.connect(
                lambda full: _InfoDialog(full or media, self).exec()
            )
            run_worker(w)
        else:
            _InfoDialog(media, self).exec()

    # ── Add ───────────────────────────────────────────────────────────────────

    def _do_add(self, media: Dict):
        api_s = (media.get("status") or "").upper()
        if api_s == "FINISHED":
            QMessageBox.information(
                self, "View Only",
                f"'{(media.get('title') or {}).get('romaji','')}' has finished airing.\n\n"
                "AnimeTracker only tracks currently airing and upcoming anime."
            )
            return

        anilist_id = media.get("id")
        if anilist_id and self.db.get_anime_by_anilist_id(anilist_id):
            QMessageBox.information(self, "Already Added",
                f"'{(media.get('title') or {}).get('romaji','')}' is already in your library.")
            return

        def fetch():
            return get_anime_by_id(anilist_id) if anilist_id else media

        w = Worker(fetch)
        w.signals.result.connect(self._commit)
        run_worker(w)

    def _commit(self, media: Dict):
        t    = media.get("title", {})
        cov  = media.get("coverImage") or {}
        nae  = media.get("nextAiringEpisode") or {}
        sd   = media.get("startDate") or {}
        api_s = (media.get("status") or "").upper()
        ws   = "planned" if api_s == "NOT_YET_RELEASED" else "watching"

        self.db.add_anime({
            "anilist_id":       media.get("id"),
            "romaji_title":     t.get("romaji", "Unknown"),
            "english_title":    t.get("english") or "",
            "native_title":     t.get("native") or "",
            "watch_status":     ws,
            "status":           media.get("status", ""),
            "cover_url":        cov.get("large") or cov.get("medium") or "",
            "banner_url":       media.get("bannerImage") or "",
            "description":      media.get("description") or "",
            "genres":           media.get("genres") or [],
            "studios":          [s["name"] for s in
                                 (media.get("studios", {}).get("nodes") or [])],
            "total_episodes":   media.get("episodes"),
            "season":           media.get("season") or "",
            "season_year":      media.get("seasonYear"),
            "average_score":    media.get("averageScore"),
            "popularity":       media.get("popularity"),
            "start_date":       format_air_date(sd),
            "next_episode_at":  nae.get("airingAt"),
            "next_episode_num": nae.get("episode"),
        })
        label = "Plan to Watch" if ws == "planned" else "Watching"
        QMessageBox.information(
            self, "Added ✓",
            f"'{t.get('romaji','')}' added as '{label}'."
        )


# ── Discover Card ─────────────────────────────────────────────────────────────

class DiscoverCard(QFrame):
    add_requested  = pyqtSignal(dict)
    info_requested = pyqtSignal(dict)

    W  = 192   # card width
    CH = 250   # cover height
    # Info strip height is dynamic (no fixed card height) — let layout decide

    def __init__(self, media: Dict, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self._media = media
        self.db     = db
        self.setObjectName("discoverCard")
        self.setFixedWidth(self.W)
        # No fixed height — info strip will expand to fit content

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Cover ─────────────────────────────────────────────────────────
        self.cover = QLabel()
        self.cover.setFixedSize(self.W, self.CH)
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setStyleSheet(
            "background:#1a1d28;border-radius:10px 10px 0 0;"
        )
        outer.addWidget(self.cover)

        # ── Info strip ────────────────────────────────────────────────────
        info = QWidget()
        info.setFixedWidth(self.W)
        info.setStyleSheet(
            "background:#111420;border-radius:0 0 10px 10px;"
        )
        il = QVBoxLayout(info)
        il.setContentsMargins(10, 9, 10, 10)
        il.setSpacing(4)

        t = media.get("title", {})
        display = t.get("english") or t.get("romaji", "")
        if len(display) > 26:
            display = display[:24] + "…"

        title_lbl = QLabel(display)
        title_lbl.setStyleSheet(
            "font-size:12px;font-weight:700;color:#dde0ed;background:transparent;"
        )
        title_lbl.setToolTip(t.get("romaji", ""))
        title_lbl.setWordWrap(True)
        il.addWidget(title_lbl)

        # Score + episodes row
        meta_parts = []
        sc  = media.get("averageScore")
        eps = media.get("episodes")
        pop = media.get("popularity", 0)
        if sc:
            meta_parts.append(f"★ {sc / 10:.1f}")
        if eps:
            meta_parts.append(f"{eps} eps")
        meta_lbl = QLabel("  ·  ".join(meta_parts) if meta_parts else "")
        meta_lbl.setStyleSheet(
            "font-size:11px;color:#6b7280;background:transparent;"
        )
        il.addWidget(meta_lbl)

        # Status-specific detail line
        api_s = (media.get("status") or "").upper()
        if api_s == "NOT_YET_RELEASED":
            sd_str = format_air_date(media.get("startDate") or {})
            date_lbl = QLabel(f"📅  {sd_str}")
            date_lbl.setStyleSheet(
                "font-size:11px;color:#fbbf24;background:transparent;"
            )
            il.addWidget(date_lbl)
        elif api_s == "RELEASING":
            nae = media.get("nextAiringEpisode") or {}
            ep  = nae.get("episode")
            if ep:
                airing_lbl = QLabel(f"▶  Ep {ep} airing soon")
                airing_lbl.setStyleSheet(
                    "font-size:11px;color:#34d399;background:transparent;"
                )
                il.addWidget(airing_lbl)

        # Genres (up to 2, as small chips)
        genres = (media.get("genres") or [])[:2]
        if genres:
            gr = QHBoxLayout()
            gr.setSpacing(4)
            gr.setContentsMargins(0, 2, 0, 0)
            for g in genres:
                chip = QLabel(g)
                chip.setStyleSheet(
                    "font-size:9px;color:#7c6af7;background:#151929;"
                    "border:1px solid #2a2550;border-radius:8px;padding:1px 6px;"
                )
                gr.addWidget(chip)
            gr.addStretch()
            il.addLayout(gr)

        il.addSpacing(4)

        # ── Buttons — always full width so text is never clipped ──────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_row.setContentsMargins(0, 0, 0, 0)

        info_btn = QPushButton("ℹ Info")
        info_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        info_btn.setMinimumHeight(28)
        info_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        info_btn.setStyleSheet(
            "QPushButton{font-size:11px;font-weight:500;padding:4px 8px;"
            "background:#1a1d28;color:#9da5c0;border:1px solid #2a2d42;"
            "border-radius:6px;}"
            "QPushButton:hover{background:#252a40;color:#c7cbd9;}"
        )
        info_btn.clicked.connect(lambda: self.info_requested.emit(self._media))
        btn_row.addWidget(info_btn)

        if api_s != "FINISHED":
            add_btn = QPushButton("+ Add")
            add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            add_btn.setMinimumHeight(28)
            add_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            add_btn.setStyleSheet(
                "QPushButton{font-size:11px;font-weight:600;padding:4px 8px;"
                "background:#4b3fa8;color:#fff;border:none;border-radius:6px;}"
                "QPushButton:hover{background:#5a4fc4;}"
            )
            add_btn.clicked.connect(lambda: self.add_requested.emit(self._media))
            btn_row.addWidget(add_btn)
        else:
            fin_lbl = QLabel("Finished")
            fin_lbl.setStyleSheet(
                "font-size:10px;color:#4a5070;padding:4px 6px;"
                "background:transparent;"
            )
            btn_row.addWidget(fin_lbl)

        il.addLayout(btn_row)
        outer.addWidget(info)

    def set_cover(self, path: str):
        if not path:
            return
        px = QPixmap(path)
        if px.isNull():
            return
        sc = px.scaled(
            self.W, self.CH,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (sc.width()  - self.W)  // 2)
        y = max(0, (sc.height() - self.CH) // 2)
        cr = sc.copy(x, y, self.W, self.CH)

        res = QPixmap(self.W, self.CH)
        res.fill(QColor(0, 0, 0, 0))
        p = QPainter(res)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path_obj = QPainterPath()
        path_obj.addRoundedRect(0, 0, self.W, self.CH, 10, 10)
        p.setClipPath(path_obj)
        p.drawPixmap(0, 0, cr)
        p.end()
        self.cover.setPixmap(res)


# ── Info Dialog ───────────────────────────────────────────────────────────────

class _InfoDialog(QDialog):
    """Full-detail popup — fetches complete data from AniList before showing."""

    def __init__(self, media: Dict, parent=None):
        super().__init__(parent)
        t = (media.get("title") or {})
        self.setWindowTitle(t.get("romaji") or t.get("english") or "Info")
        self.setMinimumSize(520, 560)
        self.setMaximumWidth(620)
        self.setStyleSheet("background:#0f1118;")
        self._build(media)

    def _build(self, media: Dict):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)

        t     = media.get("title") or {}
        sc    = media.get("averageScore")
        eps   = media.get("episodes")
        sea   = (media.get("season") or "").title()
        yr    = media.get("seasonYear") or ""
        api_s = (media.get("status") or "").replace("_", " ").title()
        sd    = format_air_date(media.get("startDate") or {})
        pop   = media.get("popularity", 0)
        studios = [s["name"] for s in
                   (media.get("studios", {}).get("nodes") or [])] if media.get("studios") else []

        # ── Title block ──────────────────────────────────────────────────
        romaji = t.get("romaji", "")
        english = t.get("english", "")
        title_lbl = QLabel(romaji)
        title_lbl.setStyleSheet(
            "font-size:18px;font-weight:700;color:#f0f1f5;letter-spacing:-0.2px;"
        )
        title_lbl.setWordWrap(True)
        lay.addWidget(title_lbl)

        if english and english != romaji:
            eng_lbl = QLabel(english)
            eng_lbl.setStyleSheet("font-size:12px;color:#4a5070;")
            eng_lbl.setWordWrap(True)
            lay.addWidget(eng_lbl)

        if studios:
            studio_lbl = QLabel(", ".join(studios))
            studio_lbl.setStyleSheet("font-size:12px;color:#4a5070;")
            lay.addWidget(studio_lbl)

        # ── Score + meta row ─────────────────────────────────────────────
        score_row = QHBoxLayout()
        score_row.setSpacing(20)

        if sc:
            score_box = QFrame()
            score_box.setStyleSheet(
                "background:#151929;border-radius:8px;padding:4px;"
            )
            sb_lay = QVBoxLayout(score_box)
            sb_lay.setContentsMargins(14, 8, 14, 8)
            sb_lay.setSpacing(2)
            sv = QLabel(f"{sc / 10:.1f}")
            sv.setStyleSheet("font-size:26px;font-weight:700;color:#7c6af7;")
            sb_lay.addWidget(sv)
            sl = QLabel("ANILIST SCORE")
            sl.setStyleSheet("font-size:9px;color:#4a5070;letter-spacing:1px;font-weight:700;")
            sb_lay.addWidget(sl)
            score_row.addWidget(score_box)

        meta_col = QVBoxLayout()
        meta_col.setSpacing(4)
        for icon, val in [
            ("📅", f"{sea} {yr}".strip() or sd),
            ("📺", f"{eps} episodes" if eps else "Episodes TBA"),
            ("📊", f"{pop:,} popularity" if pop else ""),
            ("⚡", api_s),
        ]:
            if val:
                ml = QLabel(f"{icon}  {val}")
                ml.setStyleSheet("font-size:12px;color:#6b7280;")
                meta_col.addWidget(ml)
        score_row.addLayout(meta_col)
        score_row.addStretch()
        lay.addLayout(score_row)

        # ── Genres ───────────────────────────────────────────────────────
        genres = (media.get("genres") or [])[:8]
        if genres:
            gw = QWidget()
            gw.setStyleSheet("background:transparent;")
            gl = QHBoxLayout(gw)
            gl.setContentsMargins(0, 2, 0, 2)
            gl.setSpacing(6)
            for g in genres:
                chip = QLabel(g)
                chip.setObjectName("genreChip")
                gl.addWidget(chip)
            gl.addStretch()
            lay.addWidget(gw)

        # ── Synopsis ─────────────────────────────────────────────────────
        syn_header = QLabel("SYNOPSIS")
        syn_header.setStyleSheet(
            "font-size:10px;color:#3b4260;font-weight:700;letter-spacing:1.5px;"
        )
        lay.addWidget(syn_header)

        raw_desc  = _strip_html(media.get("description") or "")
        desc_text = raw_desc if raw_desc else "No synopsis available for this title yet."

        syn = QTextEdit()
        syn.setReadOnly(True)
        syn.setPlainText(desc_text)
        syn.setFixedHeight(160)
        syn.setStyleSheet(
            "QTextEdit{background:#111420;border:1px solid #1a1d28;border-radius:8px;"
            "color:#9da5c0;font-size:12px;padding:10px;line-height:1.6;}"
        )
        lay.addWidget(syn)

        # ── Release date highlight for upcoming ──────────────────────────
        raw_api_s = (media.get("status") or "").upper()
        if raw_api_s == "NOT_YET_RELEASED":
            rel_frame = QFrame()
            rel_frame.setStyleSheet(
                "background:#1f1a0d;border:1px solid #633806;border-radius:8px;"
            )
            rfl = QHBoxLayout(rel_frame)
            rfl.setContentsMargins(14, 10, 14, 10)
            rl = QLabel(f"📅  Expected premiere:  {sd}")
            rl.setStyleSheet("font-size:13px;color:#fbbf24;font-weight:600;")
            rfl.addWidget(rl)
            lay.addWidget(rel_frame)

        # ── Close ────────────────────────────────────────────────────────
        close = QPushButton("Close")
        close.setObjectName("secondaryBtn")
        close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close.clicked.connect(self.accept)
        lay.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)