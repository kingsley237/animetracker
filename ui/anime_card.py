"""
Miroku — Anime Card Widget  (Poster redesign)

Full-bleed cover art fills the entire card.
All info — title, episode progress, countdown, badges — overlays
the cover via carefully tuned gradients so text is always readable
regardless of the art behind it.

Design principles (AniList / Crunchyroll / Plex pattern):
  - Cover IS the card. No separate info strip eating real estate.
  - Bottom gradient: dark → transparent, hosts title + meta + progress
  - Top gradient: dark → transparent, hosts score + ep-count badges
  - Rounded accent border drawn in paintEvent (curves with card corners)
  - Purple glow border when selected
  - Progress bar flush at the very bottom edge of the card
  - All text has background:transparent so it never creates boxes
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QProgressBar,
    QSizePolicy, QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import (
    QPixmap, QPainter, QPainterPath, QColor, QCursor, QFont, QPen, QRegion,
)
from ui.theme import QColor  # noqa: E402,F811  (theme-aware colours)

from core.database import DatabaseManager


# ── Border overlay ────────────────────────────────────────────────────────────

class _BorderOverlay(QWidget):
    """Paints the accent/hover border on top of the cover art."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        # Critical: prevents Qt from promoting this to a top-level window
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background:transparent;border:none;")

    def paintEvent(self, event):
        # parent() is _cover_w — need to go one more level up to AnimeCard
        cover_w = self.parent()
        if cover_w is None:
            return
        card = cover_w.parent()
        if card is None:
            return
        accent   = card.property("cardAccent") or ""
        selected = card.property("selected") == "true"
        hovered  = card.property("hovered") == "true"

        media = (getattr(card, "_anime", None) or {}).get("media_type") or "anime"
        lib = {"anime": "#8b7bff", "tv": "#38bdf8", "movie": "#fbbf24"}.get(media, "#8b7bff")
        if selected:
            border_color, width = QColor(lib), 2.5
        elif accent == "behind":
            border_color, width = QColor("#f87171"), 2.0          # new episode waiting
        elif accent == "incomplete":
            border_color, width = QColor(251, 191, 36, 200), 1.5
        elif hovered:
            border_color, width = QColor(255, 255, 255, 90), 1.2
        else:
            border_color, width = QColor(255, 255, 255, 26), 1.0   # premium hairline

        radius = getattr(card, "CARD_RADIUS", 10)
        inset  = (width / 2.0) + 0.5
        rect   = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        path   = QPainterPath()
        path.addRoundedRect(rect, radius - 1, radius - 1)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if hovered and not selected:
            p.fillPath(path, QColor(255, 255, 255, 12))           # gentle lift on hover
        pen = QPen(border_color, width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()

# ── Dropped-card helpers ──────────────────────────────────────────────────────

def _faded(pix: QPixmap) -> QPixmap:
    """Desaturated, dimmed copy of a cover (dropped cards)."""
    from PyQt6.QtGui import QImage
    img = pix.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
    out = QPixmap.fromImage(img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied))
    p = QPainter(out)
    p.fillRect(out.rect(), QColor(10, 12, 18, 95))
    p.end()
    return out


def _ago(ts) -> str:
    if not ts:
        return ""
    days = int((datetime.now().timestamp() - int(ts)) // 86400)
    if days < 1:
        return "today"
    if days < 30:
        return f"{days}d ago"
    if days < 365:
        return f"{days // 30} mo ago"
    return f"{days // 365}y ago"


# ── Countdown helper ──────────────────────────────────────────────────────────

def _format_countdown(
    seconds: int, next_ep_num: Optional[int] = None
) -> tuple[str, str]:
    """Return (display_text, color_hint)."""
    if seconds <= 0:
        if next_ep_num and next_ep_num > 1:
            return f"Ep {next_ep_num - 1} aired!", "aired"
        return "New ep aired!", "aired"
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s   = divmod(rem, 60)
    if d > 14:  return f"{d}d",          "far"
    elif d > 7: return f"{d}d {h}h",     "week"
    elif d > 0: return f"{d}d {h}h",     "soon"
    elif h > 0: return f"{h}h {m}m",     "imminent"
    else:       return f"{m}m {s:02d}s", "urgent"


_COUNTDOWN_COLORS: dict[str, str] = {
    "aired":    "#34d399",
    "urgent":   "#f87171",
    "imminent": "#fbbf24",
    "soon":     "#a594f9",
    "week":     "#38bdf8",
    "far":      "#9da5c0",
}


# ── Pixmap helpers ────────────────────────────────────────────────────────────

def _scale_crop(path: str, w: int, h: int) -> Optional[QPixmap]:
    px = QPixmap(path)
    if px.isNull():
        return None
    sc = px.scaled(w, h,
                   Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                   Qt.TransformationMode.SmoothTransformation)
    x = max(0, (sc.width()  - w) // 2)
    y = max(0, (sc.height() - h) // 2)
    return sc.copy(x, y, w, h)


# ── Card ──────────────────────────────────────────────────────────────────────

class _ClickBadge(QLabel):
    """Badge label that swallows its own click (so the card underneath
    doesn't also open the detail panel)."""
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class AnimeCard(QFrame):
    """
    Poster-style anime card.

    Cover art fills the full card area.  Info overlays the bottom
    via a dark gradient.  Badges overlay the top via a dark gradient.
    Progress bar sits flush at the bottom edge.
    """

    CARD_WIDTH   = 185
    CARD_HEIGHT  = 275
    COVER_HEIGHT = 275   # same as card — full bleed
    CARD_RADIUS  = 14

    clicked       = pyqtSignal(int)
    watch_toggled = pyqtSignal(int)
    quick_watched = pyqtSignal(int, str)    # library id, what was marked (e.g. "Ep 7")
    new_season_clicked = pyqtSignal(int)
    def __init__(self, anime: Dict[str, Any], db: DatabaseManager,
                 parent=None):
        super().__init__(parent)
        self.anime_id         = anime["id"]
        self._anime           = anime
        self._cover_faded     = None
        self._static_note     = ""
        self.db               = db
        self._next_ep_at: Optional[int] = None
        self._overlay_mode: Optional[str] = None

        self.setObjectName("animeCard")
        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("cardAccent", "")
        self.setProperty("selected", "false")
        self.setProperty("hovered", "false")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._build_ui()
        self._apply_rounded_mask()
        self.update_data(anime)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Full-bleed cover container ────────────────────────────────────
        self._cover_w = QWidget()
        self._cover_w.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self._cover_w.setStyleSheet("background:transparent;")
        # Ensure the card itself receives hover/click events
        self._cover_w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # Cover image label — fills entire card
        self.cover_label = QLabel(self._cover_w)
        self.cover_label.setObjectName("cardCover")
        self.cover_label.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._set_placeholder()

        # ── Top gradient — badge contrast ──────────────────────────────
        self._top_grad = QWidget(self._cover_w)
        self._top_grad.setFixedSize(self.CARD_WIDTH, 64)
        self._top_grad.move(0, 0)
        self._top_grad.setStyleSheet(
            "background:qlineargradient("
            "x1:0,y1:0,x2:0,y2:1,"
            "stop:0 rgba(0,0,0,0.88),"
            "stop:0.55 rgba(0,0,0,0.45),"
            "stop:1 rgba(0,0,0,0.0));"
        )
        self._top_grad.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # ── Bottom gradient — info overlay ─────────────────────────────
        self._bot_grad = QWidget(self._cover_w)
        self._bot_grad.setFixedSize(self.CARD_WIDTH, 130)
        self._bot_grad.move(0, self.CARD_HEIGHT - 130)
        self._bot_grad.setStyleSheet(
            "background:qlineargradient("
            "x1:0,y1:0,x2:0,y2:1,"
            "stop:0 rgba(0,0,0,0.0),"
            "stop:0.3 rgba(0,0,0,0.6),"
            "stop:1 rgba(0,0,0,0.97));"
        )
        self._bot_grad.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # ── TOP BADGES ─────────────────────────────────────────────────

        # Score badge — top-left
        self.score_badge_lbl = QLabel(self._cover_w)
        self.score_badge_lbl.setObjectName("coverScoreBadge")
        self.score_badge_lbl.setVisible(False)
        self.score_badge_lbl.move(8, 8)

        # Behind badge — top-left (replaces score)
        self.behind_badge_lbl = QLabel(self._cover_w)
        self.behind_badge_lbl.setObjectName("coverBehindBadge")
        self.behind_badge_lbl.setVisible(False)
        self.behind_badge_lbl.move(8, 8)

        # New-season ribbon — top-left, under any other badge
        self.new_season_badge = _ClickBadge(self._cover_w)
        self.new_season_badge.setObjectName("coverNewSeasonBadge")
        # Inline so the cover's blanket "background:transparent" can't win.
        self.new_season_badge.setStyleSheet(
            "QLabel{background-color:rgba(40,28,4,0.94);color:#fbbf24;"
            "border:1px solid rgba(251,191,36,0.60);border-radius:5px;"
            "font-size:10px;font-weight:800;padding:3px 2px;}"
            "QLabel:hover{background-color:rgba(74,52,8,0.97);}"
        )
        self.new_season_badge.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.new_season_badge.setVisible(False)
        # Bound method, not a lambda: a lambda closing over `self` keeps
        # discarded cards alive (and they then surface as stray windows).
        self.new_season_badge.clicked.connect(self._emit_new_season_clicked)

        # Ep count badge — top-right
        self.ep_cover_badge = QLabel(self._cover_w)
        self.ep_cover_badge.setObjectName("coverEpBadge")
        self.ep_cover_badge.setVisible(False)
        self.ep_cover_badge.move(0, 8)   # x set in update_data

        # ── BOTTOM INFO OVERLAY ────────────────────────────────────────

        self._info_w = QWidget(self._cover_w)
        self._info_w.setFixedWidth(self.CARD_WIDTH)
        self._info_w.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._info_w.setStyleSheet("background:transparent;")

        info_lay = QVBoxLayout(self._info_w)
        info_lay.setContentsMargins(12, 2, 12, 10)
        info_lay.setSpacing(5)
        info_lay.setAlignment(Qt.AlignmentFlag.AlignLeft)

        # Status badge (AIRING / PLANNED / etc.)
        self.status_badge = QLabel()
        f_badge = QFont()
        f_badge.setPointSize(7)
        f_badge.setWeight(QFont.Weight.Bold)
        self.status_badge.setFont(f_badge)
        self.status_badge.setFixedHeight(18)
        self.status_badge.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.status_badge.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
        info_lay.addWidget(self.status_badge, alignment=Qt.AlignmentFlag.AlignLeft)

        # Title
        self.title_label = QLabel()
        self.title_label.setObjectName("cardTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.title_label.setStyleSheet(
            "font-size:12px;font-weight:700;color:#f0f1f5;"
            "background:transparent;line-height:1.3;"
        )
        info_lay.addWidget(self.title_label, alignment=Qt.AlignmentFlag.AlignLeft)

        # Episode label
        self.ep_label = QLabel()
        self.ep_label.setObjectName("cardEpisode")
        self.ep_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.ep_label.setStyleSheet(
            "font-size:10px;color:#c0c4d6;background:transparent;"
        )
        info_lay.addWidget(self.ep_label, alignment=Qt.AlignmentFlag.AlignLeft)

        # Countdown
        self.countdown_label = QLabel()
        self.countdown_label.setObjectName("cardCountdown")
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.countdown_label.setStyleSheet(
            "font-size:10px;font-weight:600;color:#34d399;"
            "background:transparent;"
        )
        info_lay.addWidget(self.countdown_label, alignment=Qt.AlignmentFlag.AlignLeft)

        # Progress bar — flush at bottom of info area
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(
            "QProgressBar{background:rgba(255,255,255,0.12);"
            "border:none;border-radius:0;}"
            "QProgressBar::chunk{background:#7c6af7;border-radius:0;}"
        )
        info_lay.addSpacing(6)
        info_lay.addWidget(self.progress_bar)

        # Position info overlay at bottom of card
        self._info_w.adjustSize()
        self._info_w.move(0, self.CARD_HEIGHT - self._info_w.height())

        # Raise everything above gradients
        self._top_grad.raise_()
        self._bot_grad.raise_()
        self.score_badge_lbl.raise_()
        self.behind_badge_lbl.raise_()
        self.ep_cover_badge.raise_()
        self.new_season_badge.raise_()
        self._info_w.raise_()

        root.addWidget(self._cover_w)

        # Hover quick action: mark the next episode watched
        self._quick = None
        self.quick_btn = QPushButton("✓", self)
        self.quick_btn.setObjectName("cardQuickTick")
        self.quick_btn.setFixedSize(34, 34)
        self.quick_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.quick_btn.move(self.CARD_WIDTH - 44, 10)
        self.quick_btn.clicked.connect(self._do_quick)
        self.quick_btn.setVisible(False)

        # Border overlay — parented to _cover_w so it sits above the cover image
        self._border_overlay = _BorderOverlay(self._cover_w)
        self._border_overlay.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self._border_overlay.move(0, 0)
        self._border_overlay.raise_()

    def _apply_rounded_mask(self):
        """Clip all card content to rounded corners (card owns the radius)."""
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(0, 0, self.CARD_WIDTH, self.CARD_HEIGHT),
            self.CARD_RADIUS,
            self.CARD_RADIUS,
        )
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    # ── Cover ─────────────────────────────────────────────────────────────────

    def _set_placeholder(self):
        px = QPixmap(self.CARD_WIDTH, self.CARD_HEIGHT)
        px.fill(QColor("#131620"))
        p = QPainter(px)
        p.setPen(QColor("#2a2d42"))
        p.setFont(QFont("Segoe UI Emoji", 28))
        p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "📺")
        p.end()
        self.cover_label.setPixmap(px)

    def set_cover(self, path: str):
        if not path:
            return
        cropped = _scale_crop(path, self.CARD_WIDTH, self.CARD_HEIGHT)
        if not cropped:
            return
        self._cover_color = cropped
        self._cover_faded = None
        if (self._anime or {}).get("watch_status") == "dropped":
            self._cover_faded = _faded(cropped)
            self.cover_label.setPixmap(self._cover_faded)
        else:
            self.cover_label.setPixmap(cropped)

    # ── Overlay mode ──────────────────────────────────────────────────────────

    def set_overlay_mode(self, mode: Optional[str]):
        self._overlay_mode = mode
        self._refresh_overlay()

    def _refresh_overlay(self):
        if self._overlay_mode == "anilist_score":
            sc = self._anime.get("average_score")
            if sc:
                self.countdown_label.setText(f"★ {sc / 10:.1f}  AniList")
                self.countdown_label.setStyleSheet(
                    "font-size:10px;font-weight:600;color:#a594f9;"
                    "background:transparent;"
                )
            else:
                self.countdown_label.setText("No score")
                self.countdown_label.setStyleSheet(
                    "font-size:10px;color:#4a5070;background:transparent;"
                )
        elif self._overlay_mode == "user_rating":
            avg = self.db.get_average_rating(self.anime_id)
            if avg is not None:
                self.countdown_label.setText(f"★ {avg:.1f} / 6  yours")
                self.countdown_label.setStyleSheet(
                    "font-size:10px;font-weight:600;color:#fbbf24;"
                    "background:transparent;"
                )
            else:
                self.countdown_label.setText("Not rated")
                self.countdown_label.setStyleSheet(
                    "font-size:10px;color:#4a5070;background:transparent;"
                )
        else:
            self.tick_countdown()

    # ── Data update ───────────────────────────────────────────────────────────

    def update_data(self, anime: Dict[str, Any]):
        self._anime      = anime

        watched    = self.db.get_watched_count(anime["id"]) if anime["id"] > 0 else 0
        total      = anime.get("total_episodes") or 0
        next_ep    = anime.get("next_episode_num")
        ws         = anime.get("watch_status", "watching")
        api_status = (anime.get("status") or "").upper()

        # A finished/cancelled show has no real "next episode" — ignore any
        # stale next_episode_at left over from before it stopped airing.
        self._next_ep_at = (
            None if api_status in ("FINISHED", "CANCELLED")
            else anime.get("next_episode_at")
        )

        if total and api_status in ("FINISHED", "CANCELLED"):
            aired = total
        elif next_ep and next_ep > 1:
            aired = next_ep - 1
        else:
            aired = 0

        has_behind = aired > 0 and watched < aired
        is_ended = api_status in ("FINISHED", "CANCELLED")
        # Only flag as "behind" the urgent/airing way when the show is still
        # actually releasing episodes — a finished show with unwatched eps
        # is just backlog, not a new episode you're missing.
        still_airing_behind = has_behind and not is_ended
        # Marked "completed" by the user but episodes are still unwatched —
        # e.g. they clicked Complete early, or new episodes were retconned in.
        is_incomplete_completion = ws == "completed" and total and watched < total

        # ── Title ─────────────────────────────────────────────────────────
        title = anime.get("english_title") or anime.get("romaji_title", "")
        # Allow up to 2 lines — QLabel wordWrap handles it
        if len(title) > 36:
            title = title[:34] + "…"
        self.title_label.setText(title)
        self.title_label.setToolTip(
            f"{anime.get('romaji_title','')}  /  {anime.get('english_title','')}"
        )

        # ── Episode label ──────────────────────────────────────────────────
        self.ep_label.setStyleSheet(
            "font-size:10px;font-weight:700;color:#fbbf24;background:transparent;"
            if is_incomplete_completion else
            "font-size:10px;color:#c0c4d6;background:transparent;"
        )
        if ws == "completed":
            if is_incomplete_completion:
                self.ep_label.setText(f"{watched}/{total} eps · {total - watched} left")
            else:
                self.ep_label.setText(f"{watched}/{total or '?'} eps")
        elif ws == "watching":
            if aired:
                self.ep_label.setText(f"{watched}/{aired} aired")
            elif total:
                self.ep_label.setText(f"{watched}/{total} eps")
            else:
                self.ep_label.setText(f"{watched} watched")
        elif ws == "planned":
            if api_status == "NOT_YET_RELEASED":
                s_nm = (anime.get("season") or "").title()
                s_yr = anime.get("season_year") or ""
                self.ep_label.setText(f"{s_nm} {s_yr}".strip() or "TBA")
            elif is_ended:
                self.ep_label.setText(f"Finished · {total} eps" if total else "Finished airing")
            elif api_status == "RELEASING" and next_ep and next_ep > 1:
                self.ep_label.setText(f"{next_ep - 1} aired so far")
            elif total:
                self.ep_label.setText(f"{total} episodes")
            else:
                self.ep_label.setText("Plan to Watch")
        elif ws == "dropped":
            self.ep_label.setText(
                f"Dropped ep {watched}" if watched else "Dropped"
            )
        else:
            self.ep_label.setText(f"{watched} watched")

        # ── Status badge ───────────────────────────────────────────────────
        if ws == "completed" and is_incomplete_completion:
            n = total - watched
            self._set_badge("badgeIncomplete", f"{n} UNWATCHED")
        elif ws == "completed":
            self._set_badge("badgeCompleted", "FINISHED")
        elif ws == "planned" and api_status == "NOT_YET_RELEASED":
            self._set_badge("badgeUpcoming", "UPCOMING")
        elif ws == "planned" and is_ended:
            self._set_badge("badgeCompleted", "ENDED")
        elif ws == "planned" and api_status == "RELEASING":
            self._set_badge("badgeWatching", "AIRING")
        elif ws == "planned":
            self._set_badge("badgePlanned", "PLANNED")
        elif still_airing_behind:
            n = aired - watched
            self._set_badge("badgeAlert", f"+{n} EP{'S' if n > 1 else ''}")
        elif is_ended:
            self._set_badge("badgeCompleted", "FINISHED")
        else:
            self._set_badge("badgeWatching", "AIRING")

        # ── Card accent border (painted in paintEvent) ───────────────────
        if still_airing_behind and ws == "watching":
            accent = "behind"
        elif ws == "completed" and is_incomplete_completion:
            accent = "incomplete"
        elif ws == "completed" or (ws == "watching" and is_ended):
            accent = "completed"
        elif ws == "planned":
            accent = "planned"
        elif ws == "watching":
            accent = "airing"
        else:
            accent = ""
        self.setProperty("cardAccent", accent)
        self.update()
        if hasattr(self, "_border_overlay"):
            self._border_overlay.update()

        # ── Progress bar ───────────────────────────────────────────────────
        denom = total if total else (aired if aired else 1)
        self.progress_bar.setMaximum(denom)
        self.progress_bar.setValue(min(watched, denom))

        prog_color = (
            "#fbbf24" if is_incomplete_completion else
            "#34d399" if ws == "completed" else
            "#fbbf24" if has_behind       else
            "#7c6af7"
        )
        self.progress_bar.setStyleSheet(
            "QProgressBar{background:rgba(255,255,255,0.12);"
            "border:none;border-radius:0;}"
            f"QProgressBar::chunk{{background:{prog_color};border-radius:0;}}"
        )

        # ── Top badges ─────────────────────────────────────────────────────
        sc = anime.get("average_score")
        if still_airing_behind and ws == "watching":
            n = aired - watched
            self.behind_badge_lbl.setText(f"  {n} behind  ")
            self.behind_badge_lbl.adjustSize()
            self.behind_badge_lbl.setVisible(True)
            self.score_badge_lbl.setVisible(False)
        elif is_incomplete_completion:
            n = total - watched
            self.behind_badge_lbl.setText(f"  {n} unwatched  ")
            self.behind_badge_lbl.adjustSize()
            self.behind_badge_lbl.setVisible(True)
            self.score_badge_lbl.setVisible(False)
        elif sc and ws == "watching":
            self.score_badge_lbl.setText(f"  ★ {sc / 10:.1f}  ")
            self.score_badge_lbl.adjustSize()
            self.score_badge_lbl.setVisible(True)
            self.behind_badge_lbl.setVisible(False)
        else:
            self.score_badge_lbl.setVisible(False)
            self.behind_badge_lbl.setVisible(False)

        if ws == "watching" and (total or aired):
            denom_label = total or aired
            self.ep_cover_badge.setText(f"  {watched}/{denom_label}  ")
            self.ep_cover_badge.adjustSize()
            x = self.CARD_WIDTH - self.ep_cover_badge.width() - 8
            self.ep_cover_badge.move(x, 8)
            self.ep_cover_badge.setVisible(True)
        else:
            self.ep_cover_badge.setVisible(False)

        # ── Rewatches (Completed) ───────────────────────────────────────────
        if ws == "completed" and anime["id"] > 0 and not is_incomplete_completion:
            active = self.db.get_active_rewatch(anime["id"])
            times = 1 + self.db.rewatch_count(anime["id"])
            if active:
                prog = int(active.get("progress") or 0)
                self._set_badge("badgeWatching", f"↻ REWATCH {prog}/{total}" if total else "↻ REWATCHING")
                self.ep_label.setText(f"Rewatch #{active['number']} · ep {prog}")
                if total:
                    self.progress_bar.setMaximum(total)
                    self.progress_bar.setValue(min(prog, total))
                    self.progress_bar.setStyleSheet(
                        "QProgressBar{background:rgba(255,255,255,0.12);border:none;border-radius:0;}"
                        "QProgressBar::chunk{background:#7c6af7;border-radius:0;}")
            elif times > 1:
                self.ep_label.setText(f"{watched}/{total or '?'} eps · watched {times}×")

        # ── Dropped: stop point, how long ago, why ────────────────────────
        self._static_note = ""
        if ws == "dropped":
            last = anime.get("_last_episode") or 0
            ago = _ago(anime.get("_dropped_at"))
            self.ep_label.setText(
                (f"Stopped at ep {last}" if last else "Dropped before ep 1")
                + (f" · {ago}" if ago else ""))
            self.ep_label.setStyleSheet("font-size:10px;color:#c9a3aa;background:transparent;")
            self._set_badge("badgeDropped", "DROPPED")
            self.progress_bar.setVisible(False)
            reason = (anime.get("_drop_reason") or "").strip()
            if reason:
                short = reason if len(reason) <= 30 else reason[:28] + "…"
                self._static_note = f"“{short}”"
                self.countdown_label.setText(self._static_note)
                self.countdown_label.setStyleSheet(
                    "font-size:10px;font-style:italic;color:#8a90a8;background:transparent;")
            self.setProperty("cardAccent", "dropped")
            self.update()
            if hasattr(self, "_border_overlay"):
                self._border_overlay.update()
        else:
            self.progress_bar.setVisible(True)

        # ── Anime (Miroku): the Kinema card language ──────────────────
        self._cd_prefix = ""
        if (anime.get("media_type") or "anime") == "anime" and ws in ("watching", "planned", "completed"):
            self._apply_anime(anime, ws, api_status, watched, aired, total, next_ep,
                              is_ended, still_airing_behind, has_behind, is_incomplete_completion)

        # ── Movies (Kinema): runtime/year, release + verdict, no episodes ──
        if anime.get("media_type") == "movie":
            self._next_ep_at = None
            bits = []
            if anime.get("duration"):
                h, m = divmod(int(anime["duration"]), 60)
                bits.append(f"{h}h {m:02d}m" if h else f"{m}m")
            if anime.get("season_year"):
                bits.append(str(anime["season_year"]))
            if anime["id"] > 0:
                seen = 1 + self.db.rewatch_count(anime["id"]) if ws == "completed" else 0
                if seen > 1:
                    bits.append(f"seen {seen}×")
            self.ep_label.setText("  ·  ".join(bits))
            self.ep_label.setStyleSheet("font-size:10px;color:#c0c4d6;background:transparent;")
            from core.kinema_sync import release_state
            rs = release_state(anime)
            def _d(ts):
                d = datetime.fromtimestamp(ts)
                return d.strftime("%b ") + str(d.day)
            note, note_color = "", "#9da5c0"
            if ws == "completed":
                self._set_badge("badgeCompleted", "WATCHED")
                mine = self.db.get_overall_rating(anime["id"]) if anime["id"] > 0 else None
                if mine:
                    note, note_color = f"★ {mine:.0f}/6 · your rating", "#fbbf24"
                accent = "completed"
            elif rs["state"] == "digital":
                self._set_badge("badgeCompleted", "READY TO WATCH")
                note, note_color = ("Out in HD since " + _d(rs["digital_ts"]) if rs["digital_ts"]
                                    else "Out in HD"), "#34d399"
                accent = "completed"
            elif rs["state"] == "cinema":
                self._set_badge("badgeUpcoming", "IN CINEMAS")
                now = int(datetime.now().timestamp())
                if rs["digital_ts"] and rs["digital_ts"] > now:
                    days = max(1, round((rs["digital_ts"] - now) / 86400))
                    note = f"HD {_d(rs['digital_ts'])} · in {days} day{'s' if days != 1 else ''}"
                else:
                    note = "HD date not announced yet"
                note_color = "#fbbf24"
                accent = "planned"
            else:
                self._set_badge("badgeUpcoming", "COMING SOON")
                if rs["cinema_ts"]:
                    note, note_color = f"In cinemas {_d(rs['cinema_ts'])}, {datetime.fromtimestamp(rs['cinema_ts']).year}", "#fbbf24"
                accent = "planned"
            self._static_note = note
            self.countdown_label.setText(note)
            self.countdown_label.setStyleSheet(
                f"font-size:10px;font-weight:600;color:{note_color};background:transparent;")
            for w in (self.progress_bar, self.behind_badge_lbl, self.score_badge_lbl,
                      self.ep_cover_badge):
                w.setVisible(False)
            self.setProperty("cardAccent", accent)
            self.update()
            if hasattr(self, "_border_overlay"):
                self._border_overlay.update()

        # ── TV shows (Kinema): S·E progress, new episodes, next airing ────
        if anime.get("media_type") == "tv":
            self._apply_tv(anime, ws, api_status)

        # Corner chips are folded into the text lines now (Kinema style)
        self._top_grad.setVisible(False)

        # Reposition info overlay after text reflows
        self._info_w.adjustSize()
        self._info_w.move(0, self.CARD_HEIGHT - self._info_w.height())
        self._info_w.raise_()

        self._refresh_overlay()
        self.refresh_links()
        self._compute_quick(anime)

    def _apply_anime(self, anime, ws, api_status, watched, aired, total, next_ep,
                     is_ended, still_airing_behind, has_behind, incomplete):
        """Same reading order as TV cards: badge, where you are, what's next.
        Score, counts and 'behind' move from corner chips into the text."""
        sc = anime.get("average_score")
        star = f"  ·  ★ {sc / 10:.1f}" if sc else ""
        for w in (self.behind_badge_lbl, self.score_badge_lbl, self.ep_cover_badge):
            w.setVisible(False)
        rewatch = ws == "completed" and anime["id"] > 0 and self.db.get_active_rewatch(anime["id"])
        if ws == "watching":
            denom = total or aired
            reach = aired or total
            left = max(0, (aired or 0) - watched) if aired else 0
            if reach and watched < reach:
                line = f"Next Ep {watched + 1}  ·  {watched}/{denom}"
            elif denom:
                line = f"Caught up  ·  {watched}/{denom}"
            else:
                line = f"{watched} watched"
            self.ep_label.setText(line + star)
            self.ep_label.setStyleSheet("font-size:10px;color:#c0c4d6;background:transparent;")
            if still_airing_behind:
                self._set_badge("badgeAlert", "NEW EPISODE" if left == 1 else f"+{left} NEW")
            elif has_behind:
                self._set_badge("badgeWatching", f"{left} TO WATCH")
            elif self._next_ep_at:
                self._set_badge("badgeCompleted", "UP TO DATE")
            elif is_ended:
                self._set_badge("badgeCompleted", "FINISHED")
            else:
                self._set_badge("badgeWatching", "AIRING")
            mins = left * (anime.get("duration") or 24)
            h, m = divmod(mins, 60)
            time_left = f"about {h}h {m:02d}m" if h else f"about {m}m"
            if self._next_ep_at and left:
                self._cd_prefix = f"{left} left  ·  next "
            elif self._next_ep_at:
                self._cd_prefix = f"Ep {next_ep} airs " if next_ep else "Next ep "
            elif left:
                self._static_note = f"{left} left  ·  {time_left}"
                self.countdown_label.setText(self._static_note)
                self.countdown_label.setStyleSheet(
                    "font-size:10px;font-weight:600;color:#a594f9;background:transparent;")
            colour = "#f87171" if still_airing_behind else "#8b7bff"
        elif ws == "planned":
            self.ep_label.setText(self.ep_label.text() + star)
            if self._next_ep_at:
                self._cd_prefix = (f"Ep {next_ep} airs " if next_ep and next_ep > 1 else "Premieres ")
            colour = "#8b7bff"
        else:
            mine = self.db.get_overall_rating(anime["id"]) if anime["id"] > 0 else None
            if mine and not rewatch and not incomplete:
                self._static_note = f"★ {mine:.0f}/6  ·  your rating"
                self.countdown_label.setText(self._static_note)
                self.countdown_label.setStyleSheet(
                    "font-size:10px;font-weight:600;color:#fbbf24;background:transparent;")
            colour = "#fbbf24" if incomplete else "#34d399"
            if rewatch:
                colour = "#8b7bff"
        self.progress_bar.setStyleSheet(
            "QProgressBar{background:rgba(255,255,255,0.12);border:none;border-radius:0;}"
            f"QProgressBar::chunk{{background:{colour};border-radius:0;}}")

    def _apply_tv(self, anime: Dict[str, Any], ws: str, api_status: str):
        self._next_ep_at = None
        p = self.db.tv_progress(anime["id"]) if anime["id"] > 0 else {
            "total": 0, "aired": 0, "watched": 0, "unwatched_aired": 0,
            "next": None, "last": None, "upcoming": None}
        code = lambda e: f"S{e['season_number']:02d}E{e['episode_number']:02d}"
        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        ended = api_status in ("FINISHED", "CANCELLED")
        n_left = p["unwatched_aired"]

        # line 1: where you are
        if ws == "watching" and p["next"]:
            ep = f"Next {code(p['next'])}"
        elif ws == "watching" and p["watched"]:
            ep = "Caught up"
        elif ws == "completed":
            ep = f"{p['watched']} episodes watched"
        else:
            ep = f"{p['total']} episodes" if p["total"] else "No episodes listed yet"
        if p["aired"] and ws in ("watching", "dropped"):
            ep += f"  ·  {p['watched']}/{p['aired']}"
        self.ep_label.setText(ep)
        self.ep_label.setStyleSheet("font-size:10px;color:#c0c4d6;background:transparent;")

        # badge
        fresh = ws == "watching" and n_left and p["next"] and any(
            not e.get("watched") and e.get("air_date") and week_ago <= e["air_date"] <= today
            for e in self.db.get_tv_episodes(anime["id"], (p["last"] or p["next"])["season_number"]))
        if ws == "completed":
            self._set_badge("badgeCompleted", "COMPLETED"); accent = "completed"
        elif ws == "dropped":
            self._set_badge("badgeDropped", "DROPPED"); accent = "dropped"
        elif ws == "planned":
            if api_status == "NOT_YET_RELEASED" or not p["aired"]:
                self._set_badge("badgeUpcoming", "COMING SOON")
            elif ended:
                self._set_badge("badgeCompleted", "ENDED")
            else:
                self._set_badge("badgeWatching", "AIRING")
            accent = "planned"
        elif fresh:
            self._set_badge("badgeAlert", f"+{n_left} NEW" if n_left > 1 else "NEW EPISODE")
            accent = "behind"
        elif n_left:
            self._set_badge("badgeWatching", f"{n_left} TO WATCH"); accent = "airing"
        elif p["upcoming"]:
            self._set_badge("badgeCompleted", "UP TO DATE"); accent = "airing"
        else:
            self._set_badge("badgeWatching", "BETWEEN SEASONS" if not ended else "ENDED")
            accent = "airing"

        # line 2: next airing / show state
        note, color = "", "#9da5c0"
        up = p["upcoming"]
        if up and ws != "dropped":
            d = datetime.strptime(up["air_date"], "%Y-%m-%d")
            days = (d.date() - datetime.now().date()).days
            when = "today" if days == 0 else ("tomorrow" if days == 1 else f"in {days} days")
            label = ("Season " + str(up["season_number"]) + " premieres"
                     if up["episode_number"] == 1 else code(up))
            note, color = f"{label} {d.strftime('%b ')}{d.day} · {when}", "#38bdf8"
        elif ws == "watching" and n_left:
            mins = n_left * (anime.get("duration") or 45)
            h, m = divmod(mins, 60)
            note = f"{n_left} left · about {h}h {m:02d}m" if h else f"{n_left} left · about {m}m"
        elif ended:
            note = "Show ended" if api_status == "FINISHED" else "Cancelled"
        elif p["total"]:
            note = "Next season not dated yet"
        self._static_note = note
        self.countdown_label.setText(note)
        self.countdown_label.setStyleSheet(
            f"font-size:10px;font-weight:600;color:{color};background:transparent;")

        for w in (self.behind_badge_lbl, self.score_badge_lbl, self.ep_cover_badge):
            w.setVisible(False)
        denom = p["aired"] or p["total"] or 1
        self.progress_bar.setMaximum(denom)
        self.progress_bar.setValue(min(p["watched"], denom))
        self.progress_bar.setVisible(ws in ("watching", "completed", "dropped") and p["watched"] > 0)
        pc = {"completed": "#34d399", "dropped": "#b5485a"}.get(ws, "#38bdf8")
        self.progress_bar.setStyleSheet(
            "QProgressBar{background:rgba(255,255,255,0.12);border:none;border-radius:0;}"
            f"QProgressBar::chunk{{background:{pc};border-radius:0;}}")
        self.setProperty("cardAccent", accent)
        self.update()
        if hasattr(self, "_border_overlay"):
            self._border_overlay.update()

    def refresh_links(self):
        has_links = self.anime_id > 0 and self.db.has_anime_links(self.anime_id)
        return

    def _open_links_menu(self):
        from ui.anime_links import LinkOpenMenu
        links = self.db.get_anime_links(self.anime_id)
        if not links:
            return
        if len(links) == 1:
            from core.link_opener import open_link, detect_platform
            link = links[0]
            open_link(link["url"], platform=link.get("platform") or detect_platform(link["url"]))
            return
        menu = LinkOpenMenu(self.anime_id, self.db, self)
        menu.links_changed.connect(self.refresh_links)
        menu.exec(self.mapToGlobal(self.rect().center()))

    _PILLS = {
        # object name: (text colour, tint)
        "badgeWatching":   ("#e2ddff", "rgba(139,123,255,0.30)"),
        "badgeAlert":      ("#ffe1e1", "rgba(248,113,113,0.42)"),
        "badgeCompleted":  ("#d2fbe7", "rgba(52,211,153,0.30)"),
        "badgeDropped":    ("#f5c2ca", "rgba(181,72,90,0.40)"),
        "badgeIncomplete": ("#fff1c2", "rgba(251,191,36,0.34)"),
        "badgePlanned":    ("#f1efff", "rgba(157,143,255,0.26)"),
        "badgeUpcoming":   ("#fff1c2", "rgba(251,191,36,0.30)"),
    }

    def _set_badge(self, obj_name: str, text: str):
        self.status_badge.setObjectName(obj_name)
        self.status_badge.setText(text)
        fg, tint = self._PILLS.get(obj_name, ("#e8eaf2", "rgba(255,255,255,0.12)"))
        # Glass pill: dark base for contrast on any art, tinted by state.
        self.status_badge.setStyleSheet(
            f"background-color:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {tint},stop:1 rgba(8,9,14,0.86));"
            f"color:{fg};border:1px solid rgba(255,255,255,0.10);border-radius:9px;"
            "font-size:9px;font-weight:800;padding:2px 9px;letter-spacing:0.8px;")
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)
        self.status_badge.adjustSize()

    # ── Countdown ─────────────────────────────────────────────────────────────

    def tick_countdown(self):
        if self._overlay_mode:
            return
        if not self._next_ep_at:
            if not getattr(self, "_static_note", ""):
                self.countdown_label.setText("")
            return
        secs    = self._next_ep_at - int(datetime.now(timezone.utc).timestamp())
        next_ep = self._anime.get("next_episode_num") if self._anime else None
        text, hint = _format_countdown(secs, next_ep)
        color      = _COUNTDOWN_COLORS.get(hint, "#9da5c0")
        prefix = getattr(self, "_cd_prefix", "")
        if prefix and secs > 0:
            text = f"{prefix}in {text}"
        self.countdown_label.setText(text)
        self.countdown_label.setStyleSheet(
            f"font-size:10px;font-weight:600;color:{color};"
            "background:transparent;"
        )
        self._info_w.adjustSize()
        self._info_w.move(0, self.CARD_HEIGHT - self._info_w.height())

    # ── Selection ─────────────────────────────────────────────────────────────

    def set_selected(self, selected: bool):
        self.setProperty("selected", "true" if selected else "false")
        self.update()
        if hasattr(self, "_border_overlay"):
            self._border_overlay.update()

    def _compute_quick(self, anime: Dict[str, Any]):
        """What one click marks: the next aired episode of something you're watching."""
        self._quick = None
        if anime.get("id", 0) <= 0 or anime.get("watch_status") != "watching":
            return
        media = anime.get("media_type") or "anime"
        if media == "tv":
            nxt = self.db.tv_progress(anime["id"])["next"]
            if nxt:
                self._quick = ("tv", nxt["season_number"], nxt["episode_number"])
        elif media == "anime":
            total = anime.get("total_episodes") or 0
            n_next = anime.get("next_episode_num")
            ended = (anime.get("status") or "").upper() in ("FINISHED", "CANCELLED")
            aired = total if (total and (ended or not n_next)) else (n_next - 1 if n_next and n_next > 1 else 0)
            watched = {e["episode_num"] for e in self.db.get_episodes(anime["id"]) if e.get("watched")}
            n = next((k for k in range(1, aired + 1) if k not in watched), None)
            if n:
                self._quick = ("anime", n)
        if self._quick:
            label = (f"S{self._quick[1]:02d}E{self._quick[2]:02d}" if self._quick[0] == "tv"
                     else f"Episode {self._quick[1] + (anime.get('episode_offset') or 0)}")
            self.quick_btn.setToolTip(f"Mark {label} watched")

    def _do_quick(self):
        q = self._quick
        if not q:
            return
        if q[0] == "tv":
            self.db.set_tv_episode_watched(self.anime_id, q[1], q[2], True)
            what = f"S{q[1]:02d}E{q[2]:02d}"
        else:
            self.db.set_episode_watched(self.anime_id, q[1], True)
            what = f"Episode {q[1] + (self._anime.get('episode_offset') or 0)}"
        fresh = self.db.get_anime_by_id(self.anime_id)
        if fresh:
            self.update_data(fresh)
        self.quick_btn.setVisible(bool(self._quick) and self.underMouse())
        self.quick_watched.emit(self.anime_id, what)

    def enterEvent(self, event):
        if self._quick and not self._overlay_mode:
            self.quick_btn.setVisible(True)
            self.quick_btn.raise_()
        if getattr(self, "_cover_faded", None) is not None:
            self.cover_label.setPixmap(self._cover_color)   # colour comes back on hover
        self.setProperty("hovered", "true")
        self.update()
        if hasattr(self, "_border_overlay"):
            self._border_overlay.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.quick_btn.setVisible(False)
        if getattr(self, "_cover_faded", None) is not None:
            self.cover_label.setPixmap(self._cover_faded)
        self.setProperty("hovered", "false")
        self.update()
        if hasattr(self, "_border_overlay"):
            self._border_overlay.update()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        self.update()
        if hasattr(self, "_border_overlay"):
            self._border_overlay.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.update()
        if hasattr(self, "_border_overlay"):
            self._border_overlay.update()
        super().focusOutEvent(event)

    def paintEvent(self, event):
        # Base painting only; border is painted by the overlay widget above cover.
        super().paintEvent(event)

    def _emit_new_season_clicked(self):
        self.new_season_clicked.emit(self.anime_id)

    def set_new_season_badge(self, text: Optional[str], tooltip: str = ""):
        """Show/hide the amber "new season" ribbon (None hides it)."""
        if not text:
            self.new_season_badge.setVisible(False)
            return
        self.new_season_badge.setText(f"  ✦ {text}  ")
        self.new_season_badge.setToolTip(tooltip)
        self.new_season_badge.adjustSize()
        y = 8
        for other in (self.behind_badge_lbl, self.score_badge_lbl):
            if other.isVisibleTo(self):
                y = other.y() + other.height() + 6
        self.new_season_badge.move(8, y)
        self.new_season_badge.setVisible(True)
        self.new_season_badge.raise_()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.anime_id)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        if self.anime_id > 0 and self.db.has_anime_links(self.anime_id):
            self._open_links_menu()
            event.accept()
            return
        super().contextMenuEvent(event)
