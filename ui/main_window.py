"""
Miroku — Main Window
Fixed:
  - Filter pills (All/Watching/Completed/Planned) ONLY shown on Library page
  - Dropped section loads and displays correctly
  - Stats strip updates in real-time on every status change
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
from ui.theme import QColor  # noqa: E402,F811  (theme-aware colours)

from core.database import DatabaseManager
from workers.workers import Worker, ImageWorker, AiringRefreshWorker, run_worker
# UI modules imported lazily to speed up startup
from ui.anime_card import AnimeCard
from ui.update_banner import UpdateBanner


# Raikō: one sidebar, a section per library. Each library keeps its own
# tools under its own name.
NAV_SECTIONS = [
    ("", [("Home", "⌂", "home"), ("Hall of Fame", "★", "hall"), ("Music", "♪", "music")]),
    ("Miroku", [
        ("Library", "LIB", "library"),
        ("Dropped", "DROP", "dropped"),
        ("Discover", "DISC", "discover"),
    ]),
    ("Kinema", [
        ("Movies", "MOV", "movies"),
        ("TV shows", "TV", "tv"),
        ("Discover", "DISC", "kinema_discover"),
    ]),
]

# Pages that show the filter pill row (All / Watching / Completed / Planned)
_FILTER_PAGES = {"library"}


_ERROR_WINDOW = None


def _watch_app_errors(window):
    """Chain onto sys.excepthook (main.py's crash guard logs the error);
    then let the current window raise an 'Open Data Doctor' alert."""
    import sys
    import weakref
    global _ERROR_WINDOW
    first = _ERROR_WINDOW is None
    _ERROR_WINDOW = weakref.ref(window)
    if not first:
        return
    previous = sys.excepthook

    def hook(t, v, tb):
        previous(t, v, tb)
        w = _ERROR_WINDOW() if _ERROR_WINDOW else None
        if w is not None:
            try:
                QTimer.singleShot(0, w._on_app_error)
            except Exception:
                pass

    sys.excepthook = hook


def _build_app_icon() -> QIcon:
    resources = Path(__file__).parent.parent / "resources"
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 96, 128, 180, 192, 256, 512, 1024):
        path = resources / f"raiko_icon_{size}.png"
        if path.exists():
            icon.addFile(str(path))
    if icon.isNull():
        ico = resources / "raiko_app_icon.ico"
        if ico.exists():
            icon = QIcon(str(ico))
    return icon


class MainWindow(QMainWindow):
    def __init__(self, db: DatabaseManager, demo_new_season: bool = False,
                 demo_planned: bool = False):
        super().__init__()
        self.db = db
        self._demo_new_season = demo_new_season
        self._demo_planned = demo_planned
        self._meta_sync_running = False
        self._show_archived = False
        self._media = "anime"           # which library the grid shows
        self._completed_groups: Dict[str, List[int]] = {}
        self._fold_overrides: Dict[str, bool] = self._load_fold_overrides()
        self._demo_items: List[Dict] = []
        self.current_page = "library"
        self.selected_anime_id: Optional[int] = None
        self._cards: Dict[int, AnimeCard] = {}
        self._dropped_id_map: Dict[int, int] = {}  # fake_id -> real dropped_id
        self._pending_ep_refresh: Dict[int, float] = {}  # anime_id -> last refresh attempt (monotonic)
        self._current_filter = "all"
        self._search_query   = ""
        self._sort_by        = "release_date"

        self._countdown_timer = QTimer(self)
        self._refresh_timer   = QTimer(self)
        self._search_timer    = QTimer(self)
        self._notification_timer = QTimer(self)

        self.setWindowTitle("Raikō")
        self.setMinimumSize(1100, 700)

        # Window icon
        app_icon = _build_app_icon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        self.showMaximized()   # Always open fullscreen

        self._load_theme()
        self._build_ui()
        self._setup_timers()
        # Living themes: ambient effects, ornaments, Rai (click-through overlay)
        from ui import decor
        decor.register("settings_button", self._settings_btn)
        decor.register("add_button", self._add_btn)
        if "hall" in self._nav_buttons:
            decor.register("hall_nav", self._nav_buttons["hall"])
        self._decor = decor.DecorLayer(self.centralWidget())
        QTimer.singleShot(1800, self._event_ended_note)
        self._load_library()
        self._check_connection()
        self._check_anilist_status()
        self._check_tmdb_status()
        # Raikō opens on Home (Settings key 'start_page' can say 'library')
        try:
            from core.app_settings import app_settings
            start = app_settings().value("start_page", "home")
        except Exception:
            start = "home"
        if start == "home":
            QTimer.singleShot(0, lambda: self._navigate("home"))
        self._check_for_updates()
        self._setup_anilist_session()
        QTimer.singleShot(800, self._maybe_show_onboarding)
        if self._demo_new_season:
            QTimer.singleShot(3000, self._inject_demo_new_season)
        if self._demo_planned:
            QTimer.singleShot(3500, self._inject_demo_planned)

    # ── Theme ──────────────────────────────────────────────────────────────────

    def _load_theme(self, mode: str = "dark"):
        from core.app_settings import resolved_theme
        qss_file  = f"{resolved_theme()}.qss"
        qss_path  = Path(__file__).parent.parent / "resources" / "themes" / qss_file
        if not qss_path.exists():
            qss_path = Path(__file__).parent.parent / "resources" / "themes" / "dark.qss"
        if qss_path.exists():
            from ui.theme import ThemeManager
            ThemeManager.get().set_base_stylesheet(qss_path.read_text(encoding="utf-8"))

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
        self._content_row = content_row

        # Stacked pages — heavy pages loaded lazily on first navigation
        self.stack = QStackedWidget()
        self.stack.setObjectName("contentArea")

        self.library_page   = self._build_library_page()
        self.stack.addWidget(self.library_page)   # idx 0 — loaded immediately

        # Placeholders for lazy-loaded pages
        self._discover_page = None

        # Add placeholder widgets so indices stay fixed
        for _ in range(9):       # 1-5 Miroku pages, 6 Kinema Discover, 7 Home, 8 Hall of Fame, 9 Music
            ph = QWidget()
            ph.setObjectName("contentArea")
            self.stack.addWidget(ph)
        self._kinema_discover = None
        self._home_page = None
        self._hall_page = None
        self._music_page = None
        from ui.music_actions import MusicHub
        MusicHub.get().db = self.db

        content_row.addWidget(self.stack, stretch=1)

        # Content host — detail panel overlays here (does not reflow the grid)
        self._content_host = QWidget()
        host_lay = QVBoxLayout(self._content_host)
        host_lay.setContentsMargins(0, 0, 0, 0)
        host_lay.setSpacing(0)
        host_lay.addLayout(content_row)

        self._detail_scrim = QFrame(self._content_host)
        self._detail_scrim.setObjectName("detailScrim")
        self._detail_scrim.hide()
        self._detail_scrim.mousePressEvent = lambda e: self._close_detail_panel()

        from ui.detail_panel import DetailPanel
        self.detail_panel = DetailPanel(self.db, self._content_host)
        self.detail_panel.hall_changed.connect(self._on_hall_changed)
        self.detail_panel.setFixedWidth(390)
        self.detail_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.detail_panel.setStyleSheet(
            "DetailPanel{background-color:#0a0c10;border-left:1px solid #1a1d28;}"
        )
        self.detail_panel.hide()
        self.detail_panel.close_requested.connect(self._close_detail_panel)
        self.detail_panel.episode_changed.connect(self._on_episode_changed)
        self.detail_panel.watch_status_changed.connect(self._on_watch_status_changed)
        self.detail_panel.stats_changed.connect(self._update_stats_strip)
        self.detail_panel.anime_dropped.connect(self._on_anime_dropped)
        self.detail_panel.anime_deleted.connect(self._on_anime_deleted)
        self.detail_panel.links_changed.connect(self._on_detail_links_changed)
        self.detail_panel.archive_changed.connect(self._on_archive_changed)
        self.detail_panel.open_sequel.connect(self._on_card_new_season)
        self.detail_panel.dropped_restored.connect(self._on_dropped_restored)
        self.detail_panel.rewatch_changed.connect(self._on_rewatch_changed)
        self.detail_panel.movie_changed.connect(self._on_movie_changed)
        self.detail_panel.dropped_removed.connect(self._on_dropped_removed)

        # central_content holds ONLY the content host — banner floats above it
        self.central_content = QWidget()
        central_vbox = QVBoxLayout(self.central_content)
        central_vbox.setContentsMargins(0, 0, 0, 0)
        central_vbox.setSpacing(0)
        central_vbox.addWidget(self._content_host)
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
        self.notification_banner.play_trailer.connect(self._play_trailer)
        self.notification_banner.open_doctor.connect(self.open_data_doctor)
        _watch_app_errors(self)
        from ui.new_season_spotlight import NewSeasonSpotlight
        self.new_season_spotlight = NewSeasonSpotlight(central)
        self.new_season_spotlight.dismissed.connect(self._dismiss_new_season)
        self.new_season_spotlight.remind_later.connect(self._remind_new_season)
        self.new_season_spotlight.open_prequel.connect(self._open_notification_anime)
        self.new_season_spotlight.add_requested.connect(self._add_new_season)
        self.setStatusBar(self._build_status_bar())


    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        from ui import decor as _decor
        _decor.register("sidebar", sidebar)
        self.sidebar = sidebar
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
        icon_path = resources / "raiko_glyph_256.png"
        if icon_path.exists():
            icon_lbl = QLabel()
            px = QPixmap(str(icon_path)).scaled(
                44, 44, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            icon_lbl.setPixmap(px)
            icon_lbl.setObjectName("sidebarLogoMark")
            from ui import decor as _decor
            _decor.register("logo", icon_lbl)
            icon_lbl.setFixedSize(48, 44)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ll.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignHCenter)

        name = QLabel("Raikō")
        name.setObjectName("appLogoName")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ll.addWidget(name, alignment=Qt.AlignmentFlag.AlignHCenter)
        sub = QLabel("Anime · TV · Movies")
        sub.setObjectName("appLogoSub")
        sub.setWordWrap(False)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ll.addWidget(sub, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(logo_w)

        self._nav_buttons: Dict[str, QPushButton] = {}
        brands = {"Miroku": ("#8b7bff", "Anime"), "Kinema": ("#fbbf24", "Movies & TV")}
        for section, items in NAV_SECTIONS:
            if section in brands:
                color, what = brands[section]
                header = QWidget()
                header.setObjectName("sidebarBrandHeader")
                hl = QHBoxLayout(header)
                hl.setContentsMargins(14, 2, 8, 2)
                hl.setSpacing(8)
                dot = QLabel()
                dot.setFixedSize(16, 16)
                mark = resources / f"{section.lower()}_mark_64.png"
                if mark.exists():
                    dot.setPixmap(QPixmap(str(mark)).scaled(
                        16, 16, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation))
                else:
                    dot.setFixedSize(8, 8)
                    dot.setStyleSheet(f"background:{color};border-radius:4px;")
                hl.addWidget(dot, alignment=Qt.AlignmentFlag.AlignVCenter)
                name = QLabel(section)
                name.setObjectName("sidebarBrandName")
                name.setStyleSheet(f"color:{color};")
                hl.addWidget(name)
                sub = QLabel(what)
                sub.setObjectName("sidebarBrandSub")
                hl.addWidget(sub)
                hl.addStretch()
            elif section:
                header = QLabel(section.upper())
                header.setObjectName("sidebarSectionLabel")
            else:
                header = None
            if header is not None:
                lay.addWidget(header)
                lay.addSpacing(4)

            for label, token, page_id in items:
                btn = QPushButton(f"{token:<4}  {label}")
                btn.setObjectName("navBtn")
                btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                btn.clicked.connect(lambda _, p=page_id: self._navigate(p))
                self._nav_buttons[page_id] = btn
                lay.addWidget(btn)
                lay.addSpacing(2)

            lay.addSpacing(10)

        lay.addStretch()

        from ui.add_button import AddButton
        add_btn = AddButton("anime", "sidebar")
        self._add_btn = add_btn
        add_btn.clicked.connect(self._open_add_dialog)
        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._open_add_dialog)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self._open_search)
        QShortcut(QKeySequence("Ctrl+M"), self, activated=lambda: self._navigate("music"))
        lay.addWidget(add_btn)
        lay.addSpacing(8)

        cfg_btn = QPushButton("SET   Settings")
        self._settings_btn = cfg_btn
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

        from ui.anilist_user_menu import AniListUserMenu
        self.anilist_user_menu = AniListUserMenu(page)
        self.anilist_user_menu.connect_requested.connect(
            lambda: self._open_settings("account")
        )
        self.anilist_user_menu.account_settings_requested.connect(
            lambda: self._open_settings("account")
        )
        hr.addWidget(self.anilist_user_menu)
        hr.addSpacing(10)

        self.refresh_btn = QPushButton("↻  Refresh Airing")
        self.refresh_btn.setObjectName("secondaryBtn")
        self.refresh_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.refresh_btn.clicked.connect(
            lambda: self._sync_movies(manual=True) if self._media in ("movie", "tv")
            else self._refresh_airing())
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
        self._fill_sort_combo("anime")
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
        self._filter_layout = fr
        self._build_filter_pills("anime")
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
        # Re-flow cards whenever the visible width changes (panel open/close,
        # window resize) - after the new width is actually applied.
        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.timeout.connect(self._relayout_grid)
        self.scroll_area.installEventFilter(self)

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

    _FILTERS = {
        "anime": [("All", "all"), ("Watching", "watching"), ("Completed", "completed"),
                  ("Planned", "planned"), ("Behind", "behind")],
        "movie": [("All", "all"), ("Watchlist", "planned"), ("Watched", "completed")],
        "tv": [("All", "all"), ("Watching", "watching"), ("Watchlist", "planned"),
               ("Completed", "completed"), ("Dropped", "dropped")],
    }

    def _build_filter_pills(self, media: str):
        fr = self._filter_layout
        while fr.count():
            it = fr.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._filter_btns = {}
        for label, fid in self._FILTERS.get(media, self._FILTERS["anime"]):
            b = QPushButton(label)
            b.setObjectName("filterPillBehind" if fid == "behind" else "filterPill")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _, f=fid: self._set_filter(f))
            self._filter_btns[fid] = b
            fr.addWidget(b)
        fr.addStretch()
        for pid, btn in self._filter_btns.items():
            btn.setProperty("active", "true" if pid == self._current_filter else "false")

    def _set_media(self, media: str):
        """Switch the grid between the anime (Miroku) and movie (Kinema) libraries."""
        if media == self._media:
            return
        self._media = media
        self._current_filter = "all"
        self._show_archived = False
        self._search_query = ""
        self.search_bar.blockSignals(True)
        self.search_bar.clear()
        self.search_bar.blockSignals(False)
        self._build_filter_pills(media)
        self._fill_sort_combo(media)
        movie = media == "movie"
        tv = media == "tv"
        self._empty_icon.setText("🎬" if movie else "📺")
        self._empty_title.setText("No movies yet" if movie else
                                  "No TV shows yet" if tv else "Nothing here yet")
        self._empty_sub.setText(
            "Add films you want to see, or ones you've already watched." if movie else
            "Add a show you're watching, want to start, or already finished." if tv else
            "Add a currently airing or upcoming anime to start tracking.")
        self._empty_add.set_media(media)
        self.search_bar.setPlaceholderText("Search your movies…" if movie else
                                           "Search your shows…" if tv else "Search your library…")
        self.refresh_btn.setText(self._refresh_label())
        self.anilist_user_menu.setVisible(media == "anime")
        self._add_btn.set_media(media)
        self._relabel_stats_strip()

    def _refresh_label(self) -> str:
        return {"movie": "↻  Refresh Movies", "tv": "↻  Refresh Shows"}.get(
            self._media, "↻  Refresh Airing")

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
            self._stat_names = getattr(self, "_stat_names", {})
            self._stat_names[key] = lbl
            lay.addWidget(card)

        lay.addStretch()
        return w

    def _build_empty_state(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(14)

        icon = QLabel("📺")
        self._empty_icon = icon
        icon.setStyleSheet("font-size:52px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(icon)

        t = QLabel("Nothing here yet")
        self._empty_title = t
        t.setStyleSheet("font-size:18px;font-weight:600;color:#4a5070;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)

        s = QLabel("Add a currently airing or upcoming anime to start tracking.")
        self._empty_sub = s
        s.setStyleSheet("font-size:13px;color:#3a3f55;")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(s)

        from ui.add_button import AddButton
        add = AddButton("anime", "hero")
        self._empty_add = add
        add.clicked.connect(self._open_add_dialog)
        lay.addWidget(add, alignment=Qt.AlignmentFlag.AlignCenter)
        return w

    def _build_status_bar(self) -> QStatusBar:
        bar = QStatusBar()
        self.conn_label = QLabel("⬤  Checking…")
        self.conn_label.setObjectName("connStatus")
        bar.addPermanentWidget(self.conn_label)
        self.anilist_status_label = QLabel()
        self.anilist_status_label.setObjectName("connStatus")
        self.anilist_status_label.setVisible(False)
        bar.addPermanentWidget(self.anilist_status_label)
        self.tmdb_status_label = QLabel()
        self.tmdb_status_label.setObjectName("connStatus")
        self.tmdb_status_label.setVisible(False)
        bar.addPermanentWidget(self.tmdb_status_label)
        return bar

    def _reserve_panel_space(self, reserve: bool):
        """Make room for the detail panel instead of covering cards: the
        library narrows by the panel's width and the cards re-flow into
        fewer columns beside it."""
        right = (self.detail_panel.width() or 390) if reserve else 0
        if self._content_row.contentsMargins().right() == right:
            return
        self._content_row.setContentsMargins(0, 0, right, 0)
        self._content_host.layout().activate()
        # The new width is applied by activate(), so re-flow right now
        # (queued timers can be starved while the panel loads), plus one
        # safety pass for late geometry changes like a scrollbar appearing.
        self._relayout_grid()
        QTimer.singleShot(150, self._relayout_grid)

    def _relayout_grid(self):
        """Re-flow the existing grid widgets for the current width without
        rebuilding them (no flicker, no image reloads)."""
        if not hasattr(self, "grid_layout"):
            return
        cols = max(self._calc_columns(), 1)
        gl = self.grid_layout
        entries = []
        for i in range(gl.count()):
            r, c, _rs, cs = gl.getItemPosition(i)
            entries.append((r, c, cs, gl.itemAt(i).widget()))
        entries = [e for e in entries if e[3] is not None]
        if not entries:
            return
        entries.sort(key=lambda e: (e[0], e[1]))
        tiles = (AnimeCard, _SkeletonCard)
        for e in entries:
            gl.removeWidget(e[3])
        row, col = 0, 0
        for _r, _c, cs, w in entries:
            if isinstance(w, tiles):
                if col >= cols:
                    row, col = row + 1, 0
                gl.addWidget(w, row, col)
                col += 1
            else:
                if col > 0:
                    row, col = row + 1, 0
                gl.addWidget(w, row, 0, 1, cols)
                row += 1
        self._grid_cols = cols
        # Apply now: QGridLayout keeps old column widths (and the container
        # its old width) until it is re-activated.
        for c in range(gl.columnCount()):
            gl.setColumnMinimumWidth(c, 0)
            gl.setColumnStretch(c, 0)
        gl.invalidate()
        gl.activate()
        self.grid_container.updateGeometry()
        self.grid_container.adjustSize()
        if self.scroll_area.widgetResizable():
            self.grid_container.resize(self.scroll_area.viewport().width(),
                                       self.grid_container.sizeHint().height())
        sel = self._cards.get(self.selected_anime_id) if self.selected_anime_id else None
        if sel is not None and self.detail_panel.isVisible():
            self._scroll_card_into_view(sel)

    def _scroll_card_into_view(self, card):
        try:
            self.scroll_area.ensureWidgetVisible(card, 40, 60)
        except RuntimeError:
            pass

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if obj is getattr(self, "scroll_area", None) and ev.type() == QEvent.Type.Resize:
            if ev.oldSize().width() != ev.size().width():
                self._reflow_timer.start(30)
        return super().eventFilter(obj, ev)

    def _close_detail_panel(self):
        self.detail_panel.hide()
        self._detail_scrim.hide()
        self._reserve_panel_space(False)
        self.selected_anime_id = None
        self._deselect_all_cards()
        if hasattr(self, "notification_banner"):
            self.notification_banner.resume_after_detail()
            if self.notification_banner.isVisible():
                self.notification_banner.raise_()
        if hasattr(self, "new_season_spotlight"):
            self.new_season_spotlight.resume_after_detail()

    def _position_detail_overlay(self):
        host = self._content_host
        w, h = host.width(), host.height()
        panel_w = self.detail_panel.width() or 390
        self.detail_panel.setGeometry(w - panel_w, 0, panel_w, h)
        self._detail_scrim.setGeometry(0, 0, w, h)

    def _open_detail_panel(self):
        self._position_detail_overlay()
        # No dimming scrim: the panel now sits beside the cards, not on them.
        self._detail_scrim.hide()
        self.detail_panel.show()
        self.detail_panel.raise_()
        self._reserve_panel_space(True)
        sel = self._cards.get(self.selected_anime_id) if self.selected_anime_id else None
        if sel is not None:
            QTimer.singleShot(60, lambda w=sel: self._scroll_card_into_view(w))
        if hasattr(self, "notification_banner"):
            self.notification_banner.pause_for_detail()
            self.notification_banner.lower()
        if hasattr(self, "new_season_spotlight"):
            self.new_season_spotlight.pause_for_detail()

    def _on_detail_links_changed(self):
        if self.selected_anime_id and self.selected_anime_id in self._cards:
            self._cards[self.selected_anime_id].refresh_links()

    # ── Navigation ─────────────────────────────────────────────────────────────

    def _navigate(self, page_id: str):
        self.current_page = page_id
        self._set_nav_active(page_id)
        self._close_detail_panel()
        if page_id == "discover":
            self._set_media("anime")       # Miroku pages: add button = anime

        if page_id == "discover":
            if self._discover_page is None:
                from ui.kinema_add_dialog import MovieBrowser
                page = MovieBrowser(self.db, heading="Discover anime", start_source="for_you",
                                    kind="anime")
                page.setObjectName("contentArea")
                page.added.connect(self._on_anime_discover_added)
                self._discover_page = page
                self.stack.removeWidget(self.stack.widget(1))
                self.stack.insertWidget(1, page)
            self.stack.setCurrentIndex(1)
        elif page_id == "home":
            if self._home_page is None:
                from ui.home_page import HomePage
                page = HomePage(self.db, self)
                page.open_title.connect(self._open_title)
                page.changed.connect(self._on_home_changed)
                page.search_online.connect(self._search_online)
                page.open_pick.connect(self._open_pick)
                page.play_trailer.connect(self._play_trailer)
                page.open_hall.connect(lambda: self._navigate("hall"))
                self._home_page = page
                self.stack.removeWidget(self.stack.widget(7))
                self.stack.insertWidget(7, page)
            self.stack.setCurrentIndex(7)
            self._home_page.load()
        elif page_id == "music":
            if self._music_page is None:
                from ui.music_page import MusicPage
                page = MusicPage(self.db, self)
                page.open_title.connect(self._open_title)
                self._music_page = page
                self.stack.removeWidget(self.stack.widget(9))
                self.stack.insertWidget(9, page)
            self.stack.setCurrentIndex(9)
            self._music_page.load()
        elif page_id == "hall":
            if self._hall_page is None:
                from ui.hall_page import HallPage
                page = HallPage(self.db, self)
                page.open_title.connect(self._open_title)
                page.changed.connect(self._on_hall_changed)
                self._hall_page = page
                self.stack.removeWidget(self.stack.widget(8))
                self.stack.insertWidget(8, page)
            self.stack.setCurrentIndex(8)
            self._hall_page.load()
        elif page_id == "kinema_discover":
            if self._kinema_discover is None:
                from ui.kinema_add_dialog import MovieBrowser
                start = "tv" if self._media == "tv" else "movie"
                page = MovieBrowser(self.db, heading="Discover", start_source="for_you",
                                    kind=start, kind_switch=True)
                page.setObjectName("contentArea")
                page.added.connect(self._on_discover_added)
                page.kind_changed.connect(self._set_media)
                self._kinema_discover = page
                self.stack.removeWidget(self.stack.widget(6))
                self.stack.insertWidget(6, page)
            self.stack.setCurrentIndex(6)
            self._set_media(self._kinema_discover.kind)
        elif page_id in ("movies", "tv"):
            self.stack.setCurrentIndex(0)
            self._set_media("movie" if page_id == "movies" else "tv")
            self.page_title.setText("Movies" if page_id == "movies" else "TV shows")
            self.filter_row.setVisible(True)
            self.search_bar.setVisible(True)
            self._update_stats_strip()
            self._load_library()
        else:
            self.stack.setCurrentIndex(0)
            self._set_media("anime")
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
        if fid != "completed":
            self._show_archived = False
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

        media = self._media

        def fetch_data():
            if media in ("movie", "tv"):
                if search_q:
                    return self.db.search_titles(search_q, media)
                if watch_status == "completed":
                    return self.db.get_all_anime(watch_status="completed", sort_by="completed_at",
                                                 archived=show_archived, media_type=media)
                if watch_status is None:
                    return self.db.get_all_anime(sort_by=sort_by, archived=False, media_type=media)
                return self.db.get_all_anime(watch_status=watch_status, sort_by=sort_by,
                                             media_type=media)
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
                    aired   = total if (total and api_s in ("FINISHED", "CANCELLED")) else (
                               (next_ep - 1) if (next_ep and next_ep > 1) else 0)
                    watched = self.db.get_watched_count(a["id"])
                    if aired > 0 and watched < aired:
                        result.append(a)
                return result
            elif watch_status == "completed":
                return self.db.get_all_anime(
                    watch_status="completed", sort_by="completed_at",
                    archived=show_archived)
            elif watch_status is None:
                return self.db.get_all_anime(sort_by=sort_by, archived=False)
            else:
                return self.db.get_all_anime(watch_status=watch_status, sort_by=sort_by)

        show_archived = self._show_archived
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
                w = item.widget()
                w.hide()
                w.setParent(None)
                # Actually destroy it - a parentless widget that something
                # still references can otherwise pop up as its own window.
                w.deleteLater()
        self._cards.clear()

    def _render_library(self, anime_list: List[Dict],
                         current_filter: str, current_page: str):
        from PyQt6 import sip
        if sip.isdeleted(self) or sip.isdeleted(self.grid_container):
            return                      # window closed while the load was running
        """Called from worker result — renders real cards replacing skeletons."""
        self._clear_grid()

        has = bool(anime_list)
        if (not has and current_filter == "completed" and current_page in ("library", "movies", "tv")
                and not self._search_query and (self._show_archived or self.db.count_archived(self._media))):
            has = True   # keep the timeline (and its Archived toggle) visible
        self.empty_state.setVisible(not has)
        self.grid_container.setVisible(has)

        if has:
            show_grouped = (
                current_filter == "all"
                and current_page in ("library", "movies", "tv")
                and not self._search_query
            )
            show_timeline = (
                current_filter == "completed"
                and current_page in ("library", "movies", "tv")
                and not self._search_query
            )
            movie_shelves = (self._media == "movie" and current_filter in ("all", "planned")
                             and current_page in ("library", "movies", "tv") and not self._search_query)
            if movie_shelves:
                self._populate_movie_shelves(anime_list, include_watched=current_filter == "all")
            elif show_grouped:
                self._populate_grouped_grid(anime_list)
            elif show_timeline:
                self._populate_completed_timeline(anime_list)
            else:
                COLS = self._calc_columns()
                for idx, anime in enumerate(anime_list):
                    card = AnimeCard(anime, self.db)
                    card.clicked.connect(lambda aid=anime["id"]: self._on_card_clicked(aid))
                    card.new_season_clicked.connect(self._on_card_new_season)
                    card.quick_watched.connect(self._on_card_quick_watched)
                    self._cards[anime["id"]] = card
                    self.grid_layout.addWidget(card, idx // COLS, idx % COLS)
                    self._load_card_image(anime, card)

        self._update_stats_strip()
        self._apply_card_overlays()

    def _populate_movie_shelves(self, movies: List[Dict], include_watched: bool):
        """Watchlist split by what you can actually watch now (you watch in
        HD at home): Ready to watch, then Waiting for HD. Watched follows as
        one row in the All view."""
        from core.kinema_sync import release_state
        from ui.completed_view import SectionHeader
        cols = max(self._calc_columns(), 1)
        watch = [m for m in movies if m.get("watch_status") == "planned"]
        ready = [m for m in watch if release_state(m)["state"] == "digital"]
        waiting = [m for m in watch if m not in ready]
        # Waiting: whatever lands in HD soonest first
        far = 9_999_999_999
        waiting.sort(key=lambda m: (release_state(m)["digital_ts"] or far,
                                    release_state(m)["cinema_ts"] or far))
        shelves = [("ready", "Ready to watch", "#34d399", ready),
                   ("waiting", "Waiting for HD", "#fbbf24", waiting)]
        if include_watched:
            done = [m for m in movies if m.get("watch_status") == "completed"]
            shelves.append(("watched", "Watched", "#7c6af7", done))
        row = 0
        for key, label, color, items in shelves:
            if not items:
                continue
            shown = items[:cols] if key == "watched" else items
            if key == "watched" and len(items) > cols:
                hdr = SectionHeader("watched", label, len(items), color, collapsible=False,
                                    action_text=f"View all {len(items)}  \u2192")
                hdr.action.connect(lambda _k: self._set_filter("completed"))
            else:
                hdr = QLabel(f"〡 {label.upper()}  ·  {len(items)} {'film' if len(items) == 1 else 'films'}")
                hdr.setObjectName("libSectionHeader")
                hdr.setStyleSheet(f"color:{color};")
            self.grid_layout.addWidget(hdr, row, 0, 1, cols)
            row += 1
            for i, m in enumerate(shown):
                if i and i % cols == 0:
                    row += 1
                card = AnimeCard(m, self.db)
                card.clicked.connect(lambda aid=m["id"]: self._on_card_clicked(aid))
                card.new_season_clicked.connect(self._on_card_new_season)
                card.quick_watched.connect(self._on_card_quick_watched)
                self._cards[m["id"]] = card
                self.grid_layout.addWidget(card, row, i % cols)
                self._load_card_image(m, card)
            row += 1
        if not watch and not include_watched:
            msg = QLabel("Your Watchlist is empty. Add a film you want to see.")
            msg.setObjectName("completedToolbarHint")
            self.grid_layout.addWidget(msg, row, 0, 1, cols)

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
        ] if self._media == "anime" else [
            ("〡 WATCHLIST",   "planned",   "#fbbf24"),
            ("〡 WATCHED",     "completed", "#34d399"),
        ] if self._media == "movie" else [
            ("〡 WATCHING",    "watching",  "#38bdf8"),
            ("〡 WATCHLIST",   "planned",   "#6b7280"),
            ("〡 COMPLETED",   "completed", "#34d399"),
            ("〡 DROPPED",     "dropped",   "#b5485a"),
        ]
        row_num = 0
        for group_label, status, color in groups:
            members = [a for a in anime_list if a.get("watch_status") == status]
            if not members:
                continue
            total_members = len(members)
            if status == "completed":
                # Only the most recently finished row here - the full list
                # lives in the Completed timeline.
                from ui.completed_view import finished_ts
                members = sorted(members, key=finished_ts, reverse=True)[:max(COLS, 1)]
            if status == "completed" and total_members > len(members):
                from ui.completed_view import SectionHeader
                hdr = SectionHeader("all-completed", "Recently completed", total_members,
                                    color, collapsible=False,
                                    action_text=f"View all {total_members}  \u2192")
                hdr.action.connect(lambda _k: self._set_filter("completed"))
            else:
                hdr = QLabel(f"{group_label}  ·  {total_members} titles")
                hdr.setObjectName("libSectionHeader")
                hdr.setStyleSheet(f"color:{color};")
            self.grid_layout.addWidget(hdr, row_num, 0, 1, max(COLS, 1))
            row_num += 1
            for col_idx, anime in enumerate(members):
                if col_idx > 0 and col_idx % COLS == 0:
                    row_num += 1
                card = AnimeCard(anime, self.db)
                card.clicked.connect(lambda aid=anime["id"]: self._on_card_clicked(aid))
                card.new_season_clicked.connect(self._on_card_new_season)
                card.quick_watched.connect(self._on_card_quick_watched)
                self._cards[anime["id"]] = card
                self.grid_layout.addWidget(card, row_num, col_idx % COLS)
                self._load_card_image(anime, card)
            row_num += 1

    # ── Completed timeline ─────────────────────────────────────────────────────

    def _load_fold_overrides(self) -> Dict[str, bool]:
        import json
        from core.app_settings import app_settings
        try:
            return json.loads(app_settings().value("completed_fold_state", "{}") or "{}")
        except Exception:
            return {}

    def _is_folded(self, key: str) -> bool:
        from ui.completed_view import default_collapsed
        return self._fold_overrides.get(key, default_collapsed(key))

    def _populate_completed_timeline(self, anime_list: List[Dict]):
        from ui.completed_view import CompletedToolbar, SectionHeader, group_completed
        COLS = max(self._calc_columns(), 1)
        row = 0
        bar = CompletedToolbar(len(anime_list), self.db.count_archived(self._media), self._show_archived,
                               media=self._media)
        bar.archived_toggled.connect(self._toggle_archived_view)
        self.grid_layout.addWidget(bar, row, 0, 1, COLS)
        row += 1
        self._completed_groups = {}
        color = "#9da5c0" if self._show_archived else "#34d399"
        action = "Restore all" if self._show_archived else "Archive these"
        rewatching = set(self.db.get_active_rewatch_ids())
        for key, label, members in group_completed(anime_list, rewatching=rewatching,
                                                   verb="Watched" if self._media == "movie" else "Finished"):
            self._completed_groups[key] = [a["id"] for a in members]
            folded = self._is_folded(key)
            hdr = SectionHeader(key, label, len(members), color, collapsed=folded,
                                action_text=action)
            hdr.toggled.connect(self._toggle_completed_group)
            hdr.action.connect(self._archive_completed_group)
            self.grid_layout.addWidget(hdr, row, 0, 1, COLS)
            row += 1
            if folded:
                continue
            for i, anime in enumerate(members):
                if i and i % COLS == 0:
                    row += 1
                card = AnimeCard(anime, self.db)
                card.clicked.connect(lambda aid=anime["id"]: self._on_card_clicked(aid))
                card.new_season_clicked.connect(self._on_card_new_season)
                card.quick_watched.connect(self._on_card_quick_watched)
                self._cards[anime["id"]] = card
                self.grid_layout.addWidget(card, row, i % COLS)
                self._load_card_image(anime, card)
            row += 1
        if not anime_list:
            msg = QLabel("Nothing archived." if self._show_archived else
                         "Everything here is archived. Use the Archived button to see it.")
            msg.setObjectName("completedToolbarHint")
            self.grid_layout.addWidget(msg, row, 0, 1, COLS)

    def _toggle_completed_group(self, key: str):
        import json
        from core.app_settings import app_settings
        self._fold_overrides[key] = not self._is_folded(key)
        app_settings().setValue("completed_fold_state", json.dumps(self._fold_overrides))
        self._load_library()

    def _archive_completed_group(self, key: str):
        from ui.toast import Toast
        ids = self._completed_groups.get(key) or []
        if not ids:
            return
        archive = not self._show_archived
        n = self.db.set_archived(ids, archive)
        label = {"month": "this month", "year": "earlier this year"}.get(key, key)
        if archive:
            Toast.show(self, f"Archived {n} {'show' if n == 1 else 'shows'} from {label}. "
                             "Find them under Archived.", kind="success")
        else:
            Toast.show(self, f"Restored {n} {'show' if n == 1 else 'shows'} to Completed.",
                       kind="success")
        self._load_library()

    def _toggle_archived_view(self):
        self._show_archived = not self._show_archived
        self._load_library()

    def _on_archive_changed(self, anime_id: int):
        self._load_library_for_current_page()

    def _on_movie_changed(self, lib_id: int):
        """A movie's status / rating / rewatches changed in the panel (or a
        franchise film was added: lib_id -1)."""
        self._update_stats_strip()
        if lib_id < 0:
            self._load_library()
            return
        row = self.db.get_anime_by_id(lib_id)
        card = self._cards.get(lib_id)
        if not row:
            return
        moved = (card is not None and card._anime.get("watch_status") != row.get("watch_status"))
        if card is not None and not moved:
            card.update_data(row)
        else:
            self._load_library()

    def _on_rewatch_changed(self, anime_id: int):
        card = self._cards.get(anime_id)
        row = self.db.get_anime_by_id(anime_id)
        if card is not None and row:
            card.update_data(row)
        # Starting/finishing a rewatch moves the card in/out of "Rewatching now"
        if self._current_filter == "completed" and self.current_page in ("library", "movies", "tv"):
            in_group = anime_id in (self._completed_groups.get("rewatching") or [])
            now_active = self.db.get_active_rewatch(anime_id) is not None
            if in_group != now_active:
                self._load_library()

    def _on_dropped_restored(self, new_id: int, ws: str):
        from ui.toast import Toast
        self._close_detail_panel()
        where = {"watching": "Watching", "completed": "Completed (unwatched episodes flagged)",
                 "planned": "Plan to Watch"}.get(ws, "your library")
        Toast.show(self, f"Welcome back. It's in {where}.", kind="success")
        self._load_library_for_current_page()
        self._update_stats_strip()

    def _on_dropped_removed(self):
        from ui.toast import Toast
        self._close_detail_panel()
        Toast.show(self, "Removed from Dropped.", kind="info")
        self._load_library_for_current_page()
        self._update_stats_strip()

    def _run_auto_archive(self):
        from core.app_settings import app_settings
        days = int(app_settings().value("auto_archive_days", 0) or 0)
        n = self.db.auto_archive_completed(days)
        if n:
            from ui.toast import Toast
            Toast.show(self, f"Auto-archived {n} completed {'show' if n == 1 else 'shows'} "
                             "finished a while ago.", kind="info")
            self._load_library_for_current_page()

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
                "_last_episode": r.get("last_episode") or 0,
                "_dropped_at":   r.get("dropped_at"),
                "_drop_reason":  r.get("drop_reason") or "",
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

    _STAT_NAMES = {
        "anime": {"watching": "Watching", "completed": "Completed", "planned": "Planned", "dropped": "Dropped"},
        "movie": {"watching": "Watchlist", "completed": "Watched", "planned": "Hours watched",
                  "dropped": "This year"},
        "tv": {"watching": "Watching", "completed": "Completed", "planned": "Watchlist",
               "dropped": "Episodes seen"},
    }

    def _relabel_stats_strip(self):
        names = self._STAT_NAMES.get(self._media, self._STAT_NAMES["anime"])
        for key, lbl in getattr(self, "_stat_names", {}).items():
            lbl.setText(names[key].upper())

    def _update_stats_strip(self):
        if self._media == "movie":
            m = self.db.get_movie_stats()
            values = {"watching": m["watchlist"], "completed": m["watched"],
                      "planned": m["hours"], "dropped": m["this_year"]}
        elif self._media == "tv":
            t = self.db.get_tv_stats()
            values = {"watching": t["watching"], "completed": t["completed"],
                      "planned": t["planned"], "dropped": t["episodes"]}
        else:
            stats = self.db.get_stats()
            values = {k: stats.get(k, 0) for k in ("watching", "completed", "planned", "dropped")}
        for key, v in values.items():
            lbl = self._stat_labels.get(key)
            if lbl:
                lbl.setText(str(v))

    # ── Card interactions ──────────────────────────────────────────────────────

    def _on_card_clicked(self, anime_id: int):
        # Toggle detail panel
        if self.selected_anime_id == anime_id and self.detail_panel.isVisible():
            self._close_detail_panel()
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
                    "_last_episode": dropped.get("last_episode") or 0,
                    "_dropped_at":   dropped.get("dropped_at"),
                    "_drop_reason":  dropped.get("drop_reason") or "",
                })
                self._open_detail_panel()
                self._load_detail_images({
                    "id": anime_id,
                    "cover_url": dropped.get("cover_url", ""),
                    "cover_local": dropped.get("cover_local", ""),
                    "banner_url": "",
                })
            return

        anime = self.db.get_anime_by_id(anime_id)
        if not anime:
            return

        self.detail_panel.load_anime(anime)
        self._open_detail_panel()

        self._refresh_open_anime(anime)

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

    def handle_external(self, message: str):
        """From a second launch or a clicked Windows notification."""
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        if message.startswith("open:"):
            try:
                lib_id = int(message.split(":", 1)[1])
            except ValueError:
                return
            if lib_id > 0 and self.db.get_anime_by_id(lib_id):
                self._open_title(lib_id)
            else:
                self._navigate("home")

    def _open_search(self):
        """Ctrl+K: one search across anime, shows and movies."""
        if self.current_page != "home":
            self._navigate("home")
        self._home_page.focus_search()

    def _open_pick(self, hit: Dict):
        """A recommendation from Home: open it in the matching Discover preview,
        where it can be added."""
        kind = hit.get("media_type") or "anime"
        if kind == "anime":
            self._navigate("discover")
            page = self._discover_page
        else:
            self._navigate("kinema_discover")
            page = self._kinema_discover
            page.set_kind(kind)
        if page is not None:
            page._select(dict(hit))

    def _search_online(self, where: str, query: str):
        self._navigate("discover" if where == "anime" else "kinema_discover")
        page = self._discover_page if where == "anime" else self._kinema_discover
        if page is not None and query:
            page.search.setText(query)

    def _on_card_quick_watched(self, lib_id: int, what: str):
        from ui.toast import Toast
        row = self.db.get_anime_by_id(lib_id) or {}
        Toast.show(self, f"{row.get('english_title') or row.get('romaji_title') or 'Title'}: "
                         f"{what} watched.", kind="success")
        self._update_stats_strip()
        if self.detail_panel.isVisible() and self.selected_anime_id == lib_id:
            self.detail_panel.refresh_from_db()
        if self._home_page is not None and self.current_page == "home":
            self._home_page.load()

    def _on_home_changed(self, lib_id: int):
        row = self.db.get_anime_by_id(lib_id)
        card = self._cards.get(lib_id)
        if row and card is not None:
            card.update_data(row)
        self._update_stats_strip()

    def _on_hall_changed(self):
        """The Hall changed: refresh what shows Hall of Fame state elsewhere."""
        if self._home_page is not None:
            self._home_page.refresh_pantheon()
        if self._hall_page is not None and self.current_page == "hall" and self.sender() is not self._hall_page:
            self._hall_page.load()

    def _open_title(self, anime_id: int):
        anime = self.db.get_anime_by_id(anime_id)
        if not anime:
            return
        page = {"movie": "movies", "tv": "tv"}.get(anime.get("media_type") or "anime", "library")
        if self.current_page != page:
            self._navigate(page)
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

    def _on_watch_status_changed(self, anime_id: int, new_status: str):
        """Remove or update cards when watch status no longer matches the active view."""
        self._update_stats_strip()

        if (
            self.current_page in ("library", "movies", "tv")
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
                self._close_detail_panel()
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
            aired = total if (total and api_s in ("FINISHED", "CANCELLED")) else (
                (next_ep - 1) if (next_ep and next_ep > 1) else 0
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
        self._close_detail_panel()
        self._load_library(
            watch_status=None if self.current_page in ("library", "movies", "tv") else
            {"watching":"watching","completed":"completed","planned":"planned"}.get(self.current_page)
        )
        self._update_stats_strip()

    def _on_anime_deleted(self, anime_id: int):
        self._close_detail_panel()
        self._load_library()
        self._update_stats_strip()

    # ── Search & Sort ──────────────────────────────────────────────────────────

    _SORTS = {
        "anime": [("Release Date", "release_date"), ("Title", "title"), ("AniList Score", "score"),
                  ("Date Added", "date_added"), ("Your Rating", "rating")],
        # Movies default to best first; unreleased films follow by anticipation
        "movie": [("Top Rated", "top_rated"), ("Most Anticipated", "popularity"),
                  ("Newest", "newest"), ("Title", "title"), ("Date Added", "date_added"),
                  ("Your Rating", "rating")],
        "tv": [("Recently Watched", "recent"), ("Next Episode", "release_date"),
               ("Top Rated", "top_rated"), ("Title", "title"), ("Date Added", "date_added"),
               ("Your Rating", "rating")],
    }

    def _fill_sort_combo(self, media: str):
        self.sort_combo.blockSignals(True)
        self.sort_combo.clear()
        for label, key in self._SORTS.get(media, self._SORTS["anime"]):
            self.sort_combo.addItem(label, key)
        self.sort_combo.setCurrentIndex(0)
        self.sort_combo.blockSignals(False)
        self._sort_by = self.sort_combo.currentData() or "release_date"

    def _on_sort_changed(self, index: int):
        self._sort_by = self.sort_combo.itemData(index) or "release_date"
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
        self._apply_new_season_ribbons()

    def _on_search(self, text: str):
        self._search_timer.stop()
        self._search_query = text.strip()
        self._search_timer.start(280)

    # ── Dialogs ────────────────────────────────────────────────────────────────

    def _open_add_movie_dialog(self):
        from ui.kinema_add_dialog import MovieAddDialog
        from ui.toast import Toast
        dlg = MovieAddDialog(self.db, self, kind=self._media if self._media in ("movie", "tv") else "movie")

        def added(lib_id: int, title: str):
            row = self.db.get_anime_by_id(lib_id) or {}
            where = self._where_label(row)
            Toast.show(self, f"'{title}' added to {where}.", kind="success")
            self._load_library()
            self._update_stats_strip()
            if self._kinema_discover is not None:
                self._kinema_discover.refresh()

        dlg.added.connect(added)
        dlg.exec()

    def _on_discover_added(self, lib_id: int, title: str):
        from ui.toast import Toast
        row = self.db.get_anime_by_id(lib_id) or {}
        Toast.show(self, f"'{title}' added to {self._where_label(row)}.", kind="success")
        self._update_stats_strip()

    @staticmethod
    def _where_label(row: Dict) -> str:
        ws = row.get("watch_status")
        if row.get("media_type") == "tv":
            return {"watching": "Watching", "completed": "Completed"}.get(ws, "your Watchlist")
        return "Watched" if ws == "completed" else "your Watchlist"

    def _sync_movies(self, manual: bool = False):
        """Refresh movies from TMDB (dates, availability, art, trailers)."""
        from core.kinema_sync import KinemaSync
        if manual:
            self.refresh_btn.setText("↻  Refreshing…")
            self.refresh_btn.setEnabled(False)
        def both():
            ks = KinemaSync(self.db)
            a, b = ks.sync_movies(), ks.sync_tv()
            return {"changed": a["changed"] + b["changed"],
                    "art_changed": a["art_changed"] + b["art_changed"],
                    "notifications": (a["notifications"] + [n for n in b["notifications"]
                                      if n not in a["notifications"]])[:6]}

        worker = Worker(both)
        worker.signals.result.connect(self._on_metadata_synced)
        if manual:
            worker.signals.finished.connect(lambda: (
                self.refresh_btn.setText(self._refresh_label()),
                self.refresh_btn.setEnabled(True)))
        run_worker(worker)

    def _open_add_dialog(self):
        if self._media in ("movie", "tv"):
            return self._open_add_movie_dialog()
        from ui.kinema_add_dialog import MovieAddDialog
        dlg = MovieAddDialog(self.db, self, kind="anime")
        dlg.added.connect(self._on_anime_discover_added)
        dlg.exec()

    def _on_anime_discover_added(self, lib_id: int, title: str):
        from ui.toast import Toast
        row = self.db.get_anime_by_id(lib_id) or {}
        where = {"watching": "Watching", "completed": "Completed"}.get(
            row.get("watch_status"), "Plan to Watch")
        Toast.show(self, f"'{title}' added to {where}.", kind="success")
        if self.current_page == "library":
            self._load_library()
        self._update_stats_strip()
        if self._discover_page is not None and self.sender() is not self._discover_page:
            self._discover_page.refresh()

    def _setup_anilist_session(self):
        from core.anilist_auth import get_anilist_auth

        auth = get_anilist_auth(self)
        auth.session_changed.connect(self._refresh_anilist_user_menu)

    def _refresh_anilist_user_menu(self):
        if hasattr(self, "anilist_user_menu"):
            self.anilist_user_menu.refresh()

    def _open_settings(self, initial_page: str = "account"):
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.db, self, initial_page=initial_page)
        dlg.exec()
        self._refresh_anilist_user_menu()
        if dlg.preview_request:
            self.start_theme_preview(*dlg.preview_request)

    def _event_ended_note(self):
        from ui.theme import ThemeManager
        from ui.themes_catalog import info
        tm = ThemeManager.get()
        ev = getattr(tm, "ended_event", None)
        if ev is not None:
            tm.ended_event = None
            from ui.toast import Toast
            Toast.show(self, f"{ev['name']} is over — back to {info(tm.saved_id)['name']}.", kind="info")

    def start_theme_preview(self, tid: str, accent: str = ""):
        """Walk through the app in a theme without saving it."""
        from ui.theme_preview import ThemePreview
        if getattr(self, "_theme_preview", None) is not None:
            return
        self._theme_preview = ThemePreview(self, tid, accent)
        self._theme_preview.finished.connect(self._theme_preview_done)
        self._theme_preview.start()

    def _theme_preview_done(self, _applied: bool):
        self._theme_preview = None
        QTimer.singleShot(150, lambda: self._open_settings("appearance"))

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
        QTimer.singleShot(1000, self._refresh_upcoming)

        # Sequel / new-season check: relations change rarely, so every 6h.
        self._sequel_timer = QTimer(self)
        self._sequel_timer.timeout.connect(self._scan_sequels)
        self._sequel_timer.start(6 * 3600 * 1000)
        if not self._demo_new_season:
            QTimer.singleShot(8000, self._scan_sequels)

        # Metadata sync (art, trailer, dates, cast...) for Planned + Watching
        self._meta_timer = QTimer(self)
        self._meta_timer.timeout.connect(self._sync_metadata)
        self._meta_timer.start(3 * 3600 * 1000)
        QTimer.singleShot(12000, self._sync_metadata)

        # Search catalogue (popular titles, for partial-word search): weekly, in the background
        QTimer.singleShot(45000, self._refresh_catalog)
        self._catalog_timer = QTimer(self)
        self._catalog_timer.timeout.connect(self._refresh_catalog)
        self._catalog_timer.start(12 * 3600 * 1000)

        # Closed-app notifications: keep the scheduled check pointing at this Raikō
        QTimer.singleShot(20000, lambda: run_worker(Worker(
            __import__("core.background_check", fromlist=["x"]).refresh_registration)))

        # Taskbar badge: unread alerts, kept fresh
        self._badge_timer = QTimer(self)
        self._badge_timer.timeout.connect(self._update_badge)
        self._badge_timer.start(60 * 1000)
        QTimer.singleShot(3000, self._update_badge)

        # Data Doctor: quick health check shortly after start, then every 6h
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._health_check)
        self._health_timer.start(6 * 3600 * 1000)
        QTimer.singleShot(25000, self._health_check)

        # Kinema: movies (release dates, streaming availability) every 6h
        self._movie_timer = QTimer(self)
        self._movie_timer.timeout.connect(self._sync_movies)
        self._movie_timer.start(6 * 3600 * 1000)
        QTimer.singleShot(15000, self._sync_movies)
        QTimer.singleShot(2500, self._run_auto_archive)

    def _tick(self):
        import time as _time
        from datetime import datetime as _dt, timezone as _tz
        now = int(_dt.now(_tz.utc).timestamp())
        due_ids: List[int] = []
        for anime_id, card in self._cards.items():
            card.tick_countdown()
            next_at = card._next_ep_at
            if next_at and next_at <= now:
                last = self._pending_ep_refresh.get(anime_id, 0.0)
                if _time.monotonic() - last > 60:
                    self._pending_ep_refresh[anime_id] = _time.monotonic()
                    due_ids.append(anime_id)
        if due_ids:
            self._refresh_episode_arrivals(due_ids)

    def _refresh_episode_arrivals(self, anime_ids: List[int]):
        """A countdown just hit zero - pull fresh data for that anime right
        away instead of waiting for the next scheduled poll (up to 10 min
        for Watching, 30 min for Planned), so the episode/status the user
        sees updates the moment it's actually available."""
        anilist_ids = []
        for anime_id in anime_ids:
            anime = self.db.get_anime_by_id(anime_id)
            if anime and anime.get("anilist_id"):
                anilist_ids.append(anime["anilist_id"])
        if not anilist_ids:
            return
        worker = AiringRefreshWorker(anilist_ids)
        worker.signals.result.connect(self._on_airing_refreshed)
        run_worker(worker)

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
                updates["next_episode_at"]  = None
                updates["next_episode_num"] = None
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
            updates: Dict[str, Any] = {
                "status": media.get("status", anime["status"]),
            }
            nae = media.get("nextAiringEpisode")
            if nae:
                updates["next_episode_at"]  = nae.get("airingAt")
                updates["next_episode_num"] = nae.get("episode")
            else:
                # No next episode from AniList (e.g. show finished/cancelled) -
                # clear any stale cached episode instead of leaving it stuck.
                updates["next_episode_at"]  = None
                updates["next_episode_num"] = None
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
    # ── Onboarding ─────────────────────────────────────────────────────────────

    def _maybe_show_onboarding(self):
        """Raikō welcome + tour, once. People upgrading from Miroku (who have a
        library or saw the old tour) get the 'Miroku is now Raikō' welcome."""
        from core.app_settings import app_settings
        settings = app_settings()
        if settings.value("onboarding_v3_seen", False, type=bool):
            return
        upgrading = settings.value("onboarding_seen", False, type=bool) or any(
            self.db.get_all_anime(media_type=m) for m in ("anime", "tv", "movie"))
        self.start_onboarding(upgrading)

    def start_onboarding(self, upgrading: bool = False):
        from core.app_settings import app_settings
        from ui.onboarding import OnboardingOverlay, WelcomeOverlay
        settings = app_settings()

        def mark_seen():
            settings.setValue("onboarding_v3_seen", True)
            settings.setValue("onboarding_seen", True)

        def tour():
            mark_seen()
            if self.current_page != "home":
                self._navigate("home")
            ov = OnboardingOverlay(self, self.centralWidget())
            ov.finished.connect(lambda: self._navigate("home"))
            self._tour = ov

        welcome = WelcomeOverlay(self.centralWidget(), upgrading)
        welcome.tour.connect(tour)
        welcome.done.connect(mark_seen)
        self._welcome = welcome

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
        QTimer.singleShot(0, self._update_badge)
        if notifications:
            self.notification_banner.show_notifications(notifications)
        else:
            self.notification_banner.clear_if_idle()
        if any(n.get("kind") in ("auto_completed", "auto_planned") for n in notifications):
            self._load_library_for_current_page()

    def _open_notification_anime(self, anime_id: int):
        if hasattr(self, "notification_banner"):
            self.notification_banner.pause_for_detail()
        self._open_title(anime_id)

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

    # ── Data Doctor: background health check + error alerts ──────────────────

    def open_data_doctor(self):
        """Open Data Doctor; it starts diagnosing right away."""
        from ui.data_doctor import DataDoctorDialog
        dlg = DataDoctorDialog(self.db, self)
        dlg.data_changed.connect(self._after_doctor_fix)
        dlg.exec()

    def _after_doctor_fix(self):
        self._load_library()
        self._update_stats_strip()

    def _refresh_catalog(self):
        from core import catalog
        run_worker(Worker(catalog.refresh_stale))

    def _health_check(self):
        """Quick, offline scan; problems that need you raise ONE alert with
        an Open Data Doctor button (not repeated for the same problems)."""
        from core.data_health import Scanner

        def work():
            return Scanner(self.db).scan(quick=True)

        w = Worker(work)
        w.signals.result.connect(self._on_health)
        run_worker(w)

    def _on_health(self, issues):
        from PyQt6 import sip
        if sip.isdeleted(self):
            return
        import hashlib
        from core.data_health import attention_needed
        need = attention_needed(issues or [])
        if not need:
            return
        key = hashlib.sha1(",".join(sorted(i.issue_id for i in need)).encode()).hexdigest()[:12]
        n = len(need)
        names = "; ".join(dict.fromkeys(i.title for i in need[:3]))
        self.db.upsert_notification({
            "fingerprint": f"data-health:{key}", "kind": "data_health",
            "anime_id": None, "anilist_id": None,
            "title": f"Data Doctor found {n} thing{'s' if n != 1 else ''} to fix",
            "message": f"{names}. Open Data Doctor to review and fix in one click.",
            "payload": {"issues": [i.issue_id for i in need]}})
        self._show_alerts_of("data_health")

    def _on_app_error(self):
        """An error escaped somewhere in the app (caught and logged by the
        crash guard). At most one alert every 10 minutes."""
        import time as _t
        from PyQt6 import sip
        if sip.isdeleted(self) or _t.time() - getattr(self, "_last_error_alert", 0) < 600:
            return
        self._last_error_alert = _t.time()
        self.db.upsert_notification({
            "fingerprint": f"app-error:{int(_t.time())}", "kind": "app_error",
            "anime_id": None, "anilist_id": None,
            "title": "Something went wrong",
            "message": "Raikō caught an unexpected error and kept running. Data Doctor can check "
                       "your library and show what happened.",
            "payload": {}})
        self._show_alerts_of("app_error")

    def _show_alerts_of(self, kind: str):
        notes = self.db.get_due_notifications(limit=1, kinds=[kind])
        if notes:
            self.notification_banner.show_notifications(notes)
            if self.detail_panel.isVisible():
                self.notification_banner.pause_for_detail()

    # ── taskbar badge ─────────────────────────────────────────────────────────

    def _unread_count(self) -> int:
        from core.background_check import OS_KINDS
        return sum(len(self.db.get_active_notifications(k)) for k in OS_KINDS)

    def _update_badge(self):
        """Red count on Raikō's taskbar button while it's open (Windows shows
        the window icon there). Clears when nothing new is waiting."""
        from PyQt6 import sip
        if sip.isdeleted(self):
            return
        n = self._unread_count()
        if n == getattr(self, "_badge_n", None):
            return
        self._badge_n = n
        base = getattr(self, "_base_icon", None)
        if base is None:
            base = self._base_icon = self.windowIcon()
        if not n:
            self.setWindowIcon(base)
            return
        from PyQt6.QtGui import QIcon, QPainter, QPixmap, QColor, QFont
        from PyQt6.QtCore import QRectF
        icon = QIcon()
        for size in (16, 24, 32, 48, 64, 256):
            px = base.pixmap(size, size)
            if px.isNull():
                px = QPixmap(size, size)
                px.fill(QColor("#11131c"))
            p = QPainter(px)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            d = size * 0.58
            r = QRectF(size - d, 0, d, d)
            p.setPen(QColor("#0b0d12"))
            p.setBrush(QColor("#ef4444"))
            p.drawEllipse(r)
            if size >= 24:
                f = QFont("Segoe UI")
                f.setBold(True)
                f.setPixelSize(max(7, int(d * (0.62 if n < 10 else 0.5))))
                p.setFont(f)
                p.setPen(QColor("#ffffff"))
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, str(n) if n < 100 else "99+")
            p.end()
            icon.addPixmap(px)
        self.setWindowIcon(icon)

    def _dismiss_notification(self, notification_id: int):
        QTimer.singleShot(200, self._update_badge)
        self.db.dismiss_notification(notification_id)

    # ── Metadata sync ──────────────────────────────────────────────────────────

    def _sync_metadata(self, only_ids: Optional[List[int]] = None):
        if self._meta_sync_running and only_ids is None:
            return
        from core.metadata_sync import MetadataSync
        if only_ids is None:
            self._meta_sync_running = True
        worker = Worker(MetadataSync(self.db).sync, only_ids=only_ids)
        worker.signals.result.connect(self._on_metadata_synced)
        if only_ids is None:
            worker.signals.finished.connect(lambda: setattr(self, "_meta_sync_running", False))
        run_worker(worker)

    def _on_metadata_synced(self, result: Dict):
        changed = set(result.get("changed") or [])
        art = set(result.get("art_changed") or [])
        for aid in changed | art:
            card = self._cards.get(aid)
            row = self.db.get_anime_by_id(aid)
            if not row:
                continue
            if card is not None:
                card.update_data(row)
                if aid in art:
                    self._load_card_image(row, card)
            if (self.detail_panel.isVisible() and self.selected_anime_id == aid):
                self.detail_panel.refresh_from_db()
                if aid in art:
                    self._load_detail_images(row)
        if changed:
            self._apply_card_overlays()
        notes = result.get("notifications") or []
        if notes:
            self.notification_banner.show_notifications(notes)
            if self.detail_panel.isVisible():
                self.notification_banner.pause_for_detail()

    def _refresh_open_anime(self, anime: Dict):
        """Opening an anime refreshes it in the background when stale:
        metadata (10 min for Planned, a day otherwise) and its promo/theme
        video list (daily). The panel re-renders when it lands."""
        import time as _t
        if anime.get("media_type") in ("movie", "tv") and anime.get("tmdb_id"):
            limit = 6 * 3600 if anime["media_type"] == "movie" else 3600
            if _t.time() - (anime.get("meta_synced_at") or 0) > limit:
                from core.kinema_sync import KinemaSync
                ks = KinemaSync(self.db)
                fn = ks.sync_movies if anime["media_type"] == "movie" else ks.sync_tv
                w = Worker(fn, only_ids=[anime["id"]])
                w.signals.result.connect(self._on_metadata_synced)
                run_worker(w)
            return
        if not anime.get("anilist_id") or anime.get("id", 0) <= 0:
            return
        ws = anime.get("watch_status") or "watching"
        meta_age = _t.time() - (anime.get("meta_synced_at") or 0)
        vids_age = _t.time() - (anime.get("videos_synced_at") or 0)
        need_meta = meta_age > (600 if ws == "planned" else 86400)
        need_vids = vids_age > 86400
        if not (need_meta or need_vids):
            return
        aid = anime["id"]

        def work():
            from core.metadata_sync import MetadataSync
            sync = MetadataSync(self.db)
            res = {"changed": [], "art_changed": [], "notifications": []}
            if need_meta:
                res = sync.sync(statuses=(ws,), only_ids=[aid])
            fresh = self.db.get_anime_by_id(aid)
            if fresh and need_vids and fresh.get("mal_id"):
                if sync.refresh_videos(fresh, notify=False) is not None:
                    res["changed"] = list(set(res.get("changed") or []) | {aid})
            return res

        worker = Worker(work)
        worker.signals.result.connect(self._on_metadata_synced)
        run_worker(worker)

    def _play_trailer(self, trailer_id: str, site: str, title: str):
        if not trailer_id:
            return
        from ui.trailer_player import show_trailer
        show_trailer(trailer_id, site or "youtube", title, self)

    def _inject_demo_planned(self):
        """`python main.py --demo-planned`: open a Plan-to-Watch anime in the
        new detail layout and show a sample "new trailer" notification.
        Nothing is written to the database."""
        from ui.toast import Toast
        planned = self.db.get_all_anime(watch_status="planned")
        if not planned:
            Toast.show(self, "Demo: add something to Plan to Watch first.", kind="info")
            return
        pick = next((a for a in planned if a.get("trailer_id")), planned[0])
        title = pick.get("english_title") or pick.get("romaji_title") or "Anime"
        self._set_filter("planned")

        def show():
            if not pick.get("trailer_id"):
                self._on_card_clicked(pick["id"])
                return
            self.notification_banner.show_notifications([{
                "id": -101, "kind": "upcoming_trailer", "anime_id": pick["id"],
                "title": "New trailer is out",
                "message": f"{title} has a trailer. Watch it right here.",
                "payload": {"trailer_id": pick["trailer_id"],
                            "trailer_site": pick.get("trailer_site") or "youtube",
                            "anime_title": title},
            }])
            self.notification_banner.raise_()
        QTimer.singleShot(1500, show)

    # ── New-season spotlight ───────────────────────────────────────────────────

    def _scan_sequels(self):
        from core.app_settings import app_settings
        from core.notification_service import NotificationService
        include_dropped = app_settings().value("new_season_include_dropped", True, type=bool)
        service = NotificationService(self.db)
        worker = Worker(service.scan_sequels, include_dropped=include_dropped)
        worker.signals.result.connect(self._on_new_seasons_ready)
        run_worker(worker)

    def _on_new_seasons_ready(self, items):
        self._apply_new_season_ribbons()
        if items:
            self.new_season_spotlight.show_notifications(items)
            if self.detail_panel.isVisible():
                self.new_season_spotlight.pause_for_detail()

    def _new_season_items(self) -> List[Dict]:
        if self._demo_new_season:
            return list(self._demo_items)
        return self.db.get_active_notifications("new_season")

    def _apply_new_season_ribbons(self):
        if not hasattr(self, "_cards") or not hasattr(self, "new_season_spotlight"):
            return
        by_prequel: Dict[int, Dict] = {}
        for n in self._new_season_items():
            aid = n.get("anime_id")
            if aid and aid not in by_prequel:
                by_prequel[aid] = n
        for aid, card in self._cards.items():
            n = by_prequel.get(aid)
            if not n:
                card.set_new_season_badge(None)
                continue
            payload = n.get("payload") or {}
            seq = payload.get("sequel") or {}
            text = {
                "airing": "NEW SEASON AIRING",
                "announced": "SEQUEL ANNOUNCED",
            }.get(payload.get("phase"), "NEW SEASON OUT")
            card.set_new_season_badge(text, f"{seq.get('title', 'New season')} - click to view")

    def _on_card_new_season(self, anime_id: int):
        items = [n for n in self._new_season_items() if n.get("anime_id") == anime_id]
        if items:
            self.new_season_spotlight.focus_prequel(anime_id, items)

    def _find_new_season(self, notification_id: int) -> Optional[Dict]:
        for n in self._new_season_items():
            if n.get("id") == notification_id:
                return n
        return None

    def _dismiss_new_season(self, notification_id: int):
        if notification_id > 0:
            self.db.dismiss_notification(notification_id)
        else:
            self._demo_items = [n for n in self._demo_items if n.get("id") != notification_id]
        self._apply_new_season_ribbons()

    def _remind_new_season(self, notification_id: int):
        if notification_id > 0:
            self.db.remind_notification_later(notification_id, hours=24)
        from ui.toast import Toast
        Toast.show(self, "Got it. You'll be reminded tomorrow.", kind="info")

    def _add_new_season(self, notification_id: int, watch_status: str):
        from ui.toast import Toast
        item = self._find_new_season(notification_id)
        seq = ((item or {}).get("payload") or {}).get("sequel") or {}
        sid = seq.get("id")
        label = "Plan to Watch" if watch_status == "planned" else "Watching"
        title = seq.get("title") or "This anime"
        if not item or not sid:
            return
        if notification_id < 0:
            Toast.show(self, f"Demo: '{title}' would be added as {label}.", kind="success")
            self._dismiss_new_season(notification_id)
            self.new_season_spotlight.remove_notification(notification_id)
            return
        if self.db.get_anime_by_anilist_id(sid):
            Toast.show(self, f"'{title}' is already in your library.", kind="info")
            self._dismiss_new_season(notification_id)
            self.new_season_spotlight.remove_notification(notification_id)
            return

        from core.api import get_anime_by_id

        def done(media):
            if not media:
                Toast.show(self, "Could not reach AniList. Try again in a moment.", kind="error")
                return
            from core.anime_add import add_media_to_library
            add_media_to_library(self.db, media, watch_status)
            self._dismiss_new_season(notification_id)
            self.new_season_spotlight.remove_notification(notification_id)
            Toast.show(self, f"'{title}' added as {label}.", kind="success")
            self._load_library_for_current_page()

        worker = Worker(get_anime_by_id, sid)
        worker.signals.result.connect(done)
        run_worker(worker)

    def _inject_demo_new_season(self):
        """`python main.py --demo-new-season`: show sample spotlights built
        from real AniList art, without writing anything to the database."""
        from ui.toast import Toast
        Toast.show(self, "Demo mode: showing sample new-season alerts.", kind="info")
        from ui.new_season_demo import build_demo_items
        completed = [
            {"anime_id": a["id"], "anilist_id": a.get("anilist_id"),
             "title": a.get("english_title") or a.get("romaji_title"),
             "rating": self.db.get_overall_rating(a["id"])}
            for a in self.db.get_all_anime(watch_status="completed") if a.get("anilist_id")
        ]
        worker = Worker(build_demo_items, completed)
        worker.signals.error.connect(lambda e: print("demo new-season failed:", e))

        def ready(items):
            self._demo_items = items or []
            self._apply_new_season_ribbons()
            self.new_season_spotlight.show_notifications(self._demo_items)

        worker.signals.result.connect(ready)
        run_worker(worker)

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

    def _status_banner(self, kind: str):
        """The themed status banner for 'offline' / 'anilist' / 'tmdb'."""
        banners = self.__dict__.setdefault("_status_banners", {})
        if kind not in banners:
            from ui.status_banner import StatusBanner
            retry = {"offline": None,
                     "anilist": lambda: self._anilist_status_monitor.force_check(),
                     "tmdb": lambda: self._tmdb_status_monitor.force_check()}[kind]
            banners[kind] = StatusBanner(kind, self.centralWidget(),
                                         on_retry=None if kind == "offline" else retry)
        return banners[kind]

    def _on_went_offline(self):
        self._status_banner("offline").show_banner()
        # the services can't be judged while you're offline
        for k in ("anilist", "tmdb"):
            if k in self.__dict__.get("_status_banners", {}):
                self._status_banners[k].hide_banner()

    def _on_reconnected(self):
        if "offline" in self.__dict__.get("_status_banners", {}):
            self._status_banners["offline"].hide_banner()
        QTimer.singleShot(500, self._refresh_airing)
        if hasattr(self, "_anilist_status_monitor"):
            self._anilist_status_monitor.force_check()
        if hasattr(self, "_tmdb_status_monitor"):
            self._tmdb_status_monitor.force_check()

    def _is_offline(self) -> bool:
        b = self.__dict__.get("_status_banners", {}).get("offline")
        return bool(b and b.is_shown())

    # ── AniList API status ────────────────────────────────────────────────────

    def _check_anilist_status(self):
        from core.anilist_status import AniListStatusMonitor
        self._anilist_status_monitor = AniListStatusMonitor(self)
        self._anilist_status_monitor.checked.connect(self._on_anilist_checked)
        self._anilist_status_monitor.api_down.connect(self._on_anilist_down)
        self._anilist_status_monitor.api_up.connect(self._on_anilist_up)
        self._anilist_status_monitor.start()

    def _on_anilist_checked(self, is_up: bool, message: str):
        self.anilist_status_label.setVisible(True)
        if is_up:
            self.anilist_status_label.setText("⬤  AniList OK")
            self.anilist_status_label.setStyleSheet("color:#34d399;")
        else:
            self.anilist_status_label.setText("⬤  AniList down")
            self.anilist_status_label.setStyleSheet("color:#fbbf24;")
        b = self.__dict__.get("_status_banners", {}).get("anilist")
        if b and b.is_shown():
            b.set_message(message)

    def _on_anilist_down(self, message: str):
        if not self._is_offline():
            self._status_banner("anilist").show_banner(message)

    def _on_anilist_up(self):
        b = self.__dict__.get("_status_banners", {}).get("anilist")
        if b:
            b.hide_banner()
        QTimer.singleShot(500, self._refresh_airing)

    # ── TMDB status (Kinema) ──────────────────────────────────────────────────

    def _check_tmdb_status(self):
        from core.anilist_status import TMDBStatusMonitor
        self._tmdb_status_monitor = TMDBStatusMonitor(self)
        self._tmdb_status_monitor.checked.connect(self._on_tmdb_checked)
        self._tmdb_status_monitor.api_down.connect(self._on_tmdb_down)
        self._tmdb_status_monitor.api_up.connect(self._on_tmdb_up)
        self._tmdb_status_monitor.start()

    def _on_tmdb_checked(self, is_up: bool, message: str):
        self.tmdb_status_label.setVisible(True)
        self.tmdb_status_label.setText("⬤  TMDB OK" if is_up else "⬤  TMDB down")
        self.tmdb_status_label.setStyleSheet("color:#34d399;" if is_up else "color:#fbbf24;")
        b = self.__dict__.get("_status_banners", {}).get("tmdb")
        if b and b.is_shown():
            b.set_message(message)

    def _on_tmdb_down(self, message: str):
        if not self._is_offline():
            self._status_banner("tmdb").show_banner(message)

    def _on_tmdb_up(self):
        b = self.__dict__.get("_status_banners", {}).get("tmdb")
        if b:
            b.hide_banner()

    # ── Resize ─────────────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_cards"):
            # Re-flow in place; a full reload here used to flash skeletons
            QTimer.singleShot(60, self._relayout_grid)
        if hasattr(self, "detail_panel") and self.detail_panel.isVisible():
            self._position_detail_overlay()
        if hasattr(self, "update_banner") and self.update_banner.isVisible():
            self.update_banner._reposition()
        if hasattr(self, "notification_banner") and self.notification_banner.isVisible():
            self.notification_banner._reposition()
        if hasattr(self, "new_season_spotlight") and self.new_season_spotlight.isVisible():
            self.new_season_spotlight.reposition()
        if self.__dict__.get("_status_banners"):
            from ui.status_banner import relayout
            relayout(self.centralWidget())

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
