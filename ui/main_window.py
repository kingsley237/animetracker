"""
AnimeTracker — Main Window
Fixed:
  - Filter pills (All/Watching/Completed/Planned) ONLY shown on Library page
  - Dropped section loads and displays correctly
  - Stats strip updates in real-time on every status change
  - Hall of Fame added to navigation
  - App icon set
  - Cover art loads reliably (forces re-download if local cache missing)
"""
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QSizePolicy,
    QStatusBar, QApplication, QLineEdit, QGridLayout, QStackedWidget,
    QProgressBar, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QColor, QFont, QIcon, QCursor

from core.database import DatabaseManager
from workers.workers import Worker, ImageWorker, AiringRefreshWorker, run_worker
from ui.anime_card import AnimeCard
from ui.detail_panel import DetailPanel
from ui.discover_page import DiscoverPage
from ui.stats_page import StatsPage
from ui.add_dialog import AddAnimeDialog
from ui.settings_dialog import SettingsDialog
from ui.hall_of_fame import HallOfFamePage
from ui.update_banner import UpdateBanner


NAV_ITEMS = [
    ("Library",       "📚", "library"),
    ("Watching",      "▶",  "watching"),
    ("Completed",     "✓",  "completed"),
    ("Planned",       "⏳", "planned"),
    ("Dropped",       "✕",  "dropped"),
    ("Hall of Fame",  "🏆", "hof"),
    ("Discover",      "✦",  "discover"),
    ("Statistics",    "◈",  "stats"),
]

# Pages that show the filter pill row (All / Watching / Completed / Planned)
_FILTER_PAGES = {"library"}


class MainWindow(QMainWindow):
    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db
        self.current_page = "library"
        self.selected_anime_id: Optional[int] = None
        self._cards: Dict[int, AnimeCard] = {}
        self._dropped_id_map: Dict[int, int] = {}  # fake_id -> real dropped_id
        self._current_filter = "all"
        self._search_query   = ""
        self._sort_by        = "release_date"

        self._countdown_timer = QTimer(self)
        self._refresh_timer   = QTimer(self)
        self._search_timer    = QTimer(self)

        self.setWindowTitle("AnimeTracker")
        self.setMinimumSize(1100, 700)
        self.resize(1340, 840)

        # Window icon
        icon_path = Path(__file__).parent.parent / "resources" / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._load_theme()
        self._build_ui()
        self._setup_timers()
        self._load_library()
        self._check_connection()
        self._check_for_updates()

    # ── Theme ──────────────────────────────────────────────────────────────────

    def _load_theme(self):
        qss = Path(__file__).parent.parent / "resources" / "themes" / "dark.qss"
        if qss.exists():
            QApplication.instance().setStyleSheet(qss.read_text(encoding="utf-8"))

    # ── UI build ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        # Content + detail panel in a plain HBox — no splitter needed
        # Update banner — sits above content, hidden until update found
        self.update_banner = UpdateBanner()
        root.addWidget(self.update_banner)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(0)

        # Stacked pages
        self.stack = QStackedWidget()
        self.stack.setObjectName("contentArea")

        self.library_page  = self._build_library_page()
        self.discover_page = DiscoverPage(self.db, self)
        self.stats_page    = StatsPage(self.db, self)
        self.hof_page      = HallOfFamePage(self.db, self)

        self.stack.addWidget(self.library_page)
        self.stack.addWidget(self.discover_page)
        self.stack.addWidget(self.stats_page)
        self.stack.addWidget(self.hof_page)

        content_row.addWidget(self.stack, stretch=1)

        # Detail panel — fixed width, hidden by default
        self.detail_panel = DetailPanel(self.db, self)
        self.detail_panel.setFixedWidth(390)
        self.detail_panel.setVisible(False)
        self.detail_panel.episode_changed.connect(self._on_episode_changed)
        self.detail_panel.stats_changed.connect(self._update_stats_strip)
        self.detail_panel.anime_dropped.connect(self._on_anime_dropped)
        self.detail_panel.anime_deleted.connect(self._on_anime_deleted)
        content_row.addWidget(self.detail_panel)

        content_widget = QWidget()
        content_widget.setLayout(content_row)
        root.addWidget(content_widget)
        self.setStatusBar(self._build_status_bar())


    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(204)
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Logo
        logo_w = QWidget()
        ll = QVBoxLayout(logo_w)
        ll.setContentsMargins(20, 22, 20, 10)
        ll.setSpacing(2)

        # Try to show app icon inline
        icon_path = Path(__file__).parent.parent / "resources" / "icon_64.png"
        if icon_path.exists():
            icon_lbl = QLabel()
            px = QPixmap(str(icon_path)).scaled(
                36, 36, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            icon_lbl.setPixmap(px)
            icon_lbl.setFixedSize(36, 36)
            ll.addWidget(icon_lbl)

        logo = QLabel("ANIME")
        logo.setObjectName("appLogo")
        ll.addWidget(logo)
        sub = QLabel("T R A C K E R")
        sub.setObjectName("appLogoSub")
        ll.addWidget(sub)
        lay.addWidget(logo_w)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#1a1d28;margin:0 16px;")
        lay.addWidget(sep)
        lay.addSpacing(8)

        self._nav_buttons: Dict[str, QPushButton] = {}
        for label, icon, page_id in NAV_ITEMS:
            btn = QPushButton(f"  {icon}  {label}")
            btn.setObjectName("navBtn")
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(lambda _, p=page_id: self._navigate(p))
            self._nav_buttons[page_id] = btn
            lay.addWidget(btn)

            # Divider after Dropped and before Discover
            if page_id == "dropped":
                lay.addSpacing(10)
                sep2 = QFrame()
                sep2.setFrameShape(QFrame.Shape.HLine)
                sep2.setStyleSheet("color:#1a1d28;margin:0 16px;")
                lay.addWidget(sep2)
                lay.addSpacing(6)

        lay.addStretch()

        add_btn = QPushButton("  +  Add Anime")
        add_btn.setObjectName("primaryBtn")
        add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_btn.setStyleSheet("margin:0 16px 6px;padding:10px;")
        add_btn.clicked.connect(self._open_add_dialog)
        lay.addWidget(add_btn)

        cfg_btn = QPushButton("  ⚙  Settings")
        cfg_btn.setObjectName("navBtn")
        cfg_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cfg_btn.clicked.connect(self._open_settings)
        lay.addWidget(cfg_btn)
        lay.addSpacing(8)

        self._set_nav_active("library")
        return sidebar

    def _build_library_page(self) -> QWidget:
        page = QWidget()
        lay  = QVBoxLayout(page)
        lay.setContentsMargins(28, 22, 28, 12)
        lay.setSpacing(0)

        # ── Header ──
        hr = QHBoxLayout()
        self.page_title = QLabel("Library")
        self.page_title.setObjectName("pageTitle")
        hr.addWidget(self.page_title)
        hr.addStretch()

        self.refresh_btn = QPushButton("↻  Refresh Airing")
        self.refresh_btn.setObjectName("secondaryBtn")
        self.refresh_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.refresh_btn.clicked.connect(self._refresh_airing)
        hr.addWidget(self.refresh_btn)
        lay.addLayout(hr)
        lay.addSpacing(16)

        # ── Search + sort row ──
        sr = QHBoxLayout()
        sr.setSpacing(10)
        self.search_bar = QLineEdit()
        self.search_bar.setObjectName("searchBar")
        self.search_bar.setPlaceholderText("Search your library…")
        self.search_bar.setFixedHeight(36)
        self.search_bar.setMaximumWidth(300)
        self.search_bar.textChanged.connect(self._on_search)
        sr.addWidget(self.search_bar)

        from PyQt6.QtWidgets import QComboBox
        sort_lbl = QLabel("Sort:")
        sort_lbl.setStyleSheet("font-size:12px;color:#4a5070;")
        sr.addWidget(sort_lbl)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems([
            "Release Date", "Title", "AniList Score", "Date Added", "Your Rating"
        ])
        self.sort_combo.setFixedWidth(150)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        sr.addWidget(self.sort_combo)
        sr.addStretch()
        lay.addLayout(sr)
        lay.addSpacing(12)

        # ── Filter pills — ONLY on Library page ──
        self.filter_row = QWidget()
        fr = QHBoxLayout(self.filter_row)
        fr.setContentsMargins(0, 0, 0, 0)
        fr.setSpacing(6)
        self._filter_btns: Dict[str, QPushButton] = {}
        for label, fid in [
            ("All","all"),("Watching","watching"),
            ("Completed","completed"),("Planned","planned"),
            ("Behind","behind"),
        ]:
            b = QPushButton(label)
            b.setObjectName("filterPill")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _, f=fid: self._set_filter(f))
            self._filter_btns[fid] = b
            fr.addWidget(b)
        fr.addStretch()
        lay.addWidget(self.filter_row)
        lay.addSpacing(16)

        # ── Stats strip ──
        self.stats_strip = self._build_stats_strip()
        lay.addWidget(self.stats_strip)
        lay.addSpacing(18)

        # ── Grid ──
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.grid_container = QWidget()
        self.grid_layout    = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(14)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self.scroll_area.setWidget(self.grid_container)
        lay.addWidget(self.scroll_area)

        # ── Empty state ──
        self.empty_state = self._build_empty_state()
        lay.addWidget(self.empty_state)
        self.empty_state.setVisible(False)

        self._set_filter("all")
        return page

    def _build_stats_strip(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self._stat_labels: Dict[str, QLabel] = {}
        for key, label, color in [
            ("watching",  "Watching",  "#7c6af7"),
            ("completed", "Completed", "#34d399"),
            ("planned",   "Planned",   "#6b7280"),
            ("dropped",   "Dropped",   "#f87171"),
        ]:
            card = QFrame()
            card.setObjectName("statCard")
            card.setFixedHeight(66)
            card.setMinimumWidth(110)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            cl.setSpacing(2)

            val = QLabel("–")
            val.setStyleSheet(f"font-size:20px;font-weight:700;color:{color};")
            cl.addWidget(val)

            lbl = QLabel(label.upper())
            lbl.setStyleSheet(
                "font-size:10px;font-weight:700;letter-spacing:1px;"
                "color:#9da5c0;background:transparent;"
            )
            cl.addWidget(lbl)

            self._stat_labels[key] = val
            lay.addWidget(card)

        lay.addStretch()
        return w

    def _build_empty_state(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(14)

        icon = QLabel("📺")
        icon.setStyleSheet("font-size:52px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(icon)

        t = QLabel("Nothing here yet")
        t.setStyleSheet("font-size:18px;font-weight:600;color:#4a5070;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)

        s = QLabel("Add a currently airing or upcoming anime to start tracking.")
        s.setStyleSheet("font-size:13px;color:#3a3f55;")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(s)

        add = QPushButton("+ Add Anime")
        add.setObjectName("primaryBtn")
        add.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add.setFixedWidth(180)
        add.clicked.connect(self._open_add_dialog)
        lay.addWidget(add, alignment=Qt.AlignmentFlag.AlignCenter)
        return w

    def _build_status_bar(self) -> QStatusBar:
        bar = QStatusBar()
        self.conn_label = QLabel("⬤  Checking…")
        self.conn_label.setObjectName("connStatus")
        bar.addPermanentWidget(self.conn_label)
        return bar

    def _close_detail_panel(self):
        self.detail_panel.setVisible(False)
        self.selected_anime_id = None
        self._deselect_all_cards()

    def _open_detail_panel(self):
        self.detail_panel.setFixedWidth(390)
        self.detail_panel.setVisible(True)

    # ── Navigation ─────────────────────────────────────────────────────────────

    def _navigate(self, page_id: str):
        self.current_page = page_id
        self._set_nav_active(page_id)
        self.detail_panel.setVisible(False)
        self.selected_anime_id = None
        self._deselect_all_cards()

        if page_id == "discover":
            self.stack.setCurrentIndex(1)
            self.discover_page.load()
        elif page_id == "stats":
            self.stack.setCurrentIndex(2)
            self.stats_page.load()
        elif page_id == "hof":
            self.stack.setCurrentIndex(3)
            self.hof_page.load()
        else:
            self.stack.setCurrentIndex(0)
            titles = {
                "library":   "Library",
                "watching":  "Watching",
                "completed": "Completed",
                "planned":   "Plan to Watch",
                "dropped":   "Dropped",
            }
            self.page_title.setText(titles.get(page_id, page_id.title()))

            # Show filter pills ONLY on Library page
            self.filter_row.setVisible(page_id == "library")
            self.search_bar.setVisible(True)

            status_map = {
                "library":   None,
                "watching":  "watching",
                "completed": "completed",
                "planned":   "planned",
                "dropped":   "dropped",
            }
            # On non-library pages, reset filter so all of that status shows
            if page_id != "library":
                self._current_filter = "all"
            self._load_library(watch_status=status_map.get(page_id))

    def _set_nav_active(self, page_id: str):
        for pid, btn in self._nav_buttons.items():
            btn.setProperty("active", "true" if pid == page_id else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _set_filter(self, fid: str):
        self._current_filter = fid
        for pid, btn in self._filter_btns.items():
            btn.setProperty("active", "true" if pid == fid else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        ws = fid if fid not in ("all",) else None
        self._load_library(watch_status=ws)

    # ── Library loading ────────────────────────────────────────────────────────

    def _show_skeletons(self):
        """Show grey placeholder cards while real data loads."""
        COLS = self._calc_columns()
        for i in range(min(8, COLS * 2)):
            skel = QFrame()
            skel.setObjectName("animeCard")
            skel.setFixedSize(AnimeCard.CARD_WIDTH, AnimeCard.CARD_HEIGHT)
            skel.setStyleSheet(
                "QFrame{background:#0f1218;border:1px solid #1a1d28;border-radius:10px;}"
            )
            self.grid_layout.addWidget(skel, i // COLS, i % COLS)

    def _load_library(self, watch_status: Optional[str] = None):
        # Determine what status to query
        if watch_status is None and self._current_filter != "all":
            watch_status = self._current_filter

        if self._search_query:
            anime_list = self.db.search_anime(self._search_query)
        elif watch_status == "dropped":
            anime_list = self._get_dropped_as_anime()
        elif watch_status == "behind":
            # "Behind" = has aired episodes the user hasn't watched yet
            all_anime = self.db.get_all_anime(watch_status="watching", sort_by=self._sort_by)
            from datetime import datetime, timezone
            now_ts = int(datetime.now(timezone.utc).timestamp())
            anime_list = []
            for a in all_anime:
                next_ep = a.get("next_episode_num")
                next_at = a.get("next_episode_at")
                total   = a.get("total_episodes") or 0
                api_s   = (a.get("status") or "").upper()
                if next_ep and next_ep > 1:
                    aired = next_ep - 1
                elif total and api_s in ("FINISHED","CANCELLED"):
                    aired = total
                else:
                    aired = 0
                watched = self.db.get_watched_count(a["id"])
                if aired > 0 and watched < aired:
                    anime_list.append(a)
        else:
            anime_list = self.db.get_all_anime(watch_status=watch_status, sort_by=self._sort_by)

        # Clear grid
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)
        self._cards.clear()

        has = bool(anime_list)
        self.empty_state.setVisible(not has)
        self.grid_container.setVisible(has)

        if has:
            show_grouped = (
                self._current_filter == "all"
                and self.current_page == "library"
                and not self._search_query
            )
            if show_grouped:
                self._populate_grouped_grid(anime_list)
            else:
                COLS = self._calc_columns()
                for idx, anime in enumerate(anime_list):
                    card = AnimeCard(anime, self.db)
                    card.clicked.connect(lambda aid=anime["id"]: self._on_card_clicked(aid))
                    self._cards[anime["id"]] = card
                    self.grid_layout.addWidget(card, idx // COLS, idx % COLS)
                    self._load_card_image(anime, card)

        self._update_stats_strip()
        self._apply_card_overlays()

    def _populate_grouped_grid(self, anime_list: List[Dict]):
        """
        When viewing All, separate cards into status groups with a section header
        row between them.  Layout uses a single-column VBox of [header + HBox rows].
        """
        from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout
        COLS = self._calc_columns()
        groups = [
            ("▶  Watching",      "watching",  "#7c6af7"),
            ("⏳  Plan to Watch", "planned",   "#6b7280"),
            ("✓  Completed",     "completed", "#34d399"),
        ]
        row_num = 0
        for group_label, status, color in groups:
            members = [a for a in anime_list if a.get("watch_status") == status]
            if not members:
                continue
            # Section header as a full-width spanning label
            hdr = QLabel(f"  {group_label}  ({len(members)})")
            hdr.setStyleSheet(
                f"font-size:11px;font-weight:700;color:{color};"
                "background:transparent;padding:8px 0 4px 2px;"
            )
            self.grid_layout.addWidget(hdr, row_num, 0, 1, max(COLS, 1))
            row_num += 1
            for col_idx, anime in enumerate(members):
                if col_idx > 0 and col_idx % COLS == 0:
                    row_num += 1
                card = AnimeCard(anime, self.db)
                card.clicked.connect(lambda aid=anime["id"]: self._on_card_clicked(aid))
                self._cards[anime["id"]] = card
                self.grid_layout.addWidget(card, row_num, col_idx % COLS)
                self._load_card_image(anime, card)
            row_num += 1

    def _get_dropped_as_anime(self) -> List[Dict]:
        """Convert dropped_anime rows to anime-shaped dicts. Uses negative IDs to avoid collisions."""
        rows = self.db.get_dropped_anime()
        self._dropped_id_map = {}
        result = []
        for r in rows:
            fake_id = -(r["id"])   # negative so it never clashes with real anime IDs
            self._dropped_id_map[fake_id] = r["id"]
            result.append({
                "id":            fake_id,
                "romaji_title":  r["romaji_title"],
                "english_title": r.get("english_title",""),
                "watch_status":  "dropped",
                "status":        "FINISHED",
                "cover_url":     r.get("cover_url",""),
                "cover_local":   r.get("cover_local",""),
                "genres":        r.get("genres",[]),
                "total_episodes":r.get("last_episode"),
                "next_episode_at": None,
                "next_episode_num": None,
                "episode_offset": 0,
                "_dropped_id":   r["id"],   # keep real id for delete
                "anilist_id":    r.get("anilist_id"),
                "description":   "",
                "studios":       [],
                "average_score": None,
                "season":        "",
                "season_year":   None,
            })
        return result

    def _calc_columns(self) -> int:
        w = self.scroll_area.width() - 20
        return max(1, w // (AnimeCard.CARD_WIDTH + 14))

    def _load_card_image(self, anime: Dict, card: AnimeCard):
        local = anime.get("cover_local","")
        url   = anime.get("cover_url","")

        # 1. Use local cached file if it exists and is valid
        if local and Path(local).exists() and Path(local).stat().st_size > 500:
            card.set_cover(local)
            return

        # 2. Check image cache by URL
        if url and url.startswith("http"):
            from core.image_cache import get_cached_path
            cached = get_cached_path(url)
            if cached:
                card.set_cover(str(cached))
                # Update DB with correct local path
                self.db.update_anime(anime["id"], {"cover_local": str(cached)})
                return
            # 3. Download
            worker = ImageWorker(url, anime["id"], "card")
            worker.signals.result.connect(self._on_image_downloaded)
            run_worker(worker)
        elif url and not url.startswith("http"):
            card.set_cover(url)

    def _on_image_downloaded(self, result):
        anime_id, size, path = result
        if not path:
            return
        # Only update the card if this was a card-level download (size == "card" or int id)
        # Never overwrite an already-loaded card cover from a detail-panel download
        if size == "card" and anime_id in self._cards:
            self._cards[anime_id].set_cover(path)
            self.db.update_anime(anime_id, {"cover_local": path})
        elif size not in ("cover", "banner"):
            # Legacy: int-keyed download — update card only if no cover already set
            if anime_id in self._cards:
                self._cards[anime_id].set_cover(path)
            self.db.update_anime(anime_id, {"cover_local": path})
        # Detail panel images
        if self.selected_anime_id == anime_id:
            if size == "cover":
                self.detail_panel.set_cover(path)
            elif size == "banner":
                self.detail_panel.set_banner(path)

    def _update_stats_strip(self):
        stats = self.db.get_stats()
        for key in ("watching", "completed", "planned", "dropped"):
            lbl = self._stat_labels.get(key)
            if lbl:
                lbl.setText(str(stats.get(key, 0)))

    # ── Card interactions ──────────────────────────────────────────────────────

    def _on_card_clicked(self, anime_id: int):
        # Toggle detail panel
        if self.selected_anime_id == anime_id and self.detail_panel.isVisible():
            self.detail_panel.setVisible(False)
            self.selected_anime_id = None
            self._deselect_all_cards()
            return

        self.selected_anime_id = anime_id
        self._deselect_all_cards()
        if anime_id in self._cards:
            self._cards[anime_id].set_selected(True)

        # Dropped items: use fake negative ID to look up real dropped row
        if self.current_page == "dropped":
            real_dropped_id = self._dropped_id_map.get(anime_id)
            if real_dropped_id is None:
                return
            dropped = next(
                (d for d in self.db.get_dropped_anime() if d["id"] == real_dropped_id), None
            )
            if dropped:
                self.detail_panel.load_anime({
                    "id": anime_id,
                    "_dropped_id": real_dropped_id,
                    "romaji_title": dropped["romaji_title"],
                    "english_title": dropped.get("english_title",""),
                    "watch_status": "dropped",
                    "status": "",
                    "genres": dropped.get("genres",[]),
                    "description": "",
                    "cover_url": dropped.get("cover_url",""),
                    "cover_local": dropped.get("cover_local",""),
                    "total_episodes": dropped.get("last_episode"),
                    "next_episode_at": None,
                    "next_episode_num": None,
                    "episode_offset": 0,
                    "anilist_id": dropped.get("anilist_id"),
                    "studios": [],
                    "average_score": None,
                    "season": "",
                    "season_year": None,
                })
                self._open_detail_panel()
            return

        anime = self.db.get_anime_by_id(anime_id)
        if not anime:
            return

        self.detail_panel.load_anime(anime)
        self._open_detail_panel()

        # Load cover
        self._load_detail_images(anime)

    def _load_detail_images(self, anime: Dict):
        aid = anime["id"]

        # Always clear first so a previous anime's art never bleeds through
        self.detail_panel.clear_images()

        # Cover
        local = anime.get("cover_local","")
        url   = anime.get("cover_url","")
        if local and Path(local).exists() and Path(local).stat().st_size > 500:
            self.detail_panel.set_cover(local)
        elif url and url.startswith("http"):
            from core.image_cache import get_cached_path
            c = get_cached_path(url)
            if c:
                self.detail_panel.set_cover(str(c))
            else:
                w = ImageWorker(url, aid, "cover")
                w.signals.result.connect(self._on_image_downloaded)
                run_worker(w)
        # No url at all — placeholder already shown by clear_images()

        # Banner
        banner_url = anime.get("banner_url","")
        if banner_url:
            from core.image_cache import get_cached_path
            bc = get_cached_path(banner_url)
            if bc:
                self.detail_panel.set_banner(str(bc))
            else:
                wb = ImageWorker(banner_url, aid, "banner")
                wb.signals.result.connect(self._on_image_downloaded)
                run_worker(wb)
        else:
            # No banner — show solid color placeholder
            self.detail_panel.clear_banner()

    def _deselect_all_cards(self):
        for card in self._cards.values():
            card.set_selected(False)

    def _on_episode_changed(self, anime_id: int):
        anime = self.db.get_anime_by_id(anime_id)
        if anime and anime_id in self._cards:
            self._cards[anime_id].update_data(anime)
        self._update_stats_strip()

    def _on_anime_dropped(self, anime_id: int):
        self.detail_panel.setVisible(False)
        self.selected_anime_id = None
        self._load_library(
            watch_status=None if self.current_page == "library" else
            {"watching":"watching","completed":"completed","planned":"planned"}.get(self.current_page)
        )
        self._update_stats_strip()

    def _on_anime_deleted(self, anime_id: int):
        self.detail_panel.setVisible(False)
        self.selected_anime_id = None
        self._load_library()
        self._update_stats_strip()

    # ── Search & Sort ──────────────────────────────────────────────────────────

    def _on_sort_changed(self, index: int):
        sort_map = {
            0: "release_date",
            1: "title",
            2: "score",
            3: "date_added",
            4: "rating",
        }
        self._sort_by = sort_map.get(index, "release_date")
        self._load_library()
        # Apply persistent overlay to all cards based on sort
        self._apply_card_overlays()

    def _apply_card_overlays(self):
        """Set each card's overlay mode so scores/ratings stay visible."""
        overlay = None
        if self._sort_by == "score":
            overlay = "anilist_score"
        elif self._sort_by == "rating":
            overlay = "user_rating"
        for card in self._cards.values():
            card.set_overlay_mode(overlay)

    def _on_search(self, text: str):
        self._search_timer.stop()
        self._search_query = text.strip()
        self._search_timer.start(280)

    # ── Dialogs ────────────────────────────────────────────────────────────────

    def _open_add_dialog(self):
        dlg = AddAnimeDialog(self.db, self)
        if dlg.exec():
            self._load_library()
            self._update_stats_strip()

    def _open_settings(self):
        SettingsDialog(self.db, self).exec()

    # ── Timers ─────────────────────────────────────────────────────────────────

    def _setup_timers(self):
        self._countdown_timer.timeout.connect(self._tick)
        self._countdown_timer.start(1000)

        # Airing refresh every 10 min
        self._refresh_timer.timeout.connect(self._refresh_airing)
        self._refresh_timer.start(600_000)

        # Upcoming dates refresh every 30 min (upcoming anime dates change frequently)
        self._upcoming_timer = QTimer(self)
        self._upcoming_timer.timeout.connect(self._refresh_upcoming)
        self._upcoming_timer.start(1_800_000)  # 30 min

        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._load_library)

    def _tick(self):
        for card in self._cards.values():
            card.tick_countdown()

    def _refresh_airing(self):
        all_anime = self.db.get_all_anime(watch_status="watching")
        ids = [a["anilist_id"] for a in all_anime if a.get("anilist_id")]
        if not ids:
            return
        self.refresh_btn.setText("↻  Refreshing…")
        self.refresh_btn.setEnabled(False)

        worker = AiringRefreshWorker(ids)
        worker.signals.result.connect(self._on_airing_refreshed)
        worker.signals.finished.connect(lambda: (
            self.refresh_btn.setText("↻  Refresh Airing"),
            self.refresh_btn.setEnabled(True),
        ))
        run_worker(worker)

    def _on_airing_refreshed(self, results: Dict[int, Optional[Dict]]):
        for anilist_id, media in results.items():
            if not media:
                continue
            anime = self.db.get_anime_by_anilist_id(anilist_id)
            if not anime:
                continue
            updates: Dict[str, Any] = {
                "status":         media.get("status", anime["status"]),
                "total_episodes": media.get("episodes") or anime.get("total_episodes"),
                "average_score":  media.get("averageScore"),
            }
            nae = media.get("nextAiringEpisode")
            if nae:
                updates["next_episode_at"]  = nae.get("airingAt")
                updates["next_episode_num"] = nae.get("episode")
            else:
                updates["next_episode_at"] = None
            self.db.update_anime(anime["id"], updates)
            if anime["id"] in self._cards:
                refreshed = self.db.get_anime_by_id(anime["id"])
                if refreshed:
                    self._cards[anime["id"]].update_data(refreshed)

    # ── Upcoming date refresh ─────────────────────────────────────────────────

    def _refresh_upcoming(self):
        """Refresh start dates for all planned/upcoming anime every 30 min."""
        planned = self.db.get_all_anime(watch_status="planned")
        ids = [a["anilist_id"] for a in planned if a.get("anilist_id")]
        if not ids:
            return
        worker = AiringRefreshWorker(ids)
        worker.signals.result.connect(self._on_upcoming_refreshed)
        run_worker(worker)

    def _on_upcoming_refreshed(self, results: Dict[int, Optional[Dict]]):
        for anilist_id, media in results.items():
            if not media:
                continue
            anime = self.db.get_anime_by_anilist_id(anilist_id)
            if not anime:
                continue
            updates: Dict[str, Any] = {}
            nae = media.get("nextAiringEpisode")
            if nae:
                updates["next_episode_at"]  = nae.get("airingAt")
                updates["next_episode_num"] = nae.get("episode")
                # If upcoming anime now has an airing date, it might have started
                updates["status"] = media.get("status", anime["status"])
            sd = media.get("startDate")
            if sd:
                from core.api import format_air_date
                updates["start_date"] = format_air_date(sd)
                updates["season_year"] = sd.get("year")
            if updates:
                self.db.update_anime(anime["id"], updates)
                if anime["id"] in self._cards:
                    refreshed = self.db.get_anime_by_id(anime["id"])
                    if refreshed:
                        self._cards[anime["id"]].update_data(refreshed)

    # ── Update check ───────────────────────────────────────────────────────────

    def _check_for_updates(self):
        """Check GitHub Releases for a newer version. Runs in background."""
        from core.updater import UpdateChecker
        from workers.workers import get_pool
        checker = UpdateChecker()
        checker.signals.update_available.connect(self._on_update_available)
        get_pool().start(checker)

    def _on_update_available(self, version: str, notes: str, url: str):
        self.update_banner.show_update(version, notes, url)

    # ── Connection check ───────────────────────────────────────────────────────

    def _check_connection(self):
        def check():
            from core.api import check_connection
            return check_connection()
        w = Worker(check)
        w.signals.result.connect(self._on_conn_result)
        run_worker(w)

    def _on_conn_result(self, result):
        ok, quality, ms = result
        if not ok:
            self.conn_label.setText("⬤  Offline")
            self.conn_label.setStyleSheet("color:#f87171;")
        elif quality == "poor":
            self.conn_label.setText(f"⬤  Slow  ({ms:.0f}ms)")
            self.conn_label.setStyleSheet("color:#fbbf24;")
        else:
            self.conn_label.setText(f"⬤  Online  ({ms:.0f}ms)")
            self.conn_label.setStyleSheet("color:#34d399;")

    # ── Resize ─────────────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(60, self._load_library)