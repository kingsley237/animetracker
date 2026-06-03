"""
Miroku — Statistics Page
Clean redesign: content-driven heights, no fixed constraints, no paintEvent tricks.

Sections
--------
1. Activity heatmap  (HeatmapSection)
2. Four KPI tiles
3. Status donut (left) + Top genres (right)
4. Rating distribution
"""
from typing import Dict, List, Tuple

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from core.database import DatabaseManager
from ui.heatmap_widget import HeatmapSection

# ── Palette ────────────────────────────────────────────────────────────────────
C_PURPLE = "#7c6af7"
C_GREEN  = "#34d399"
C_AMBER  = "#fbbf24"
C_RED    = "#f87171"
C_BLUE   = "#38bdf8"
C_TEAL   = "#2dd4bf"
C_PINK   = "#f472b6"
C_ORANGE = "#fb923c"
C_GREY   = "#6b7280"
C_TEXT   = "#dde0ed"
C_DIM    = "#4a5070"
C_CARD   = "#111420"
C_BORDER = "#1a1d28"

_GENRE_COLORS  = [C_PURPLE, C_GREEN, C_AMBER, C_RED,
                  C_BLUE, C_ORANGE, C_TEAL, C_PINK]
_RATING_LABELS = {1:"Terrible", 2:"Bad", 3:"Fair",
                  4:"Good", 5:"Great", 6:"Masterpiece"}
_RATING_COLORS = {1:C_RED, 2:C_ORANGE, 3:C_AMBER,
                  4:C_GREEN, 5:C_PURPLE, 6:C_TEAL}


def _card(parent=None) -> QFrame:
    """Base card frame — dark bg, border, rounded corners via QSS."""
    f = QFrame(parent)
    f.setObjectName("statsPageCard")
    f.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return f


def _section_header(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(
        f"font-size:10px;font-weight:700;color:{C_DIM};"
        "letter-spacing:1.8px;background:transparent;"
    )
    return l


def _vline(color: str, width: int = 3) -> QFrame:
    """Thin colored vertical accent bar."""
    f = QFrame()
    f.setFixedWidth(width)
    f.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    f.setStyleSheet(f"background:{color};border-radius:2px;")
    return f


# ── Page ───────────────────────────────────────────────────────────────────────

class StatsPage(QWidget):
    def __init__(self, db: DatabaseManager, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._body = QWidget()
        self._body.setStyleSheet("background:transparent;")
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(32, 32, 32, 64)
        self._body_lay.setSpacing(36)

        scroll.setWidget(self._body)
        root.addWidget(scroll)

    def load(self) -> None:
        while self._body_lay.count():
            item = self._body_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._render(self.db.get_stats())

    def _render(self, s: Dict) -> None:
        # Title
        title = QLabel("Statistics")
        title.setObjectName("pageTitle")
        self._body_lay.addWidget(title)

        # Heatmap
        self._body_lay.addWidget(HeatmapSection(self.db))

        # KPI row
        self._body_lay.addWidget(_KpiRow(s))

        # Status + Genres side by side
        status_data: List[Tuple[str, int, str]] = [
            ("Watching",      s.get("watching",  0), C_PURPLE),
            ("Completed",     s.get("completed", 0), C_GREEN),
            ("Plan to Watch", s.get("planned",   0), C_GREY),
            ("Dropped",       s.get("dropped",   0), C_RED),
        ]
        mid = QHBoxLayout()
        mid.setSpacing(20)
        mid.setContentsMargins(0, 0, 0, 0)

        status_card = _StatusCard(status_data)
        mid.addWidget(status_card, stretch=1)

        top_genres = s.get("top_genres", [])
        if top_genres:
            genres_card = _GenresCard(top_genres)
            mid.addWidget(genres_card, stretch=1)

        mid_w = QWidget()
        mid_w.setStyleSheet("background:transparent;")
        mid_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        mid_w.setLayout(mid)
        self._body_lay.addWidget(mid_w)

        # Ratings
        dist = self._rating_dist()
        if dist:
            self._body_lay.addWidget(_RatingCard(dist))

        self._body_lay.addStretch(1)

    def _rating_dist(self) -> List[Tuple[int, int]]:
        conn = self.db._get_conn()
        rows = conn.execute(
            "SELECT CAST(ROUND(score) AS INTEGER) AS s, COUNT(*) AS c "
            "FROM ratings GROUP BY s ORDER BY s DESC"
        ).fetchall()
        return [(r[0], r[1]) for r in rows if r[0] and 1 <= r[0] <= 6]


# ── KPI row ────────────────────────────────────────────────────────────────────

class _KpiRow(QWidget):
    """Four stat tiles in a horizontal row."""

    def __init__(self, s: Dict, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        watched  = s.get("total_episodes_watched", 0)
        mins     = watched * 24
        days     = mins // 1440
        rem_h    = (mins % 1440) // 60
        time_str = (f"{days}d {rem_h}h" if days > 0
                    else f"{mins // 60}h {mins % 60}m" if mins >= 60
                    else f"{mins}m")
        avg      = s.get("average_score")

        tiles = [
            (str(watched),                          "EPISODES WATCHED", C_GREEN),
            (str(s.get("completed", 0)),            "COMPLETED",        C_PURPLE),
            (f"{avg:.1f} / 6" if avg else "—",      "AVG YOUR RATING",  C_AMBER),
            (time_str if watched else "—",          "TIME INVESTED",    C_TEAL),
        ]

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        for val, label, color in tiles:
            lay.addWidget(_KpiTile(val, label, color))


class _KpiTile(QFrame):
    """Single KPI: colored left-accent bar + large number + label."""

    def __init__(self, value: str, label: str, color: str,
                 parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("statsPageCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Left accent bar
        accent = QFrame()
        accent.setFixedWidth(4)
        accent.setStyleSheet(
            f"background:{color};border-top-left-radius:10px;"
            "border-bottom-left-radius:10px;border-radius:0px;"
            f"background:{color};"
        )
        accent.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        outer.addWidget(accent)

        # Content
        inner = QVBoxLayout()
        inner.setContentsMargins(20, 24, 20, 24)
        inner.setSpacing(10)

        val_lbl = QLabel(value)
        val_lbl.setStyleSheet(
            f"font-size:34px;font-weight:700;color:{color};"
            "letter-spacing:-0.5px;background:transparent;"
        )
        inner.addWidget(val_lbl)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            "font-size:11px;color:#4a5070;font-weight:700;"
            "letter-spacing:1px;background:transparent;"
        )
        inner.addWidget(lbl)

        outer.addLayout(inner)


# ── Donut ──────────────────────────────────────────────────────────────────────

class _DonutWidget(QWidget):
    """Pure QPainter donut — fixed square size, no clipping issues."""

    SIZE   = 200
    STROKE = 20
    GAP    = 4   # degrees gap between segments

    def __init__(self, data: List[Tuple[str, int, str]], parent=None) -> None:
        super().__init__(parent)
        self._data  = [(l, v, c) for l, v, c in data if v > 0]
        self._total = sum(v for _, v, _ in self._data)
        self.setFixedSize(self.SIZE, self.SIZE)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        half   = self.STROKE // 2 + 2
        size   = self.SIZE - half * 2
        rect   = QRectF(half, half, size, size)

        # Background ring
        bg = QPen(QColor(C_BORDER))
        bg.setWidth(self.STROKE)
        bg.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(bg)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)

        if not self._data or self._total == 0:
            p.end()
            return

        n_gaps      = len(self._data)
        total_gap   = self.GAP * n_gaps * 16
        available   = (360 * 16) - total_gap
        angle       = 90 * 16        # 12 o'clock

        seg = QPen()
        seg.setWidth(self.STROKE)
        seg.setCapStyle(Qt.PenCapStyle.FlatCap)

        for _, value, color in self._data:
            span = max(round((value / self._total) * available), 1)
            seg.setColor(QColor(color))
            p.setPen(seg)
            p.drawArc(rect, angle, -span)
            angle -= span + self.GAP * 16

        # Centre: total number
        p.setPen(QPen(QColor(C_TEXT)))
        f = QFont()
        f.setPointSize(22)
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(
            QRectF(half, half + size * 0.22, size, size * 0.38),
            Qt.AlignmentFlag.AlignCenter,
            str(self._total),
        )

        # Centre: "in library"
        p.setPen(QPen(QColor(C_DIM)))
        f2 = QFont()
        f2.setPointSize(8)
        p.setFont(f2)
        p.drawText(
            QRectF(half, half + size * 0.60, size, size * 0.22),
            Qt.AlignmentFlag.AlignCenter,
            "in library",
        )
        p.end()


# ── Status card ────────────────────────────────────────────────────────────────

class _StatusCard(QFrame):
    """Donut + 4-row legend."""

    def __init__(self, data: List[Tuple[str, int, str]], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("statsPageCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 28)
        lay.setSpacing(0)

        lay.addWidget(_section_header("YOUR LIBRARY"))
        lay.addSpacing(24)
        lay.addWidget(_DonutWidget(data), alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(28)

        # Legend rows
        for label, value, color in data:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(10)

            dot = QLabel("●")
            dot.setFixedWidth(16)
            dot.setStyleSheet(f"font-size:10px;color:{color};background:transparent;")
            row.addWidget(dot)

            name = QLabel(label)
            name.setStyleSheet("font-size:13px;color:#8a91a6;background:transparent;")
            row.addWidget(name, 1)

            cnt = QLabel(str(value))
            cnt.setStyleSheet(
                f"font-size:15px;font-weight:700;color:{color};background:transparent;"
            )
            cnt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(cnt)

            lay.addLayout(row)
            lay.addSpacing(14)


# ── Genres card ────────────────────────────────────────────────────────────────

class _GenresCard(QFrame):
    """Top genres with proportional bars."""

    def __init__(self, genres: List[Tuple[str, int]], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("statsPageCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 28)
        lay.setSpacing(0)

        lay.addWidget(_section_header("TOP GENRES"))
        lay.addSpacing(24)

        max_c = max((c for _, c in genres), default=1)

        for i, (genre, count) in enumerate(genres[:8]):
            color = _GENRE_COLORS[i % len(_GENRE_COLORS)]

            # Genre name + count on one line
            top = QHBoxLayout()
            top.setContentsMargins(0, 0, 0, 0)
            top.setSpacing(0)

            g = QLabel(genre)
            g.setStyleSheet("font-size:13px;color:#c0c4d6;background:transparent;")
            top.addWidget(g)
            top.addStretch()

            c = QLabel(str(count))
            c.setStyleSheet(
                f"font-size:13px;font-weight:700;color:{color};background:transparent;"
            )
            top.addWidget(c)
            lay.addLayout(top)
            lay.addSpacing(7)

            # Bar
            bar = QProgressBar()
            bar.setMaximum(max_c)
            bar.setValue(count)
            bar.setTextVisible(False)
            bar.setFixedHeight(7)
            bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            bar.setStyleSheet(
                f"QProgressBar{{background:{C_BORDER};border:none;border-radius:3px;}}"
                f"QProgressBar::chunk{{background:{color};border-radius:3px;}}"
            )
            lay.addWidget(bar)

            if i < len(genres[:8]) - 1:
                lay.addSpacing(18)


# ── Rating card ────────────────────────────────────────────────────────────────

class _RatingCard(QFrame):
    """Rating distribution — one row per star level."""

    def __init__(self, dist: List[Tuple[int, int]], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("statsPageCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 28)
        lay.setSpacing(0)

        lay.addWidget(_section_header("YOUR RATINGS"))
        lay.addSpacing(24)

        max_c = max((c for _, c in dist), default=1)

        for score, count in sorted(dist, key=lambda x: x[0], reverse=True):
            color = _RATING_COLORS.get(score, C_PURPLE)
            ltext = _RATING_LABELS.get(score, "")

            row = QHBoxLayout()
            row.setContentsMargins(0, 8, 0, 8)
            row.setSpacing(14)

            # Star score
            star = QLabel(f"★ {score}")
            star.setFixedWidth(40)
            star.setStyleSheet(
                f"font-size:15px;font-weight:700;color:{color};background:transparent;"
            )
            row.addWidget(star)

            # Label
            name = QLabel(ltext)
            name.setFixedWidth(100)
            name.setStyleSheet("font-size:13px;color:#5a6080;background:transparent;")
            row.addWidget(name)

            # Bar
            bar = QProgressBar()
            bar.setMaximum(max_c)
            bar.setValue(count)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            bar.setStyleSheet(
                f"QProgressBar{{background:{C_BORDER};border:none;border-radius:4px;}}"
                f"QProgressBar::chunk{{background:{color};border-radius:4px;}}"
            )
            row.addWidget(bar, 1)

            # Count
            cnt = QLabel(f"{count}×")
            cnt.setFixedWidth(40)
            cnt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cnt.setStyleSheet("font-size:13px;color:#4a5070;background:transparent;")
            row.addWidget(cnt)

            lay.addLayout(row)