"""
Miroku — AniList API Status Banner

Floating warning shown when AniList's own API is down (distinct from
OfflineBanner, which covers the user's internet). Tells the user this
is AniList's problem, not theirs, shows when it was last checked, and
gives a manual "Check now" retry that re-runs the exact same POST
request that detected the outage in the first place.

There is deliberately no "check elsewhere" link. Every option tried
either doesn't check the actual thing that's down (graphql.anilist.co
specifically requires a POST with a real query — a plain browser visit
gets a generic 404, and general "is anilist.co up" checkers are
checking the website, a different service, so they can and do say
"up" while the API stays disabled) or requires an account just to look
(their Discord) or is fake (a community "status page" with zero
configured monitors that always reads "operational" no matter what).
Showing any of those next to our own accurate, live result just
produces a conflicting signal that looks like OUR check is wrong.
Our own check here already IS the correct, specific, live answer —
"Check now" re-runs it, nothing else is more authoritative.
"""
from datetime import datetime

from PyQt6.QtCore import Qt, QPropertyAnimation
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton


class ApiStatusBanner(QWidget):
    """Floating AniList-down indicator — bottom-left corner, stacked
    above OfflineBanner when both are visible."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._visible = False
        self._on_retry = None
        self._build()
        self.hide()

    def _build(self):
        self.setFixedWidth(340)

        outer = QWidget(self)
        self._outer = outer
        outer.setStyleSheet(
            "QWidget{background:#1a1206;border-radius:12px;}"
        )
        main_lay = QVBoxLayout(outer)
        main_lay.setContentsMargins(16, 12, 16, 12)
        main_lay.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)

        dot = QLabel("●")
        dot.setFixedWidth(14)
        dot.setStyleSheet("font-size:10px;color:#fbbf24;background:transparent;font-weight:700;")
        top.addWidget(dot)

        title = QLabel("AniList API is down")
        title.setStyleSheet("font-size:13px;font-weight:700;color:#fbbf24;background:transparent;")
        top.addWidget(title)
        top.addStretch()
        main_lay.addLayout(top)

        self._msg_lbl = QLabel()
        self._msg_lbl.setWordWrap(True)
        self._msg_lbl.setStyleSheet("font-size:11px;color:#c7ad6b;background:transparent;line-height:1.5;")
        main_lay.addWidget(self._msg_lbl)

        self._checked_lbl = QLabel()
        self._checked_lbl.setStyleSheet("font-size:10px;color:#7a6a3f;background:transparent;")
        main_lay.addWidget(self._checked_lbl)

        actions = QHBoxLayout()
        actions.setSpacing(10)

        self._retry_btn = QPushButton("Check now")
        self._retry_btn.setObjectName("secondaryBtn")
        self._retry_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._retry_btn.setStyleSheet(
            self._retry_btn.styleSheet() + "font-size:11px;padding:4px 10px;"
        )
        self._retry_btn.setToolTip(
            "Re-runs the exact request that detected this outage — the\n"
            "most accurate check available for graphql.anilist.co specifically."
        )
        self._retry_btn.clicked.connect(self._retry_clicked)
        actions.addWidget(self._retry_btn)
        actions.addStretch()
        main_lay.addLayout(actions)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(outer)
        outer.adjustSize()
        self.adjustSize()

    def set_on_retry(self, callback):
        self._on_retry = callback

    def _retry_clicked(self):
        self.show_checking()
        if self._on_retry:
            self._on_retry()

    def show_checking(self):
        """Called the moment 'Check now' is clicked — before the network
        round trip returns — so the click has visible, immediate feedback
        instead of the button just sitting there looking unresponsive."""
        self._retry_btn.setEnabled(False)
        self._retry_btn.setText("Checking…")
        self._checked_lbl.setText("Checking AniList now…")
        self._resize_to_content()

    def update_message(self, message: str):
        self._retry_btn.setEnabled(True)
        self._retry_btn.setText("Check now")
        self._msg_lbl.setText(
            message or "AniList's API isn't responding right now. "
                        "Discover and library updates are paused until it's back."
        )
        self._checked_lbl.setText(f"Last checked {datetime.now().strftime('%H:%M:%S')}")
        # The word-wrapped message can be a different number of lines every
        # time (a fresh error message, or just a longer sentence), so the
        # window has to be re-measured each time rather than only once at
        # construction — otherwise it keeps whatever height it had when the
        # label was still empty and the real text gets clipped.
        self._resize_to_content()

    def _resize_to_content(self):
        self._outer.layout().activate()
        self._outer.adjustSize()
        self.layout().activate()
        self.adjustSize()
        if self._visible:
            self._reposition()

    def show_down(self, message: str = ""):
        self.update_message(message)
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
        self._show_anim = anim

    def hide_down(self):
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
        y_offset = self.height() + 20
        # Stack above the offline banner if it's also visible.
        sibling = getattr(pw.window(), "_offline_banner", None)
        if sibling is not None and sibling.isVisible():
            y_offset += sibling.height() + 12
        self.move(pg.x() + 20, pg.y() - y_offset)
