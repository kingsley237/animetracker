"""
Miroku — Hall of Fame  (Gallery / Cinematic redesign)

This is a structural rebuild, not a style pass. The old page was a
vertical list of cards; this one is a media gallery:

  - A cinematic hero zone up top: a blurred, scrim-darkened backdrop of
    your Champion's banner art, with the page header, clickable tier
    filter chips, and the Champion's own info sitting directly on it —
    like a streaming service's featured banner, not a stat block.
  - Tiers render as horizontal-scrolling poster Shelves (Netflix-row
    style) instead of stacked rows. A Wall view (dense poster grid) is
    the alternative for browsing everything at once.
  - Clicking any poster opens a full-screen cinematic Detail Overlay —
    its own blurred backdrop, inline note editing, and ‹ › arrows (or
    Left/Right arrow keys) to browse straight through your whole
    collection without closing it.
  - "Surprise Me" jumps the overlay to a random pick from your
    collection — a small delight feature, not just a utility.

Everything else (tiers, manual reordering, notes, trailers, PNG
export) still works — it just now lives inside the overlay instead of
being crammed onto every row.

DB note
-------
The `hall_of_fame` table gains a `tier` TEXT column (NULL = untiered).
Migration runs safely on first load via ALTER TABLE … ADD COLUMN IF NOT EXISTS.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QRectF, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QKeyEvent, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame,
    QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QStackedLayout, QTextEdit, QVBoxLayout, QWidget,
)

from core.database import DatabaseManager
from workers.workers import ImageWorker, Worker, run_worker

# ── Tier definitions ───────────────────────────────────────────────────────────
TIERS: List[Tuple[str, str, str]] = [
    ("S", "All-Time Greats",   "#fbbf24"),   # gold
    ("A", "Exceptional",       "#a594f9"),   # purple
    ("B", "Really Good",       "#34d399"),   # green
    ("C", "Good",              "#38bdf8"),   # blue
    ("D", "Worth Watching",    "#9da5c0"),   # grey
]
TIER_KEYS   = [t[0] for t in TIERS]
TIER_COLORS = {t[0]: t[2] for t in TIERS}
TIER_LABELS = {t[0]: t[1] for t in TIERS}

CHAMPION_FALLBACK_COLOR = "#fbbf24"
NEUTRAL_RANK_COLOR = "#9da5c0"

HERO_HEIGHT = 460


# ── Shared pixmap helpers ───────────────────────────────────────────────────────

def _rounded_scaled_pixmap(path: str, w: int, h: int, radius: int = 8,
                            ring_color: Optional[str] = None) -> Optional[QPixmap]:
    """Cover-fit crop + rounded corners, with an optional tier-colored
    ring — the same treatment applied to every cover surface in the
    page (champion, posters, overlay) so they read as one component
    family instead of each inventing its own border style."""
    px = QPixmap(path)
    if px.isNull():
        return None
    px = px.scaled(
        w, h,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    cx = (px.width() - w) // 2
    cy = (px.height() - h) // 2
    px = px.copy(cx, cy, w, h)
    rounded = QPixmap(w, h)
    rounded.fill(QColor(0, 0, 0, 0))
    pt = QPainter(rounded)
    pt.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(0.0, 0.0, float(w), float(h), radius, radius)
    pt.setClipPath(clip)
    pt.drawPixmap(0, 0, px)
    pt.end()

    if ring_color:
        pt2 = QPainter(rounded)
        pt2.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(ring_color))
        pen.setWidthF(2.4)
        pt2.setPen(pen)
        pt2.setBrush(Qt.BrushStyle.NoBrush)
        inset = 1.2
        ring = QPainterPath()
        ring.addRoundedRect(
            QRectF(inset, inset, w - inset * 2, h - inset * 2), radius - 1, radius - 1
        )
        pt2.drawPath(ring)
        pt2.end()
    return rounded


def _backdrop_pixmap(path: str, w: int, h: int, blur_radius: int = 36) -> Optional[QPixmap]:
    """Cover-fit crop + blur + dark scrim, all baked into one static
    pixmap. Baking the blur via an offscreen QGraphicsScene (instead of
    a live QGraphicsBlurEffect left attached to a widget) avoids a real
    z-order bug: a blurred widget's effect compositing does not reliably
    respect sibling stacking order inside a QStackedLayout, so foreground
    text ended up rendered *behind* the "blurred" image. A plain QLabel
    showing an already-composited pixmap has no such ambiguity."""
    src = QPixmap(path)
    if src.isNull() or w <= 0 or h <= 0:
        return None

    scaled = src.scaled(
        w, h,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    cx = (scaled.width() - w) // 2
    cy = (scaled.height() - h) // 2
    cropped = scaled.copy(cx, cy, w, h)

    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(cropped)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(blur_radius)
    item.setGraphicsEffect(effect)
    scene.addItem(item)

    result = QPixmap(w, h)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scene.render(painter, QRectF(0, 0, w, h), QRectF(0, 0, w, h))

    grad = QLinearGradient(0, 0, 0, h)
    grad.setColorAt(0.0, QColor(10, 12, 18, 210))
    grad.setColorAt(1.0, QColor(10, 12, 18, 248))
    painter.fillRect(0, 0, w, h, grad)
    painter.end()
    return result


class _FullBleedContainer(QWidget):
    """A container whose direct children are each resized to fill it,
    in insertion order — later children paint on top. Used for the
    backdrop image + foreground content in the hero zone and overlay
    banner, using plain sibling z-order (no QStackedLayout)."""

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        for child in self.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            child.setGeometry(0, 0, self.width(), self.height())


def _meta_line_html(entry: Dict, db: DatabaseManager) -> str:
    """One merged, color-coded line: your score · AniList score · year · eps."""
    parts: List[str] = []
    avg = db.get_average_rating(entry["id"])
    if avg is not None:
        parts.append(f"<span style='color:#fbbf24;font-weight:700;'>★ {avg:.1f}</span>")
    sc = entry.get("average_score")
    if sc:
        parts.append(f"<span style='color:#a594f9;'>AL {sc / 10:.1f}</span>")
    bits = []
    yr = entry.get("season_year")
    if yr:
        bits.append(str(yr))
    eps = entry.get("total_episodes")
    if eps:
        bits.append(f"{eps} eps")
    if bits:
        parts.append(f"<span style='color:#9da5c0;'>{' · '.join(bits)}</span>")
    return "&nbsp;&nbsp;·&nbsp;&nbsp;".join(parts)


def _genre_chip_row(genres: List[str], cap: int = 4) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(6)
    shown = genres[:cap]
    overflow = len(genres) - len(shown)
    for g in shown:
        chip = QLabel(g)
        chip.setStyleSheet(
            "background:rgba(124,106,247,26);color:#c4b8ff;"
            "border:1px solid #4b3fa855;border-radius:8px;"
            "font-size:10px;padding:2px 8px;"
        )
        row.addWidget(chip)
    if overflow > 0:
        more = QLabel(f"+{overflow}")
        more.setStyleSheet(
            "background:transparent;color:#6b7280;font-size:10px;padding:2px 4px;"
        )
        row.addWidget(more)
    row.addStretch()
    return row


def _toolbar_btn(text: str, obj: str) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName(obj)
    b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    b.setFixedHeight(34)
    return b


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _migrate(db: DatabaseManager) -> None:
    """Ensure hall_of_fame table exists with tier column."""
    conn = db._get_conn()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS hall_of_fame "
        "(rank INTEGER PRIMARY KEY, anime_id INTEGER UNIQUE, "
        " note TEXT, tier TEXT, added_at INTEGER)"
    )
    try:
        conn.execute("ALTER TABLE hall_of_fame ADD COLUMN tier TEXT")
    except Exception:
        pass
    conn.commit()


def _load_hof(db: DatabaseManager) -> List[Dict]:
    _migrate(db)
    conn = db._get_conn()
    rows = conn.execute(
        "SELECT h.rank, h.note, h.tier, h.added_at, a.* "
        "FROM hall_of_fame h JOIN anime a ON h.anime_id = a.id "
        "ORDER BY h.rank"
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for k in ("genres", "studios"):
            if isinstance(d.get(k), str):
                try:
                    d[k] = json.loads(d[k])
                except Exception:
                    d[k] = []
        result.append(d)
    return result


def _save_hof_order(db: DatabaseManager, ordered_ids: List[int]) -> None:
    conn = db._get_conn()
    for rank, aid in enumerate(ordered_ids, 1):
        conn.execute(
            "UPDATE hall_of_fame SET rank=? WHERE anime_id=?", (rank, aid)
        )
    conn.commit()


def _add_to_hof(db: DatabaseManager, anime_id: int,
                note: str = "", tier: str = "") -> None:
    _migrate(db)
    conn = db._get_conn()
    max_rank = conn.execute(
        "SELECT MAX(rank) FROM hall_of_fame"
    ).fetchone()[0] or 0
    conn.execute(
        "INSERT OR IGNORE INTO hall_of_fame "
        "(rank, anime_id, note, tier, added_at) VALUES (?,?,?,?,?)",
        (max_rank + 1, anime_id, note, tier,
         int(datetime.now(timezone.utc).timestamp())),
    )
    conn.commit()


def _remove_from_hof(db: DatabaseManager, anime_id: int) -> None:
    conn = db._get_conn()
    conn.execute("DELETE FROM hall_of_fame WHERE anime_id=?", (anime_id,))
    conn.commit()


def _update_hof_note(db: DatabaseManager, anime_id: int, note: str) -> None:
    conn = db._get_conn()
    conn.execute(
        "UPDATE hall_of_fame SET note=? WHERE anime_id=?", (note, anime_id)
    )
    conn.commit()


def _update_hof_tier(db: DatabaseManager, anime_id: int, tier: str) -> None:
    conn = db._get_conn()
    conn.execute(
        "UPDATE hall_of_fame SET tier=? WHERE anime_id=?", (tier, anime_id)
    )
    conn.commit()


def _in_hof(db: DatabaseManager, anime_id: int) -> bool:
    conn = db._get_conn()
    r = conn.execute(
        "SELECT 1 FROM hall_of_fame WHERE anime_id=?", (anime_id,)
    ).fetchone()
    return bool(r)


def add_anilist_media_to_hof(
    db: DatabaseManager, media: Dict
) -> Tuple[bool, str]:
    from core.api import format_air_date

    anilist_id = media.get("id")
    if anilist_id:
        existing = db.get_anime_by_anilist_id(anilist_id)
        if existing:
            if _in_hof(db, existing["id"]):
                return False, "already_in_hof"
            _add_to_hof(db, existing["id"])
            return True, existing.get("romaji_title", "Anime")

    t   = media.get("title", {})
    cov = media.get("coverImage") or {}
    sd  = media.get("startDate") or {}
    nae = media.get("nextAiringEpisode") or {}
    api_s = (media.get("status") or "").upper()
    ws = (
        "completed"  if api_s == "FINISHED"
        else "planned" if api_s == "NOT_YET_RELEASED"
        else "watching"
    )
    new_id = db.add_anime({
        "hof_only":      1,
        "anilist_id":    media.get("id"),
        "romaji_title":  t.get("romaji", "Unknown"),
        "english_title": t.get("english") or "",
        "watch_status":  ws,
        "status":        media.get("status", ""),
        "cover_url":     cov.get("large") or cov.get("medium") or "",
        "banner_url":    media.get("bannerImage") or "",
        "description":   media.get("description") or "",
        "genres":        media.get("genres") or [],
        "studios":       [
            s["name"]
            for s in (media.get("studios", {}).get("nodes") or [])
        ],
        "total_episodes":  media.get("episodes"),
        "season":          media.get("season") or "",
        "season_year":     media.get("seasonYear"),
        "average_score":   media.get("averageScore"),
        "trailer_id":      (media.get("trailer") or {}).get("id"),
        "trailer_site":    (media.get("trailer") or {}).get("site"),
        "start_date":      format_air_date(sd),
        "next_episode_at": nae.get("airingAt"),
        "next_episode_num": nae.get("episode"),
    })
    _add_to_hof(db, new_id)
    return True, t.get("romaji", "Anime")


# ── Elevated card (soft self-painted shadow, used by Wall view) ───────────────

class _ElevatedCard(QWidget):
    """Wraps a card widget in a self-painted soft shadow.

    QGraphicsDropShadowEffect paints outside the source widget's own
    geometry, and inside a scrolling layout that overflow gets clipped
    unpredictably by neighboring widgets. Reserving the shadow's margin
    inside *this* widget's own layout margins keeps the effect
    self-contained so it can never be clipped by a sibling.
    """

    def __init__(
        self, inner: QWidget, radius: int = 12, margin: int = 14,
        strength: int = 110, color: str = "#000000", parent=None,
    ) -> None:
        super().__init__(parent)
        self._inner    = inner
        self._radius   = radius
        self._margin   = margin
        self._strength = strength
        self._color    = QColor(color)
        self.setSizePolicy(inner.sizePolicy())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(margin, margin - 5, margin, margin + 7)
        lay.addWidget(inner)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._inner.geometry()
        steps = 6
        for i in range(steps, 0, -1):
            t = i / steps
            grow  = self._margin * t
            alpha = max(1, int(self._strength * (1 - t) ** 2 / steps))
            c = QColor(self._color)
            c.setAlpha(min(255, alpha))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            rr = QRectF(r).adjusted(-grow * 0.6, -grow * 0.25, grow * 0.6, grow * 1.15)
            path = QPainterPath()
            path.addRoundedRect(
                rr, self._radius + grow * 0.35, self._radius + grow * 0.35
            )
            p.drawPath(path)
        p.end()
        super().paintEvent(ev)


# ── Poster card (shared by Shelves and Wall view) ──────────────────────────────

class _PosterCard(QFrame):
    """Cover-forward poster. Cover art, bottom gradient, tier ring, tier
    badge, title, and score are all baked together into one
    QPainter-composed pixmap — one rendering path instead of stacking
    separate QLabel overlays on top of a QLabel cover, which is what
    silently clipped the tier-letter text before. The tier ring matches
    the Champion and overlay cover treatment, so every cover surface on
    the page reads as the same component."""

    clicked = pyqtSignal(int)

    CARD_W = 156
    CARD_H = 226
    RADIUS = 12

    def __init__(self, entry: Dict, db: DatabaseManager, parent=None) -> None:
        super().__init__(parent)
        self._aid   = entry["id"]
        self._entry = entry
        self.setObjectName("hofPosterCard")
        self.setFixedSize(self.CARD_W, self.CARD_H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self._cover_lbl = QLabel(self)
        self._cover_lbl.setFixedSize(self.CARD_W, self.CARD_H)
        self._cover_lbl.setStyleSheet("background:transparent;")
        self._compose(None)

    def _compose(self, cover_px: Optional[QPixmap]) -> None:
        tier  = (self._entry.get("tier") or "").strip().upper()
        color = TIER_COLORS.get(tier)

        canvas = QPixmap(self.CARD_W, self.CARD_H)
        canvas.fill(QColor(0, 0, 0, 0))
        p = QPainter(canvas)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(0.0, 0.0, float(self.CARD_W), float(self.CARD_H),
                            self.RADIUS, self.RADIUS)
        p.setClipPath(clip)

        if cover_px is not None:
            p.drawPixmap(0, 0, cover_px)
        else:
            p.fillRect(0, 0, self.CARD_W, self.CARD_H, QColor("#111420"))

        grad = QLinearGradient(0, self.CARD_H - 86, 0, self.CARD_H)
        grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        grad.setColorAt(1.0, QColor(0, 0, 0, 245))
        p.fillRect(0, self.CARD_H - 86, self.CARD_W, 86, grad)

        if color:
            badge_w, badge_h = 25, 22
            bx, by = self.CARD_W - badge_w - 8, 8
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            badge_path = QPainterPath()
            badge_path.addRoundedRect(bx, by, badge_w, badge_h, 5, 5)
            p.drawPath(badge_path)
            p.setPen(QColor("#0d0f14"))
            f = QFont()
            f.setPointSize(10)
            f.setWeight(QFont.Weight.Black)
            p.setFont(f)
            p.drawText(QRectF(bx, by, badge_w, badge_h),
                       Qt.AlignmentFlag.AlignCenter, tier)

        title = self._entry.get("english_title") or self._entry.get("romaji_title", "")
        p.setPen(QColor("#f5f6ff"))
        f2 = QFont()
        f2.setPointSize(9)
        f2.setWeight(QFont.Weight.Bold)
        p.setFont(f2)
        title_rect = QRectF(10, self.CARD_H - 64, self.CARD_W - 20, 36)
        p.drawText(title_rect, int(Qt.TextFlag.TextWordWrap) | Qt.AlignmentFlag.AlignLeft,
                   title[:36])

        sc = self._entry.get("average_score")
        if sc:
            p.setPen(QColor("#a594f9"))
            f3 = QFont()
            f3.setPointSize(8)
            f3.setWeight(QFont.Weight.DemiBold)
            p.setFont(f3)
            p.drawText(QRectF(10, self.CARD_H - 24, self.CARD_W - 20, 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"★ {sc / 10:.1f}")
        p.end()

        if color:
            p2 = QPainter(canvas)
            p2.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(color))
            pen.setWidthF(2.4)
            p2.setPen(pen)
            p2.setBrush(Qt.BrushStyle.NoBrush)
            inset = 1.2
            ring = QPainterPath()
            ring.addRoundedRect(
                QRectF(inset, inset, self.CARD_W - inset * 2, self.CARD_H - inset * 2),
                self.RADIUS - 1, self.RADIUS - 1,
            )
            p2.drawPath(ring)
            p2.end()

        self._cover_lbl.setPixmap(canvas)

    def set_cover(self, path: str) -> None:
        if not path:
            return
        px = QPixmap(path)
        if px.isNull():
            return
        px = px.scaled(
            self.CARD_W, self.CARD_H,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        cx = (px.width() - self.CARD_W) // 2
        cy = (px.height() - self.CARD_H) // 2
        px = px.copy(cx, cy, self.CARD_W, self.CARD_H)
        self._compose(px)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._aid)
        super().mousePressEvent(ev)


# ── Shelf (horizontal-scrolling poster row) ────────────────────────────────────

class _Shelf(QWidget):
    """A tier's posters as a horizontal-scrolling shelf, with ‹ › nav
    buttons paging the scroll area. `cards` exposes (entry, card) pairs
    so the page can drive image loading."""

    poster_clicked = pyqtSignal(int)

    def __init__(self, entries: List[Dict], db: DatabaseManager, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        self.cards: List[Tuple[Dict, _PosterCard]] = []

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        prev_btn = QPushButton("‹")
        prev_btn.setObjectName("shelfNavBtn")
        prev_btn.setFixedSize(32, 32)
        prev_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        prev_btn.clicked.connect(lambda: self._page(-1))
        lay.addWidget(prev_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("hofShelfScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setFixedHeight(_PosterCard.CARD_H + 34)

        inner = QWidget()
        inner.setStyleSheet("background:transparent;")
        inner_lay = QHBoxLayout(inner)
        inner_lay.setContentsMargins(10, 10, 10, 20)
        inner_lay.setSpacing(16)
        for entry in entries:
            tier_val = (entry.get("tier") or "").strip().upper()
            card = _PosterCard(entry, db)
            card.clicked.connect(self.poster_clicked.emit)
            shadow_color = TIER_COLORS.get(tier_val, "#000000")
            wrapped = _ElevatedCard(
                card, radius=_PosterCard.RADIUS, margin=9,
                strength=45 if tier_val in TIER_COLORS else 60,
                color=shadow_color,
            )
            inner_lay.addWidget(wrapped)
            self.cards.append((entry, card))
        inner_lay.addStretch()
        self._scroll.setWidget(inner)
        lay.addWidget(self._scroll, 1)

        next_btn = QPushButton("›")
        next_btn.setObjectName("shelfNavBtn")
        next_btn.setFixedSize(32, 32)
        next_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        next_btn.clicked.connect(lambda: self._page(1))
        lay.addWidget(next_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def _page(self, direction: int) -> None:
        bar = self._scroll.horizontalScrollBar()
        bar.setValue(bar.value() + direction * 500)


# ── Cinematic detail overlay ────────────────────────────────────────────────────

class _DetailOverlay(QWidget):
    """Full-window overlay opened from any poster. Its own blurred
    backdrop, inline note editing, and ‹ › / arrow-key navigation
    through the whole collection without closing."""

    closed             = pyqtSignal()
    remove_requested   = pyqtSignal(int)
    note_edited        = pyqtSignal(int, str)
    tier_changed       = pyqtSignal(int, str)
    trailer_requested  = pyqtSignal(str, str)
    move_up_requested  = pyqtSignal(int)
    move_down_requested = pyqtSignal(int)
    nav_requested      = pyqtSignal(int)   # -1 / +1

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("hofOverlayScrim")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._aid: Optional[int] = None
        self._entry: Dict = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(36, 36, 36, 36)
        outer.setSpacing(14)

        self._prev_btn = QPushButton("‹")
        self._prev_btn.setObjectName("overlayNavBtn")
        self._prev_btn.setFixedSize(44, 44)
        self._prev_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._prev_btn.clicked.connect(lambda: self.nav_requested.emit(-1))
        outer.addWidget(self._prev_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._panel = QFrame()
        self._panel.setObjectName("hofOverlayPanel")
        self._panel.setMaximumWidth(860)
        self._panel.setMinimumWidth(620)
        outer.addWidget(self._panel, 1)

        self._next_btn = QPushButton("›")
        self._next_btn.setObjectName("overlayNavBtn")
        self._next_btn.setFixedSize(44, 44)
        self._next_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._next_btn.clicked.connect(lambda: self.nav_requested.emit(1))
        outer.addWidget(self._next_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._panel_lay = QVBoxLayout(self._panel)
        self._panel_lay.setContentsMargins(0, 0, 0, 0)
        self._panel_lay.setSpacing(0)

        self._banner_lbl: Optional[QLabel] = None
        self._cover_lbl: Optional[QLabel] = None

    def mousePressEvent(self, ev) -> None:
        if not self._panel.geometry().contains(ev.pos()):
            self.closed.emit()
        super().mousePressEvent(ev)

    def keyPressEvent(self, ev: QKeyEvent) -> None:
        if ev.key() == Qt.Key.Key_Escape:
            self.closed.emit()
        elif ev.key() == Qt.Key.Key_Left:
            self.nav_requested.emit(-1)
        elif ev.key() == Qt.Key.Key_Right:
            self.nav_requested.emit(1)
        else:
            super().keyPressEvent(ev)

    def populate(self, entry: Dict, db: DatabaseManager) -> None:
        self._aid = entry["id"]
        self._entry = entry

        while self._panel_lay.count():
            item = self._panel_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # ── Mini banner strip (blurred backdrop + close button) ───────────
        banner_area = _FullBleedContainer()
        banner_area.setFixedHeight(150)

        self._banner_lbl = QLabel(banner_area)
        self._banner_lbl.setObjectName("hofBackdropImage")
        self._banner_lbl.setScaledContents(True)
        self._banner_lbl.setGeometry(0, 0, 1, 150)

        top_row_w = QWidget(banner_area)
        top_row_w.setStyleSheet("background:transparent;")
        top_row_w.setGeometry(0, 0, 1, 150)
        trl = QHBoxLayout(top_row_w)
        trl.setContentsMargins(18, 16, 18, 0)
        trl.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setObjectName("overlayCloseBtn")
        close_btn.setFixedSize(34, 34)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.clicked.connect(self.closed.emit)
        trl.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)

        self._panel_lay.addWidget(banner_area)

        # ── Scrollable body ────────────────────────────────────────────────
        body_scroll = QScrollArea()
        body_scroll.setWidgetResizable(True)
        body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body.setStyleSheet("background:transparent;")
        blay = QVBoxLayout(body)
        blay.setContentsMargins(30, 22, 30, 26)
        blay.setSpacing(14)

        top_row = QHBoxLayout()
        top_row.setSpacing(20)

        self._cover_lbl = QLabel()
        self._cover_lbl.setFixedSize(126, 182)
        self._cover_lbl.setStyleSheet("background:#1a1d28;border-radius:8px;")
        top_row.addWidget(self._cover_lbl, 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(8)

        tier_val = (entry.get("tier") or "").strip().upper()
        if tier_val in TIER_COLORS:
            badge_row = QHBoxLayout()
            badge_row.setSpacing(6)
            tb = QLabel(f" {tier_val} — {TIER_LABELS[tier_val]} ")
            tb.setStyleSheet(
                f"background:{TIER_COLORS[tier_val]};color:#0d0f14;"
                "font-size:11px;font-weight:900;border-radius:5px;padding:2px 6px;"
            )
            badge_row.addWidget(tb)
            badge_row.addStretch()
            info.addLayout(badge_row)

        title = entry.get("english_title") or entry.get("romaji_title", "")
        tl = QLabel(title)
        tl.setWordWrap(True)
        tl.setStyleSheet(
            "font-size:24px;font-weight:900;color:#f5f6ff;"
            "background:transparent;letter-spacing:-0.4px;"
        )
        info.addWidget(tl)

        meta_html = _meta_line_html(entry, db)
        if meta_html:
            ml = QLabel(meta_html)
            ml.setStyleSheet("font-size:13px;background:transparent;")
            info.addWidget(ml)

        info.addLayout(_genre_chip_row(entry.get("genres") or [], cap=6))
        info.addStretch()
        top_row.addLayout(info, 1)
        blay.addLayout(top_row)

        note_lbl = QLabel("Personal note")
        note_lbl.setStyleSheet(
            "font-size:11px;color:#6b7280;font-weight:700;"
            "letter-spacing:0.4px;background:transparent;"
        )
        blay.addWidget(note_lbl)

        self._note_edit = QTextEdit()
        self._note_edit.setPlaceholderText("What made this special for you?")
        self._note_edit.setPlainText(entry.get("note") or "")
        self._note_edit.setFixedHeight(72)
        blay.addWidget(self._note_edit)

        added = entry.get("added_at")
        if added:
            try:
                date_str = datetime.fromtimestamp(added).strftime(
                    "Added to Hall of Fame on %d %b %Y"
                )
                dl = QLabel(date_str)
                dl.setStyleSheet("font-size:11px;color:#4a5070;background:transparent;")
                blay.addWidget(dl)
            except Exception:
                pass

        # ── Actions ─────────────────────────────────────────────────────────
        actions = QHBoxLayout()
        actions.setSpacing(8)

        if entry.get("trailer_id"):
            t_btn = QPushButton("▶  Trailer")
            t_btn.setObjectName("secondaryBtn")
            t_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            t_btn.clicked.connect(
                lambda: self.trailer_requested.emit(
                    entry.get("trailer_id", ""), entry.get("trailer_site", "youtube")
                )
            )
            actions.addWidget(t_btn)

        up_btn = QPushButton("▲")
        up_btn.setObjectName("iconBtn")
        up_btn.setFixedSize(30, 30)
        up_btn.setToolTip("Move up")
        up_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        up_btn.clicked.connect(lambda: self.move_up_requested.emit(self._aid))
        actions.addWidget(up_btn)

        down_btn = QPushButton("▼")
        down_btn.setObjectName("iconBtn")
        down_btn.setFixedSize(30, 30)
        down_btn.setToolTip("Move down")
        down_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        down_btn.clicked.connect(lambda: self.move_down_requested.emit(self._aid))
        actions.addWidget(down_btn)

        tier_combo = QComboBox()
        tier_combo.setFixedWidth(150)
        tier_combo.addItem("No tier", "")
        for k, lbl, _ in TIERS:
            tier_combo.addItem(f"{k} — {lbl}", k)
        cur = (entry.get("tier") or "").strip().upper()
        for i in range(tier_combo.count()):
            if tier_combo.itemData(i) == cur:
                tier_combo.setCurrentIndex(i)
                break
        tier_combo.currentIndexChanged.connect(
            lambda idx, c=tier_combo: self.tier_changed.emit(self._aid, c.itemData(idx))
        )
        actions.addWidget(tier_combo)
        actions.addStretch()

        save_btn = QPushButton("Save Note")
        save_btn.setObjectName("secondaryBtn")
        save_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save_btn.clicked.connect(self._save_note)
        actions.addWidget(save_btn)

        rm_btn = QPushButton("Remove")
        rm_btn.setObjectName("dangerBtn")
        rm_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        rm_btn.clicked.connect(lambda: self.remove_requested.emit(self._aid))
        actions.addWidget(rm_btn)

        blay.addLayout(actions)
        blay.addStretch()

        body_scroll.setWidget(body)
        self._panel_lay.addWidget(body_scroll, 1)

    def _save_note(self) -> None:
        self.note_edited.emit(self._aid, self._note_edit.toPlainText().strip())

    def set_banner(self, path: str) -> None:
        if self._banner_lbl and path:
            px = _backdrop_pixmap(path, 900, 150)
            if px:
                self._banner_lbl.setPixmap(px)

    def set_cover(self, path: str) -> None:
        if self._cover_lbl and path:
            tier_val = (self._entry.get("tier") or "").strip().upper()
            px = _rounded_scaled_pixmap(path, 126, 182, ring_color=TIER_COLORS.get(tier_val))
            if px:
                self._cover_lbl.setPixmap(px)


# ── Main page ──────────────────────────────────────────────────────────────────

class HallOfFamePage(QWidget):
    """Hall of Fame — Gallery / Cinematic redesign."""

    def __init__(self, db: DatabaseManager, parent=None) -> None:
        super().__init__(parent)
        self.db         = db
        self._entries:  List[Dict] = []
        self._view_mode = "shelves"   # "shelves" | "wall"
        self._active_tier_filter: Optional[str] = None
        self._tier_pills: List[Tuple[QPushButton, str, str]] = []
        self._champion_id: Optional[int] = None
        self._overlay_order: List[Dict] = []
        self._overlay_index = 0
        self._build_ui()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._hero = self._build_hero_zone()
        root.addWidget(self._hero)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._content_w = QWidget()
        self._content_w.setStyleSheet("background:transparent;")
        self._content_lay = QVBoxLayout(self._content_w)
        self._content_lay.setContentsMargins(32, 26, 32, 48)
        self._content_lay.setSpacing(22)

        self.scroll.setWidget(self._content_w)
        root.addWidget(self.scroll, 1)

        self._overlay = _DetailOverlay(self)
        self._overlay.setVisible(False)
        self._overlay.closed.connect(self._close_overlay)
        self._overlay.remove_requested.connect(self._remove_from_overlay)
        self._overlay.note_edited.connect(self._edit_note)
        self._overlay.tier_changed.connect(self._change_tier)
        self._overlay.trailer_requested.connect(self._open_trailer)
        self._overlay.move_up_requested.connect(self._move_up)
        self._overlay.move_down_requested.connect(self._move_down)
        self._overlay.nav_requested.connect(self._overlay_navigate)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        if self._overlay.isVisible():
            self._overlay.setGeometry(self.rect())

    def _build_hero_zone(self) -> QWidget:
        # QStackedLayout(StackAll) — safe here because the backdrop is a
        # pre-baked static pixmap (see `_backdrop_pixmap`), not a live
        # QGraphicsEffect. That combination is what broke z-ordering
        # before. Using a real layout also means `hero` naturally sizes
        # itself from fg's actual content height instead of a hardcoded
        # guess that content could silently overflow past.
        hero = QWidget()
        hero.setMinimumHeight(HERO_HEIGHT)
        stack = QStackedLayout(hero)
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        stack.setContentsMargins(0, 0, 0, 0)

        self._backdrop_lbl = QLabel()
        self._backdrop_lbl.setObjectName("hofBackdropImage")
        self._backdrop_lbl.setScaledContents(True)
        stack.addWidget(self._backdrop_lbl)

        fg = QWidget()
        fg.setStyleSheet("background:transparent;")
        flay = QVBoxLayout(fg)
        flay.setContentsMargins(32, 22, 32, 26)
        flay.setSpacing(14)

        hdr = QHBoxLayout()
        hdr.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(4)
        title = QLabel("🏆  Hall of Fame")
        title.setObjectName("pageTitle")
        col.addWidget(title)
        sub = QLabel("Your personal all-time greatest anime — ranked, tiered, celebrated.")
        sub.setObjectName("pageSubtitle")
        col.addWidget(sub)
        hdr.addLayout(col)
        hdr.addStretch()

        self._shelves_btn = _toolbar_btn("▤  Shelves", "navBtn")
        self._shelves_btn.setProperty("active", "true")
        self._shelves_btn.clicked.connect(lambda: self._set_view("shelves"))
        hdr.addWidget(self._shelves_btn)

        self._wall_btn = _toolbar_btn("⊞  Wall", "navBtn")
        self._wall_btn.clicked.connect(lambda: self._set_view("wall"))
        hdr.addWidget(self._wall_btn)

        surprise_btn = _toolbar_btn("🔀  Surprise Me", "secondaryBtn")
        surprise_btn.clicked.connect(self._surprise_me)
        hdr.addWidget(surprise_btn)

        export_btn = _toolbar_btn("↓  Export", "secondaryBtn")
        export_btn.clicked.connect(self._export_image)
        hdr.addWidget(export_btn)

        add_btn = QPushButton("+ Add Anime")
        add_btn.setObjectName("primaryBtn")
        add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_btn.clicked.connect(self._open_add)
        hdr.addWidget(add_btn)

        flay.addLayout(hdr)

        self._tier_strip = self._make_tier_strip()
        flay.addWidget(self._tier_strip)

        flay.addStretch(1)

        self._champion_slot = QWidget()
        self._champion_slot.setStyleSheet("background:transparent;")
        self._champion_slot_lay = QVBoxLayout(self._champion_slot)
        self._champion_slot_lay.setContentsMargins(0, 0, 0, 0)
        flay.addWidget(self._champion_slot)

        stack.addWidget(fg)
        stack.setCurrentWidget(fg)
        return hero

    def _make_tier_strip(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._tier_pills = []
        for key, label, color in TIERS:
            pill = QPushButton(f"{key} · {label}")
            pill.setObjectName("tierFilterPill")
            pill.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            pill.setFixedHeight(30)
            pill.clicked.connect(lambda _=False, k=key: self._toggle_tier_filter(k))
            lay.addWidget(pill)
            self._tier_pills.append((pill, key, color))
        lay.addStretch()
        self._restyle_tier_pills()
        return w

    def _restyle_tier_pills(self) -> None:
        for pill, key, color in self._tier_pills:
            active = self._active_tier_filter == key
            rgb = QColor(color).getRgb()[:3]
            if active:
                pill.setStyleSheet(
                    f"QPushButton{{background:rgba{rgb + (30,)};"
                    f"border:1.5px solid {color};border-radius:14px;"
                    f"color:{color};font-size:12px;font-weight:700;padding:5px 14px;}}"
                )
            else:
                pill.setStyleSheet(
                    f"QPushButton{{background:rgba(10,12,18,0.55);"
                    f"border:1px solid {color}55;border-radius:14px;"
                    f"color:{color};font-size:12px;font-weight:500;padding:5px 14px;}}"
                    f"QPushButton:hover{{border-color:{color}a0;}}"
                )

    def _toggle_tier_filter(self, key: str) -> None:
        self._active_tier_filter = None if self._active_tier_filter == key else key
        self._restyle_tier_pills()
        self._render()

    # ── Public API ─────────────────────────────────────────────────────────────

    def load(self) -> None:
        self._entries = _load_hof(self.db)
        self._render()

    def _set_view(self, mode: str) -> None:
        self._view_mode = mode
        for btn, m in [(self._shelves_btn, "shelves"), (self._wall_btn, "wall")]:
            btn.setProperty("active", "true" if m == mode else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._render()

    def _compute_champion(self) -> Optional[Tuple[Dict, Optional[str], Optional[str]]]:
        if not self._entries:
            return None
        for key, _label, color in TIERS:
            for e in self._entries:
                if (e.get("tier") or "").strip().upper() == key:
                    return e, key, color
        return self._entries[0], None, None

    def _filtered_entries(self) -> List[Dict]:
        if self._active_tier_filter is None:
            return list(self._entries)
        return [
            e for e in self._entries
            if (e.get("tier") or "").strip().upper() == self._active_tier_filter
        ]

    # ── Render ─────────────────────────────────────────────────────────────────

    def _render(self) -> None:
        while self._content_lay.count():
            item = self._content_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        champion = self._compute_champion()
        if champion:
            entry, tier_key, color = champion
            self._champion_id = entry["id"]
            self._populate_champion(entry, tier_key, color or CHAMPION_FALLBACK_COLOR)
        else:
            self._champion_id = None
            self._backdrop_lbl.setPixmap(QPixmap())
            self._populate_empty_champion()

        self._tier_strip.setVisible(bool(self._entries))
        self.scroll.setVisible(bool(self._entries))
        if not self._entries:
            return

        filtered = self._filtered_entries()
        if self._active_tier_filter and not filtered:
            self._render_no_matches()
            return

        body_entries = [e for e in filtered if e["id"] != self._champion_id]

        if self._view_mode == "wall":
            self._render_wall(body_entries, showcased=(not body_entries and filtered))
        else:
            self._render_shelves(body_entries, showcased=(not body_entries and filtered))

    def _populate_champion(self, entry: Dict, tier_key: Optional[str], color: str) -> None:
        while self._champion_slot_lay.count():
            item = self._champion_slot_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        row = QHBoxLayout()
        row.setSpacing(22)

        self._champion_cover_lbl = QLabel()
        self._champion_cover_lbl.setFixedSize(112, 160)
        self._champion_cover_lbl.setStyleSheet("background:#1a1d28;border-radius:8px;")
        row.addWidget(self._champion_cover_lbl)

        info = QVBoxLayout()
        info.setSpacing(7)

        crown_row = QHBoxLayout()
        crown_row.setSpacing(8)
        crown = QLabel("👑  Champion")
        crown.setStyleSheet(
            f"font-size:13px;font-weight:900;color:{color};"
            "background:transparent;letter-spacing:0.4px;"
        )
        crown_row.addWidget(crown)
        if tier_key:
            tb = QLabel(f" {tier_key} ")
            tb.setStyleSheet(
                f"background:{color};color:#0d0f14;font-size:10px;"
                "font-weight:900;border-radius:4px;padding:1px 4px;"
            )
            crown_row.addWidget(tb)
        crown_row.addStretch()
        info.addLayout(crown_row)

        title = entry.get("english_title") or entry.get("romaji_title", "")
        tl = QLabel(title)
        tl.setWordWrap(True)
        tl.setStyleSheet(
            "font-size:25px;font-weight:900;color:#f5f6ff;"
            "background:transparent;letter-spacing:-0.5px;"
        )
        info.addWidget(tl)

        meta_html = _meta_line_html(entry, self.db)
        if meta_html:
            ml = QLabel(meta_html)
            ml.setStyleSheet("font-size:13px;background:transparent;")
            info.addWidget(ml)

        info.addLayout(_genre_chip_row(entry.get("genres") or [], cap=4))
        row.addLayout(info, 1)

        actions = QVBoxLayout()
        actions.setSpacing(8)
        actions.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        details_btn = QPushButton("View Details")
        details_btn.setObjectName("primaryBtn")
        details_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        details_btn.clicked.connect(self._open_champion_details)
        actions.addWidget(details_btn)

        if entry.get("trailer_id"):
            t_btn = QPushButton("▶  Trailer")
            t_btn.setObjectName("secondaryBtn")
            t_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            t_btn.clicked.connect(
                lambda: self._open_trailer(
                    entry.get("trailer_id", ""), entry.get("trailer_site", "youtube")
                )
            )
            actions.addWidget(t_btn)

        row.addLayout(actions)
        self._champion_slot_lay.addLayout(row)

        if entry.get("banner_url"):
            self._load_banner(entry, lambda p: self._backdrop_lbl.setPixmap(
                _backdrop_pixmap(p, 1600, HERO_HEIGHT) or QPixmap()
            ))
        else:
            self._backdrop_lbl.setPixmap(QPixmap())
        self._load_cover(entry, lambda p: self._champion_cover_lbl.setPixmap(
            _rounded_scaled_pixmap(p, 112, 160, ring_color=color) or QPixmap()
        ))

    def _populate_empty_champion(self) -> None:
        while self._champion_slot_lay.count():
            item = self._champion_slot_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        col = QVBoxLayout()
        col.setSpacing(10)
        lbl = QLabel("Your Hall of Fame is empty.")
        lbl.setStyleSheet(
            "font-size:18px;font-weight:700;color:#e2e4ec;background:transparent;"
        )
        col.addWidget(lbl)
        sub = QLabel("Add your all-time favourite anime to crown a Champion.")
        sub.setStyleSheet("font-size:13px;color:#8a91a6;background:transparent;")
        col.addWidget(sub)
        cta = QPushButton("+ Add Anime")
        cta.setObjectName("primaryBtn")
        cta.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cta.clicked.connect(self._open_add)
        col.addWidget(cta, 0, Qt.AlignmentFlag.AlignLeft)
        self._champion_slot_lay.addLayout(col)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _render_no_matches(self) -> None:
        label = TIER_LABELS.get(self._active_tier_filter, self._active_tier_filter)
        msg = QLabel(f"No titles in {label} yet.")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(
            "font-size:13px;color:#4a5070;background:transparent;padding:40px 0;"
        )
        self._content_lay.addWidget(msg)
        clear_btn = QPushButton("Clear filter")
        clear_btn.setObjectName("secondaryBtn")
        clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        clear_btn.clicked.connect(lambda: self._toggle_tier_filter(self._active_tier_filter))
        self._content_lay.addWidget(clear_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        self._content_lay.addStretch(1)

    def _showcased_notice(self) -> QWidget:
        msg = QLabel("Your Champion from this tier is already showcased above. ↑")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(
            "font-size:13px;color:#4a5070;background:transparent;padding:24px 0;"
        )
        return msg

    def _render_shelves(self, entries: List[Dict], showcased: bool = False) -> None:
        tiered: Dict[str, List[Dict]] = {k: [] for k in TIER_KEYS}
        untiered: List[Dict] = []
        for e in entries:
            t = (e.get("tier") or "").strip().upper()
            if t in tiered:
                tiered[t].append(e)
            else:
                untiered.append(e)

        any_shown = False
        for key, label, color in TIERS:
            members = tiered[key]
            if not members:
                continue
            any_shown = True
            self._content_lay.addWidget(self._tier_section_header(key, label, color, len(members)))
            self._content_lay.addSpacing(10)
            shelf = _Shelf(members, self.db)
            shelf.poster_clicked.connect(self._on_poster_clicked)
            self._content_lay.addWidget(shelf)
            self._content_lay.addSpacing(20)
            for entry, card in shelf.cards:
                self._load_cover(entry, card.set_cover)

        if untiered:
            any_shown = True
            self._content_lay.addWidget(self._untiered_header(len(untiered)))
            self._content_lay.addSpacing(10)
            shelf = _Shelf(untiered, self.db)
            shelf.poster_clicked.connect(self._on_poster_clicked)
            self._content_lay.addWidget(shelf)
            for entry, card in shelf.cards:
                self._load_cover(entry, card.set_cover)

        if not any_shown and showcased:
            self._content_lay.addWidget(self._showcased_notice())

        self._content_lay.addStretch(1)

    def _render_wall(self, entries: List[Dict], showcased: bool = False) -> None:
        if not entries:
            if showcased:
                self._content_lay.addWidget(self._showcased_notice())
            self._content_lay.addStretch(1)
            return

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        COLS = 6
        for idx, entry in enumerate(entries):
            tier_val = (entry.get("tier") or "").strip().upper()
            card = _PosterCard(entry, self.db)
            card.clicked.connect(self._on_poster_clicked)
            shadow_color = TIER_COLORS.get(tier_val, "#000000")
            wrapped = _ElevatedCard(
                card, radius=10, margin=9,
                strength=45 if tier_val in TIER_COLORS else 65,
                color=shadow_color,
            )
            grid.addWidget(wrapped, idx // COLS, idx % COLS)
            self._load_cover(entry, card.set_cover)

        w = QWidget()
        w.setStyleSheet("background:transparent;")
        w.setLayout(grid)
        self._content_lay.addWidget(w)
        self._content_lay.addStretch(1)

    def _tier_section_header(self, key: str, label: str, color: str, count: int) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        badge = QLabel(f" {key} ")
        badge.setStyleSheet(
            f"background:{color};color:#0d0f14;font-size:13px;"
            "font-weight:900;border-radius:5px;padding:2px 4px;"
        )
        lay.addWidget(badge)

        lbl = QLabel(f"{label}  ·  {count} title{'s' if count != 1 else ''}")
        lbl.setStyleSheet(
            f"font-size:13px;font-weight:700;color:{color};"
            "background:transparent;letter-spacing:0.3px;"
        )
        lay.addWidget(lbl)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background:{color}33;border:none;max-height:1px;")
        line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay.addWidget(line, 1)
        return w

    def _untiered_header(self, count: int) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lbl = QLabel(f"Untiered  ·  {count} title{'s' if count != 1 else ''}")
        lbl.setStyleSheet(
            "font-size:13px;font-weight:700;color:#4a5070;background:transparent;"
        )
        lay.addWidget(lbl)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background:#1a1d28;border:none;max-height:1px;")
        line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay.addWidget(line, 1)
        return w

    # ── Image loading ────────────────────────────────────────────────────────

    def _load_cover(self, entry: Dict, on_ready) -> None:
        local = entry.get("cover_local", "")
        url   = entry.get("cover_url", "")
        if local and Path(local).exists():
            on_ready(local)
            return
        if url and url.startswith("http"):
            from core.image_cache import get_cached_path
            cached = get_cached_path(url)
            if cached:
                on_ready(str(cached))
                return
            iw = ImageWorker(url, entry.get("id", 0), "cover")
            iw.signals.result.connect(lambda r: on_ready(r[2]) if r and r[2] else None)
            run_worker(iw)
        elif url:
            on_ready(url)

    def _load_banner(self, entry: Dict, on_ready) -> None:
        url = entry.get("banner_url", "")
        if not url:
            return
        from core.image_cache import get_cached_path
        cached = get_cached_path(url)
        if cached:
            on_ready(str(cached))
            return
        bw = ImageWorker(url, entry.get("id", 0), "banner")
        bw.signals.result.connect(lambda r: on_ready(r[2]) if r and r[2] else None)
        run_worker(bw)

    def _load_overlay_images(self, entry: Dict) -> None:
        self._load_cover(entry, self._overlay.set_cover)
        self._load_banner(entry, self._overlay.set_banner)

    # ── Overlay control ────────────────────────────────────────────────────────

    def _on_poster_clicked(self, anime_id: int) -> None:
        entry = next((e for e in self._entries if e["id"] == anime_id), None)
        if entry:
            self._open_overlay_for(entry)

    def _open_champion_details(self) -> None:
        entry = next((e for e in self._entries if e["id"] == self._champion_id), None)
        if entry:
            self._open_overlay_for(entry)

    def _surprise_me(self) -> None:
        if not self._entries:
            from ui.toast import Toast
            Toast.show(self.window(), "Add some anime to your Hall of Fame first!", kind="info")
            return
        entry = random.choice(self._entries)
        self._open_overlay_for(entry)

    def _open_overlay_for(self, entry: Dict) -> None:
        self._overlay_order = self._entries
        self._overlay_index = next(
            (i for i, e in enumerate(self._overlay_order) if e["id"] == entry["id"]), 0
        )
        self._show_overlay_current()

    def _show_overlay_current(self) -> None:
        if not self._overlay_order:
            return
        entry = self._overlay_order[self._overlay_index]
        self._overlay.populate(entry, self.db)
        self._load_overlay_images(entry)
        self._overlay.setGeometry(self.rect())
        self._overlay.setVisible(True)
        self._overlay.raise_()
        self._overlay.setFocus()

    def _overlay_navigate(self, direction: int) -> None:
        if not self._overlay_order:
            return
        self._overlay_index = (self._overlay_index + direction) % len(self._overlay_order)
        self._show_overlay_current()

    def _close_overlay(self) -> None:
        self._overlay.setVisible(False)

    def _sync_overlay_if_open(self, anime_id: int) -> None:
        if not self._overlay.isVisible():
            return
        self._overlay_order = self._entries
        idx = next((i for i, e in enumerate(self._entries) if e["id"] == anime_id), None)
        if idx is None:
            self._close_overlay()
            return
        self._overlay_index = idx
        self._show_overlay_current()

    # ── Actions ────────────────────────────────────────────────────────────────

    def _open_add(self) -> None:
        dlg = _AddToHofDialog(self.db, self)
        if dlg.exec():
            self.load()
            if getattr(dlg, "added_title", ""):
                from ui.toast import Toast
                Toast.show(
                    self.window(), f"'{dlg.added_title}' added to Hall of Fame.", kind="success"
                )

    def _remove_from_overlay(self, anime_id: int) -> None:
        self._close_overlay()
        self._remove(anime_id)

    def _remove(self, anime_id: int) -> None:
        name = next(
            (e.get("romaji_title", "?") for e in self._entries if e["id"] == anime_id), "?"
        )
        if (
            QMessageBox.question(
                self, "Remove from Hall of Fame",
                f"Remove '{name}' from your Hall of Fame?\n(The anime stays in your library.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            _remove_from_hof(self.db, anime_id)
            self.load()
            from ui.toast import Toast
            Toast.show(self.window(), f"'{name}' removed from Hall of Fame.", kind="success")

    def _edit_note(self, anime_id: int, note: str) -> None:
        _update_hof_note(self.db, anime_id, note)
        self.load()
        self._sync_overlay_if_open(anime_id)
        from ui.toast import Toast
        Toast.show(self.window(), "Note saved.", kind="success")

    def _change_tier(self, anime_id: int, tier: str) -> None:
        if not tier:
            return
        _update_hof_tier(self.db, anime_id, tier)
        name = next((e.get("romaji_title", "") for e in self._entries if e["id"] == anime_id), "")
        self.load()
        self._sync_overlay_if_open(anime_id)
        from ui.toast import Toast
        label = TIER_LABELS.get(tier, tier)
        Toast.show(self.window(), f"'{name}' moved to Tier {tier} — {label}.", kind="success")

    def _move_up(self, anime_id: int) -> None:
        idx = next((i for i, e in enumerate(self._entries) if e["id"] == anime_id), -1)
        if idx <= 0:
            return
        self._entries[idx], self._entries[idx - 1] = self._entries[idx - 1], self._entries[idx]
        _save_hof_order(self.db, [e["id"] for e in self._entries])
        self.load()
        self._sync_overlay_if_open(anime_id)

    def _move_down(self, anime_id: int) -> None:
        idx = next((i for i, e in enumerate(self._entries) if e["id"] == anime_id), -1)
        if idx < 0 or idx >= len(self._entries) - 1:
            return
        self._entries[idx], self._entries[idx + 1] = self._entries[idx + 1], self._entries[idx]
        _save_hof_order(self.db, [e["id"] for e in self._entries])
        self.load()
        self._sync_overlay_if_open(anime_id)

    def _open_trailer(self, trailer_id: str, trailer_site: str) -> None:
        try:
            from ui.trailer_player import TrailerPlayer
            dlg = TrailerPlayer(trailer_id, trailer_site, self)
            dlg.exec()
        except Exception as exc:
            QMessageBox.information(self, "Trailer", f"Could not open trailer: {exc}")

    # ── Export (PNG snapshot) ────────────────────────────────────────────────

    def _export_image(self) -> None:
        if not self._entries:
            QMessageBox.information(self, "Export", "Add some anime to your Hall of Fame first!")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Hall of Fame",
            str(Path.home() / "miroku_hall_of_fame.png"), "PNG Image (*.png)",
        )
        if not path:
            return

        COLS, CARD_W, CARD_H, PAD, HEADER = 5, 130, 185, 16, 56
        n      = len(self._entries)
        rows   = (n + COLS - 1) // COLS
        width  = COLS * CARD_W + (COLS + 1) * PAD
        height = rows * CARD_H + (rows + 1) * PAD + HEADER

        px = QPixmap(width, height)
        px.fill(QColor("#0d0f14"))
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        p.setPen(QColor("#f0f1f5"))
        f = QFont(); f.setPointSize(14); f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(PAD, 0, width - PAD * 2, HEADER,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "🏆  My Hall of Fame — Miroku")

        f2 = QFont(); f2.setPointSize(8)
        p.setFont(f2)
        p.setPen(QColor("#4a5070"))
        p.drawText(PAD, 0, width - PAD * 2, HEADER,
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   datetime.now().strftime("%d %b %Y"))

        for idx, entry in enumerate(self._entries):
            col_i, row_i = idx % COLS, idx // COLS
            x = PAD + col_i * (CARD_W + PAD)
            y = HEADER + PAD + row_i * (CARD_H + PAD)

            p.setBrush(QColor("#111420"))
            p.setPen(QColor("#1a1d28"))
            card_path = QPainterPath()
            card_path.addRoundedRect(x, y, CARD_W, CARD_H, 8, 8)
            p.drawPath(card_path)

            local = entry.get("cover_local", "")
            url   = entry.get("cover_url", "")
            cover_px = None
            if local and Path(local).exists():
                cover_px = QPixmap(local)
            elif url:
                from core.image_cache import get_cached_path
                cached = get_cached_path(url)
                if cached:
                    cover_px = QPixmap(str(cached))
            if cover_px and not cover_px.isNull():
                cover_px = cover_px.scaled(
                    CARD_W, CARD_H - 40,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                cx = (cover_px.width() - CARD_W) // 2
                cy = (cover_px.height() - (CARD_H - 40)) // 2
                cover_px = cover_px.copy(cx, cy, CARD_W, CARD_H - 40)
                clip = QPainterPath()
                clip.addRoundedRect(x, y, CARD_W, CARD_H - 40, 8, 8)
                p.setClipPath(clip)
                p.drawPixmap(x, y, cover_px)
                p.setClipping(False)

            p.setBrush(QColor(NEUTRAL_RANK_COLOR))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(x + 6, y + 6, 22, 22)
            p.setPen(QColor("#0d0f14"))
            f3 = QFont(); f3.setPointSize(7); f3.setWeight(QFont.Weight.Bold)
            p.setFont(f3)
            p.drawText(x + 6, y + 6, 22, 22, Qt.AlignmentFlag.AlignCenter, str(idx + 1))

            tier = (entry.get("tier") or "").strip().upper()
            if tier in TIER_COLORS:
                tc = QColor(TIER_COLORS[tier]); tc.setAlpha(200)
                p.setBrush(tc); p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(x + CARD_W - 28, y + 6, 22, 16, 4, 4)
                p.setPen(QColor("#0d0f14"))
                f4 = QFont(); f4.setPointSize(7); f4.setWeight(QFont.Weight.Bold)
                p.setFont(f4)
                p.drawText(x + CARD_W - 28, y + 6, 22, 16, Qt.AlignmentFlag.AlignCenter, tier)

            p.setPen(QColor("#e8eaf5"))
            f5 = QFont(); f5.setPointSize(7); f5.setWeight(QFont.Weight.Bold)
            p.setFont(f5)
            title = (entry.get("english_title") or entry.get("romaji_title", ""))[:28]
            p.drawText(x + 4, y + CARD_H - 38, CARD_W - 8, 18,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

            sc = entry.get("average_score")
            if sc:
                p.setPen(QColor("#a594f9"))
                f6 = QFont(); f6.setPointSize(6)
                p.setFont(f6)
                p.drawText(x + 4, y + CARD_H - 20, CARD_W - 8, 16,
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           f"★ {sc / 10:.1f}")

        p.end()
        px.save(path)
        from ui.toast import Toast
        Toast.show(self.window(), f"Hall of Fame exported to {Path(path).name}", kind="success")


# ── Add dialog (unchanged logic, preserved fully) ─────────────────────────────

class _AddToHofDialog(QDialog):
    def __init__(self, db: DatabaseManager, parent=None) -> None:
        super().__init__(parent)
        self.db             = db
        self.setWindowTitle("Add to Hall of Fame")
        self.setMinimumSize(660, 560)
        self.setStyleSheet("background:#0f1118;")
        self._selected_media: Optional[Dict] = None
        self._results:        List[Dict]     = []
        self.added_title = ""
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)
        self._row_refs: List[QFrame] = []
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        t = QLabel("Add to Hall of Fame")
        t.setObjectName("dialogTitle")
        lay.addWidget(t)

        s = QLabel(
            "Search any anime — from any era, any status. "
            "Hall of Fame is for your all-time greats, no restrictions."
        )
        s.setObjectName("dialogSubtitle")
        s.setWordWrap(True)
        lay.addWidget(s)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(6)
        self.lib_tab_btn = QPushButton("My Library")
        self.lib_tab_btn.setObjectName("filterPill")
        self.lib_tab_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.lib_tab_btn.clicked.connect(lambda: self._switch_tab("library"))
        tab_row.addWidget(self.lib_tab_btn)

        self.al_tab_btn = QPushButton("Search AniList")
        self.al_tab_btn.setObjectName("filterPill")
        self.al_tab_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.al_tab_btn.clicked.connect(lambda: self._switch_tab("anilist"))
        tab_row.addWidget(self.al_tab_btn)
        tab_row.addStretch()
        lay.addLayout(tab_row)

        self.search = QLineEdit()
        self.search.setObjectName("searchBar")
        self.search.setPlaceholderText("Search by title…")
        self.search.setFixedHeight(36)
        self.search.textChanged.connect(self._on_search_text)
        lay.addWidget(self.search)

        self.bar = QProgressBar()
        self.bar.setFixedHeight(2)
        self.bar.setRange(0, 0)
        self.bar.setVisible(False)
        self.bar.setStyleSheet(
            "QProgressBar{background:#1a1d28;border:none;}"
            "QProgressBar::chunk{background:#7c6af7;}"
        )
        lay.addWidget(self.bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(320)
        self._list_w = QWidget()
        self._list_w.setStyleSheet("background:transparent;")
        self._list_lay = QVBoxLayout(self._list_w)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(5)
        self._list_lay.addStretch()
        scroll.setWidget(self._list_w)
        lay.addWidget(scroll)

        self.preview_lbl = QLabel("")
        self.preview_lbl.setStyleSheet(
            "font-size:12px;color:#34d399;padding:4px 0;min-height:20px;"
        )
        lay.addWidget(self.preview_lbl)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondaryBtn")
        cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)

        self.ok_btn = QPushButton("Add to Hall of Fame")
        self.ok_btn.setObjectName("primaryBtn")
        self.ok_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.ok_btn.setEnabled(False)
        self.ok_btn.clicked.connect(self._add)
        btns.addWidget(self.ok_btn)
        lay.addLayout(btns)

        self._tab = "library"
        self._switch_tab("library")

    def _switch_tab(self, tab: str) -> None:
        self._tab = tab
        self._selected_media = None
        self.ok_btn.setEnabled(False)
        self.preview_lbl.setText("")
        for btn, t in [(self.lib_tab_btn, "library"), (self.al_tab_btn, "anilist")]:
            btn.setProperty("active", "true" if tab == t else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if tab == "library":
            self.search.setPlaceholderText("Filter library by title…")
            self._load_library()
        else:
            self.search.setPlaceholderText("Search any anime on AniList…")
            self._clear_list()

    def _on_search_text(self, text: str) -> None:
        if self._tab == "library":
            self._filter_library(text)
        else:
            self._search_timer.start(380)

    def _load_library(self) -> None:
        self._all_anime = self.db.get_all_anime()
        self._render_library(self._all_anime)

    def _filter_library(self, text: str) -> None:
        q = text.lower()
        filtered = (
            [
                a for a in self._all_anime
                if q in (a.get("romaji_title", "")).lower()
                or q in (a.get("english_title", "")).lower()
            ]
            if q else self._all_anime
        )
        self._render_library(filtered)

    def _render_library(self, anime_list: List[Dict]) -> None:
        self._clear_list()
        for i, anime in enumerate(anime_list):
            in_hof = _in_hof(self.db, anime["id"])
            row = _LibRow(anime, in_hof)
            row.selected.connect(self._on_lib_sel)
            self._list_lay.insertWidget(i, row)
            self._row_refs.append(row)

    def _on_lib_sel(self, anime_id: int) -> None:
        for r in self._row_refs:
            if hasattr(r, "_aid"):
                r.set_selected(r._aid == anime_id)
        anime = self.db.get_anime_by_id(anime_id)
        if anime:
            self._selected_media = {
                "_from_library": True,
                "_lib_id":       anime_id,
                "id":            anime.get("anilist_id"),
                "title": {
                    "romaji":  anime.get("romaji_title", ""),
                    "english": anime.get("english_title", ""),
                },
            }
            self.ok_btn.setEnabled(True)
            self.preview_lbl.setText(f"✓  Selected: {anime.get('romaji_title', '')}")

    def _do_search(self) -> None:
        q = self.search.text().strip()
        if len(q) < 2:
            return
        self.bar.setVisible(True)
        from workers.workers import SearchWorker
        w = SearchWorker(q)
        w.signals.result.connect(self._on_anilist_results)
        w.signals.finished.connect(lambda: self.bar.setVisible(False))
        run_worker(w)

    def _on_anilist_results(self, results: List[Dict]) -> None:
        self._results = results
        self._clear_list()
        if not results:
            lbl = QLabel("No results.")
            lbl.setStyleSheet("color:#4a5070;padding:12px;")
            self._list_lay.insertWidget(0, lbl)
            return
        for i, media in enumerate(results[:15]):
            row = _AniListRow(media, i)
            row.selected.connect(self._on_anilist_sel)
            self._list_lay.insertWidget(i, row)
            self._row_refs.append(row)
            url = (media.get("coverImage") or {}).get("medium", "")
            if url:
                iw = ImageWorker(url, i, "cover")
                iw.signals.result.connect(
                    lambda r, rw=row: (rw.set_cover(r[2]) if r and r[2] else None)
                )
                run_worker(iw)

    def _on_anilist_sel(self, idx: int) -> None:
        for r in self._row_refs:
            if hasattr(r, "idx"):
                r.set_selected(r.idx == idx)
        media = self._results[idx]
        self._selected_media = media
        self.ok_btn.setEnabled(True)
        title = (media.get("title") or {}).get("romaji", "")
        status = (media.get("status") or "").replace("_", " ").title()
        self.preview_lbl.setText(f"✓  Selected: {title}  ({status})")

    def _clear_list(self) -> None:
        for r in self._row_refs:
            r.setParent(None)
        self._row_refs = []
        for i in reversed(range(self._list_lay.count())):
            w = self._list_lay.itemAt(i).widget()
            if w:
                w.setParent(None)

    def _add(self) -> None:
        if not self._selected_media:
            return
        m = self._selected_media

        if m.get("_from_library"):
            lib_id = m["_lib_id"]
            if _in_hof(self.db, lib_id):
                from ui.toast import Toast
                Toast.show(self.window(), "Already in your Hall of Fame.", kind="info")
                return
            _add_to_hof(self.db, lib_id)
            anime = self.db.get_anime_by_id(lib_id)
            self.added_title = (anime or {}).get("romaji_title", "Anime")
            self.accept()
            return

        anilist_id = m.get("id")
        existing   = self.db.get_anime_by_anilist_id(anilist_id) if anilist_id else None
        if existing:
            if _in_hof(self.db, existing["id"]):
                from ui.toast import Toast
                Toast.show(self.window(), "Already in your Hall of Fame.", kind="info")
                return
            _add_to_hof(self.db, existing["id"])
            self.added_title = existing.get("romaji_title", "Anime")
            self.accept()
            return

        self.ok_btn.setEnabled(False)
        self.ok_btn.setText("Adding…")

        from core.api import get_anime_by_id

        def fetch() -> Dict:
            return get_anime_by_id(anilist_id) if anilist_id else m

        def commit(full_media: Dict) -> None:
            ok, title = add_anilist_media_to_hof(self.db, full_media)
            if not ok:
                from ui.toast import Toast
                Toast.show(self.window(), "Already in your Hall of Fame.", kind="info")
                self.ok_btn.setEnabled(True)
                self.ok_btn.setText("Add to Hall of Fame")
                return
            self.added_title = title
            self.accept()

        def on_err(e: str) -> None:
            self.ok_btn.setEnabled(True)
            self.ok_btn.setText("Add to Hall of Fame")
            QMessageBox.critical(self, "Error", f"Could not fetch data: {e}")

        w = Worker(fetch)
        w.signals.result.connect(commit)
        w.signals.error.connect(on_err)
        run_worker(w)


# ── Shared row widgets (reused in add dialog) ──────────────────────────────────

class _LibRow(QFrame):
    selected = pyqtSignal(int)
    _BASE = "QFrame{background:#111420;border:1px solid #1a1d28;border-radius:8px;}"
    _SEL  = "QFrame{background:#151929;border:1px solid #4b3fa8;border-radius:8px;}"
    _HOF  = "QFrame{background:#0e1620;border:1px solid #1e2d45;border-radius:8px;}"

    def __init__(self, anime: Dict, in_hof: bool, parent=None) -> None:
        super().__init__(parent)
        self._aid    = anime["id"]
        self._in_hof = in_hof
        self.setFixedHeight(52)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(self._HOF if in_hof else self._BASE)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        title = anime.get("english_title") or anime.get("romaji_title", "")
        tl = QLabel(title[:60])
        tl.setStyleSheet(
            f"font-size:13px;font-weight:600;color:{'#4a5070' if in_hof else '#dde0ed'};"
        )
        lay.addWidget(tl)
        lay.addStretch()

        if in_hof:
            lay.addWidget(QLabel("🏆"))

        ws = anime.get("watch_status", "")
        if ws:
            wl = QLabel(ws.title())
            wl.setStyleSheet("font-size:11px;color:#4a5070;")
            lay.addWidget(wl)

    def set_selected(self, sel: bool) -> None:
        if self._in_hof:
            return
        self.setStyleSheet(self._SEL if sel else self._BASE)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and not self._in_hof:
            self.selected.emit(self._aid)
        super().mousePressEvent(e)


class _AniListRow(QFrame):
    selected = pyqtSignal(int)
    _BASE = "QFrame{background:#111420;border:1px solid #1a1d28;border-radius:8px;}"
    _SEL  = "QFrame{background:#151929;border:1px solid #4b3fa8;border-radius:8px;}"

    def __init__(self, media: Dict, idx: int, parent=None) -> None:
        super().__init__(parent)
        self.idx = idx
        self.setFixedHeight(64)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(self._BASE)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 12, 8)
        lay.setSpacing(12)

        self.cover = QLabel()
        self.cover.setFixedSize(34, 48)
        self.cover.setStyleSheet("background:#1a1d28;border-radius:4px;")
        lay.addWidget(self.cover)

        info = QVBoxLayout()
        info.setSpacing(2)
        t    = media.get("title", {})
        tl   = QLabel((t.get("romaji") or t.get("english") or "")[:60])
        tl.setStyleSheet("font-size:13px;font-weight:600;color:#dde0ed;")
        info.addWidget(tl)

        api_s = (media.get("status") or "").upper()
        s_col = {
            "RELEASING":       "#34d399",
            "FINISHED":        "#a594f9",
            "NOT_YET_RELEASED": "#fbbf24",
        }.get(api_s, "#6b7280")
        s_txt = {
            "RELEASING":       "● AIRING",
            "FINISHED":        "● FINISHED",
            "NOT_YET_RELEASED": "● UPCOMING",
        }.get(api_s, api_s)
        sl = QLabel(s_txt)
        sl.setStyleSheet(f"font-size:10px;font-weight:700;color:{s_col};")
        info.addWidget(sl)
        lay.addLayout(info)
        lay.addStretch()

        sc = media.get("averageScore")
        if sc:
            scl = QLabel(f"★ {sc / 10:.1f}")
            scl.setStyleSheet("font-size:12px;color:#a594f9;font-weight:600;")
            lay.addWidget(scl)

    def set_cover(self, path: str) -> None:
        if not path:
            return
        px = QPixmap(path).scaled(
            34, 48,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.cover.setPixmap(px)

    def set_selected(self, sel: bool) -> None:
        self.setStyleSheet(self._SEL if sel else self._BASE)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.idx)
        super().mousePressEvent(e)
