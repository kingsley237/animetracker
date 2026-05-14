"""
Miroku — Offline Banner
Shown as a floating card (not a flat bar) when internet is unavailable.
Auto-hides on reconnect. Repositions on window resize.
"""
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer
from PyQt6.QtGui import QCursor


class OfflineBanner(QWidget):
    """
    Floating offline indicator — bottom-left corner of the parent window.
    Much more visible than the old amber bar.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._visible = False
        self._build()
        self.hide()

    def _build(self):
        self.setFixedWidth(320)

        outer = QWidget(self)
        outer.setStyleSheet(
            "QWidget{"
            "background:#1a0d00;"
            "border-radius:12px;"
            "}"
        )
        main_lay = QVBoxLayout(outer)
        main_lay.setContentsMargins(16, 12, 16, 12)
        main_lay.setSpacing(6)

        # Top row — icon + title
        top = QHBoxLayout()
        top.setSpacing(10)

        dot = QLabel("●")
        dot.setFixedWidth(14)
        dot.setStyleSheet(
            "font-size:10px;color:#f97316;background:transparent;"
            "font-weight:700;"
        )
        # Pulse animation via timer
        self._dot_state = True
        self._dot_lbl = dot
        self._pulse = QTimer()
        self._pulse.timeout.connect(self._pulse_dot)
        self._pulse.start(900)
        top.addWidget(dot)

        title = QLabel("No Internet Connection")
        title.setStyleSheet(
            "font-size:13px;font-weight:700;color:#fb923c;"
            "background:transparent;"
        )
        top.addWidget(title)
        top.addStretch()
        main_lay.addLayout(top)

        # Subtitle
        sub = QLabel(
            "Miroku is offline. Your library is still available.\n"
            "Live data will resume when you reconnect."
        )
        sub.setStyleSheet(
            "font-size:11px;color:#9a6820;background:transparent;"
            "line-height:1.5;"
        )
        sub.setWordWrap(True)
        main_lay.addWidget(sub)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(outer)
        outer.adjustSize()
        self.adjustSize()

    def _pulse_dot(self):
        self._dot_state = not self._dot_state
        self._dot_lbl.setStyleSheet(
            f"font-size:10px;color:{'#f97316' if self._dot_state else '#7c3a0a'};"
            "background:transparent;font-weight:700;"
        )

    def show_offline(self):
        if self._visible:
            return
        self._visible = True
        self._reposition()
        self.show()
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(300)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start()
        self._show_anim = anim   # keep reference

    def hide_offline(self):
        if not self._visible:
            return
        self._visible = False
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(300)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(self.hide)
        anim.start()
        self._hide_anim = anim

    def reposition(self):
        self._reposition()

    def _reposition(self):
        if not self.parent():
            return
        pw = self.parent()
        pg = pw.mapToGlobal(pw.rect().bottomLeft())
        self.move(pg.x() + 20, pg.y() - self.height() - 20)