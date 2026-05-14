"""
AnimeTracker — Toast notification widget.

Lightweight, auto-dismissing overlay message — replaces QMessageBox
for non-interactive feedback (success, info, warning, error).

Usage:
    from ui.toast import Toast
    Toast.show(parent_widget, "Anime added!", kind="success")
    Toast.show(parent_widget, "Network error", kind="error")
"""
from PyQt6.QtWidgets import QLabel, QWidget, QHBoxLayout, QApplication
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QColor


_KIND_STYLES = {
    "success": ("✓", "#34d399", "#0e2a1f", "#1a5c3a"),
    "error":   ("✕", "#f87171", "#2a0a0a", "#7f1d1d"),
    "warning": ("⚠", "#fbbf24", "#2a1a00", "#92400e"),
    "info":    ("ℹ", "#7c6af7", "#151929", "#2a2550"),
}
_DEFAULT_DURATION = 3500   # ms — industry standard for toasts


class Toast(QWidget):
    """Self-positioning, auto-dismissing toast notification."""

    def __init__(self, parent: QWidget, message: str, kind: str = "info",
                 duration: int = _DEFAULT_DURATION):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        icon, fg, bg, border = _KIND_STYLES.get(kind, _KIND_STYLES["info"])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 18, 10)
        layout.setSpacing(8)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(
            f"font-size:16px;color:{fg};background:transparent;font-weight:700;"
        )
        layout.addWidget(icon_lbl)

        msg_lbl = QLabel(message)
        msg_lbl.setStyleSheet(
            f"font-size:12px;color:{fg};background:transparent;font-weight:500;"
        )
        msg_lbl.setWordWrap(False)
        layout.addWidget(msg_lbl)

        self.setStyleSheet(
            f"QWidget{{background:{bg};"
            f"border-radius:10px;}}"
        )
        self.adjustSize()
        self._reposition()

        # Fade in
        self._opacity = 0.0
        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(180)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        QWidget.show(self)
        self._anim.start()

        # Auto-dismiss
        QTimer.singleShot(duration, self._dismiss)

    def _reposition(self):
        if self.parent():
            pw = self.parent()
            pr = pw.rect()
            x = pr.right() - self.width() - 20
            y = pr.bottom() - self.height() - 20
            self.move(pw.mapToGlobal(self.rect().topLeft()))
            # Position bottom-right of parent
            gpos = pw.mapToGlobal(
                pw.rect().bottomRight()
            )
            self.move(gpos.x() - self.width() - 20,
                      gpos.y() - self.height() - 20)

    def _dismiss(self):
        self._anim2 = QPropertyAnimation(self, b"windowOpacity")
        self._anim2.setDuration(300)
        self._anim2.setStartValue(1.0)
        self._anim2.setEndValue(0.0)
        self._anim2.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim2.finished.connect(self.deleteLater)
        self._anim2.start()

    @staticmethod
    def popup(parent: QWidget, message: str, kind: str = "info",
              duration: int = _DEFAULT_DURATION) -> "Toast":
        """
        Convenience factory. Returns the toast instance.

        Args:
            parent: Parent widget — toast positions relative to it.
            message: Text to display.
            kind: 'success' | 'error' | 'warning' | 'info'
            duration: Visible duration in milliseconds.
        """
        t = Toast(parent, message, kind, duration)
        return t

    @staticmethod
    def show(parent: QWidget, message: str, kind: str = "info",
             duration: int = _DEFAULT_DURATION) -> "Toast":
        """Backward-compatible alias for existing Toast.show(...) call sites."""
        return Toast.popup(parent, message, kind, duration)
