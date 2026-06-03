"""
Miroku — Main Window
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
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRectF
from PyQt6.QtGui import QPixmap, QColor, QFont, QIcon, QCursor, QPainterPath, QRegion

from core.database import DatabaseManager
from workers.workers import Worker, ImageWorker, AiringRefreshWorker, run_worker
# UI modules imported lazily to speed up startup
from ui.anime_card import AnimeCard
from ui.update_banner import UpdateBanner


NAV_SECTIONS = [
    ("Library", [
        ("Library", "LIB", "library"),
        ("Dropped", "DROP", "dropped"),
    ]),
    ("Explore", [
        ("Discover", "DISC", "discover"),
        ("Calendar", "CAL", "calendar"),
        ("Miroku Stream", "PLAY", "stream"),
    ]),
    ("Personal", [
        ("Hall of Fame", "HOF", "hof"),
        ("Statistics", "DATA", "stats"),
    ]),
]

# Pages that show the filter pill row (All / Watching / Completed / Planned)
_FILTER_PAGES = {"library"}


def _build_app_icon() -> QIcon:
    resources = Path(__file__).parent.parent / "resources"
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 96, 128, 180, 192, 256, 512, 1024):
        path = resources / f"miroku_lettermark_{size}.png"
        if path.exists():
            icon.addFile(str(path))
    if icon.isNull():
        ico = resources / "miroku_app_icon.ico"
        if ico.exists():
            icon = QIcon(str(ico))
    return icon


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
        self._notification_timer = QTimer(self)

        self.setWindowTitle("Miroku")
        self.setMinimumSize(1100, 700)

        # Window icon
        app_icon = _build_app_icon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        self.showMaximized()   # Always open fullscreen

        self._load_theme()
        self._build_ui()
        self._setup_timers()
        self._load_library()
        self._check_connection()
        self._check_for_updates()
        QTimer.singleShot(800, self._maybe_show_onboarding)

    # ── Theme ──────────────────────────────────────────────────────────────────

    def _load_theme(self, mode: str = "dark"):
        from core.app_settings import resolved_theme
        qss_file  = f"{resolved_theme()}.qss"
        qss_path  = Path(__file__).parent.parent / "resources" / "themes" / qss_file
        if not qss_path.exists():
            qss_path = Path(__file__).parent.parent / "resources" / "themes" / "dark.qss"
        if qss_path.exists():
            QApplication.instance().setStyleSheet(qss_path.read_text(encoding="utf-8"))

    def toggle_theme(self):
        from core.app_settings import preferred_theme, set_preferred_theme
        current  = preferred_theme()
        new_theme = "light" if current == "dark" else "dark"
        set_preferred_theme(new_theme)
        self._load_theme(new_theme)

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
        self.update_banner = UpdateBanner()
        # (banner wired into central_vbox later)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(0)

        # Stacked pages — heavy pages loaded lazily on first navigation
        self.stack = QStackedWidget()
        self.stack.setObjectName("contentArea")

        self.library_page   = self._build_library_page()
        self.stack.addWidget(self.library_page)   # idx 0 — loaded immediately

        # Placeholders for lazy-loaded pages
        self._discover_page = None
        self._stats_page    = None
        self._hof_page      = None
        self._stream_page   = None
        self._calendar_page = None

        # Add placeholder widgets so indices stay fixed
        for _ in range(5):
            ph = QWidget()
            ph.setObjectName("contentArea")
            self.stack.addWidget(ph)

        content_row.addWidget(self.stack, stretch=1)

        # Detail panel — fixed width, hidden by default
        from ui.detail_panel import DetailPanel
        self.detail_panel = DetailPanel(self.db, self)
        self.detail_panel.setFixedWidth(390)
        self.detail_panel.setVisible(False)
        self.detail_panel.episode_changed.connect(self._on_episode_changed)
        self.detail_panel.watch_status_changed.connect(self._on_watch_status_changed)
        self.detail_panel.stats_changed.connect(self._update_stats_strip)
        self.detail_panel.anime_dropped.connect(self._on_anime_dropped)
        self.detail_panel.anime_deleted.connect(self._on_anime_deleted)
        content_row.addWidget(self.detail_panel)

        # central_content holds ONLY the content row — banner floats above it
        self.central_content = QWidget()
        central_vbox = QVBoxLayout(self.central_content)
        central_vbox.setContentsMargins(0, 0, 0, 0)
        central_vbox.setSpacing(0)
        content_widget = QWidget()
        content_widget.setLayout(content_row)
        central_vbox.addWidget(content_widget)
        root.addWidget(self.central_content)

        # Toast banner — parented to central widget so it floats over content
        # Re-parent it here so it overlays correctly
        self.update_banner.setParent(central)
        self.update_banner.raise_()
        from ui.notification_banner import NotificationBanner
        self.notification_banner = NotificationBanner(central)
        self.notification_banner.open_anime.connect(self._open_notification_anime)
        self.notification_banner.mark_watched.connect(self._mark_notification_episode)
        self.notification_banner.move_to_watching.connect(self._move_notification_to_watching)
        self.notification_banner.remind_later.connect(self._remind_notification_later)
        self.notification_banner.dismissed.connect(self._dismiss_notification)
        self.setStatusBar(self._build_status_bar())


    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(232)
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(14, 0, 14, 14)
        lay.setSpacing(0)

        # Brand
        logo_w = QWidget()
        logo_w.setObjectName("sidebarBrand")
        ll = QVBoxLayout(logo_w)
        ll.setContentsMargins(0, 22, 0, 18)
        ll.setSpacing(7)
        ll.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        resources = Path(__file__).parent.parent / "resources"
        lettermark_path = resources / "miroku_lettermark_512.png"
        icon_path = lettermark_path if lettermark_path.exists() else resources / "miroku_lettermark_256.png"
        if icon_path.exists():
            icon_lbl = QLabel()
            px = QPixmap(str(icon_path)).scaled(
                44, 44, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            icon_lbl.setPixmap(px)
            icon_lbl.setObjectName("sidebarLogoMark")
            icon_lbl.setFixedSize(48, 44)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ll.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignHCenter)

        sub = QLabel("Anime progress tracker")
        sub.setObjectName("appLogoSub")
        sub.setWordWrap(False)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ll.addWidget(sub, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(logo_w)

        self._nav_buttons: Dict[str, QPushButton] = {}
        for section, items in NAV_SECTIONS:
            header = QLabel(section.upper())
            header.setObjectName("sidebarSectionLabel")
            lay.addWidget(header)
            lay.addSpacing(6)

            for label, token, page_id in items:
                btn = QPushButton(f"{token:<4}  {label}")
                btn.setObjectName("navBtn")
                btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                btn.clicked.connect(lambda _, p=page_id: self._navigate(p))
                self._nav_buttons[page_id] = btn
                lay.addWidget(btn)
                lay.addSpacing(4)

            lay.addSpacing(12)

        lay.addStretch()

        add_btn = QPushButton("+  Add Anime")
        add_btn.setObjectName("primaryBtn")
        add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_btn.clicked.connect(self._open_add_dialog)
        lay.addWidget(add_btn)
        lay.addSpacing(8)

        cfg_btn = QPushButton("SET   Settings")
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
            b.setObjectName("filterPillBehind" if fid == "behind" else "filterPill")
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
            card.setFixedHeight(80)
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
            if self._discover_page is None:
                from ui.discover_page import DiscoverPage
                self._discover_page = DiscoverPage(self.db, self)
                self.stack.removeWidget(self.stack.widget(1))
                self.stack.insertWidget(1, self._discover_page)
            self.stack.setCurrentIndex(1)
            self._discover_page.load()
        elif page_id == "stats":
            if self._stats_page is None:
                from ui.stats_page import StatsPage
                self._stats_page = StatsPage(self.db, self)
                self.stack.removeWidget(self.stack.widget(2))
                self.stack.insertWidget(2, self._stats_page)
            self.stack.setCurrentIndex(2)
            self._stats_page.load()
        elif page_id == "hof":
            if self._hof_page is None:
                from ui.hall_of_fame import HallOfFamePage
                self._hof_page = HallOfFamePage(self.db, self)
                self.stack.removeWidget(self.stack.widget(3))
                self.stack.insertWidget(3, self._hof_page)
            self.stack.setCurrentIndex(3)
            self._hof_page.load()
        elif page_id == "stream":
            if self._stream_page is None:
                from ui.animestream_page import AnimeStreamPage
                self._stream_page = AnimeStreamPage(self.db, self)
                self.stack.removeWidget(self.stack.widget(4))
                self.stack.insertWidget(4, self._stream_page)
            self.stack.setCurrentIndex(4)
        elif page_id == "calendar":
            if self._calendar_page is None:
                from ui.release_calendar_page import ReleaseCalendarPage
                self._calendar_page = ReleaseCalendarPage(self.db, self)
                self._calendar_page.anime_selected.connect(self._open_anime_from_calendar)
                self._calendar_page.data_changed.connect(self._on_episode_changed)
                self.stack.removeWidget(self.stack.widget(5))
                self.stack.insertWidget(5, self._calendar_page)
            self.stack.setCurrentIndex(5)
            self._calendar_page.load()
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
        """Show shimmer skeleton cards immediately while DB fetch runs."""
        COLS = self._calc_columns()
        count = min(12, COLS * 3)
        for i in range(count):
            skel = _SkeletonCard()
            self.grid_layout.addWidget(skel, i // COLS, i % COLS)

    def _load_library(self, watch_status: Optional[str] = None):
        """
        Non-blocking library load:
        1. Show skeleton cards immediately (instant visual feedback)
        2. Fetch data from DB in background worker
        3. Replace skeletons with real cards when done
        """
        if watch_status is None and self._current_filter != "all":
            watch_status = self._current_filter

        # Show skeletons FIRST — instant feedback before any data work
        self._clear_grid()
        self.empty_state.setVisible(False)
        self.grid_container.setVisible(True)
        self._show_skeletons()

        # Snapshot params for the background worker
        search_q   = self._search_query
        sort_by    = self._sort_by
        current_filter = self._current_filter
        current_page   = self.current_page

        def fetch_data():
            if search_q:
                return self.db.search_anime(search_q)
            elif watch_status == "dropped":
                return self._get_dropped_as_anime()
            elif watch_status == "behind":
                from datetime import datetime, timezone
                all_anime = self.db.get_all_anime(watch_status="watching", sort_by=sort_by)
                result = []
                for a in all_anime:
                    next_ep = a.get("next_episode_num")
                    total   = a.get("total_episodes") or 0
                    api_s   = (a.get("status") or "").upper()
                    aired   = (next_ep - 1) if (next_ep and next_ep > 1) else (
                               total if (total and api_s in ("FINISHED","CANCELLED")) else 0)
                    watched = self.db.get_watched_count(a["id"])
                    if aired > 0 and watched < aired:
                        result.append(a)
                return result
            else:
                return self.db.get_all_anime(watch_status=watch_status, sort_by=sort_by)

        worker = Worker(fetch_data)
        worker.signals.result.connect(
            lambda anime_list: self._render_library(
                anime_list, current_filter, current_page
            )
        )
        run_worker(worker)

    def _clear_grid(self):
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)
        self._cards.clear()

    def _render_library(self, anime_list: List[Dict],
                         current_filter: str, current_page: str):
        """Called from worker result — renders real cards replacing skeletons."""
        self._clear_grid()

        has = bool(anime_list)
        self.empty_state.setVisible(not has)
        self.grid_container.setVisible(has)

        if has:
            show_grouped = (
                current_filter == "all"
                and current_page == "library"
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
            ("〡 WATCHING",    "watching",  "#a594f9"),
            ("〡 PLAN TO WATCH", "planned", "#6b7280"),
            ("〡 COMPLETED",   "completed", "#34d399"),
        ]
        row_num = 0
        for group_label, status, color in groups:
            members = [a for a in anime_list if a.get("watch_status") == status]
            if not members:
                continue
            # Section header as a full-width spanning label
            hdr = QLabel(f"{group_label}  ·  {len(members)} titles")
            hdr.setObjectName("libSectionHeader")
            hdr.setStyleSheet(f"color:{color};")
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

    def _open_anime_from_calendar(self, anime_id: int):
        self._navigate("library")
        anime = self.db.get_anime_by_id(anime_id)
        if not anime:
            return
        self.selected_anime_id = anime_id
        self.detail_panel.load_anime(anime)
        self._open_detail_panel()
        self._load_detail_images(anime)

    def _deselect_all_cards(self):
        for card in self._cards.values():
            card.set_selected(False)

    def _on_episode_changed(self, anime_id: int):
        anime = self.db.get_anime_by_id(anime_id)
        if anime and anime_id in self._cards:
            self._cards[anime_id].update_data(anime)
        self._update_stats_strip()
        if self._calendar_page is not None:
            self._calendar_page.load()

    def _on_watch_status_changed(self, anime_id: int, new_status: str):
        """Remove or update cards when watch status no longer matches the active view."""
        self._update_stats_strip()

        if (
            self.current_page == "library"
            and self._current_filter == "all"
            and not self._search_query
        ):
            self._load_library()
            return

        if self._search_query:
            anime = self.db.get_anime_by_id(anime_id)
            if anime and anime_id in self._cards:
                self._cards[anime_id].update_data(anime)
            return

        if not self._anime_belongs_on_current_view(new_status, anime_id):
            self._remove_card_from_grid(anime_id)
            if self.selected_anime_id == anime_id:
                self.detail_panel.setVisible(False)
                self.selected_anime_id = None
            return

        anime = self.db.get_anime_by_id(anime_id)
        if not anime:
            return
        if anime_id in self._cards:
            self._cards[anime_id].update_data(anime)
        else:
            self._load_library_for_current_page()

    def _anime_belongs_on_current_view(self, watch_status: str, anime_id: int) -> bool:
        page_map = {
            "watching": "watching",
            "planned": "planned",
            "completed": "completed",
        }
        if self.current_page in page_map:
            return watch_status == page_map[self.current_page]

        if self.current_page != "library":
            return True

        if self._current_filter in (None, "all"):
            return True

        if self._current_filter == "behind":
            if watch_status != "watching":
                return False
            anime = self.db.get_anime_by_id(anime_id)
            if not anime:
                return False
            next_ep = anime.get("next_episode_num")
            total = anime.get("total_episodes") or 0
            api_s = (anime.get("status") or "").upper()
            aired = (next_ep - 1) if (next_ep and next_ep > 1) else (
                total if (total and api_s in ("FINISHED", "CANCELLED")) else 0
            )
            watched = self.db.get_watched_count(anime_id)
            return aired > 0 and watched < aired

        if self._current_filter == "dropped":
            return watch_status == "dropped"

        return watch_status == self._current_filter

    def _remove_card_from_grid(self, anime_id: int):
        card = self._cards.pop(anime_id, None)
        if card:
            self.grid_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        has_cards = bool(self._cards)
        self.empty_state.setVisible(not has_cards)
        self.grid_container.setVisible(has_cards)

    def _load_library_for_current_page(self):
        status_map = {
            "watching": "watching",
            "planned": "planned",
            "completed": "completed",
            "dropped": "dropped",
        }
        if self.current_page in status_map:
            self._load_library(watch_status=status_map[self.current_page])
        else:
            self._load_library()

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
        from ui.add_dialog import AddAnimeDialog
        dlg = AddAnimeDialog(self.db, self)
        if dlg.exec():
            self._load_library()
            self._update_stats_strip()
            if getattr(dlg, "added_title", ""):
                from ui.toast import Toast
                if getattr(dlg, "added_to_hof", False):
                    Toast.show(
                        self,
                        f"'{dlg.added_title}' added to Hall of Fame.",
                        kind="success",
                    )
                    if self._hof_page is not None:
                        self._hof_page.load()
                else:
                    Toast.show(
                        self,
                        f"'{dlg.added_title}' added as {dlg.added_status}.",
                        kind="success",
                    )

    def _open_settings(self):
        from ui.settings_dialog import SettingsDialog
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

        self._notification_timer.timeout.connect(self._scan_notifications)
        self._notification_timer.start(300_000)
        QTimer.singleShot(1800, self._scan_notifications)

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
        if self._calendar_page is not None:
            self._calendar_page.load()
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
        if self._calendar_page is not None:
            self._calendar_page.load()
    # ── Onboarding ─────────────────────────────────────────────────────────────

    def _maybe_show_onboarding(self):
        # ── Toggle for testing: set True to always show tutorial ──────────────
        FORCE_ONBOARDING = False
        # ─────────────────────────────────────────────────────────────────────
        from core.app_settings import app_settings
        settings    = app_settings()
        seen        = settings.value("onboarding_seen", False, type=bool)
        total_anime = len(self.db.get_all_anime())
        # First ever use = never seen the tour AND library is completely empty
        is_first_use = (not seen) and (total_anime == 0)
        if FORCE_ONBOARDING or is_first_use:
            from ui.onboarding import OnboardingOverlay
            overlay = OnboardingOverlay(self, self.centralWidget())
            overlay.finished.connect(
                lambda: settings.setValue("onboarding_seen", True)
            )

    # ── Update check ───────────────────────────────────────────────────────────

    def _check_for_updates(self):
        """Check GitHub Releases for a newer version. Runs in background."""
        from core.updater import UpdateChecker
        from workers.workers import get_pool
        checker = UpdateChecker()
        checker.signals.update_available.connect(self._on_update_available)
        get_pool().start(checker)

    def _on_update_available(self, version: str, notes: str, url: str):
        # Ensure banner is parented to centralWidget so it floats correctly
        self.update_banner.setParent(self.centralWidget())
        self.update_banner._reposition()
        self.update_banner.show_update(version, notes, url)
        self.update_banner.raise_()

    # ── Connectivity monitor ───────────────────────────────────────────────────

    def _scan_notifications(self):
        from core.notification_service import NotificationService
        service = NotificationService(self.db)
        worker = Worker(service.scan)
        worker.signals.result.connect(self._on_notifications_ready)
        run_worker(worker)

    def _on_notifications_ready(self, notifications):
        if notifications:
            self.notification_banner.show_notifications(notifications)
        else:
            self.notification_banner.clear_if_idle()

    def _open_notification_anime(self, anime_id: int):
        self._open_anime_from_calendar(anime_id)

    def _mark_notification_episode(self, anime_id: int, episode: int):
        if not anime_id or not episode:
            return
        self.db.set_episode_watched(anime_id, episode, True)
        self._on_episode_changed(anime_id)
        from ui.toast import Toast
        Toast.show(self, f"Episode {episode} marked watched.", kind="success")

    def _move_notification_to_watching(self, anime_id: int):
        if not anime_id:
            return
        self.db.update_anime(anime_id, {"watch_status": "watching"})
        self._on_watch_status_changed(anime_id, "watching")
        from ui.toast import Toast
        Toast.show(self, "Moved to Watching.", kind="success")

    def _remind_notification_later(self, notification_id: int):
        self.db.remind_notification_later(notification_id, hours=24)
        from ui.toast import Toast
        Toast.show(self, "Reminder moved to tomorrow.", kind="info")

    def _dismiss_notification(self, notification_id: int):
        self.db.dismiss_notification(notification_id)

    def _check_connection(self):
        from core.connectivity import ConnectivityMonitor
        self._conn_monitor = ConnectivityMonitor(self)
        self._conn_monitor.status_changed.connect(self._on_conn_status)
        self._conn_monitor.went_offline.connect(self._on_went_offline)
        self._conn_monitor.reconnected.connect(self._on_reconnected)
        self._conn_monitor.start()

    def _on_conn_status(self, is_online: bool, latency_ms: float):
        if not is_online:
            self.conn_label.setText("⬤  Offline")
            self.conn_label.setStyleSheet("color:#f87171;")
        elif latency_ms > 600:
            self.conn_label.setText(f"⬤  Slow  ({latency_ms:.0f}ms)")
            self.conn_label.setStyleSheet("color:#fbbf24;")
        else:
            self.conn_label.setText(f"⬤  Online  ({latency_ms:.0f}ms)")
            self.conn_label.setStyleSheet("color:#34d399;")

    def _on_went_offline(self):
        """Show floating offline banner."""
        if not hasattr(self, "_offline_banner"):
            from ui.offline_banner import OfflineBanner
            self._offline_banner = OfflineBanner(self.centralWidget())
        self._offline_banner.show_offline()

    def _on_reconnected(self):
        """Hide offline banner and refresh airing data."""
        if hasattr(self, "_offline_banner"):
            self._offline_banner.hide_offline()
        QTimer.singleShot(500, self._refresh_airing)

    # ── Resize ─────────────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(60, self._load_library)
        if hasattr(self, "update_banner") and self.update_banner.isVisible():
            self.update_banner._reposition()
        if hasattr(self, "notification_banner") and self.notification_banner.isVisible():
            self.notification_banner._reposition()
        if hasattr(self, "_offline_banner") and self._offline_banner.isVisible():
            self._offline_banner.reposition()

# ── Skeleton card widget ───────────────────────────────────────────────────────

class _SkeletonCard(QFrame):
    """
    Animated shimmer placeholder shown while library data loads.
    Pure CSS animation — no timers needed.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(AnimeCard.CARD_WIDTH, AnimeCard.CARD_HEIGHT)
        self.setObjectName("skeletonCard")
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(0, 0, AnimeCard.CARD_WIDTH, AnimeCard.CARD_HEIGHT),
            AnimeCard.CARD_RADIUS,
            AnimeCard.CARD_RADIUS,
        )
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        self.setStyleSheet("""
            QFrame#skeletonCard {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #111420, stop:0.5 #1a1d2e, stop:1 #111420
                );
                border: none;
            }
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Poster skeleton — full bleed, text lines overlaid at bottom
        cover = QFrame()
        cover.setFixedSize(AnimeCard.CARD_WIDTH, AnimeCard.CARD_HEIGHT)
        cover.setStyleSheet("background:#131620;border:none;")
        lay.addWidget(cover)

        # Shimmer text lines at bottom to suggest info overlay
        for w_frac, ypos in [(0.7, AnimeCard.CARD_HEIGHT - 46),
                              (0.55, AnimeCard.CARD_HEIGHT - 30),
                              (1.0, AnimeCard.CARD_HEIGHT - 6)]:
            line = QFrame(cover)
            line.setFixedSize(int(AnimeCard.CARD_WIDTH * w_frac), 6)
            line.move(10, ypos)
            line.setStyleSheet(
                "background:#1e2130;border-radius:3px;border:none;"
            )

        # Shimmer animation via QPropertyAnimation on opacity would require
        # QGraphicsOpacityEffect; instead use a simple QTimer pulse
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._pulse)
        self._timer.start(600)

    def _pulse(self):
        self._phase = 1 - self._phase
        bg = "#1a1d2e" if self._phase else "#111420"
        self.setStyleSheet(f"""
            QFrame#skeletonCard {{
                background:{bg};
                border:1px solid #1a1d28;
                border-radius:10px;
            }}
        """)
