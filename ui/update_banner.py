"""
AnimeTracker — Update Banner Widget
A non-intrusive banner that slides in at the top of the main window
when a newer version is available on GitHub.
"""
import webbrowser
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor


class UpdateBanner(QWidget):
    """
    Slim banner shown at the top of the content area when an update is available.
    Contains: icon · version info · release notes summary · Download btn · Dismiss btn.
    Hidden by default. Call show_update() to activate it.
    """

    dismissed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self.setFixedHeight(48)
        self.setStyleSheet(
            "background:#1e1847;"
            "border-bottom:1px solid #4b3fa8;"
        )
        self._build_ui()

    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 12, 0)
        lay.setSpacing(12)

        # Icon
        icon = QLabel("✦")
        icon.setStyleSheet("font-size:16px;color:#7c6af7;background:transparent;")
        lay.addWidget(icon)

        # Message
        self._msg = QLabel()
        self._msg.setStyleSheet(
            "font-size:13px;color:#c7cbd9;background:transparent;"
        )
        self._msg.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay.addWidget(self._msg)

        # Release notes (brief)
        self._notes = QLabel()
        self._notes.setStyleSheet(
            "font-size:11px;color:#6b7280;background:transparent;"
        )
        self._notes.setMaximumWidth(300)
        lay.addWidget(self._notes)

        # Download button
        self._dl_btn = QPushButton("Download Update")
        self._dl_btn.setStyleSheet(
            "QPushButton{"
            "background:#4b3fa8;color:#ffffff;border:none;"
            "border-radius:6px;padding:6px 16px;"
            "font-size:12px;font-weight:600;"
            "}"
            "QPushButton:hover{background:#5a4fc4;}"
        )
        self._dl_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._dl_btn.clicked.connect(self._download)
        lay.addWidget(self._dl_btn)

        # Dismiss button
        dismiss = QPushButton("✕")
        dismiss.setStyleSheet(
            "QPushButton{background:transparent;color:#4a5070;"
            "border:none;font-size:14px;padding:4px 8px;}"
            "QPushButton:hover{color:#9da5c0;}"
        )
        dismiss.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        dismiss.setToolTip("Dismiss — remind me next launch")
        dismiss.clicked.connect(self._dismiss)
        lay.addWidget(dismiss)

        self._download_url = ""

    def show_update(self, version: str, notes: str, download_url: str):
        """Call this when a newer version is found."""
        self._download_url = download_url
        self._msg.setText(
            f"  AnimeTracker  <b>{version}</b>  is available  —  you have v2.0.0"
        )
        # Show first line of release notes only
        first_line = (notes.strip().split("\n")[0])[:80] if notes.strip() else ""
        if first_line:
            self._notes.setText(f'"{first_line}…"')
        else:
            self._notes.setText("")
        self.setVisible(True)

    def _download(self):
        if self._download_url:
            webbrowser.open(self._download_url)

    def _dismiss(self):
        self.setVisible(False)
        self.dismissed.emit()