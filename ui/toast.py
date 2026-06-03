"""
Miroku — Toast Notification System

Toasts stack vertically bottom-right, newest at bottom.
Max 3 visible — oldest auto-dismissed when limit exceeded.
"""
from __future__ import annotations
from typing import ClassVar
from PyQt6.QtWidgets import QLabel, QWidget, QHBoxLayout
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint

_KIND_STYLES: dict[str, tuple[str, str, str, str]] = {
    "success": ("✓", "#34d399", "#0a1f15", "#1a5c3a"),
    "error":   ("✕", "#f87171", "#1f0a0a", "#7f1d1d"),
    "warning": ("⚠", "#fbbf24", "#1f1500", "#92400e"),
    "info":    ("ℹ", "#a594f9", "#11102a", "#2a2550"),
}
_DEFAULT_DURATION_MS: int = 3500
_MARGIN:              int = 20
_SPACING:             int = 8
_MAX_TOASTS:          int = 3


class _ToastManager:
    """
    Process-global singleton — owns all live toasts, manages stacking.
    Toasts stack upward from bottom-right of the parent window.
    """
    _instance: ClassVar[_ToastManager | None] = None
    _toasts:   ClassVar[list[Toast]]          = []

    @classmethod
    def get(cls) -> _ToastManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def add(self, toast: Toast) -> None:
        if len(self._toasts) >= _MAX_TOASTS:
            self._toasts[0]._dismiss_immediate()
        self._toasts.append(toast)
        self._reposition_all()

    def remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._reposition_all()

    def _reposition_all(self) -> None:
        for i, t in enumerate(self._toasts):
            p = t.parent()
            if p is None:
                continue
            global_br = p.mapToGlobal(QPoint(p.width(), p.height()))
            # Each toast stacks upward; i=0 oldest (top), last = newest (bottom)
            above_height = sum(
                self._toasts[j].height() + _SPACING
                for j in range(i + 1, len(self._toasts))
            )
            t.move(
                global_br.x() - _MARGIN - t.width(),
                global_br.y() - _MARGIN - t.height() - above_height,
            )


class Toast(QWidget):
    """Auto-dismissing toast, managed by _ToastManager for stacking."""

    def __init__(self, parent: QWidget, message: str,
                 kind: str = "info", duration: int = _DEFAULT_DURATION_MS):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        icon_ch, fg, bg, border = _KIND_STYLES.get(kind, _KIND_STYLES["info"])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 18, 10)
        layout.setSpacing(8)

        icon_lbl = QLabel(icon_ch)
        icon_lbl.setStyleSheet(
            f"font-size:14px;color:{fg};background:transparent;font-weight:700;"
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

        _ToastManager.get().add(self)

        self.setWindowOpacity(0.0)
        QWidget.show(self)   # explicit — avoids resolving to Toast.show() static method
        self._in_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._in_anim.setDuration(180)
        self._in_anim.setStartValue(0.0)
        self._in_anim.setEndValue(1.0)
        self._in_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._in_anim.start()

        QTimer.singleShot(duration, self._dismiss)

    def _dismiss(self) -> None:
        self._out_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._out_anim.setDuration(300)
        self._out_anim.setStartValue(1.0)
        self._out_anim.setEndValue(0.0)
        self._out_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._out_anim.finished.connect(self._on_dismissed)
        self._out_anim.start()

    def _dismiss_immediate(self) -> None:
        _ToastManager.get().remove(self)
        self.close()

    def _on_dismissed(self) -> None:
        _ToastManager.get().remove(self)
        self.close()

    @staticmethod
    def show(parent: QWidget, message: str,
             kind: str = "info",
             duration: int = _DEFAULT_DURATION_MS) -> "Toast":
        return Toast(parent, message, kind, duration)

    @staticmethod
    def popup(parent: QWidget, message: str,
              kind: str = "info",
              duration: int = _DEFAULT_DURATION_MS) -> "Toast":
        return Toast(parent, message, kind, duration)