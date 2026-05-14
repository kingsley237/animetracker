"""
Miroku — Settings Dialog
General preferences, AniList login, data migration, backup, about.
"""
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QFrame, QFileDialog, QMessageBox, QTabWidget,
    QCheckBox, QComboBox, QProgressBar,
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QCursor, QPixmap

from core.database import DatabaseManager, BACKUP_DIR
from core.image_cache import cache_size_mb, purge_cache
from workers.workers import ImportWorker, run_worker


class SettingsDialog(QDialog):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db       = db
        self.settings = QSettings("Miroku", "Miroku")
        self._json_path: Optional[str] = None

        self.setWindowTitle("Settings")
        self.setMinimumSize(560, 520)
        self.setStyleSheet("background:#0f1118;")
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        # Header — no close button (window already has one)
        hdr = QWidget()
        hdr.setStyleSheet("background:#0a0c10;border-bottom:1px solid #1a1d28;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24, 16, 24, 16)
        t = QLabel("Settings")
        t.setObjectName("dialogTitle")
        hl.addWidget(t)
        hl.addStretch()
        lay.addWidget(hdr)

        tabs = QTabWidget()
        tabs.setStyleSheet("QTabWidget::pane{padding:20px;background:transparent;}")
        tabs.addTab(self._general_tab(),  "General")
        tabs.addTab(self._data_tab(),     "Data & Migration")
        tabs.addTab(self._about_tab(),    "About")
        lay.addWidget(tabs)

    # ── General ───────────────────────────────────────────────────────────────

    def _general_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)
        lay.setSpacing(16)

        # ── AniList Account ──────────────────────────────────────────────
        lay.addWidget(self._section("ANILIST ACCOUNT"))

        try:
            from core.anilist_auth import AniListAuth, ANILIST_CLIENT_ID
            self._auth = AniListAuth()
            al_configured = bool(ANILIST_CLIENT_ID)
        except Exception:
            al_configured = False
            self._auth = None

        if not al_configured:
            lbl = QLabel(
                "AniList sync is not yet configured. "
                "Open core/anilist_auth.py and add your Client ID and Secret "
                "from anilist.co/settings/developer to enable score syncing."
            )
            lbl.setStyleSheet("font-size:12px;color:#4a5070;")
            lbl.setWordWrap(True)
            lay.addWidget(lbl)
        elif self._auth and self._auth.is_logged_in():
            user_row = QHBoxLayout()
            self._al_status = QLabel(
                f"✓  Logged in as  {self._auth.get_username()}"
            )
            self._al_status.setStyleSheet("font-size:13px;color:#34d399;")
            user_row.addWidget(self._al_status)
            user_row.addStretch()
            out_btn = QPushButton("Log out")
            out_btn.setObjectName("dangerBtn")
            out_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            out_btn.clicked.connect(self._al_logout)
            user_row.addWidget(out_btn)
            lay.addLayout(user_row)
        else:
            desc = QLabel(
                "Log in with your AniList account to sync ratings.\n"
                "You control exactly what gets submitted — always shown before sending."
            )
            desc.setStyleSheet("font-size:12px;color:#6b7280;")
            desc.setWordWrap(True)
            lay.addWidget(desc)

            login_row = QHBoxLayout()
            login_btn = QPushButton("Connect AniList Account")
            login_btn.setObjectName("primaryBtn")
            login_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            login_btn.clicked.connect(self._al_login)
            login_row.addWidget(login_btn)
            login_row.addStretch()
            lay.addLayout(login_row)

            self._al_result = QLabel("")
            self._al_result.setStyleSheet("font-size:12px;color:#4a5070;")
            lay.addWidget(self._al_result)

        # ── Display ──────────────────────────────────────────────────────
        lay.addWidget(self._section("DISPLAY"))

        auto_cb = QCheckBox("Auto-refresh airing data every 10 minutes")
        auto_cb.setChecked(self.settings.value("auto_refresh", True, type=bool))
        auto_cb.stateChanged.connect(
            lambda v: self.settings.setValue("auto_refresh", bool(v))
        )
        lay.addWidget(auto_cb)

        banner_cb = QCheckBox("Show banner images in detail panel")
        banner_cb.setChecked(self.settings.value("show_banners", True, type=bool))
        banner_cb.stateChanged.connect(
            lambda v: self.settings.setValue("show_banners", bool(v))
        )
        lay.addWidget(banner_cb)

        # ── Image cache ──────────────────────────────────────────────────
        lay.addWidget(self._section("IMAGE CACHE"))

        cr = QHBoxLayout()
        self.cache_lbl = QLabel(f"Cache size: {cache_size_mb()} MB")
        self.cache_lbl.setStyleSheet("font-size:13px;color:#9da5c0;")
        cr.addWidget(self.cache_lbl)
        cr.addStretch()
        clr = QPushButton("Clear Cache")
        clr.setObjectName("dangerBtn")
        clr.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        clr.clicked.connect(self._clear_cache)
        cr.addWidget(clr)
        lay.addLayout(cr)

        lay.addStretch()
        return w

    # ── AniList login actions ─────────────────────────────────────────────────

    def _al_login(self):
        from core.anilist_auth import AniListAuth
        auth = AniListAuth()
        auth.login_success.connect(self._al_login_done)
        auth.login_failed.connect(self._al_login_fail)
        if hasattr(self, '_al_result'):
            self._al_result.setText(
                "Browser opened — log in on AniList then return here."
            )
        auth.start_login()
        self._auth_ref = auth  # keep alive

    def _al_login_done(self, username: str):
        QMessageBox.information(
            self, "AniList Connected",
            f"Logged in as {username}. "
            "Your ratings will now offer to sync to AniList."
        )
        if hasattr(self, '_al_result'):
            self._al_result.setText(f"Logged in as {username}")
            self._al_result.setStyleSheet("font-size:12px;color:#34d399;")

    def _al_login_fail(self, error: str):
        if hasattr(self, '_al_result'):
            self._al_result.setText(f"Login failed: {error}")
            self._al_result.setStyleSheet("font-size:12px;color:#f87171;")

    def _al_logout(self):
        from core.anilist_auth import AniListAuth
        AniListAuth().logout()
        if hasattr(self, '_al_status'):
            self._al_status.setText("Logged out.")
            self._al_status.setStyleSheet("font-size:12px;color:#4a5070;")

    def _on_theme_changed(self, text: str):
        theme = "light" if text == "Light" else "dark"
        self.settings.setValue("theme", theme)
        if self.parent() and hasattr(self.parent(), "toggle_theme"):
            self.parent().toggle_theme()

    # ── Data ──────────────────────────────────────────────────────────────────

    def _data_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)
        lay.setSpacing(16)

        lay.addWidget(self._section("MIGRATE FROM OLD VERSION (anime_info.json)"))

        desc = QLabel(
            "If you used the old terminal version, import your anime_info.json here.\n"
            "All anime, episodes, ratings and dropped entries will be migrated.\n"
            "No duplicates will be created."
        )
        desc.setStyleSheet("font-size:12px;color:#6b7280;line-height:1.6;")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        self.mig_bar = QProgressBar()
        self.mig_bar.setFixedHeight(2)
        self.mig_bar.setRange(0, 0)
        self.mig_bar.setVisible(False)
        self.mig_bar.setStyleSheet(
            "QProgressBar{background:#1a1d28;border:none;}"
            "QProgressBar::chunk{background:#34d399;}"
        )
        lay.addWidget(self.mig_bar)

        mr = QHBoxLayout()
        self.mig_path_lbl = QLabel("No file selected")
        self.mig_path_lbl.setStyleSheet("font-size:12px;color:#4a5070;")
        mr.addWidget(self.mig_path_lbl)
        mr.addStretch()

        browse = QPushButton("Browse…")
        browse.setObjectName("secondaryBtn")
        browse.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        browse.clicked.connect(self._browse)
        mr.addWidget(browse)

        self.import_btn = QPushButton("Import Now")
        self.import_btn.setObjectName("primaryBtn")
        self.import_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._run_import)
        mr.addWidget(self.import_btn)
        lay.addLayout(mr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#1a1d28;")
        lay.addWidget(sep)

        lay.addWidget(self._section("BACKUP"))
        bd = QLabel(
            f"Automatic backups keep the last 5 snapshots.\n"
            f"Backup folder:  {BACKUP_DIR}"
        )
        bd.setStyleSheet("font-size:12px;color:#6b7280;")
        bd.setWordWrap(True)
        lay.addWidget(bd)

        br = QHBoxLayout()
        bnow = QPushButton("Backup Now")
        bnow.setObjectName("secondaryBtn")
        bnow.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        bnow.clicked.connect(self._backup)
        br.addWidget(bnow)
        br.addStretch()
        lay.addLayout(br)
        lay.addStretch()
        return w

    # ── About ─────────────────────────────────────────────────────────────────

    def _about_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)
        lay.setSpacing(10)

        # Logo
        resources = Path(__file__).parent.parent / "resources"
        logo_path = resources / "logo_lettermark_256.png"
        icon_path = logo_path if logo_path.exists() else resources / "icon_256.png"
        if icon_path.exists():
            ir = QHBoxLayout()
            px_lbl = QLabel()
            px = QPixmap(str(icon_path)).scaled(
                72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            px_lbl.setPixmap(px)
            ir.addWidget(px_lbl)
            ir.addStretch()
            lay.addLayout(ir)

        name_lbl = QLabel("Miroku")
        name_lbl.setStyleSheet(
            "font-size:24px;font-weight:700;color:#7c6af7;letter-spacing:1px;"
        )
        lay.addWidget(name_lbl)

        try:
            from core.updater import APP_VERSION
            _ver = APP_VERSION
        except Exception:
            _ver = "2.0.0"
        ver_lbl = QLabel(f"Version {_ver}")
        ver_lbl.setStyleSheet("font-size:13px;color:#4a5070;")
        lay.addWidget(ver_lbl)

        lay.addSpacing(8)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#1a1d28;")
        lay.addWidget(sep)

        for text in [
            "Powered by the AniList GraphQL API (public, no auth required for browsing)",
            "Built with Python 3.11+ and PyQt6",
            "Cover art © respective copyright holders",
            "Database stored locally — your data never leaves your machine",
        ]:
            lbl = QLabel(text)
            lbl.setStyleSheet("font-size:12px;color:#4a5070;")
            lbl.setWordWrap(True)
            lay.addWidget(lbl)

        lay.addStretch()

        lic = QLabel("Released under the MIT License")
        lic.setStyleSheet("font-size:11px;color:#3b4260;")
        lay.addWidget(lic)
        return w

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _section(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            "font-size:10px;color:#3b4260;font-weight:700;letter-spacing:1.5px;"
        )
        return l

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
            self, "Confirm Migration",
            "Import all anime from your old anime_info.json?\n"
            "Existing entries will NOT be duplicated.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return

        self.mig_bar.setVisible(True)
        self.import_btn.setEnabled(False)

        w = ImportWorker(self._json_path, self.db)
        w.signals.result.connect(self._on_import_done)
        w.signals.error.connect(self._on_import_error)
        w.signals.finished.connect(lambda: self.mig_bar.setVisible(False))
        run_worker(w)

    def _on_import_done(self, count: int):
        self.import_btn.setEnabled(True)
        from ui.toast import Toast
        Toast.show(self.window(), f"Imported {count} anime.", kind="success")

    def _on_import_error(self, error: str):
        self.import_btn.setEnabled(True)
        QMessageBox.critical(self, "Migration Failed", f"Error:\n{error}")

    def _backup(self):
        try:
            dest = self.db.backup()
            from ui.toast import Toast
            Toast.show(self.window(), f"Backup created: {dest.name}", kind="success")
        except Exception as e:
            QMessageBox.critical(self, "Backup Failed", str(e))

    def _clear_cache(self):
        if QMessageBox.question(
            self, "Clear Cache",
            "Delete all cached cover images?\nThey will re-download when needed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            purge_cache(max_size_mb=0)
            self.cache_lbl.setText("Cache size: 0.0 MB")
            from ui.toast import Toast
            Toast.show(self.window(), "Image cache cleared.", kind="success")
