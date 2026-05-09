"""
AnimeTracker — Offline Banner
Shown at top of content area when internet connection is lost.
Hides automatically when connection is restored.
"""
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor


class OfflineBanner(QWidget):
    """
    A slim amber banner informing the user they are offline.
    The app continues to work with cached data — this just informs.
    """
    retry_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setStyleSheet(
            "background:#451a03;"
            "border-bottom:1px solid #92400e;"
        )
        self.setVisible(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 16, 0)
        lay.setSpacing(10)

        icon = QLabel("⚠")
        icon.setStyleSheet("font-size:14px;color:#fbbf24;background:transparent;")
        lay.addWidget(icon)

        msg = QLabel(
            "No internet connection  —  "
            "Your library is available. "
            "Cover art and airing data require a connection."
        )
        msg.setStyleSheet("font-size:12px;color:#fde68a;background:transparent;")
        lay.addWidget(msg)
        lay.addStretch()

        retry = QPushButton("Retry")
        retry.setStyleSheet(
            "QPushButton{background:#92400e;color:#fde68a;"
            "border:none;border-radius:5px;padding:4px 12px;font-size:11px;}"
            "QPushButton:hover{background:#b45309;}"
        )
        retry.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        retry.clicked.connect(self.retry_clicked)
        lay.addWidget(retry)