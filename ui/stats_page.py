"""
AnimeTracker — Statistics Page
Complete redesign: professional dashboard layout.
Sections: headline KPIs · status breakdown · watch progress · genre chart · score distribution
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QScrollArea, QSizePolicy, QGridLayout,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QLinearGradient

from core.database import DatabaseManager


# ── Palette ────────────────────────────────────────────────────────────────────
C_PURPLE  = "#7c6af7"
C_GREEN   = "#34d399"
C_AMBER   = "#fbbf24"
C_RED     = "#f87171"
C_BLUE    = "#38bdf8"
C_ORANGE  = "#fb923c"
C_TEAL    = "#2dd4bf"
C_PINK    = "#f472b6"
C_MUTED   = "#4a5070"
C_TEXT    = "#dde0ed"
C_DIM     = "#3b4260"
C_CARD    = "#111420"
C_BORDER  = "#1a1d28"


class StatsPage(QWidget):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.body = QWidget()
        self.body.setStyleSheet("background:transparent;")
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(32, 24, 32, 32)
        self.body_lay.setSpacing(28)

        self.scroll.setWidget(self.body)
        lay.addWidget(self.scroll)

    # ── Load ───────────────────────────────────────────────────────────────────

    def load(self):
        # Wipe all previous widgets
        while self.body_lay.count():
            item = self.body_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        stats = self.db.get_stats()
        self._render(stats)

    def _render(self, s: Dict):
        # ── Page header ──────────────────────────────────────────────────
        hdr = QVBoxLayout()
        hdr.setSpacing(4)
        title = QLabel("Statistics")
        title.setObjectName("pageTitle")
        hdr.addWidget(title)
        sub = QLabel("Your anime journey at a glance")
        sub.setStyleSheet(f"font-size:13px;color:{C_MUTED};")
        hdr.addWidget(sub)
        hdr_w = QWidget()
        hdr_w.setStyleSheet("background:transparent;")
        hdr_w.setLayout(hdr)
        self.body_lay.addWidget(hdr_w)

        # ── Section 1: Key numbers (2×2 grid) ───────────────────────────
        self.body_lay.addWidget(self._section_label("YOUR NUMBERS"))

        kpi_grid = QGridLayout()
        kpi_grid.setSpacing(12)
        kpi_defs = [
            (str(s.get("total", 0)),                        "Total in Library",          C_PURPLE, "📚"),
            (str(s.get("total_episodes_watched", 0)),       "Episodes Watched",           C_GREEN,  "▶"),
            (f"{s['average_score']:.1f} / 6"
             if s.get("average_score") else "–",            "Your Average Rating",        C_AMBER,  "★"),
            (str(s.get("watching", 0) + s.get("completed", 0)),
                                                            "Watched or Watching",        C_BLUE,   "◈"),
        ]
        for i, (val, label, color, icon) in enumerate(kpi_defs):
            card = self._kpi_card(val, label, color, icon)
            kpi_grid.addWidget(card, i // 2, i % 2)

        kpi_w = QWidget()
        kpi_w.setStyleSheet("background:transparent;")
        kpi_w.setLayout(kpi_grid)
        self.body_lay.addWidget(kpi_w)

        # ── Section 2: Status breakdown ──────────────────────────────────
        self.body_lay.addWidget(self._section_label("STATUS BREAKDOWN"))

        status_data = [
            ("Watching",      s.get("watching", 0),   C_PURPLE),
            ("Completed",     s.get("completed", 0),  C_GREEN),
            ("Plan to Watch", s.get("planned", 0),    C_MUTED),
            ("Dropped",       s.get("dropped", 0),    C_RED),
        ]
        total_lib = max(sum(v for _, v, _ in status_data), 1)

        # Individual row cards
        status_rows_w = QWidget()
        status_rows_w.setStyleSheet("background:transparent;")
        sr_lay = QVBoxLayout(status_rows_w)
        sr_lay.setContentsMargins(0, 0, 0, 0)
        sr_lay.setSpacing(8)

        for label, count, color in status_data:
            row = self._status_row(label, count, total_lib, color)
            sr_lay.addWidget(row)

        self.body_lay.addWidget(status_rows_w)

        # Stacked bar below
        bar_data = [(l, v, c) for l, v, c in status_data]
        self.body_lay.addWidget(_StackedBar(bar_data, total_lib))

        # ── Section 3: Watch time estimate (compact) ────────────────────
        watched_eps = s.get("total_episodes_watched", 0)
        if watched_eps > 0:
            minutes  = watched_eps * 24
            hours    = minutes // 60
            days     = hours // 24
            rem_h    = hours % 24
            time_str = f"{days}d {rem_h}h" if days > 0 else f"{hours}h {minutes % 60}m"
            self.body_lay.addWidget(
                self._wide_info_card(f"≈ {time_str}", "Estimated watch time", C_TEAL, "⏱")
            )

        # ── Section 4: Genre breakdown ───────────────────────────────────
        top_genres = s.get("top_genres", [])
        if top_genres:
            self.body_lay.addWidget(self._section_label("TOP GENRES"))
            chart = _GenreChart(top_genres)
            self.body_lay.addWidget(chart)



        # ── Section 5: Remarkable anime ────────────────────────────────
        self.body_lay.addWidget(self._section_label("HIGHLIGHTS FROM YOUR LIBRARY"))
        remarkable = self.db.get_remarkable_anime()
        if remarkable:
            for key, icon, title_fmt in [
                ("most_watched",  "▶", lambda r: f"{r.get('cnt',0)} eps watched"),
                ("highest_rated", "🏆", lambda r: f"avg {r.get('avg_sc',0):.1f}/6 rating"),
                ("lowest_rated",  "📉", lambda r: f"avg {r.get('avg_sc',0):.1f}/6 rating"),
                ("most_recent",   "🆕", lambda r: "Most recently added"),
            ]:
                entry = remarkable.get(key)
                if not entry: continue
                name = entry.get("english_title") or entry.get("romaji_title","")
                subtitle = title_fmt(entry)
                lbl_map = {
                    "most_watched":  "Most Episodes Watched",
                    "highest_rated": "Highest Rated by You",
                    "lowest_rated":  "Lowest Rated by You",
                    "most_recent":   "Most Recently Added",
                }
                self.body_lay.addWidget(
                    self._highlight_row(icon, lbl_map[key], name, subtitle)
                )

        self.body_lay.addStretch()

    # ── Widget builders ────────────────────────────────────────────────────────

    def _section_label(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"font-size:10px;color:{C_DIM};font-weight:700;letter-spacing:1.8px;"
        )
        return l

    def _kpi_card(self, value: str, label: str, color: str, icon: str) -> QFrame:
        card = QFrame()
        card.setObjectName("statCard")
        card.setMinimumHeight(96)
        lay  = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(6)

        top = QHBoxLayout()
        ic  = QLabel(icon)
        ic.setStyleSheet(f"font-size:18px;background:transparent;")
        top.addWidget(ic)
        top.addStretch()
        lay.addLayout(top)

        val = QLabel(value)
        val.setStyleSheet(
            f"font-size:28px;font-weight:700;color:{color};"
            "letter-spacing:-0.5px;background:transparent;"
        )
        lay.addWidget(val)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"font-size:11px;color:{C_MUTED};font-weight:500;background:transparent;"
        )
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        return card

    def _status_row(self, label: str, count: int, total: int,
                    color: str) -> QFrame:
        """Horizontal progress row: label · bar · count · pct"""
        row = QFrame()
        row.setObjectName("statCard")
        row.setFixedHeight(52)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(12)

        # Color dot
        dot = QLabel("●")
        dot.setStyleSheet(f"font-size:10px;color:{color};background:transparent;")
        dot.setFixedWidth(14)
        lay.addWidget(dot)

        # Label
        lbl = QLabel(label)
        lbl.setStyleSheet(f"font-size:13px;color:{C_TEXT};background:transparent;")
        lbl.setFixedWidth(120)
        lay.addWidget(lbl)

        # Progress bar
        from PyQt6.QtWidgets import QProgressBar
        bar = QProgressBar()
        bar.setMaximum(total)
        bar.setValue(count)
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        bar.setStyleSheet(
            f"QProgressBar{{background:{C_BORDER};border:none;border-radius:3px;}}"
            f"QProgressBar::chunk{{background:{color};border-radius:3px;}}"
        )
        bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay.addWidget(bar)

        # Count
        cnt = QLabel(str(count))
        cnt.setStyleSheet(
            f"font-size:15px;font-weight:700;color:{color};background:transparent;"
        )
        cnt.setFixedWidth(36)
        cnt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(cnt)

        # Percentage
        pct = (count / total * 100) if total else 0
        pct_lbl = QLabel(f"{pct:.0f}%")
        pct_lbl.setStyleSheet(f"font-size:11px;color:{C_MUTED};background:transparent;")
        pct_lbl.setFixedWidth(36)
        pct_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(pct_lbl)
        return row

    def _wide_info_card(self, value: str, sub: str, color: str, icon: str) -> QFrame:
        card = QFrame()
        card.setObjectName("statCard")
        card.setFixedHeight(72)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(16)

        ic = QLabel(icon)
        ic.setStyleSheet(f"font-size:24px;background:transparent;")
        lay.addWidget(ic)

        col = QVBoxLayout()
        col.setSpacing(2)
        val = QLabel(value)
        val.setStyleSheet(
            f"font-size:22px;font-weight:700;color:{color};background:transparent;"
        )
        col.addWidget(val)
        sub_lbl = QLabel(sub)
        sub_lbl.setStyleSheet(f"font-size:11px;color:{C_MUTED};background:transparent;")
        col.addWidget(sub_lbl)
        lay.addLayout(col)
        lay.addStretch()
        return card


# ── Custom paint widgets ───────────────────────────────────────────────────────

    def _highlight_row(self, icon: str, category: str,
                       anime_name: str, subtitle: str) -> QFrame:
        row = QFrame()
        row.setObjectName("statCard")
        row.setFixedHeight(58)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(12)

        ic = QLabel(icon)
        ic.setStyleSheet("font-size:18px;background:transparent;")
        ic.setFixedWidth(24)
        lay.addWidget(ic)

        col = QVBoxLayout()
        col.setSpacing(2)
        cat_lbl = QLabel(category.upper())
        cat_lbl.setStyleSheet(
            f"font-size:9px;font-weight:700;color:{C_DIM};"
            "letter-spacing:1px;background:transparent;"
        )
        col.addWidget(cat_lbl)
        name_lbl = QLabel(anime_name[:50])
        name_lbl.setStyleSheet(
            f"font-size:13px;font-weight:600;color:{C_TEXT};background:transparent;"
        )
        col.addWidget(name_lbl)
        lay.addLayout(col)
        lay.addStretch()

        sub_lbl = QLabel(subtitle)
        sub_lbl.setStyleSheet(f"font-size:12px;color:{C_MUTED};background:transparent;")
        lay.addWidget(sub_lbl)
        return row


class _StackedBar(QWidget):
    """Compact stacked horizontal bar with legend."""

    def __init__(self, data: List[Tuple], total: int, parent=None):
        super().__init__(parent)
        self.data  = [(l, v, c) for l, v, c in data if v > 0]
        self.total = max(total, 1)
        self.setFixedHeight(36)
        self.setStyleSheet("background:transparent;")

    def paintEvent(self, ev):
        if not self.data:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w  = self.width() - 2
        bh = 10
        by = 4
        x  = 1

        p.setBrush(QBrush(QColor(C_BORDER)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(x, by, w, bh, 5, 5)

        cx = x
        for i, (label, value, color) in enumerate(self.data):
            sw = max(int((value / self.total) * w), 2)
            p.setBrush(QBrush(QColor(color)))
            if i == 0:
                p.drawRoundedRect(cx, by, sw, bh, 5, 5)
                p.drawRect(cx + sw - 5, by, 5, bh)
            elif i == len(self.data) - 1:
                p.drawRoundedRect(cx, by, sw, bh, 5, 5)
                p.drawRect(cx, by, 5, bh)
            else:
                p.drawRect(cx, by, sw, bh)
            cx += sw

        p.end()


class _GenreChart(QWidget):
    COLORS = [C_PURPLE, C_GREEN, C_AMBER, C_RED,
              C_BLUE, C_ORANGE, C_TEAL, C_PINK]

    def __init__(self, genres: List[Tuple], parent=None):
        super().__init__(parent)
        self.genres = genres
        self.setMinimumHeight(len(genres) * 38 + 8)
        self.setStyleSheet("background:transparent;")

    def paintEvent(self, ev):
        if not self.genres:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        max_v   = max(v for _, v in self.genres)
        label_w = 150
        num_w   = 40
        bar_w   = self.width() - label_w - num_w - 16
        row_h   = 34

        font = QFont()
        font.setPointSize(10)
        p.setFont(font)

        for i, (genre, count) in enumerate(self.genres):
            y   = i * row_h + 4
            col = QColor(self.COLORS[i % len(self.COLORS)])

            # Genre label
            p.setPen(QPen(QColor(C_TEXT)))
            p.drawText(0, y, label_w, 22,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       genre)

            # Bar background
            p.setBrush(QBrush(QColor(C_BORDER)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(label_w, y + 4, bar_w, 14, 5, 5)

            # Bar fill with gradient
            fill_w = max(int((count / max_v) * bar_w), 6)
            grad   = QLinearGradient(label_w, 0, label_w + fill_w, 0)
            col2   = QColor(col)
            col2.setAlpha(100)
            grad.setColorAt(0, col)
            grad.setColorAt(1, col2)
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(label_w, y + 4, fill_w, 14, 5, 5)

            # Count label
            p.setPen(QPen(QColor(C_TEXT)))
            small = QFont()
            small.setPointSize(9)
            p.setFont(small)
            p.drawText(label_w + bar_w + 8, y, num_w, 22,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       str(count))
            p.setFont(font)

        p.end()


class _RatingDist(QWidget):
    """Bar chart of rating distribution (1–6)."""
    LABELS = {1: "Terrible", 2: "Bad", 3: "Fair",
               4: "Good",    5: "Great", 6: "Masterpiece"}
    COLORS = {1: C_RED, 2: "#fb923c", 3: C_AMBER,
               4: C_GREEN, 5: C_PURPLE, 6: C_TEAL}

    def __init__(self, dist: List[Tuple[int, int]], parent=None):
        super().__init__(parent)
        self.dist = dist   # [(score_int, count), ...]
        self.setMinimumHeight(len(dist) * 38 + 8)
        self.setStyleSheet("background:transparent;")

    def paintEvent(self, ev):
        if not self.dist:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        max_v   = max(c for _, c in self.dist)
        label_w = 120
        num_w   = 50
        bar_w   = self.width() - label_w - num_w - 16
        row_h   = 34

        font = QFont()
        font.setPointSize(10)
        p.setFont(font)

        for i, (score, count) in enumerate(self.dist):
            y   = i * row_h + 4
            col = QColor(self.COLORS.get(score, C_PURPLE))
            lbl = f"★ {score}  {self.LABELS.get(score, '')}"

            p.setPen(QPen(QColor(C_TEXT)))
            p.drawText(0, y, label_w, 22,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       lbl)

            p.setBrush(QBrush(QColor(C_BORDER)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(label_w, y + 4, bar_w, 14, 5, 5)

            fill_w = max(int((count / max_v) * bar_w), 6)
            p.setBrush(QBrush(col))
            p.drawRoundedRect(label_w, y + 4, fill_w, 14, 5, 5)

            p.setPen(QPen(QColor(C_TEXT)))
            small = QFont(); small.setPointSize(9)
            p.setFont(small)
            p.drawText(label_w + bar_w + 8, y, num_w, 22,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"{count}×")
            p.setFont(font)

        p.end()