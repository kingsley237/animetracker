"""
AnimeTracker — Update Toast Notification
Industry standard pattern: floating toast anchored top-right,
does NOT affect layout at all. Appears over the content like a
notification — same as VS Code, Obsidian, Slack update notifications.
"""
import webbrowser
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal, QPoint
from PyQt6.QtGui import QCursor


class UpdateBanner(QWidget):
    """
    Floating toast notification — top-right corner of the window.
    Does NOT push any layout. Rendered above everything as an overlay.
    Shown for 12 seconds then fades, or dismissed by user.
    """
    dismissed = pyqtSignal()

    TOAST_W = 340
    TOAST_H = 88
    MARGIN   = 16   # distance from right/top edge

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.TOAST_W, self.TOAST_H)
        self.setVisible(False)

        # Float above other widgets
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.Widget)

        self.setStyleSheet("""
            QWidget#toastCard {
                background: #1e1847;
                border: 1.5px solid #4b3fa8;
                border-radius: 12px;
            }
        """)

        # Card container
        card = QWidget(self)
        card.setObjectName("toastCard")
        card.setGeometry(0, 0, self.TOAST_W, self.TOAST_H)

        outer = QVBoxLayout(card)
        outer.setContentsMargins(14, 10, 10, 10)
        outer.setSpacing(6)

        # Top row: icon + message + dismiss
        top = QHBoxLayout()
        top.setSpacing(8)
        top.setContentsMargins(0, 0, 0, 0)

        icon = QLabel("✦")
        icon.setStyleSheet(
            "font-size:14px;color:#7c6af7;background:transparent;border:none;"
        )
        top.addWidget(icon)

        self._msg = QLabel()
        self._msg.setStyleSheet(
            "font-size:12px;font-weight:600;color:#e2e4ec;"
            "background:transparent;border:none;"
        )
        self._msg.setWordWrap(False)
        top.addWidget(self._msg, stretch=1)

        x_btn = QPushButton("✕")
        x_btn.setFixedSize(22, 22)
        x_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#4a5070;"
            "border:none;font-size:12px;padding:0;}"
            "QPushButton:hover{color:#9da5c0;}"
        )
        x_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x_btn.setToolTip("Dismiss")
        x_btn.clicked.connect(self._dismiss)
        top.addWidget(x_btn)
        outer.addLayout(top)

        # Bottom row: release note snippet + download button
        bot = QHBoxLayout()
        bot.setSpacing(8)
        bot.setContentsMargins(22, 0, 0, 0)

        self._notes = QLabel()
        self._notes.setStyleSheet(
            "font-size:10px;color:#6b7280;background:transparent;border:none;"
        )
        self._notes.setWordWrap(False)
        bot.addWidget(self._notes, stretch=1)

        self._dl_btn = QPushButton("Download")
        self._dl_btn.setFixedHeight(26)
        self._dl_btn.setStyleSheet(
            "QPushButton{background:#4b3fa8;color:#fff;border:none;"
            "border-radius:6px;padding:0 14px;"
            "font-size:11px;font-weight:600;}"
            "QPushButton:hover{background:#5a4fc4;}"
        )
        self._dl_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._dl_btn.clicked.connect(self._download)
        bot.addWidget(self._dl_btn)
        outer.addLayout(bot)

        self._download_url = ""

        # Auto-dismiss after 15 seconds
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._dismiss)

    # ── Public API ────────────────────────────────────────────────────────────

    def show_update(self, version: str, notes: str, download_url: str):
        self._download_url = download_url
        self._msg.setText(f"Update available — v{version.lstrip('v')}")
        first = (notes.strip().split("\n")[0])[:55] if notes.strip() else ""
        self._notes.setText(first + ("…" if first else ""))
        self._reposition()
        self.setVisible(True)
        self.raise_()
        self._auto_timer.start(15_000)

    def _reposition(self):
        """Place top-right of the parent window, below the title bar."""
        parent = self.parent()
        if not parent:
            return
        x = parent.width()  - self.TOAST_W - self.MARGIN
        y = self.MARGIN + 8
        self.move(x, y)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _download(self):
        if self._download_url:
            webbrowser.open(self._download_url)

    def _dismiss(self):
        self._auto_timer.stop()
        self.setVisible(False)
        self.dismissed.emit()

    # ── Reposition on parent resize ───────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible():
            self._reposition()