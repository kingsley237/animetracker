"""
Miroku — Statistics Page  (Wrapped-style recap redesign)

This is a structural rebuild, not a style pass. The old page was a
uniform stack of identically-bordered dark cards (plus a literal
"4 tiles with a colored accent bar" hero-metric block — the generic
SaaS pattern). This one reads as a single narrative recap, closer to
a "Year in Review" than a dashboard:

  - An auto-generated recap sentence up top — real data woven into
    readable prose ("You've watched 92 episodes across 20 anime.
    June was your biggest month. Action is your most-watched genre.")
  - Each major section is its own tinted "slide" — a different accent
    color carries each one, instead of uniform neutral cards.
  - Favorite genres render as a ranked, medal-style list instead of
    plain bars.
  - Two new breakdowns that didn't exist before: by decade and by
    studio — using data (season_year, studios) that was already being
    collected but never surfaced.

Sections
--------
1. Recap headline
2. Activity heatmap  (HeatmapSection, unchanged)
3. Overview stat strip
4. Library breakdown (donut) + Favorite genres (ranked list)
5. Decade breakdown + Studio breakdown  (NEW)
6. Rating distribution
"""
import calendar
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from core.database import DatabaseManager
from ui.heatmap_widget import HeatmapSection
from ui.stat_strip import StatStrip

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
C_BORDER = "#1a1d28"

_GENRE_COLORS  = [C_PURPLE, C_GREEN, C_AMBER, C_RED,
                  C_BLUE, C_ORANGE, C_TEAL, C_PINK]
_RATING_LABELS = {1:"Terrible", 2:"Bad", 3:"Fair",
                  4:"Good", 5:"Great", 6:"Masterpiece"}
_RATING_COLORS = {1:C_RED, 2:C_ORANGE, 3:C_AMBER,
                  4:C_GREEN, 5:C_PURPLE, 6:C_TEAL}
_MEDALS = ["🥇", "🥈", "🥉"]


def _slide(accent: str, radius: int = 18) -> Tuple[QFrame, QVBoxLayout]:
    """A tinted 'slide' container — one accent color carries the whole
    section, instead of a uniform neutral card repeated everywhere."""
    f = QFrame()
    f.setObjectName("statsSlide")
    rgb = QColor(accent).getRgb()[:3]
    f.setStyleSheet(
        f"QFrame#statsSlide{{background-color:rgba{rgb + (16,)};"
        f"border:1px solid rgba{rgb + (55,)};border-radius:{radius}px;}}"
    )
    f.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(30, 26, 30, 28)
    lay.setSpacing(0)
    return f, lay


def _card_title(text: str, color: str = C_TEXT) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(
        f"font-size:14px;font-weight:700;color:{color};background:transparent;"
    )
    return l


def _bar_row(label: str, value: int, max_value: int, color: str,
             count_suffix: str = "") -> QWidget:
    """Shared row builder — used by Genres, Decades, Studios, Ratings so
    every breakdown in the page carries identical spacing and rhythm."""
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(7)

    top = QHBoxLayout()
    top.setContentsMargins(0, 0, 0, 0)
    top.setSpacing(8)
    l = QLabel(label)
    l.setStyleSheet(f"font-size:13px;color:{C_TEXT};background:transparent;")
    top.addWidget(l)
    top.addStretch()
    c = QLabel(f"{value}{count_suffix}")
    c.setStyleSheet(f"font-size:13px;font-weight:700;color:{color};background:transparent;")
    top.addWidget(c)
    lay.addLayout(top)

    bar = QProgressBar()
    bar.setMaximum(max(max_value, 1))
    bar.setValue(value)
    bar.setTextVisible(False)
    bar.setFixedHeight(7)
    bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    bar.setStyleSheet(
        f"QProgressBar{{background:{C_BORDER};border:none;border-radius:3px;}}"
        f"QProgressBar::chunk{{background:{color};border-radius:3px;}}"
    )
    lay.addWidget(bar)
    return w


# ── Donut ──────────────────────────────────────────────────────────────────────

class _DonutWidget(QWidget):
    SIZE, STROKE, GAP = 200, 20, 4

    def __init__(self, data: List[Tuple[str, int, str]], parent=None) -> None:
        super().__init__(parent)
        self._data  = [(l, v, c) for l, v, c in data if v > 0]
        self._total = sum(v for _, v, _ in self._data)
        self.setFixedSize(self.SIZE, self.SIZE)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        half = self.STROKE // 2 + 2
        size = self.SIZE - half * 2
        rect = QRectF(half, half, size, size)

        bg = QPen(QColor(C_BORDER))
        bg.setWidth(self.STROKE)
        bg.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(bg)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)

        if not self._data or self._total == 0:
            p.end()
            return

        n_gaps    = len(self._data)
        available = (360 * 16) - (self.GAP * n_gaps * 16)
        angle     = 90 * 16
        seg = QPen(); seg.setWidth(self.STROKE); seg.setCapStyle(Qt.PenCapStyle.FlatCap)
        for _, value, color in self._data:
            span = max(round((value / self._total) * available), 1)
            seg.setColor(QColor(color))
            p.setPen(seg)
            p.drawArc(rect, angle, -span)
            angle -= span + self.GAP * 16

        p.setPen(QPen(QColor(C_TEXT)))
        f = QFont(); f.setPointSize(22); f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(QRectF(half, half + size * 0.22, size, size * 0.38),
                   Qt.AlignmentFlag.AlignCenter, str(self._total))

        p.setPen(QPen(QColor(C_DIM)))
        f2 = QFont(); f2.setPointSize(8)
        p.setFont(f2)
        p.drawText(QRectF(half, half + size * 0.60, size, size * 0.22),
                   Qt.AlignmentFlag.AlignCenter, "in library")
        p.end()


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
        self._body_lay.setSpacing(24)

        scroll.setWidget(self._body)
        root.addWidget(scroll)

    def load(self) -> None:
        while self._body_lay.count():
            item = self._body_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._render(self.db.get_stats())

    def _render(self, s: Dict) -> None:
        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel("Statistics")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        sub = QLabel("A look back at what you've watched, rated, and binged.")
        sub.setObjectName("pageSubtitle")
        header.addWidget(sub)
        header_w = QWidget()
        header_w.setStyleSheet("background:transparent;")
        header_w.setLayout(header)
        self._body_lay.addWidget(header_w)

        best_month_name, best_month_count = self._best_month()
        self._body_lay.addWidget(self._make_recap_slide(s, best_month_name, best_month_count))

        activity_slide, activity_lay = _slide(C_TEAL)
        activity_lay.addWidget(_card_title("Watch activity", C_TEAL))
        activity_lay.addSpacing(18)
        activity_lay.addWidget(HeatmapSection(self.db))
        self._body_lay.addWidget(activity_slide)

        self._body_lay.addWidget(self._make_overview_strip(s))

        status_data: List[Tuple[str, int, str]] = [
            ("Watching",      s.get("watching",  0), C_PURPLE),
            ("Completed",     s.get("completed", 0), C_GREEN),
            ("Plan to Watch", s.get("planned",   0), C_GREY),
            ("Dropped",       s.get("dropped",   0), C_RED),
        ]
        mid = QHBoxLayout()
        mid.setSpacing(20)
        mid.setContentsMargins(0, 0, 0, 0)
        mid.addWidget(self._make_library_slide(status_data), stretch=1)
        top_genres = s.get("top_genres", [])
        if top_genres:
            mid.addWidget(self._make_genres_slide(top_genres), stretch=1)
        mid_w = QWidget()
        mid_w.setStyleSheet("background:transparent;")
        mid_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        mid_w.setLayout(mid)
        self._body_lay.addWidget(mid_w)

        decades = self.db.get_decade_breakdown()
        top_studios = s.get("top_studios", [])
        if decades or top_studios:
            low = QHBoxLayout()
            low.setSpacing(20)
            low.setContentsMargins(0, 0, 0, 0)
            if decades:
                low.addWidget(self._make_decades_slide(decades), stretch=1)
            if top_studios:
                low.addWidget(self._make_studios_slide(top_studios), stretch=1)
            low_w = QWidget()
            low_w.setStyleSheet("background:transparent;")
            low_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            low_w.setLayout(low)
            self._body_lay.addWidget(low_w)

        dist = self._rating_dist()
        if dist:
            self._body_lay.addWidget(self._make_ratings_slide(dist))

        self._body_lay.addStretch(1)

    # ── Recap ──────────────────────────────────────────────────────────────────

    def _make_recap_slide(self, s: Dict, best_month_name: Optional[str],
                          best_month_count: int) -> QFrame:
        f = QFrame()
        f.setObjectName("statsRecapSlide")
        f.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay = QVBoxLayout(f)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(10)

        lay.addWidget(_card_title("Your recap", C_PURPLE))
        lay.addSpacing(8)

        recap = QLabel(self._build_recap_html(s, best_month_name, best_month_count))
        recap.setObjectName("recapHeadline")
        recap.setWordWrap(True)
        lay.addWidget(recap)
        return f

    def _build_recap_html(self, s: Dict, best_month_name: Optional[str],
                          best_month_count: int) -> str:
        watched = s.get("total_episodes_watched", 0)
        total   = s.get("total", 0)
        avg     = s.get("average_score")
        top_genres = s.get("top_genres") or []
        top_genre  = top_genres[0][0] if top_genres else None

        parts: List[str] = []
        if watched:
            parts.append(
                f"You've watched <b style='color:{C_PURPLE};'>{watched} episodes</b> "
                f"across <b style='color:{C_TEXT};'>{total} anime</b>."
            )
        else:
            parts.append(f"You're tracking <b style='color:{C_TEXT};'>{total} anime</b> so far.")

        if best_month_name and best_month_count:
            parts.append(
                f"<b style='color:{C_GREEN};'>{best_month_name}</b> was your biggest month "
                f"this year with <b style='color:{C_TEXT};'>{best_month_count} episodes</b>."
            )
        if top_genre:
            parts.append(
                f"<b style='color:{C_AMBER};'>{top_genre}</b> is your most-watched genre."
            )
        if avg:
            parts.append(
                f"Your average rating sits at <b style='color:{C_PINK};'>{avg:.1f} / 6</b>."
            )
        return "&nbsp; ".join(parts)

    def _best_month(self) -> Tuple[Optional[str], int]:
        now = datetime.now()
        try:
            rows = self.db.get_watch_log_year(now.year)
        except Exception:
            return None, 0
        counts: Dict[int, int] = {}
        for r in rows:
            m = datetime.fromtimestamp(r["watched_at"]).month
            counts[m] = counts.get(m, 0) + 1
        if not counts:
            return None, 0
        best = max(counts, key=counts.get)
        return calendar.month_name[best], counts[best]

    # ── Overview strip ───────────────────────────────────────────────────────

    def _make_overview_strip(self, s: Dict) -> StatStrip:
        watched  = s.get("total_episodes_watched", 0)
        mins     = watched * 24
        days     = mins // 1440
        rem_h    = (mins % 1440) // 60
        time_str = (f"{days}d {rem_h}h" if days > 0
                    else f"{mins // 60}h {mins % 60}m" if mins >= 60
                    else f"{mins}m")
        avg = s.get("average_score")
        this_month = self._episodes_this_month()
        trend = f"+{this_month} this month" if this_month else None

        items = [
            (str(watched),                     "Episodes watched", trend),
            (str(s.get("completed", 0)),       "Completed",        None),
            (f"{avg:.1f} / 6" if avg else "—", "Avg. your rating", None),
            (time_str if watched else "—",     "Time invested",    None),
        ]
        return StatStrip(items)

    def _episodes_this_month(self) -> int:
        now = datetime.now()
        try:
            rows = self.db.get_watch_log_year(now.year)
        except Exception:
            return 0
        return sum(
            1 for r in rows
            if datetime.fromtimestamp(r["watched_at"]).month == now.month
        )

    # ── Library breakdown ────────────────────────────────────────────────────

    def _make_library_slide(self, data: List[Tuple[str, int, str]]) -> QFrame:
        f, lay = _slide(C_GREEN)
        total = sum(v for _, v, _ in data) or 1

        lay.addWidget(_card_title("Library breakdown", C_GREEN))
        lay.addSpacing(20)
        lay.addWidget(_DonutWidget(data), alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(24)

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
            pct = round((value / total) * 100)
            cnt = QLabel(f"{value}  ·  {pct}%")
            cnt.setStyleSheet(f"font-size:13px;font-weight:700;color:{color};background:transparent;")
            cnt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(cnt)
            lay.addLayout(row)
            lay.addSpacing(14)
        return f

    # ── Favorite genres — ranked / medal list ────────────────────────────────

    def _make_genres_slide(self, genres: List[Tuple[str, int]]) -> QFrame:
        f, lay = _slide(C_AMBER)
        lay.addWidget(_card_title("Favorite genres", C_AMBER))
        lay.addSpacing(20)

        top8  = genres[:8]
        max_c = max((c for _, c in top8), default=1)

        for i, (genre, count) in enumerate(top8):
            color = _GENRE_COLORS[i % len(_GENRE_COLORS)]
            row = QHBoxLayout()
            row.setSpacing(12)

            rank_lbl = QLabel(_MEDALS[i] if i < 3 else f"#{i + 1}")
            rank_lbl.setFixedWidth(28)
            rank_lbl.setStyleSheet(
                f"font-size:{'17px' if i < 3 else '13px'};"
                f"background:transparent;color:{C_DIM if i >= 3 else C_TEXT};"
            )
            row.addWidget(rank_lbl)

            name_lbl = QLabel(genre)
            name_lbl.setStyleSheet(
                f"font-size:{'16px' if i == 0 else '13px'};"
                f"font-weight:{'800' if i == 0 else '500'};"
                f"color:{C_TEXT};background:transparent;"
            )
            row.addWidget(name_lbl, 1)

            count_lbl = QLabel(str(count))
            count_lbl.setStyleSheet(
                f"font-size:13px;font-weight:700;color:{color};background:transparent;"
            )
            row.addWidget(count_lbl)
            lay.addLayout(row)
            lay.addSpacing(6)

            bar = QProgressBar()
            bar.setMaximum(max_c)
            bar.setValue(count)
            bar.setTextVisible(False)
            bar.setFixedHeight(6)
            bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            bar.setStyleSheet(
                f"QProgressBar{{background:{C_BORDER};border:none;border-radius:3px;}}"
                f"QProgressBar::chunk{{background:{color};border-radius:3px;}}"
            )
            lay.addWidget(bar)
            if i < len(top8) - 1:
                lay.addSpacing(16)
        return f

    # ── Decade breakdown (NEW) ───────────────────────────────────────────────

    def _make_decades_slide(self, decades: List[Tuple[int, int]]) -> QFrame:
        f, lay = _slide(C_BLUE)
        lay.addWidget(_card_title("By decade", C_BLUE))
        lay.addSpacing(20)

        max_c = max((c for _, c in decades), default=1)
        for i, (decade, count) in enumerate(decades):
            lay.addWidget(_bar_row(f"{decade}s", count, max_c, C_BLUE))
            if i < len(decades) - 1:
                lay.addSpacing(16)
        return f

    # ── Studio breakdown (NEW) ───────────────────────────────────────────────

    def _make_studios_slide(self, studios: List[Tuple[str, int]]) -> QFrame:
        f, lay = _slide(C_PINK)
        lay.addWidget(_card_title("Top studios", C_PINK))
        lay.addSpacing(20)

        top8  = studios[:8]
        max_c = max((c for _, c in top8), default=1)
        for i, (studio, count) in enumerate(top8):
            lay.addWidget(_bar_row(studio, count, max_c, C_PINK))
            if i < len(top8) - 1:
                lay.addSpacing(14)
        return f

    # ── Ratings ───────────────────────────────────────────────────────────────

    def _make_ratings_slide(self, dist: List[Tuple[int, int]]) -> QFrame:
        f, lay = _slide(C_PURPLE)
        lay.addWidget(_card_title("Your ratings", C_PURPLE))
        lay.addSpacing(20)

        ordered = sorted(dist, key=lambda x: x[0], reverse=True)
        max_c   = max((c for _, c in ordered), default=1)
        for i, (score, count) in enumerate(ordered):
            color = _RATING_COLORS.get(score, C_PURPLE)
            ltext = _RATING_LABELS.get(score, "")
            lay.addWidget(_bar_row(f"★ {score}   {ltext}", count, max_c, color, count_suffix="×"))
            if i < len(ordered) - 1:
                lay.addSpacing(16)
        return f

    def _rating_dist(self) -> List[Tuple[int, int]]:
        conn = self.db._get_conn()
        rows = conn.execute(
            "SELECT CAST(ROUND(score) AS INTEGER) AS s, COUNT(*) AS c "
            "FROM ratings GROUP BY s ORDER BY s DESC"
        ).fetchall()
        return [(r[0], r[1]) for r in rows if r[0] and 1 <= r[0] <= 6]
