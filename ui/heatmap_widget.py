"""
Miroku — Activity Heatmap Widget

GitHub-style 52-week × 7-day calendar heatmap showing daily episode
watch activity.  Rendered entirely with QPainter — no external deps.

Design decisions (from research):
  - Single-hue ramp (purple) — rainbow scales create false boundaries
  - 5 intensity levels (0-4): 0=empty, 1=1ep, 2=2-3eps, 3=4-6eps, 4=7+
  - Week columns left→right (oldest→newest), rows Mon→Sun top→bottom
  - Month labels above grid, aligned to first week of each month
  - Hover tooltip: date + episode count + up to 3 anime titles
  - Streak counter + total episodes below the grid
  - Year selector when multiple years have data
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QPainter, QPainterPath, QPen,
)
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QToolTip, QVBoxLayout, QWidget,
)

from core.database import DatabaseManager

# ── Color ramp — 5 levels, single-hue purple ─────────────────────────────────
_LEVEL_COLORS = [
    QColor("#1a1d28"),   # 0 — empty
    QColor("#2d2566"),   # 1 — 1 episode
    QColor("#4a3fa8"),   # 2 — 2-3 episodes
    QColor("#7c6af7"),   # 3 — 4-6 episodes
    QColor("#a594f9"),   # 4 — 7+ episodes
]

_CELL   = 11    # cell size px
_GAP    = 3     # gap between cells
_STRIDE = _CELL + _GAP   # 14px per cell
_WEEKS  = 53    # always render 53 columns so we never cut off
_DAYS   = 7
_LEFT_PAD  = 28  # space for Mon/Wed/Fri labels
_TOP_PAD   = 20  # space for month labels
_BOTTOM_PAD = 0

_MONTH_ABBR = ["Jan","Feb","Mar","Apr","May","Jun",
               "Jul","Aug","Sep","Oct","Nov","Dec"]
_DAY_ABBR   = ["Mon","","Wed","","Fri","",""]


def _ep_to_level(count: int) -> int:
    if count == 0: return 0
    if count == 1: return 1
    if count <= 3: return 2
    if count <= 6: return 3
    return 4


class ActivityHeatmap(QWidget):
    """
    Full-year episode activity heatmap.

    Args:
        db:   DatabaseManager instance.
        year: Calendar year to display (defaults to current year).
    """

    def __init__(self, db: DatabaseManager, year: Optional[int] = None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.db   = db
        self._year: int = year or datetime.now().year
        # {date_str: [{episode_num, anime_title}, ...]}
        self._data: Dict[str, List[dict]] = {}
        # Pre-computed per-date counts
        self._counts: Dict[str, int] = {}
        self._hovered_date: Optional[str] = None
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._load()

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load(self):
        """Load and bucket watch_log rows into per-date lists."""
        self._data   = {}
        self._counts = {}
        try:
            rows = self.db.get_watch_log_year(self._year)
        except Exception:
            return
        for row in rows:
            d = datetime.fromtimestamp(row["watched_at"]).strftime("%Y-%m-%d")
            self._data.setdefault(d, []).append({
                "episode_num": row["episode_num"],
                "anime_title": row.get("anime_title", ""),
            })
        self._counts = {d: len(v) for d, v in self._data.items()}
        self.updateGeometry()
        self.update()

    def set_year(self, year: int):
        self._year = year
        self._load()

    # ── Sizing ────────────────────────────────────────────────────────────────

    def sizeHint(self) -> QSize:
        w = _LEFT_PAD + _WEEKS * _STRIDE + 10
        h = _TOP_PAD  + _DAYS  * _STRIDE + _BOTTOM_PAD + 4
        return QSize(w, h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # ── Grid geometry helpers ─────────────────────────────────────────────────

    def _first_day(self) -> date:
        """First Monday on or before Jan 1 of the display year."""
        jan1 = date(self._year, 1, 1)
        # weekday() 0=Mon … 6=Sun
        offset = jan1.weekday()          # days since last Monday
        return jan1 - timedelta(days=offset)

    def _cell_rect(self, week: int, day: int) -> QRect:
        x = _LEFT_PAD + week * _STRIDE
        y = _TOP_PAD  + day  * _STRIDE
        return QRect(x, y, _CELL, _CELL)

    def _date_at(self, week: int, day: int) -> date:
        return self._first_day() + timedelta(weeks=week, days=day)

    def _week_day_at_pos(self, pos: QPoint) -> Optional[Tuple[int, int]]:
        x = pos.x() - _LEFT_PAD
        y = pos.y() - _TOP_PAD
        if x < 0 or y < 0:
            return None
        week = x // _STRIDE
        day  = y // _STRIDE
        if week >= _WEEKS or day >= _DAYS:
            return None
        # Check inside the cell (not in the gap)
        if (x % _STRIDE) > _CELL or (y % _STRIDE) > _CELL:
            return None
        return week, day

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        first = self._first_day()
        today = date.today()

        # Month label positions: track first week each month appears
        month_x: Dict[int, int] = {}

        for week in range(_WEEKS):
            for day in range(_DAYS):
                d = first + timedelta(weeks=week, days=day)
                if d.year != self._year and week > 0:
                    continue   # skip days outside the target year
                ds    = d.strftime("%Y-%m-%d")
                count = self._counts.get(ds, 0)
                level = _ep_to_level(count)
                color = _LEVEL_COLORS[level]

                r = self._cell_rect(week, day)

                # Highlight today
                if d == today:
                    p.setPen(QPen(QColor("#7c6af7"), 1))
                else:
                    p.setPen(Qt.PenStyle.NoPen)

                # Hover highlight
                if self._hovered_date == ds and count > 0:
                    lighter = QColor(color)
                    lighter.setAlpha(220)
                    p.setBrush(lighter)
                else:
                    p.setBrush(color)

                p.drawRoundedRect(r, 2, 2)

                # Track month first occurrence
                if d.day == 1 or (week == 0 and day == 0):
                    month_x.setdefault(d.month, r.x())

        # Month labels
        p.setPen(QColor("#4a5070"))
        f = QFont(); f.setPointSize(8)
        p.setFont(f)
        for month, mx in month_x.items():
            p.drawText(mx, 0, 40, _TOP_PAD - 2,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                       _MONTH_ABBR[month - 1])

        # Day-of-week labels
        for i, lbl in enumerate(_DAY_ABBR):
            if not lbl:
                continue
            y = _TOP_PAD + i * _STRIDE
            p.drawText(0, y, _LEFT_PAD - 4, _CELL,
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       lbl)

        p.end()

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def mouseMoveEvent(self, event):
        wd = self._week_day_at_pos(event.pos())
        if wd is None:
            self._hovered_date = None
            QToolTip.hideText()
            self.update()
            return

        week, day = wd
        d  = self._date_at(week, day)
        ds = d.strftime("%Y-%m-%d")

        if ds != self._hovered_date:
            self._hovered_date = ds
            self.update()

        entries = self._data.get(ds, [])
        if entries:
            count  = len(entries)
            titles = list({e["anime_title"] for e in entries if e["anime_title"]})[:3]
            tip    = f"<b>{d.strftime('%d %b %Y')}</b><br>{count} episode{'s' if count != 1 else ''}"
            if titles:
                tip += "<br><span style='color:#9da5c0'>" + "<br>".join(titles) + "</span>"
            QToolTip.showText(event.globalPosition().toPoint(), tip, self)
        else:
            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"<b>{d.strftime('%d %b %Y')}</b><br>No episodes", self
            )

    def leaveEvent(self, _ev):
        self._hovered_date = None
        self.update()


# ── Container widget with year selector + stats ───────────────────────────────

class HeatmapSection(QWidget):
    """
    Full heatmap section for the Stats page.
    Includes year selector, the heatmap grid, and streak / total stats below.
    """

    def __init__(self, db: DatabaseManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.db = db
        self._build()
        self.refresh()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # ── Header row: title + year selector ────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(10)

        title = QLabel("WATCH ACTIVITY")
        title.setStyleSheet(
            "font-size:10px;color:#3b4260;font-weight:700;letter-spacing:1.8px;"
        )
        hdr.addWidget(title)
        hdr.addStretch()

        self._year_combo = QComboBox()
        self._year_combo.setFixedWidth(80)
        self._year_combo.currentTextChanged.connect(self._on_year_changed)
        hdr.addWidget(self._year_combo)

        lay.addLayout(hdr)

        # ── Heatmap canvas ────────────────────────────────────────────────
        self._heatmap = ActivityHeatmap(self.db)
        lay.addWidget(self._heatmap)

        # ── Legend ────────────────────────────────────────────────────────
        legend_row = QHBoxLayout()
        legend_row.setSpacing(4)
        legend_row.addStretch()
        legend_lbl = QLabel("Less")
        legend_lbl.setStyleSheet("font-size:9px;color:#4a5070;")
        legend_row.addWidget(legend_lbl)
        for color in _LEVEL_COLORS:
            swatch = QFrame()
            swatch.setFixedSize(10, 10)
            swatch.setStyleSheet(
                f"background:{color.name()};border-radius:2px;"
            )
            legend_row.addWidget(swatch)
        more_lbl = QLabel("More")
        more_lbl.setStyleSheet("font-size:9px;color:#4a5070;")
        legend_row.addWidget(more_lbl)
        lay.addLayout(legend_row)

        # ── Stats row: streak + total ─────────────────────────────────────
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)

        self._streak_card = self._make_stat_card("–", "Day streak", "#fbbf24")
        self._total_card  = self._make_stat_card("–", "Episodes this year", "#7c6af7")
        self._busiest_card = self._make_stat_card("–", "Busiest day", "#34d399")

        for card in (self._streak_card, self._total_card, self._busiest_card):
            stats_row.addWidget(card)
        stats_row.addStretch()
        lay.addLayout(stats_row)

    def _make_stat_card(self, value: str, label: str,
                        color: str) -> QFrame:
        card = QFrame()
        card.setObjectName("statCard")
        card.setFixedHeight(85)
        card.setMinimumWidth(140)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 8, 14, 8)
        cl.setSpacing(2)
        val_lbl = QLabel(value)
        val_lbl.setStyleSheet(
            f"font-size:22px;font-weight:700;color:{color};"
            "background:transparent;"
        )
        lbl_lbl = QLabel(label)
        lbl_lbl.setStyleSheet(
            "font-size:10px;color:#4a5070;font-weight:500;background:transparent;"
        )
        cl.addWidget(val_lbl)
        cl.addWidget(lbl_lbl)
        # Store val label for updates
        card._val_lbl = val_lbl   # type: ignore[attr-defined]
        return card

    def refresh(self):
        """Reload data. Call whenever the stats page is shown."""
        # Populate year selector
        years = self.db.get_available_log_years()
        self._year_combo.blockSignals(True)
        self._year_combo.clear()
        for y in years:
            self._year_combo.addItem(str(y))
        self._year_combo.blockSignals(False)

        # Update heatmap
        current_year = int(self._year_combo.currentText() or datetime.now().year)
        self._heatmap.set_year(current_year)

        # Streak
        streak = self.db.get_current_streak()
        self._streak_card._val_lbl.setText(  # type: ignore[attr-defined]
            str(streak) if streak else "0"
        )

        # Total this year
        total = sum(self._heatmap._counts.values())
        self._total_card._val_lbl.setText(str(total))  # type: ignore[attr-defined]

        # Busiest single day
        if self._heatmap._counts:
            best_ds    = max(self._heatmap._counts, key=self._heatmap._counts.get)
            best_count = self._heatmap._counts[best_ds]
            d          = datetime.strptime(best_ds, "%Y-%m-%d")
            self._busiest_card._val_lbl.setText(  # type: ignore[attr-defined]
                f"{best_count}ep · {d.strftime('%d %b')}"
            )
        else:
            self._busiest_card._val_lbl.setText("–")  # type: ignore[attr-defined]

    def _on_year_changed(self, text: str):
        if text:
            self._heatmap.set_year(int(text))
            total = sum(self._heatmap._counts.values())
            self._total_card._val_lbl.setText(str(total))  # type: ignore[attr-defined]