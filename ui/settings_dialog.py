"""
Miroku - Settings Dialog
General preferences, AniList login, data migration, backup, about.
"""
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QFrame, QFileDialog, QMessageBox, QCheckBox,
    QProgressBar, QStackedWidget, QScrollArea, QComboBox,
    QLineEdit,
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QCursor, QPixmap

from core.database import DatabaseManager, BACKUP_DIR
from core.image_cache import cache_size_mb, purge_cache
from workers.workers import ImportWorker, run_worker


class SettingsDialog(QDialog):
    def __init__(self, db: DatabaseManager, parent=None, initial_page: str = "account"):
        super().__init__(parent)
        from core.app_settings import app_settings
        self.db = db
        self.settings = app_settings()
        self._initial_page = initial_page
        self._json_path: Optional[str] = None
        self._nav_buttons: dict[str, QPushButton] = {}
        self.preview_request = None          # (theme id, accent) when "Preview" was clicked

        self.setWindowTitle("Settings")
        self.setMinimumSize(780, 560)
        self.resize(860, 620)
        self.setObjectName("settingsDialog")
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        body = QWidget()
        body.setObjectName("settingsBody")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(28, 24, 28, 24)
        body_lay.setSpacing(18)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(4)

        title = QLabel("Settings")
        title.setObjectName("settingsTitle")
        title_box.addWidget(title)

        subtitle = QLabel("Manage account connections, local data, and app storage.")
        subtitle.setObjectName("settingsSubtitle")
        title_box.addWidget(subtitle)

        header.addLayout(title_box)
        header.addStretch()

        close = QPushButton("Close")
        close.setObjectName("secondaryBtn")
        close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close.clicked.connect(self.accept)
        header.addWidget(close)
        body_lay.addLayout(header)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_account())
        self.stack.addWidget(self._page_appearance())
        self.stack.addWidget(self._page_preferences())
        self.stack.addWidget(self._page_data())
        self.stack.addWidget(self._page_about())
        body_lay.addWidget(self.stack)

        root.addWidget(body, stretch=1)
        self._select_page(self._initial_page)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("settingsNav")
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(18, 22, 18, 18)
        lay.setSpacing(8)

        brand = QLabel("Raikō")
        brand.setObjectName("settingsNavBrand")
        lay.addWidget(brand)

        caption = QLabel("Preferences")
        caption.setObjectName("settingsNavCaption")
        lay.addWidget(caption)
        lay.addSpacing(18)

        for key, label in [
            ("account", "Account"),
            ("appearance", "Appearance"),
            ("preferences", "Preferences"),
            ("data", "Data and Backup"),
            ("about", "About"),
        ]:
            btn = QPushButton(label)
            btn.setObjectName("settingsNavBtn")
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(lambda _, k=key: self._select_page(k))
            self._nav_buttons[key] = btn
            lay.addWidget(btn)

        lay.addStretch()

        version = QLabel(self._version_text())
        version.setObjectName("settingsNavVersion")
        lay.addWidget(version)
        return sidebar

    def _select_page(self, key: str):
        order = ["account", "appearance", "preferences", "data", "about"]
        idx = order.index(key) if key in order else 0
        self.stack.setCurrentIndex(idx)
        for pid, btn in self._nav_buttons.items():
            btn.setProperty("active", "true" if pid == key else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # Pages

    def _page_account(self) -> QWidget:
        page, lay = self._page()
        lay.addWidget(self._hero(
            "AniList account",
            "Connect AniList when you want Miroku to offer rating sync."
        ))

        try:
            from core.anilist_auth import (
                REDIRECT_URI,
                credentials_configured,
                get_anilist_auth,
                get_client_credentials,
            )
            self._auth = get_anilist_auth(self)
            al_configured = credentials_configured()
            client_id, client_secret = get_client_credentials()
        except Exception:
            self._auth = None
            al_configured = False
            client_id, client_secret = "", ""
            REDIRECT_URI = "http://localhost:7731/callback"

        cred_card, cred_lay = self._card("API credentials")
        cred_lay.addWidget(self._body_text(
            "Create your own AniList developer app at anilist.co/settings/developer. "
            "Each install needs its own Client ID and Secret — the old bundled "
            "credentials no longer work."
        ))
        cred_lay.addWidget(self._helper_text(
            f"Set the redirect URI to exactly: {REDIRECT_URI}"
        ))

        id_row = QHBoxLayout()
        id_row.addWidget(self._body_text("Client ID"))
        id_row.addStretch()
        self._al_client_id = QLineEdit(client_id)
        self._al_client_id.setPlaceholderText("Your AniList client ID")
        self._al_client_id.setFixedWidth(280)
        id_row.addWidget(self._al_client_id)
        cred_lay.addLayout(id_row)

        secret_row = QHBoxLayout()
        secret_row.addWidget(self._body_text("Client Secret"))
        secret_row.addStretch()
        self._al_client_secret = QLineEdit(client_secret)
        self._al_client_secret.setPlaceholderText("Your AniList client secret")
        self._al_client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self._al_client_secret.setFixedWidth(280)
        secret_row.addWidget(self._al_client_secret)
        cred_lay.addLayout(secret_row)

        save_row = QHBoxLayout()
        self._al_cred_status = QLabel(
            "Credentials saved." if al_configured else "Save credentials before connecting."
        )
        self._al_cred_status.setObjectName(
            "settingsGoodText" if al_configured else "settingsMutedText"
        )
        save_row.addWidget(self._al_cred_status)
        save_row.addStretch()

        save_btn = QPushButton("Save credentials")
        save_btn.setObjectName("secondaryBtn")
        save_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save_btn.clicked.connect(self._al_save_credentials)
        save_row.addWidget(save_btn)
        cred_lay.addLayout(save_row)
        lay.addWidget(cred_card)

        card, cl = self._card("Connection")

        if self._auth and self._auth.is_logged_in():
            row = QHBoxLayout()
            self._al_status = QLabel(
                f"Connected as {self._auth.get_username()}"
            )
            self._al_status.setObjectName("settingsGoodText")
            row.addWidget(self._al_status)
            row.addStretch()

            out_btn = QPushButton("Log out")
            out_btn.setObjectName("dangerBtn")
            out_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            out_btn.clicked.connect(self._al_logout)
            row.addWidget(out_btn)
            cl.addLayout(row)
        else:
            cl.addWidget(self._body_text(
                "Log in with AniList to sync ratings. Miroku still asks before "
                "submitting anything to your AniList profile."
            ))

            row = QHBoxLayout()
            self._al_login_btn = QPushButton("Connect AniList")
            self._al_login_btn.setObjectName("primaryBtn")
            self._al_login_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._al_login_btn.clicked.connect(self._al_login)
            self._al_login_btn.setEnabled(al_configured)
            row.addWidget(self._al_login_btn)

            self._al_cancel_btn = QPushButton("Cancel")
            self._al_cancel_btn.setObjectName("secondaryBtn")
            self._al_cancel_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._al_cancel_btn.setVisible(False)
            self._al_cancel_btn.clicked.connect(self._al_cancel)
            row.addWidget(self._al_cancel_btn)

            row.addStretch()
            cl.addLayout(row)

            self._al_result = QLabel(
                "Not connected." if al_configured else "Save API credentials above first."
            )
            self._al_result.setObjectName("settingsMutedText")
            cl.addWidget(self._al_result)
            self._al_connect_signals()

        lay.addWidget(card)
        lay.addStretch()
        return page

    def _page_appearance(self) -> QWidget:
        page, lay = self._page()
        lay.addWidget(self._hero(
            "Appearance",
            "Pick how Raikō looks. Click a theme to use it, or Preview to walk through the app in it first."
        ))
        card, cl = self._card("Theme")
        from ui.appearance import AppearancePage
        self.appearance = AppearancePage()
        self.appearance.preview_requested.connect(self._preview_theme)
        cl.addWidget(self.appearance)
        lay.addWidget(card)
        lay.addStretch()
        return page

    def _preview_theme(self, tid: str, accent: str):
        self.preview_request = (tid, accent)
        self.accept()

    def _page_preferences(self) -> QWidget:
        page, lay = self._page()
        lay.addWidget(self._hero(
            "Preferences",
            "Tune the small behaviors that shape your daily tracking flow."
        ))

        display, dl = self._card("Display and refresh")

        # (themes moved to their own page: Settings → Appearance)

        auto_cb = QCheckBox("Refresh airing data automatically")
        auto_cb.setChecked(self.settings.value("auto_refresh", True, type=bool))
        auto_cb.stateChanged.connect(
            lambda v: self.settings.setValue("auto_refresh", bool(v))
        )
        dl.addWidget(auto_cb)
        dl.addWidget(self._helper_text("Checks active shows every 10 minutes."))

        banner_cb = QCheckBox("Show banner images in the detail panel")
        banner_cb.setChecked(self.settings.value("show_banners", True, type=bool))
        banner_cb.stateChanged.connect(
            lambda v: self.settings.setValue("show_banners", bool(v))
        )
        dl.addWidget(banner_cb)
        dl.addWidget(self._helper_text(
            "Keeps anime pages richer when banner art is available."
        ))

        links_browser_cb = QCheckBox("Always open quick links in browser")
        links_browser_cb.setChecked(
            self.settings.value("links_always_open_browser", False, type=bool)
        )
        links_browser_cb.stateChanged.connect(
            lambda v: self.settings.setValue("links_always_open_browser", bool(v))
        )
        dl.addWidget(links_browser_cb)
        dl.addWidget(self._helper_text(
            "When off, Telegram and other app links open in their native apps when available."
        ))

        sequel_cb = QCheckBox("Alert me about new seasons of anime I dropped")
        sequel_cb.setChecked(
            self.settings.value("new_season_include_dropped", True, type=bool)
        )
        sequel_cb.stateChanged.connect(
            lambda v: self.settings.setValue("new_season_include_dropped", bool(v))
        )
        dl.addWidget(sequel_cb)
        dl.addWidget(self._helper_text(
            "Sequels of completed anime are always announced. Checked every 6 hours."
        ))

        arch_row = QHBoxLayout()
        arch_row.addWidget(QLabel("Auto-archive completed anime"))
        arch_row.addStretch()
        self.archive_combo = QComboBox()
        _arch_opts = [("Never", 0), ("After 3 months", 90),
                      ("After 6 months", 182), ("After 1 year", 365)]
        for text, days in _arch_opts:
            self.archive_combo.addItem(text, days)
        _cur_days = int(self.settings.value("auto_archive_days", 0) or 0)
        self.archive_combo.setCurrentIndex(
            next((i for i, (_t, d) in enumerate(_arch_opts) if d == _cur_days), 0))
        self.archive_combo.currentIndexChanged.connect(
            lambda i: self.settings.setValue("auto_archive_days", self.archive_combo.itemData(i))
        )
        arch_row.addWidget(self.archive_combo)
        dl.addLayout(arch_row)
        dl.addWidget(self._helper_text(
            "Archived shows leave the Completed list but stay in search."
        ))
        lay.addWidget(display)

        # TV shows & movies (Kinema) - data from TMDB
        kin, kl = self._card("TV shows & movies")
        reg_row = QHBoxLayout()
        reg_lbl = QLabel("Your country")
        reg_lbl.setObjectName("settingsValueText")
        reg_row.addWidget(reg_lbl)
        reg_row.addStretch()
        self.region_combo = QComboBox()
        _regions = [("United States", "US"), ("United Kingdom", "GB"), ("Canada", "CA"),
                    ("France", "FR"), ("Germany", "DE"), ("Spain", "ES"), ("Italy", "IT"),
                    ("Japan", "JP"), ("Brazil", "BR"), ("Mexico", "MX"), ("India", "IN"),
                    ("Australia", "AU"), ("Nigeria", "NG"), ("South Africa", "ZA"),
                    ("Cameroon", "CM")]
        for text, code in _regions:
            self.region_combo.addItem(text, code)
        _cur_region = str(self.settings.value("tmdb_region", "US") or "US").upper()
        self.region_combo.setCurrentIndex(
            next((i for i, (_t, c) in enumerate(_regions) if c == _cur_region), 0))
        self.region_combo.setFixedWidth(180)
        self.region_combo.currentIndexChanged.connect(
            lambda i: self.settings.setValue("tmdb_region", self.region_combo.itemData(i)))
        reg_row.addWidget(self.region_combo)
        kl.addLayout(reg_row)
        kl.addWidget(self._helper_text(
            "Used for where-to-watch and local release dates."))

        alert_row = QHBoxLayout()
        alert_lbl = QLabel("Tell me when a Watchlist film is out")
        alert_lbl.setObjectName("settingsValueText")
        alert_row.addWidget(alert_lbl)
        alert_row.addStretch()
        self.movie_alert_combo = QComboBox()
        _modes = [("Digitally (HD)", "digital"), ("In cinemas", "cinema"),
                  ("Both", "both"), ("Never", "off")]
        for text, key in _modes:
            self.movie_alert_combo.addItem(text, key)
        _cur_mode = str(self.settings.value("movie_alert_mode", "digital") or "digital")
        self.movie_alert_combo.setCurrentIndex(
            next((i for i, (_t, k) in enumerate(_modes) if k == _cur_mode), 0))
        self.movie_alert_combo.setFixedWidth(180)
        self.movie_alert_combo.currentIndexChanged.connect(
            lambda i: self.settings.setValue("movie_alert_mode", self.movie_alert_combo.itemData(i)))
        alert_row.addWidget(self.movie_alert_combo)
        kl.addLayout(alert_row)
        kl.addWidget(self._helper_text(
            "One notification per film, the day it's out. Your Watchlist also shows "
            "Ready to watch and Waiting for HD at a glance."))

        from PyQt6.QtWidgets import QLineEdit
        key_row = QHBoxLayout()
        key_lbl = QLabel("Your own TMDB key (optional)")
        key_lbl.setObjectName("settingsValueText")
        key_row.addWidget(key_lbl)
        key_row.addStretch()
        self.tmdb_key_edit = QLineEdit()
        self.tmdb_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.tmdb_key_edit.setPlaceholderText("Paste a key or read token")
        self.tmdb_key_edit.setFixedWidth(240)
        self.tmdb_key_edit.setText(str(self.settings.value("tmdb_token_override", "") or ""))
        self.tmdb_key_edit.editingFinished.connect(
            lambda: self.settings.setValue("tmdb_token_override", self.tmdb_key_edit.text().strip()))
        key_row.addWidget(self.tmdb_key_edit)
        kl.addLayout(key_row)
        kl.addWidget(self._helper_text(
            "Leave empty to use the built-in key. A free key is available from themoviedb.org."))
        lay.addWidget(kin)

        # Windows notifications while Raikō is closed (opt-in scheduled check)
        notif, nl = self._card("Notifications when Raikō is closed")
        from core import background_check as bc
        self.os_notify_cb = QCheckBox("Notify me about new episodes, HD releases and new seasons even when Raikō is closed")
        self.os_notify_cb.setChecked(bc.enabled())
        nl.addWidget(self.os_notify_cb)
        freq_row = QHBoxLayout()
        freq_row.addWidget(QLabel("Check"))
        freq_row.addStretch()
        self.os_notify_freq = QComboBox()
        for text, h in (("Every hour", 1), ("Every 3 hours", 3), ("Every 6 hours", 6), ("Every 12 hours", 12)):
            self.os_notify_freq.addItem(text, h)
        self.os_notify_freq.setCurrentIndex(max(0, self.os_notify_freq.findData(bc.interval_hours())))
        self.os_notify_freq.setFixedWidth(180)
        freq_row.addWidget(self.os_notify_freq)
        nl.addLayout(freq_row)
        test_row = QHBoxLayout()
        self.os_notify_status = QLabel("")
        self.os_notify_status.setObjectName("settingsMutedText")
        self.os_notify_status.setWordWrap(True)
        test_row.addWidget(self.os_notify_status, 1)
        test_btn = QPushButton("Send a test notification")
        test_btn.setObjectName("secondaryBtn")
        test_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        test_btn.clicked.connect(self._test_os_notification)
        test_row.addWidget(test_btn)
        nl.addLayout(test_row)
        nl.addWidget(self._helper_text(
            "Windows starts Raikō invisibly for a few seconds at each check (and after you log in or "
            "your PC wakes), shows a notification for anything new, then closes it again. Nothing keeps "
            "running in between. Each event notifies once; Windows Focus / Do Not Disturb is respected."))
        self.os_notify_cb.toggled.connect(self._toggle_os_notify)
        self.os_notify_freq.currentIndexChanged.connect(
            lambda _i: self.os_notify_cb.isChecked() and self._toggle_os_notify(True))
        self._refresh_os_notify_status()
        lay.addWidget(notif)

        cache, cl = self._card("Image cache")
        row = QHBoxLayout()
        self.cache_lbl = QLabel(f"{cache_size_mb()} MB stored locally")
        self.cache_lbl.setObjectName("settingsValueText")
        row.addWidget(self.cache_lbl)
        row.addStretch()

        clr = QPushButton("Clear cache")
        clr.setObjectName("dangerBtn")
        clr.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        clr.clicked.connect(self._clear_cache)
        row.addWidget(clr)
        cl.addLayout(row)
        cl.addWidget(self._helper_text(
            "Cached covers and banners will download again when needed."
        ))
        lay.addWidget(cache)
        lay.addStretch()
        return page

    def _page_data(self) -> QWidget:
        page, lay = self._page()
        lay.addWidget(self._hero(
            "Data and backup",
            "Import older libraries and keep a local safety copy of your data."
        ))

        migrate, ml = self._card("Legacy import")
        ml.addWidget(self._body_text(
            "Import anime_info.json from the old terminal version. Existing "
            "anime will not be duplicated."
        ))

        self.mig_bar = QProgressBar()
        self.mig_bar.setFixedHeight(3)
        self.mig_bar.setRange(0, 0)
        self.mig_bar.setVisible(False)
        ml.addWidget(self.mig_bar)

        row = QHBoxLayout()
        self.mig_path_lbl = QLabel("No file selected")
        self.mig_path_lbl.setObjectName("settingsMutedText")
        row.addWidget(self.mig_path_lbl)
        row.addStretch()

        browse = QPushButton("Browse")
        browse.setObjectName("secondaryBtn")
        browse.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        browse.clicked.connect(self._browse)
        row.addWidget(browse)

        self.import_btn = QPushButton("Import")
        self.import_btn.setObjectName("primaryBtn")
        self.import_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._run_import)
        row.addWidget(self.import_btn)
        ml.addLayout(row)
        lay.addWidget(migrate)

        backup, bl = self._card("Backups")
        bl.addWidget(self._body_text(
            "Raikō keeps the latest 5 backup snapshots in your local backup "
            "folder."
        ))
        path = QLabel(str(BACKUP_DIR))
        path.setObjectName("settingsPathText")
        path.setWordWrap(True)
        bl.addWidget(path)

        br = QHBoxLayout()
        bnow = QPushButton("Create backup")
        bnow.setObjectName("secondaryBtn")
        bnow.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        bnow.clicked.connect(self._backup)
        br.addWidget(bnow)
        br.addStretch()
        bl.addLayout(br)
        lay.addWidget(backup)

        # ── Data Doctor ───────────────────────────────────────────────────
        doctor, dl = self._card("Data Integrity")
        dl.addWidget(self._body_text(
            "Scan your library for inconsistencies — overcounted episodes, "
            "duplicate entries, status mismatches — and fix them interactively. "
            "Every fix is shown to you before anything changes."
        ))
        dr = QHBoxLayout()
        doc_btn = QPushButton("Open Data Doctor")
        doc_btn.setObjectName("secondaryBtn")
        doc_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        doc_btn.clicked.connect(self._open_data_doctor)
        dr.addWidget(doc_btn)
        dr.addStretch()
        dl.addLayout(dr)
        lay.addWidget(doctor)

        lay.addStretch()
        return page

    def _page_about(self) -> QWidget:
        page, lay = self._page()
        lay.addWidget(self._hero(
            "About Raikō",
            "One home for everything you watch: anime in Miroku, TV shows and movies in Kinema."
        ))

        about, al = self._card("")
        top = QHBoxLayout()

        resources = Path(__file__).parent.parent / "resources"
        icon_path = resources / "raiko_icon_256.png"
        if icon_path.exists():
            icon = QLabel()
            px = QPixmap(str(icon_path)).scaled(
                72, 72,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            icon.setPixmap(px)
            top.addWidget(icon)

        copy = QVBoxLayout()
        name = QLabel("Raikō")
        name.setObjectName("settingsAboutName")
        copy.addWidget(name)

        version = QLabel(self._version_text())
        version.setObjectName("settingsMutedText")
        copy.addWidget(version)
        top.addLayout(copy)
        top.addStretch()
        al.addLayout(top)

        for text in [
            "Powered by the AniList GraphQL API for public anime data.",
            "TV and movie data from TMDB. This product uses the TMDB API "
            "but is not endorsed or certified by TMDB.",
            "Where-to-watch availability provided by JustWatch.",
            "Built with Python and PyQt6.",
            "Your library database is stored locally on this machine.",
            "Cover art remains the property of its respective copyright holders.",
        ]:
            al.addWidget(self._body_text(text))

        license_label = QLabel("MIT License")
        license_label.setObjectName("settingsPathText")
        al.addWidget(license_label)
        replay = QPushButton("Replay the welcome tour")
        replay.setObjectName("secondaryBtn")
        replay.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        replay.clicked.connect(self._replay_tour)
        al.addWidget(replay, alignment=Qt.AlignmentFlag.AlignLeft)

        lay.addWidget(about)
        lay.addStretch()
        return page

    def _on_theme_changed(self):
        theme = self.theme_combo.currentData() or "dark"
        from core.app_settings import set_preferred_theme
        set_preferred_theme(theme)
        mw = self.parent()
        while mw is not None:
            if hasattr(mw, "_load_theme"):
                mw._load_theme(theme)
                break
            mw = mw.parent()
        from ui.toast import Toast
        Toast.show(self.window(), "Appearance preference saved.", kind="success")

    # AniList actions

    def _al_set_busy(self, busy: bool):
        if hasattr(self, "_al_login_btn"):
            self._al_login_btn.setEnabled(not busy)
        if hasattr(self, "_al_cancel_btn"):
            self._al_cancel_btn.setVisible(busy)

    def _al_set_result(self, text: str, tone: str = "muted"):
        if not hasattr(self, "_al_result"):
            return
        self._al_result.setText(text)
        name = {
            "good": "settingsGoodText",
            "bad": "settingsBadText",
            "muted": "settingsMutedText",
        }.get(tone, "settingsMutedText")
        self._al_result.setObjectName(name)
        self._al_result.style().unpolish(self._al_result)
        self._al_result.style().polish(self._al_result)

    def _al_connect_signals(self):
        if self._auth is None:
            return
        for sig, slot in (
            (self._auth.login_success, self._al_login_done),
            (self._auth.login_failed, self._al_login_fail),
            (self._auth.login_status, self._al_login_status),
        ):
            try:
                sig.disconnect(slot)
            except TypeError:
                pass
            sig.connect(slot)

    def _al_save_credentials(self):
        from core.anilist_auth import save_client_credentials, credentials_configured

        client_id = self._al_client_id.text().strip()
        client_secret = self._al_client_secret.text().strip()
        if not client_id or not client_secret:
            self._al_cred_status.setText("Enter both Client ID and Secret.")
            self._al_cred_status.setObjectName("settingsBadText")
            self._al_cred_status.style().unpolish(self._al_cred_status)
            self._al_cred_status.style().polish(self._al_cred_status)
            return

        save_client_credentials(client_id, client_secret)
        self._al_cred_status.setText("Credentials saved.")
        self._al_cred_status.setObjectName("settingsGoodText")
        self._al_cred_status.style().unpolish(self._al_cred_status)
        self._al_cred_status.style().polish(self._al_cred_status)

        if hasattr(self, "_al_login_btn"):
            self._al_login_btn.setEnabled(credentials_configured())
        if hasattr(self, "_al_result"):
            self._al_set_result("Credentials saved. You can connect now.", "good")

    def _al_login(self):
        from core.anilist_auth import credentials_configured, get_anilist_auth

        if not credentials_configured():
            self._al_set_result(
                "Save your AniList Client ID and Secret above first.",
                "bad",
            )
            return

        self._auth = get_anilist_auth(self)
        self._al_connect_signals()
        self._al_set_busy(True)
        self._al_set_result("Starting a fresh AniList login…", "muted")
        self._auth.start_login()

    def _al_cancel(self):
        if self._auth is not None:
            self._auth.cancel_login()
        self._al_set_busy(False)
        self._al_set_result("Cancelling login…", "muted")

    def _al_login_status(self, message: str):
        self._al_set_result(message, "muted")

    def _al_login_done(self, username: str):
        self._al_set_busy(False)
        from ui.toast import Toast
        Toast.show(self.window(), f"AniList connected as {username}.", kind="success")
        self._refresh_account_page()

    def _al_login_fail(self, error: str):
        self._al_set_busy(False)
        self._al_set_result(error, "bad")

    def _refresh_account_page(self):
        current = self.stack.currentIndex()
        old = self.stack.widget(0)
        self.stack.removeWidget(old)
        old.deleteLater()
        self.stack.insertWidget(0, self._page_account())
        self.stack.setCurrentIndex(current)

    def _al_logout(self):
        from core.anilist_auth import get_anilist_auth

        self._auth = get_anilist_auth(self)
        self._auth.logout()
        from ui.toast import Toast
        Toast.show(self.window(), "AniList disconnected.", kind="info")
        self._refresh_account_page()

    # Data actions

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select anime_info.json", str(Path.home()), "JSON Files (*.json)"
        )
        if path:
            self._json_path = path
            self.mig_path_lbl.setText(Path(path).name)
            self.import_btn.setEnabled(True)

    def _run_import(self):
        if not self._json_path:
            return
        if QMessageBox.question(
            self,
            "Confirm Import",
            "Import all anime from this anime_info.json?\n"
            "Existing entries will not be duplicated.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return

        self.mig_bar.setVisible(True)
        self.import_btn.setEnabled(False)

        worker = ImportWorker(self._json_path, self.db)
        worker.signals.result.connect(self._on_import_done)
        worker.signals.error.connect(self._on_import_error)
        worker.signals.finished.connect(lambda: self.mig_bar.setVisible(False))
        run_worker(worker)

    def _on_import_done(self, count: int):
        self.import_btn.setEnabled(True)
        from ui.toast import Toast
        Toast.show(self.window(), f"Imported {count} anime.", kind="success")

    def _on_import_error(self, error: str):
        self.import_btn.setEnabled(True)
        QMessageBox.critical(self, "Import Failed", f"Error:\n{error}")

    def _backup(self):
        try:
            dest = self.db.backup()
            from ui.toast import Toast
            Toast.show(self.window(), f"Backup created: {dest.name}", kind="success")
        except Exception as exc:
            QMessageBox.critical(self, "Backup Failed", str(exc))
    
    def _main_db(self):
        mw = self.parent()
        while mw is not None and not hasattr(mw, "db"):
            mw = mw.parent()
        return getattr(mw, "db", None) or self.db

    def _toggle_os_notify(self, on: bool):
        from core import background_check as bc
        if on:
            ok = bc.enable(self._main_db(), self.os_notify_freq.currentData() or 3)
            if not ok:
                self.os_notify_cb.blockSignals(True)
                self.os_notify_cb.setChecked(False)
                self.os_notify_cb.blockSignals(False)
                QMessageBox.warning(self, "Couldn't set up notifications",
                                    "Windows didn't accept the scheduled check. Please try again.")
        else:
            bc.disable()
        self._refresh_os_notify_status()

    def _refresh_os_notify_status(self):
        from core import background_check as bc
        if bc.enabled():
            self.os_notify_status.setText(f"On · checks every {bc.interval_hours()} h, at log-in and after sleep.")
        else:
            self.os_notify_status.setText("Off. New things only show inside Raikō.")
        self.os_notify_freq.setEnabled(bc.enabled())

    def _test_os_notification(self):
        from core import background_check as bc
        shown = bc.test_toast()
        if not shown:
            QMessageBox.information(self, "Test notification",
                                    "Windows didn't show it. Check Settings → System → Notifications → Raikō.")

    def _replay_tour(self):
        mw = self.parent()
        while mw is not None and not hasattr(mw, "start_onboarding"):
            mw = mw.parent()
        self.accept()
        if mw is not None:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(150, lambda: mw.start_onboarding(False))

    def _open_data_doctor(self):
        from ui.data_doctor import DataDoctorDialog
        dlg = DataDoctorDialog(self.db, self)
        dlg.data_changed.connect(self._on_doctor_fixed)
        dlg.exec()

    def _on_doctor_fixed(self):
        """Refresh the main window library immediately after data fixes."""
        mw = self.parent()
        if mw is None:
            return
        # Walk up to MainWindow
        w = mw
        while w is not None:
            if hasattr(w, "_load_library"):
                w._load_library()
                w._update_stats_strip()
                from ui.toast import Toast
                Toast.show(w, "Library refreshed after data fixes.", kind="success")
                break
            w = w.parent()

    def _clear_cache(self):
        if QMessageBox.question(
            self,
            "Clear Cache",
            "Delete all cached cover images?\nThey will re-download when needed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            purge_cache(max_size_mb=0)
            self.cache_lbl.setText("0.0 MB stored locally")
            from ui.toast import Toast
            Toast.show(self.window(), "Image cache cleared.", kind="success")

    # Helpers

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(14)
        scroll.setWidget(page)
        return scroll, lay

    def _hero(self, title: str, subtitle: str) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 2)
        lay.setSpacing(4)

        t = QLabel(title)
        t.setObjectName("settingsPageTitle")
        lay.addWidget(t)

        s = QLabel(subtitle)
        s.setObjectName("settingsPageSubtitle")
        s.setWordWrap(True)
        lay.addWidget(s)
        return box

    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("settingsCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        if title:
            label = QLabel(title)
            label.setObjectName("settingsCardTitle")
            lay.addWidget(label)
        return card, lay

    def _body_text(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("settingsBodyText")
        label.setWordWrap(True)
        return label

    def _helper_text(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("settingsHelperText")
        label.setWordWrap(True)
        return label

    def _version_text(self) -> str:
        try:
            from core.updater import APP_VERSION
            version = APP_VERSION
        except Exception:
            version = "2.0.0"
        return f"Version {version}"
