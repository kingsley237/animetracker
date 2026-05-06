"""
AnimeTracker — Anime Card Widget
Displays cover art, episode progress, countdown, and status badge.
Persistent score/rating overlay when sorted by score or rating.
"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QProgressBar,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QCursor, QFont

from core.database import DatabaseManager


def _format_countdown(seconds: int, next_ep_num: Optional[int] = None) -> tuple[str, str]:
    """
    Returns (display_text, color_hint).
    FIX 4: Removed "Ep N in" prefix — card already shows episode info.
    FIX 2: Color hints drive time-proximity coloring:
      aired    = green  (ep just dropped)
      urgent   = red    (< 1 hour)
      imminent = amber  (< 24 hours)
      soon     = purple (< 7 days)
      week     = blue   (< 14 days)
      far      = muted  (> 14 days)
    """
    if seconds <= 0:
        if next_ep_num and next_ep_num > 1:
            return f"Ep {next_ep_num - 1} just aired!", "aired"
        return "New episode just aired!", "aired"
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s   = divmod(rem, 60)
    # Clean time string — no episode prefix
    if d > 14:  return f"Next in {d}d",            "far"
    elif d > 7: return f"Next in {d}d {h}h",       "week"
    elif d > 0: return f"Next in {d}d {h}h {m}m",  "soon"
    elif h > 0: return f"Next in {h}h {m}m",       "imminent"
    else:       return f"Next in {m}m {s:02d}s",   "urgent"


def _rounded_pixmap(pixmap: QPixmap, radius: int = 10) -> QPixmap:
    result = QPixmap(pixmap.size())
    result.fill(QColor(0, 0, 0, 0))
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return result


class AnimeCard(QFrame):
    CARD_WIDTH  = 180
    CARD_HEIGHT = 310
    COVER_HEIGHT = 240

    clicked       = pyqtSignal(int)
    watch_toggled = pyqtSignal(int)

    def __init__(self, anime: Dict[str, Any], db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.anime_id     = anime["id"]
        self._anime       = anime
        self.db           = db
        self._next_ep_at: Optional[int] = None
        # Overlay mode: None | "anilist_score" | "user_rating"
        self._overlay_mode: Optional[str] = None

        self.setObjectName("animeCard")
        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._build_ui()
        self.update_data(anime)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Cover
        self.cover_label = QLabel()
        self.cover_label.setObjectName("cardCover")
        self.cover_label.setFixedSize(self.CARD_WIDTH, self.COVER_HEIGHT)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_placeholder()
        root.addWidget(self.cover_label)

        # Info strip — fixed 70px so text can never overflow into cover
        info = QWidget()
        info.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT - self.COVER_HEIGHT)
        info.setStyleSheet("background:#111420;border-radius:0 0 10px 10px;")
        il = QVBoxLayout(info)
        il.setContentsMargins(10, 7, 10, 7)
        il.setSpacing(3)

        # Row 1 — title
        self.title_label = QLabel()
        self.title_label.setObjectName("cardTitle")
        self.title_label.setWordWrap(False)
        f = QFont(); f.setPointSize(9); f.setWeight(QFont.Weight.DemiBold)
        self.title_label.setFont(f)
        il.addWidget(self.title_label)

        # Row 2 — episode text  +  status badge
        r2 = QHBoxLayout()
        r2.setSpacing(4)
        r2.setContentsMargins(0, 0, 0, 0)
        self.ep_label = QLabel()
        self.ep_label.setObjectName("cardEpisode")
        f2 = QFont(); f2.setPointSize(8)
        self.ep_label.setFont(f2)
        r2.addWidget(self.ep_label)
        r2.addStretch()
        self.status_badge = QLabel()
        f3 = QFont(); f3.setPointSize(7); f3.setWeight(QFont.Weight.Bold)
        self.status_badge.setFont(f3)
        r2.addWidget(self.status_badge)
        il.addLayout(r2)

        # Row 3 — countdown / overlay label
        self.countdown_label = QLabel()
        self.countdown_label.setObjectName("cardCountdown")
        f4 = QFont(); f4.setPointSize(7); f4.setWeight(QFont.Weight.Medium)
        self.countdown_label.setFont(f4)
        il.addWidget(self.countdown_label)

        # Row 4 — progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setTextVisible(False)
        il.addWidget(self.progress_bar)

        root.addWidget(info)

    # ── Cover ──────────────────────────────────────────────────────────────────

    def _set_placeholder(self):
        px = QPixmap(self.CARD_WIDTH, self.COVER_HEIGHT)
        px.fill(QColor("#1a1d28"))
        p = QPainter(px)
        p.setPen(QColor("#2a2d42"))
        p.setFont(QFont("Segoe UI Emoji", 28))
        p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "📺")
        p.end()
        self.cover_label.setPixmap(px)

    def set_cover(self, path: str):
        if not path:
            return
        px = QPixmap(path)
        if px.isNull():
            return
        scaled = px.scaled(
            self.CARD_WIDTH, self.COVER_HEIGHT,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width()  - self.CARD_WIDTH)  // 2)
        y = max(0, (scaled.height() - self.COVER_HEIGHT) // 2)
        cropped = scaled.copy(x, y, self.CARD_WIDTH, self.COVER_HEIGHT)
        self.cover_label.setPixmap(_rounded_pixmap(cropped, 10))

    # ── Overlay mode (persists until changed) ─────────────────────────────────

    def set_overlay_mode(self, mode: Optional[str]):
        """
        mode = None          → show countdown (default)
        mode = "anilist_score" → show AniList score permanently
        mode = "user_rating"   → show user avg rating permanently
        """
        self._overlay_mode = mode
        self._refresh_overlay()

    def _refresh_overlay(self):
        if self._overlay_mode == "anilist_score":
            sc = self._anime.get("average_score")
            if sc:
                self.countdown_label.setText(f"★ {sc / 10:.1f} / 10  AniList score")
                self.countdown_label.setStyleSheet(
                    "color:#7c6af7;font-size:10px;font-weight:600;"
                )
            else:
                self.countdown_label.setText("No AniList score yet")
                self.countdown_label.setStyleSheet("color:#3b4260;font-size:10px;")
        elif self._overlay_mode == "user_rating":
            avg = self.db.get_average_rating(self.anime_id)
            if avg is not None:
                self.countdown_label.setText(f"★ {avg:.1f} / 6  your rating")
                self.countdown_label.setStyleSheet(
                    "color:#fbbf24;font-size:10px;font-weight:600;"
                )
            else:
                self.countdown_label.setText("Not rated yet")
                self.countdown_label.setStyleSheet("color:#3b4260;font-size:10px;")
        else:
            self.tick_countdown()

    # ── Data update ────────────────────────────────────────────────────────────

    def update_data(self, anime: Dict[str, Any]):
        self._anime      = anime
        self._next_ep_at = anime.get("next_episode_at")

        # Title
        title = anime.get("english_title") or anime.get("romaji_title", "Unknown")
        if len(title) > 22:
            title = title[:20] + "…"
        self.title_label.setText(title)
        self.title_label.setToolTip(
            f"{anime.get('romaji_title','')}  /  {anime.get('english_title','')}"
        )

        # Episode counts
        watched    = self.db.get_watched_count(anime["id"]) if anime["id"] > 0 else 0
        total      = anime.get("total_episodes") or 0
        next_ep    = anime.get("next_episode_num")
        ws         = anime.get("watch_status", "watching")
        api_status = (anime.get("status") or "").upper()

        # Aired count: episodes that have aired so far
        if next_ep and next_ep > 1:
            aired = next_ep - 1
        elif total and api_status in ("FINISHED", "CANCELLED"):
            aired = total
        else:
            aired = 0

        has_unwatched_aired = aired > 0 and watched < aired

        # Episode label — always clear about what watched/aired means
        if ws == "completed":
            self.ep_label.setText(f"Watched {watched}/{total or '?'} eps")
        elif aired and total:
            self.ep_label.setText(f"Watched {watched}/{aired} aired")
        elif aired:
            self.ep_label.setText(f"Watched {watched}/{aired} aired")
        elif total:
            self.ep_label.setText(f"0/{total} eps")
        else:
            self.ep_label.setText(f"Watched {watched} eps")

        self.ep_label.setToolTip(
            f"You have watched {watched} episode(s). "
            + (f"{aired} have aired so far." if aired else "")
        )

        # ── Status badge — fully self-explanatory words only ──────────────────
        # Research: Carbon DS + Mobbin = never use abbreviations in status chips.
        # Each badge must be understandable with zero context.
        if ws == "completed":
            self._set_badge("badgeCompleted", "FINISHED")
        elif ws == "planned" and api_status == "NOT_YET_RELEASED":
            self._set_badge("badgeUpcoming", "UPCOMING")
        elif ws == "planned":
            self._set_badge("badgePlanned", "PLANNED")
        elif has_unwatched_aired:
            n = aired - watched
            self._set_badge("badgeAlert", f"+{n} EP{'S' if n > 1 else ''}")
        elif api_status == "RELEASING":
            self._set_badge("badgeWatching", "AIRING")
        else:
            self._set_badge("badgeWatching", "AIRING")

        # ── Unwatched border ──────────────────────────────────────────────────
        self.setProperty("hasUnwatched", "true" if has_unwatched_aired else "false")
        self.style().unpolish(self)
        self.style().polish(self)

        if has_unwatched_aired:
            self.cover_label.setToolTip(
                f"⚠  {aired - watched} episode(s) aired that you haven't watched yet!"
            )
        else:
            self.cover_label.setToolTip("")

        # ── Progress bar ──────────────────────────────────────────────────────
        denom = total if total else (aired if aired else 1)
        self.progress_bar.setMaximum(denom)
        self.progress_bar.setValue(min(watched, denom))
        status_prop = (
            "completed" if ws == "completed" else
            "alert"     if has_unwatched_aired else
            "upcoming"  if ws == "planned"    else ""
        )
        self.progress_bar.setProperty("status", status_prop)
        self.progress_bar.style().unpolish(self.progress_bar)
        self.progress_bar.style().polish(self.progress_bar)

        # Refresh overlay / countdown
        self._refresh_overlay()

    def _set_badge(self, obj_name: str, text: str):
        self.status_badge.setObjectName(obj_name)
        self.status_badge.setText(text)
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

    # ── Countdown ─────────────────────────────────────────────────────────────

    def _secs_until(self) -> int:
        if not self._next_ep_at:
            return 99999
        return self._next_ep_at - int(datetime.now(timezone.utc).timestamp())

    def tick_countdown(self):
        # Only tick if not in a persistent overlay mode
        if self._overlay_mode:
            return
        if not self._next_ep_at:
            self.countdown_label.setText("")
            return
        secs = self._secs_until()
        next_ep_num = self._anime.get("next_episode_num") if self._anime else None
        text, hint  = _format_countdown(secs, next_ep_num)
        color = {
            "aired":    "#34d399",   # green  — just dropped
            "urgent":   "#f87171",   # red    — < 1 hour
            "imminent": "#fbbf24",   # amber  — < 24 hours
            "soon":     "#a594f9",   # purple — < 7 days
            "week":     "#38bdf8",   # blue   — < 14 days
            "far":      "#4a5070",   # muted  — > 14 days
        }.get(hint, "#4a5070")
        self.countdown_label.setText(text)
        self.countdown_label.setStyleSheet(
            f"color:{color};font-size:10px;font-weight:600;"
        )

    # ── Selection ─────────────────────────────────────────────────────────────

    def set_selected(self, selected: bool):
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.anime_id)
        super().mousePressEvent(event)