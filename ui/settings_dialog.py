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
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QCursor, QPixmap

from core.database import DatabaseManager, BACKUP_DIR
from core.image_cache import cache_size_mb, purge_cache
from workers.workers import ImportWorker, run_worker


class SettingsDialog(QDialog):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        from core.app_settings import app_settings
        self.db = db
        self.settings = app_settings()
        self._json_path: Optional[str] = None
        self._nav_buttons: dict[str, QPushButton] = {}

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
        self.stack.addWidget(self._page_preferences())
        self.stack.addWidget(self._page_data())
        self.stack.addWidget(self._page_about())
        body_lay.addWidget(self.stack)

        root.addWidget(body, stretch=1)
        self._select_page("account")

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("settingsNav")
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(18, 22, 18, 18)
        lay.setSpacing(8)

        brand = QLabel("Miroku")
        brand.setObjectName("settingsNavBrand")
        lay.addWidget(brand)

        caption = QLabel("Preferences")
        caption.setObjectName("settingsNavCaption")
        lay.addWidget(caption)
        lay.addSpacing(18)

        for key, label in [
            ("account", "Account"),
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
        order = ["account", "preferences", "data", "about"]
        self.stack.setCurrentIndex(order.index(key))
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

        card, cl = self._card("Connection")

        try:
            from core.anilist_auth import AniListAuth, ANILIST_CLIENT_ID
            self._auth = AniListAuth()
            al_configured = bool(ANILIST_CLIENT_ID)
        except Exception:
            self._auth = None
            al_configured = False

        if not al_configured:
            cl.addWidget(self._body_text(
                "AniList sync is not configured yet. Add the Client ID and "
                "Secret in core/anilist_auth.py to enable score syncing."
            ))
        elif self._auth and self._auth.is_logged_in():
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
            login_btn = QPushButton("Connect AniList")
            login_btn.setObjectName("primaryBtn")
            login_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            login_btn.clicked.connect(self._al_login)
            row.addWidget(login_btn)
            row.addStretch()
            cl.addLayout(row)

            self._al_result = QLabel("")
            self._al_result.setObjectName("settingsMutedText")
            cl.addWidget(self._al_result)

        lay.addWidget(card)
        lay.addStretch()
        return page

    def _page_preferences(self) -> QWidget:
        page, lay = self._page()
        lay.addWidget(self._hero(
            "Preferences",
            "Tune the small behaviors that shape your daily tracking flow."
        ))

        display, dl = self._card("Display and refresh")

        theme_row = QHBoxLayout()
        theme_label = QLabel("Appearance")
        theme_label.setObjectName("settingsValueText")
        theme_row.addWidget(theme_label)
        theme_row.addStretch()
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.addItem("System", "system")
        self.theme_combo.addItem("Light (coming soon)", "light")
        self.theme_combo.setFixedWidth(180)
        from core.app_settings import preferred_theme
        current_theme = preferred_theme()
        idx = self.theme_combo.findData(current_theme)
        self.theme_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_row.addWidget(self.theme_combo)
        dl.addLayout(theme_row)
        dl.addWidget(self._helper_text(
            "System and Light currently use the dark stylesheet until a full light theme ships."
        ))

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
        lay.addWidget(display)

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
            "Miroku keeps the latest 5 backup snapshots in your local backup "
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
            "About Miroku",
            "A focused desktop tracker for currently airing and upcoming anime."
        ))

        about, al = self._card("")
        top = QHBoxLayout()

        resources = Path(__file__).parent.parent / "resources"
        logo_path = resources / "miroku_lettermark_1024.png"
        icon_path = logo_path if logo_path.exists() else resources / "miroku_lettermark_512.png"
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
        name = QLabel("Miroku")
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
            "Built with Python and PyQt6.",
            "Your library database is stored locally on this machine.",
            "Cover art remains the property of its respective copyright holders.",
        ]:
            al.addWidget(self._body_text(text))

        license_label = QLabel("MIT License")
        license_label.setObjectName("settingsPathText")
        al.addWidget(license_label)

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

    def _al_login(self):
        from core.anilist_auth import AniListAuth
        auth = AniListAuth()
        auth.login_success.connect(self._al_login_done)
        auth.login_failed.connect(self._al_login_fail)
        if hasattr(self, "_al_result"):
            self._al_result.setText("Browser opened. Finish login on AniList.")
        auth.start_login()
        self._auth_ref = auth

    def _al_login_done(self, username: str):
        if hasattr(self, "_al_result"):
            self._al_result.setText(f"Connected as {username}")
            self._al_result.setObjectName("settingsGoodText")
            self._al_result.style().unpolish(self._al_result)
            self._al_result.style().polish(self._al_result)
        from ui.toast import Toast
        Toast.show(self.window(), f"AniList connected as {username}.", kind="success")

    def _al_login_fail(self, error: str):
        if hasattr(self, "_al_result"):
            self._al_result.setText(f"Login failed: {error}")
            self._al_result.setObjectName("settingsBadText")
            self._al_result.style().unpolish(self._al_result)
            self._al_result.style().polish(self._al_result)

    def _al_logout(self):
        from core.anilist_auth import AniListAuth
        AniListAuth().logout()
        if hasattr(self, "_al_status"):
            self._al_status.setText("Logged out")
            self._al_status.setObjectName("settingsMutedText")
            self._al_status.style().unpolish(self._al_status)
            self._al_status.style().polish(self._al_status)
        from ui.toast import Toast
        Toast.show(self.window(), "AniList disconnected.", kind="info")

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
