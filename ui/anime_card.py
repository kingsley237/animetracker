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
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QProgressBar,
    QSizePolicy, QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import (
    QPixmap, QPainter, QPainterPath, QColor, QCursor, QFont, QPen, QRegion,
)

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

        if selected:
            border_color, width = QColor("#b8a8ff"), 2.5
        elif hovered:
            border_color, width = QColor("#6b5fc4"), 2.0
        elif accent == "behind":
            border_color, width = QColor("#f87171"), 2.0
        elif accent == "airing":
            border_color, width = QColor("#7c6af7"), 1.5
        elif accent == "planned":
            border_color, width = QColor("#9d8fff"), 1.5
        elif accent == "completed":
            border_color, width = QColor("#34d399"), 1.5
        elif accent == "incomplete":
            border_color, width = QColor("#fbbf24"), 2.0
        else:
            border_color, width = QColor("#2a3048"), 1.0

        radius = getattr(card, "CARD_RADIUS", 10)
        inset  = (width / 2.0) + 0.5
        rect   = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        path   = QPainterPath()
        path.addRoundedRect(rect, radius - 1, radius - 1)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(border_color, width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()

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
    CARD_RADIUS  = 10

    clicked       = pyqtSignal(int)
    watch_toggled = pyqtSignal(int)
    def __init__(self, anime: Dict[str, Any], db: DatabaseManager,
                 parent=None):
        super().__init__(parent)
        self.anime_id         = anime["id"]
        self._anime           = anime
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
        self._info_w.raise_()

        root.addWidget(self._cover_w)

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

        # Top overlay: you requested it to be present on Watching cards only.
        # (Planned cards do not have any top-right text; keep them clean.)
        self._top_grad.setVisible(ws == "watching")

        # Reposition info overlay after text reflows
        self._info_w.adjustSize()
        self._info_w.move(0, self.CARD_HEIGHT - self._info_w.height())
        self._info_w.raise_()

        self._refresh_overlay()
        self.refresh_links()

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

    def _set_badge(self, obj_name: str, text: str):
        self.status_badge.setObjectName(obj_name)
        self.status_badge.setText(text)
        # High-contrast pills so status is readable on any cover art
        if obj_name == "badgeWatching":
            self.status_badge.setStyleSheet(
                "background-color:rgba(6,8,16,0.94);"
                "color:#d7d2ff;"
                "border:1px solid #7c6af7;"
                "border-radius:4px;"
                "font-size:9px;font-weight:700;"
                "padding:2px 8px;letter-spacing:0.6px;"
            )
        elif obj_name == "badgeAlert":
            self.status_badge.setStyleSheet(
                "background-color:rgba(6,8,16,0.94);"
                "color:#fecaca;"
                "border:1px solid #f87171;"
                "border-radius:4px;"
                "font-size:9px;font-weight:700;"
                "padding:2px 8px;letter-spacing:0.6px;"
            )
        elif obj_name == "badgeCompleted":
            self.status_badge.setStyleSheet(
                "background-color:rgba(6,8,16,0.94);"
                "color:#bbf7d0;"
                "border:1px solid #34d399;"
                "border-radius:4px;"
                "font-size:9px;font-weight:700;"
                "padding:2px 8px;letter-spacing:0.6px;"
            )
        elif obj_name == "badgeIncomplete":
            # Distinct from FINISHED (green) and AIRING alert (red) — this
            # means the user marked it complete but hasn't watched everything.
            self.status_badge.setStyleSheet(
                "background-color:rgba(6,8,16,0.94);"
                "color:#fde68a;"
                "border:1px solid #fbbf24;"
                "border-radius:4px;"
                "font-size:9px;font-weight:700;"
                "padding:2px 8px;letter-spacing:0.6px;"
            )
        elif obj_name == "badgePlanned":
            self.status_badge.setStyleSheet(
                "background-color:rgba(6,8,16,0.94);"
                "color:#f4f2ff;"
                "border:1px solid #9d8fff;"
                "border-radius:4px;"
                "font-size:9px;font-weight:700;"
                "padding:2px 8px;letter-spacing:0.6px;"
            )
        elif obj_name == "badgeUpcoming":
            self.status_badge.setStyleSheet(
                "background-color:rgba(6,8,16,0.94);"
                "color:#fde68a;"
                "border:1px solid #fbbf24;"
                "border-radius:4px;"
                "font-size:9px;font-weight:700;"
                "padding:2px 8px;letter-spacing:0.6px;"
            )
        else:
            self.status_badge.setStyleSheet("")
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)
        self.status_badge.adjustSize()

    # ── Countdown ─────────────────────────────────────────────────────────────

    def tick_countdown(self):
        if self._overlay_mode:
            return
        if not self._next_ep_at:
            self.countdown_label.setText("")
            return
        secs    = self._next_ep_at - int(datetime.now(timezone.utc).timestamp())
        next_ep = self._anime.get("next_episode_num") if self._anime else None
        text, hint = _format_countdown(secs, next_ep)
        color      = _COUNTDOWN_COLORS.get(hint, "#9da5c0")
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

    def enterEvent(self, event):
        self.setProperty("hovered", "true")
        self.update()
        if hasattr(self, "_border_overlay"):
            self._border_overlay.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
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
