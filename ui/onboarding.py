"""
Miroku — Onboarding Tutorial
Spotlight coach-mark overlay for new users.
Industry standard: semi-transparent full-screen overlay with a highlighted
'spotlight' cutout around the target widget, plus a tooltip card explaining it.

Toggle for testing:
    In core/database.py → DatabaseManager.__init__:
        FORCE_ONBOARDING = True   # always show tutorial (for testing)
        FORCE_ONBOARDING = False  # normal behaviour (remove line when done)
"""
from typing import List, Tuple, Optional, Callable

from PyQt6.QtWidgets import (
    QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout,
    QApplication, QSizePolicy,
)
from PyQt6.QtCore import (
    Qt, QRect, QPoint, QPropertyAnimation, QEasingCurve,
    QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QBrush, QPen, QFont,
)


# ── Each step is: (target_widget_name, title, description) ───────────────────
# target_widget_name is the attribute name on MainWindow

TOUR_STEPS: List[Tuple[str, str, str]] = [
    (
        "sidebar",
        "Navigation",
        "Use the sidebar to switch between your Library, Watching list, "
        "Hall of Fame, Discover, and Statistics.",
    ),
    (
        "search_bar",
        "Search your library",
        "Type here to instantly search across all anime in your library "
        "by title or genre.",
    ),
    (
        "sort_combo",
        "Sort your library",
        "Sort by Release Date (default), Title, AniList Score, "
        "Date Added, or Your Rating.",
    ),
    (
        "filter_row",
        "Filter by status",
        "Quick-filter your library: All, Watching, Completed, Planned, "
        "or 'Behind' — anime with episodes you haven't watched yet.",
    ),
    (
        "stats_strip",
        "At a glance",
        "These four cards always show live counts of your Watching, "
        "Completed, Planned, and Dropped anime.",
    ),
    (
        "refresh_btn",
        "Refresh airing data",
        "Click this to pull the latest episode air times from AniList. "
        "It also runs automatically every 10 minutes.",
    ),
]


class OnboardingOverlay(QWidget):
    """
    Full-screen semi-transparent overlay that:
    1. Dims everything except the target widget (spotlight effect)
    2. Shows a floating card with step number, title, and description
    3. Has Next / Skip buttons
    """
    finished = pyqtSignal()

    def __init__(self, main_window, parent: QWidget):
        super().__init__(parent)
        self._mw         = main_window
        self._steps      = TOUR_STEPS
        self._current    = 0
        self._spotlight  = QRect()

        # Cover the entire window
        self.setGeometry(parent.rect())
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)

        # Build the card widget
        self._card = _TourCard(self)
        self._card.next_clicked.connect(self._next)
        self._card.skip_clicked.connect(self._finish)

        self._show_step(0)
        self.show()
        self.raise_()

    # ── Steps ──────────────────────────────────────────────────────────────────

    def _show_step(self, idx: int):
        if idx >= len(self._steps):
            self._finish()
            return

        attr, title, desc = self._steps[idx]
        self._current = idx

        # Find the target widget
        target: Optional[QWidget] = getattr(self._mw, attr, None)
        if target and target.isVisible():
            # Map target rect to overlay coordinates
            global_rect = QRect(
                target.mapToGlobal(QPoint(0, 0)),
                target.size(),
            )
            self._spotlight = QRect(
                self.mapFromGlobal(global_rect.topLeft()),
                global_rect.size(),
            ).adjusted(-8, -8, 8, 8)
        else:
            self._spotlight = QRect()

        self._card.set_content(
            step=idx + 1,
            total=len(self._steps),
            title=title,
            description=desc,
            is_last=(idx == len(self._steps) - 1),
        )
        self._position_card()
        self.update()

    def _position_card(self):
        """Position the card below or above the spotlight."""
        cw, ch = 320, self._card.sizeHint().height() + 20
        self._card.setFixedWidth(cw)

        if self._spotlight.isNull():
            # Center card
            cx = (self.width()  - cw) // 2
            cy = (self.height() - ch) // 2
        else:
            cx = self._spotlight.left()
            cy = self._spotlight.bottom() + 14
            # Flip above if too low
            if cy + ch > self.height() - 20:
                cy = self._spotlight.top() - ch - 14
            # Keep within bounds
            cx = max(12, min(cx, self.width() - cw - 12))
            cy = max(12, cy)

        self._card.move(cx, cy)
        self._card.adjustSize()
        self._card.show()

    def _next(self):
        self._show_step(self._current + 1)

    def _finish(self):
        self.hide()
        self.finished.emit()
        self.deleteLater()

    # ── Paint ──────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Full dim
        full = QPainterPath()
        full.addRect(0, 0, self.width(), self.height())

        if not self._spotlight.isNull():
            # Cut out spotlight
            cutout = QPainterPath()
            cutout.addRoundedRect(
                float(self._spotlight.x()), float(self._spotlight.y()),
                float(self._spotlight.width()), float(self._spotlight.height()),
                10, 10,
            )
            dim_path = full.subtracted(cutout)
        else:
            dim_path = full

        painter.fillPath(dim_path, QColor(0, 0, 0, 175))

        if not self._spotlight.isNull():
            # Spotlight border ring
            painter.setPen(QPen(QColor("#7c6af7"), 2.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self._spotlight, 10, 10)

        painter.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_card()


# ── Tour card widget ──────────────────────────────────────────────────────────

class _TourCard(QWidget):
    next_clicked = pyqtSignal()
    skip_clicked = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet("""
            QWidget {
                background: #1a1730;
                border: 1.5px solid #4b3fa8;
                border-radius: 12px;
            }
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)

        # Step counter
        self._counter = QLabel()
        self._counter.setStyleSheet(
            "font-size:10px;font-weight:700;color:#4a5070;"
            "letter-spacing:1.5px;background:transparent;border:none;"
        )
        lay.addWidget(self._counter)

        # Title
        self._title = QLabel()
        self._title.setStyleSheet(
            "font-size:15px;font-weight:700;color:#f0f1f5;"
            "background:transparent;border:none;"
        )
        self._title.setWordWrap(True)
        lay.addWidget(self._title)

        # Description
        self._desc = QLabel()
        self._desc.setStyleSheet(
            "font-size:12px;color:#9da5c0;line-height:1.6;"
            "background:transparent;border:none;"
        )
        self._desc.setWordWrap(True)
        lay.addWidget(self._desc)

        lay.addSpacing(4)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._skip = QPushButton("Skip tour")
        self._skip.setStyleSheet(
            "QPushButton{background:transparent;color:#4a5070;"
            "border:none;font-size:11px;padding:6px 0;}"
            "QPushButton:hover{color:#9da5c0;}"
        )
        self._skip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip.clicked.connect(self.skip_clicked)
        btn_row.addWidget(self._skip)
        btn_row.addStretch()

        self._next_btn = QPushButton("Next  →")
        self._next_btn.setStyleSheet(
            "QPushButton{background:#4b3fa8;color:#fff;"
            "border:none;border-radius:7px;"
            "font-size:12px;font-weight:600;padding:7px 20px;}"
            "QPushButton:hover{background:#5a4fc4;}"
        )
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_btn.clicked.connect(self.next_clicked)
        btn_row.addWidget(self._next_btn)

        lay.addLayout(btn_row)

    def set_content(self, step: int, total: int, title: str,
                    description: str, is_last: bool):
        self._counter.setText(f"STEP {step} OF {total}")
        self._title.setText(title)
        self._desc.setText(description)
        self._next_btn.setText("Finish  ✓" if is_last else "Next  →")
        self._skip.setVisible(not is_last)
        self.adjustSize()