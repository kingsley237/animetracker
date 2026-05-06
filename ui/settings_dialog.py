"""
AnimeTracker — Settings Dialog
Preferences, JSON migration, backup/restore, cache management.
"""
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QFrame, QFileDialog, QMessageBox, QTabWidget,
    QCheckBox, QSpinBox, QFormLayout, QLineEdit, QProgressBar,
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QCursor

from core.database import DatabaseManager, BACKUP_DIR
from core.image_cache import cache_size_mb, purge_cache
from workers.workers import ImportWorker, Worker, run_worker


class SettingsDialog(QDialog):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self.settings = QSettings("AnimeTracker", "AnimeTracker")

        self.setWindowTitle("Settings")
        self.setMinimumSize(520, 480)
        self.setStyleSheet("background-color: #0f1118;")

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Title
        header = QWidget()
        header.setStyleSheet("background: #0a0c10; border-bottom: 1px solid #1a1d28;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(24, 16, 24, 16)

        t = QLabel("Settings")
        t.setObjectName("dialogTitle")
        hl.addWidget(t)
        hl.addStretch()

        close = QPushButton("✕")
        close.setObjectName("iconBtn")
        close.setFixedSize(28, 28)
        close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close.clicked.connect(self.accept)
        hl.addWidget(close)
        layout.addWidget(header)

        # Tabs
        tabs = QTabWidget()
        tabs.setStyleSheet("QTabWidget::pane { padding: 20px; background: transparent; }")

        tabs.addTab(self._build_general_tab(), "General")
        tabs.addTab(self._build_data_tab(), "Data & Migration")
        tabs.addTab(self._build_about_tab(), "About")

        layout.addWidget(tabs)

    # ─── General ──────────────────────────────────────────────────────────────

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(20)

        section = QLabel("DISPLAY")
        section.setStyleSheet(
            "font-size: 10px; color: #3b4260; font-weight: 700; letter-spacing: 1.5px;"
        )
        layout.addWidget(section)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        auto_refresh = QCheckBox("Auto-refresh airing data every 10 minutes")
        auto_refresh.setChecked(
            self.settings.value("auto_refresh", True, type=bool)
        )
        auto_refresh.stateChanged.connect(
            lambda v: self.settings.setValue("auto_refresh", bool(v))
        )
        form.addRow("", auto_refresh)

        show_banners = QCheckBox("Show banner images in detail panel")
        show_banners.setChecked(
            self.settings.value("show_banners", True, type=bool)
        )
        show_banners.stateChanged.connect(
            lambda v: self.settings.setValue("show_banners", bool(v))
        )
        form.addRow("", show_banners)

        layout.addLayout(form)

        section2 = QLabel("IMAGE CACHE")
        section2.setStyleSheet(
            "font-size: 10px; color: #3b4260; font-weight: 700; letter-spacing: 1.5px;"
        )
        layout.addWidget(section2)

        cache_info_row = QHBoxLayout()
        self.cache_size_lbl = QLabel(f"Current cache size: {cache_size_mb()} MB")
        self.cache_size_lbl.setStyleSheet("font-size: 13px; color: #9da5c0;")
        cache_info_row.addWidget(self.cache_size_lbl)
        cache_info_row.addStretch()

        clear_cache_btn = QPushButton("Clear Cache")
        clear_cache_btn.setObjectName("dangerBtn")
        clear_cache_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        clear_cache_btn.clicked.connect(self._clear_cache)
        cache_info_row.addWidget(clear_cache_btn)
        layout.addLayout(cache_info_row)

        layout.addStretch()
        return w

    # ─── Data & Migration ─────────────────────────────────────────────────────

    def _build_data_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(20)

        # Migration section
        mig_section = QLabel("MIGRATE FROM OLD VERSION")
        mig_section.setStyleSheet(
            "font-size: 10px; color: #3b4260; font-weight: 700; letter-spacing: 1.5px;"
        )
        layout.addWidget(mig_section)

        mig_desc = QLabel(
            "If you have an existing anime_info.json from the old terminal version,\n"
            "import it here. All your anime, episodes, ratings, and dropped list\n"
            "will be migrated automatically."
        )
        mig_desc.setStyleSheet("font-size: 13px; color: #6b7280; line-height: 1.6;")
        mig_desc.setWordWrap(True)
        layout.addWidget(mig_desc)

        self.migration_bar = QProgressBar()
        self.migration_bar.setFixedHeight(2)
        self.migration_bar.setRange(0, 0)
        self.migration_bar.setVisible(False)
        self.migration_bar.setStyleSheet(
            "QProgressBar { background: #1a1d28; border: none; }"
            "QProgressBar::chunk { background: #34d399; }"
        )
        layout.addWidget(self.migration_bar)

        mig_row = QHBoxLayout()
        self.mig_path_lbl = QLabel("No file selected")
        self.mig_path_lbl.setStyleSheet("font-size: 12px; color: #4a5070;")
        mig_row.addWidget(self.mig_path_lbl)
        mig_row.addStretch()

        browse_btn = QPushButton("Browse…")
        browse_btn.setObjectName("secondaryBtn")
        browse_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        browse_btn.clicked.connect(self._browse_json)
        mig_row.addWidget(browse_btn)

        self.import_btn = QPushButton("Import Now")
        self.import_btn.setObjectName("primaryBtn")
        self.import_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._run_migration)
        mig_row.addWidget(self.import_btn)
        layout.addLayout(mig_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #1a1d28;")
        layout.addWidget(sep)

        # Backup section
        backup_section = QLabel("BACKUP & RESTORE")
        backup_section.setStyleSheet(
            "font-size: 10px; color: #3b4260; font-weight: 700; letter-spacing: 1.5px;"
        )
        layout.addWidget(backup_section)

        backup_desc = QLabel(
            f"Database backups are saved automatically (last 5 kept).\n"
            f"Backup folder: {BACKUP_DIR}"
        )
        backup_desc.setStyleSheet("font-size: 12px; color: #6b7280;")
        backup_desc.setWordWrap(True)
        layout.addWidget(backup_desc)

        backup_row = QHBoxLayout()
        backup_now_btn = QPushButton("Backup Now")
        backup_now_btn.setObjectName("secondaryBtn")
        backup_now_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        backup_now_btn.clicked.connect(self._backup_now)
        backup_row.addWidget(backup_now_btn)
        backup_row.addStretch()
        layout.addLayout(backup_row)

        layout.addStretch()
        return w

    # ─── About ────────────────────────────────────────────────────────────────

    def _build_about_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(10)

        logo = QLabel("ANIMETRACKER")
        logo.setStyleSheet(
            "font-size: 22px; font-weight: 700; color: #7c6af7; letter-spacing: 2px;"
        )
        layout.addWidget(logo)

        ver = QLabel("Version 2.0.0")
        ver.setStyleSheet("font-size: 13px; color: #4a5070;")
        layout.addWidget(ver)

        layout.addSpacing(16)

        for text in [
            "Data powered by AniList GraphQL API",
            "Built with Python 3.11+ and PyQt6",
            "Cover art © respective copyright holders",
            "Database stored at: ~/.animetracker/anime.db",
        ]:
            lbl = QLabel(text)
            lbl.setStyleSheet("font-size: 12px; color: #6b7280;")
            layout.addWidget(lbl)

        layout.addStretch()
        return w

    # ─── Actions ──────────────────────────────────────────────────────────────

    def _browse_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select anime_info.json", str(Path.home()),
            "JSON Files (*.json)"
        )
        if path:
            self._json_path = path
            short = Path(path).name
            self.mig_path_lbl.setText(short)
            self.import_btn.setEnabled(True)

    def _run_migration(self):
        if not hasattr(self, "_json_path"):
            return
        reply = QMessageBox.question(
            self, "Confirm Migration",
            "This will import all anime from your old anime_info.json into the new database.\n"
            "Existing entries will be skipped (no duplicates). Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.migration_bar.setVisible(True)
        self.import_btn.setEnabled(False)

        worker = ImportWorker(self._json_path, self.db)
        worker.signals.result.connect(self._on_migration_done)
        worker.signals.error.connect(self._on_migration_error)
        worker.signals.finished.connect(lambda: self.migration_bar.setVisible(False))
        run_worker(worker)

    def _on_migration_done(self, count: int):
        self.import_btn.setEnabled(True)
        QMessageBox.information(
            self, "Migration Complete",
            f"Successfully imported {count} anime from your old library.\n\n"
            "Go back to the Library tab to see your anime.\n"
            "Tip: Run 'Refresh' to fetch cover art and latest airing info."
        )

    def _on_migration_error(self, error: str):
        self.import_btn.setEnabled(True)
        QMessageBox.critical(self, "Migration Failed", f"Error: {error}")

    def _backup_now(self):
        try:
            dest = self.db.backup()
            QMessageBox.information(
                self, "Backup Created",
                f"Database backed up to:\n{dest}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Backup Failed", str(e))

    def _clear_cache(self):
        reply = QMessageBox.question(
            self, "Clear Image Cache",
            "This will delete all cached cover images.\n"
            "They will be re-downloaded when needed. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            purge_cache(max_size_mb=0)
            self.cache_size_lbl.setText("Current cache size: 0.0 MB")