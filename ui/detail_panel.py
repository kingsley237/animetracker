"""
Miroku — Detail Panel
Fixed:
  - Episodes only shown up to last aired (next_episode_num - 1)
  - Cannot rate an episode that hasn't aired yet
  - Per-episode rating + overall anime rating
  - Synopsis/meta fetched from AniList if missing (imported anime)
  - Status change emits signal immediately (real-time card update)
"""
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QPushButton, QSizePolicy, QMessageBox, QDialog,
    QTextEdit, QDialogButtonBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QColor, QPainter, QPainterPath, QCursor, QFont

from core.database import DatabaseManager

RATING_LABELS = {
    1: "Terrible",
    2: "Bad",
    3: "Fair",
    4: "Good",
    5: "Great",
    6: "Masterpiece",
}

WATCH_STATUS_LABELS = {
    "watching": "Watching",
    "completed": "Completed",
    "planned": "Plan to Watch",
    "dropped": "Dropped",
}

def _strip_html(txt: str) -> str:
    return re.sub(r"<[^>]+>", "", txt or "")

def _score_color(s: float) -> str:
    if s >= 8: return "#a594f9"
    if s >= 6: return "#34d399"
    if s >= 4: return "#fbbf24"
    return "#f87171"


class DetailPanel(QWidget):
    episode_changed       = pyqtSignal(int)   # anime_id — card + stats strip refresh
    stats_changed         = pyqtSignal()      # status changed → stats strip
    watch_status_changed  = pyqtSignal(int, str)  # anime_id, new watch_status
    anime_dropped    = pyqtSignal(int)
    anime_deleted    = pyqtSignal(int)
    close_requested  = pyqtSignal()
    links_changed    = pyqtSignal()

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self._anime: Optional[Dict] = None
        self._ep_rows: Dict[int, "_EpRow"] = {}
        self.setObjectName("detailPanel")
        self.setFixedWidth(390)
        self._build_ui()

    # ── build ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(14, 12, 14, 10)
        top_bar.setSpacing(8)

        panel_title = QLabel("Details")
        panel_title.setObjectName("detailPanelTitle")
        top_bar.addWidget(panel_title)
        top_bar.addStretch()

        x = QPushButton("X")
        x.setObjectName("iconBtn")
        x.setFixedSize(28, 28)
        x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x.clicked.connect(self.close_requested.emit)
        top_bar.addWidget(x)
        outer.addLayout(top_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        body = QWidget()
        self._lay = QVBoxLayout(body)
        self._lay.setContentsMargins(14, 0, 14, 18)
        self._lay.setSpacing(12)

        # Banner
        self.banner_lbl = QLabel()
        self.banner_lbl.setObjectName("detailHeroBanner")
        self.banner_lbl.setFixedHeight(132)
        self.banner_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lay.addWidget(self.banner_lbl)

        # Cover + title
        hdr = QFrame()
        hdr.setObjectName("detailSummaryCard")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 14, 14, 14)
        hl.setSpacing(12)

        self.cover_lbl = QLabel()
        self.cover_lbl.setObjectName("detailCover")
        self.cover_lbl.setFixedSize(88, 128)
        self.cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(self.cover_lbl)

        tb = QVBoxLayout()
        tb.setSpacing(5)
        tb.setContentsMargins(0, 0, 0, 0)

        self.title_lbl = QLabel()
        self.title_lbl.setObjectName("detailTitle")
        self.title_lbl.setWordWrap(True)
        tb.addWidget(self.title_lbl)

        self.eng_lbl = QLabel()
        self.eng_lbl.setObjectName("detailEngTitle")
        self.eng_lbl.setWordWrap(True)
        tb.addWidget(self.eng_lbl)

        self.studio_lbl = QLabel()
        self.studio_lbl.setObjectName("detailStudio")
        self.studio_lbl.setWordWrap(True)
        tb.addWidget(self.studio_lbl)

        tb.addSpacing(6)

        metrics = QHBoxLayout()
        metrics.setSpacing(10)

        score_box = QFrame()
        score_box.setObjectName("detailMetricBox")
        sc_col = QVBoxLayout(score_box)
        sc_col.setContentsMargins(10, 8, 10, 8)
        sc_col.setSpacing(0)
        self.score_lbl = QLabel("–")
        self.score_lbl.setObjectName("detailScore")
        self.score_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sc_col.addWidget(self.score_lbl)
        sl = QLabel("SCORE")
        sl.setObjectName("detailScoreLabel")
        sl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sc_col.addWidget(sl)
        metrics.addWidget(score_box)

        self.meta_lbl = QLabel()
        self.meta_lbl.setObjectName("detailMeta")
        self.meta_lbl.setWordWrap(True)
        metrics.addWidget(self.meta_lbl, stretch=1)
        tb.addLayout(metrics)

        hl.addLayout(tb, stretch=1)
        self._lay.addWidget(hdr)

        # Progress info — last watched + next airing (clear, separate lines)
        self.progress_info_lbl = QLabel()
        self.progress_info_lbl.setObjectName("detailProgressCard")
        self.progress_info_lbl.setWordWrap(True)
        self.progress_info_lbl.setVisible(False)
        self._lay.addWidget(self.progress_info_lbl)

        # Genres
        self.genres_w = QWidget()
        self.genres_l = QHBoxLayout(self.genres_w)
        self.genres_l.setContentsMargins(0, 0, 0, 0)
        self.genres_l.setSpacing(6)
        self.genres_l.addStretch()
        self._lay.addWidget(self.genres_w)

        # Synopsis
        synopsis_card = self._detail_card("Synopsis")
        synopsis_lay = synopsis_card.layout()
        self.synopsis_lbl = QLabel()
        self.synopsis_lbl.setObjectName("detailSynopsis")
        self.synopsis_lbl.setWordWrap(True)
        self.synopsis_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        synopsis_lay.addWidget(self.synopsis_lbl)
        self._lay.addWidget(synopsis_card)

        # Quick links (streaming, Telegram, etc.)
        links_card = self._detail_card("Quick links")
        from ui.anime_links import LinksManagerWidget
        self.links_manager = LinksManagerWidget(self.db)
        self.links_manager.links_changed.connect(self.links_changed.emit)
        links_card.layout().addWidget(self.links_manager)
        self._lay.addWidget(links_card)

        # Status actions
        actions_card = self._detail_card("Actions")
        arl = QHBoxLayout()
        arl.setContentsMargins(0, 0, 0, 0)
        arl.setSpacing(8)

        self.status_btn = QPushButton("Watching")
        self.status_btn.setObjectName("secondaryBtn")
        self.status_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.status_btn.clicked.connect(self._cycle_status)
        arl.addWidget(self.status_btn)

        drop_btn = QPushButton("Drop")
        drop_btn.setObjectName("dangerBtn")
        drop_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        drop_btn.clicked.connect(self._drop)
        arl.addWidget(drop_btn)

        del_btn = QPushButton("Delete")
        del_btn.setObjectName("dangerBtn")
        del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        del_btn.clicked.connect(self._delete)
        arl.addWidget(del_btn)
        actions_card.layout().addLayout(arl)
        self._lay.addWidget(actions_card)

        # Overall rating
        rating_card = self._detail_card("Overall rating")
        self.overall_rating = _RatingWidget(self.db, overall=True)
        self.overall_rating.rated.connect(self._on_overall_rated)
        rating_card.layout().addWidget(self.overall_rating)
        self._lay.addWidget(rating_card)

        # Episodes
        episodes_card = self._detail_card("")
        episodes_lay = episodes_card.layout()
        ep_hdr = QHBoxLayout()
        ep_hdr.setContentsMargins(0, 0, 0, 0)
        ep_hdr.addWidget(self._section_label("Episodes"))
        ep_hdr.addStretch()
        self.mark_all_btn = QPushButton("Mark watched")
        self.mark_all_btn.setObjectName("secondaryBtn")
        self.mark_all_btn.setStyleSheet(
            self.mark_all_btn.styleSheet() + "font-size:11px;padding:4px 10px;"
        )
        self.mark_all_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.mark_all_btn.clicked.connect(self._mark_all)
        ep_hdr.addWidget(self.mark_all_btn)
        episodes_lay.addLayout(ep_hdr)

        # Episode list container
        self.ep_container = QWidget()
        self.ep_vbox = QVBoxLayout(self.ep_container)
        self.ep_vbox.setContentsMargins(0, 0, 0, 0)
        self.ep_vbox.setSpacing(5)
        episodes_lay.addWidget(self.ep_container)
        self._lay.addWidget(episodes_card)
        self._lay.addStretch()

        scroll.setWidget(body)
        outer.addWidget(scroll)

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("detailSectionLabel")
        return lbl

    def _detail_card(self, title: str) -> QFrame:
        card = QFrame()
        card.setObjectName("detailCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        if title:
            lay.addWidget(self._section_label(title))
        return card

    # ── load ───────────────────────────────────────────────────────────────────

    def load_anime(self, anime: Dict):
        self._anime = anime
        aid = anime["id"]

        self.title_lbl.setText(anime.get("romaji_title", ""))
        eng = anime.get("english_title", "")
        show_eng = bool(eng and eng != anime.get("romaji_title"))
        self.eng_lbl.setText(eng if show_eng else "")
        self.eng_lbl.setVisible(show_eng)

        studios = anime.get("studios") or []
        self.studio_lbl.setText(", ".join(studios) if studios else "")

        sc = anime.get("average_score")
        if sc:
            self.score_lbl.setText(f"{sc/10:.1f}")
            self.score_lbl.setStyleSheet(
                f"font-size:22px;font-weight:700;color:{_score_color(sc/10)};"
            )
        else:
            self.score_lbl.setText("–")
            self.score_lbl.setStyleSheet("")

        total  = anime.get("total_episodes") or 0
        season = (anime.get("season") or "").title()
        year   = anime.get("season_year") or ""
        api_status = (anime.get("status") or "").upper()
        status_display = api_status.replace("_", " ").title()

        # Episode progress line
        next_ep    = anime.get("next_episode_num")
        next_ep_at = anime.get("next_episode_at")
        watched    = self.db.get_watched_count(anime["id"]) if anime.get("id") and anime["id"] > 0 else 0

        if total and api_status in ("FINISHED", "CANCELLED"):
            aired = total
        elif next_ep and next_ep > 1:
            aired = next_ep - 1
        else:
            aired = 0

        meta_parts = []
        if season or year:
            meta_parts.append(f"{season} {year}".strip())
        if total:
            meta_parts.append(f"{total} episodes total")
        meta_parts.append(status_display)
        self.meta_lbl.setText("  ·  ".join(meta_parts))

        # ── Progress block — clear, unambiguous ──────────────────────
        # Show: last watched ep + next airing ep separately
        detail_ws = anime.get("watch_status", "watching")
        is_incomplete_completion = detail_ws == "completed" and total and watched < total

        prog_lines = []
        if is_incomplete_completion:
            prog_lines.append(
                f"⚠ Marked Completed but {total - watched} episode(s) unwatched "
                f"({watched}/{total})"
            )
        elif watched > 0:
            prog_lines.append(f"Last watched: Episode {watched}")
        elif aired > 0:
            prog_lines.append("Not started yet")

        if next_ep and next_ep_at and api_status not in ("FINISHED", "CANCELLED"):
            from datetime import datetime, timezone
            now_ts = int(datetime.now(timezone.utc).timestamp())
            secs   = next_ep_at - now_ts
            if secs <= 0:
                prog_lines.append(f"Episode {next_ep - 1} just aired")
            else:
                d, rem = divmod(secs, 86400)
                h, rem = divmod(rem, 3600)
                m      = rem // 60
                if d > 0:
                    time_str = f"{d}d {h}h {m}m"
                elif h > 0:
                    time_str = f"{h}h {m}m"
                else:
                    time_str = f"{m}m"
                prog_lines.append(f"Episode {next_ep} airs in {time_str}")
        elif api_status in ("FINISHED", "CANCELLED"):
            prog_lines.append(f"Finished airing ({total or '?'} eps total)")

        if prog_lines:
            self.progress_info_lbl.setText("\n".join(prog_lines))
            self.progress_info_lbl.setVisible(True)
            if is_incomplete_completion:
                self.progress_info_lbl.setStyleSheet(
                    "background-color:#1f1a0a;border:1px solid #fbbf24;"
                    "border-radius:8px;color:#fde68a;font-size:12px;"
                    "line-height:1.7;padding:10px 14px;font-weight:600;"
                )
            else:
                self.progress_info_lbl.setStyleSheet("")
        else:
            self.progress_info_lbl.setVisible(False)

        # Genres
        for i in reversed(range(self.genres_l.count())):
            w = self.genres_l.itemAt(i).widget()
            if w: w.setParent(None)
        for g in (anime.get("genres") or [])[:5]:
            chip = QLabel(g)
            chip.setObjectName("genreChip")
            self.genres_l.insertWidget(self.genres_l.count() - 1, chip)

        # Synopsis — if empty, fetch from AniList in background
        desc = _strip_html(anime.get("description") or "")
        if not desc and anime.get("anilist_id"):
            self.synopsis_lbl.setText("Loading synopsis…")
            self._fetch_missing_meta(anime)
        else:
            synopsis = desc[:500] + ("…" if len(desc) > 500 else "")
            self.synopsis_lbl.setText(synopsis or "No synopsis available.")

        ws = anime.get("watch_status", "watching")
        self.status_btn.setText(WATCH_STATUS_LABELS.get(ws, ws.title()))

        # Overall rating
        self.overall_rating.load(aid, episode_num=0)

        # Episode list
        self._build_episodes(anime)

        if anime.get("id", 0) > 0:
            self.links_manager.load(anime["id"])
        else:
            self.links_manager.load(-1)

    def _fetch_missing_meta(self, anime: Dict):
        """Fetch synopsis/studios/score from AniList for imported anime with no data."""
        from workers.workers import Worker, run_worker
        from core.api import get_anime_by_id

        def fetch():
            return get_anime_by_id(anime["anilist_id"])

        def on_done(media):
            if not media:
                self.synopsis_lbl.setText("No synopsis available.")
                return
            desc = _strip_html(media.get("description") or "")
            synopsis = desc[:500] + ("…" if len(desc) > 500 else "")
            self.synopsis_lbl.setText(synopsis or "No synopsis available.")

            # Persist to DB so we don't fetch again
            updates = {}
            if desc:
                updates["description"] = desc
            sc = media.get("averageScore")
            if sc:
                updates["average_score"] = sc
                self.score_lbl.setText(f"{sc/10:.1f}")
                self.score_lbl.setStyleSheet(
                    f"font-size:22px;font-weight:700;color:{_score_color(sc/10)};"
                )
            studios = [s["name"] for s in (media.get("studios", {}).get("nodes") or [])]
            if studios:
                updates["studios"] = studios
                self.studio_lbl.setText(", ".join(studios))
            eps = media.get("episodes")
            if eps:
                updates["total_episodes"] = eps
                # Rebuild episode list with correct count
                if self._anime and self._anime["id"] == anime["id"]:
                    self._anime["total_episodes"] = eps
                    self._build_episodes(self._anime)
            if updates:
                self.db.update_anime(anime["id"], updates)

        w = Worker(fetch)
        w.signals.result.connect(on_done)
        run_worker(w)

    def set_cover(self, path: str):
        if not path: return
        px = QPixmap(path)
        if px.isNull(): return
        target_w = self.cover_lbl.width() or 88
        target_h = self.cover_lbl.height() or 128
        sc = px.scaled(target_w, target_h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation)
        x = (sc.width() - target_w) // 2
        y = (sc.height() - target_h) // 2
        cr = sc.copy(x, y, target_w, target_h)
        res = QPixmap(target_w, target_h)
        res.fill(QColor(0, 0, 0, 0))
        p = QPainter(res)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pa = QPainterPath()
        pa.addRoundedRect(0, 0, target_w, target_h, 8, 8)
        p.setClipPath(pa)
        p.drawPixmap(0, 0, cr)
        p.end()
        self.cover_lbl.setPixmap(res)

    def set_banner(self, path: str):
        if not path: return
        px = QPixmap(path)
        if px.isNull(): return
        w = self.banner_lbl.width() or 380
        h = self.banner_lbl.height() or 132
        sc = px.scaled(w, h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation)
        x = (sc.width() - w) // 2
        self.banner_lbl.setPixmap(sc.copy(x, 0, w, h))

    def clear_images(self):
        """Reset cover and banner to placeholders. Call before loading a new anime."""
        # Cover placeholder — dark rounded rect
        placeholder = QPixmap(
            self.cover_lbl.width() or 88,
            self.cover_lbl.height() or 128,
        )
        placeholder.fill(QColor("#1a1d28"))
        self.cover_lbl.setPixmap(placeholder)
        # Banner placeholder — solid dark strip
        self.clear_banner()

    def clear_banner(self):
        """Reset banner to solid colour placeholder."""
        self.banner_lbl.setPixmap(QPixmap())   # empty - stylesheet bg shows

    # ── Episode list ───────────────────────────────────────────────────────────

    def _build_episodes(self, anime: Dict):
        for i in reversed(range(self.ep_vbox.count())):
            w = self.ep_vbox.itemAt(i).widget()
            if w: w.setParent(None)
        self._ep_rows.clear()

        aid      = anime["id"]
        total    = anime.get("total_episodes") or 0
        offset   = anime.get("episode_offset", 0)
        next_ep  = anime.get("next_episode_num")         # episode that will air next
        next_at  = anime.get("next_episode_at")          # UTC timestamp of next ep
        now_ts   = int(datetime.now(timezone.utc).timestamp())

        # How many episodes have actually aired?
        api_status = (anime.get("status") or "").upper()
        if total and (not next_ep or api_status in ("FINISHED", "CANCELLED")):
            # Finished / no next ep scheduled
            aired_count = total
        elif next_ep and next_ep > 1:
            # episodes 1 … (next_ep - 1) have aired
            aired_count = next_ep - 1
        else:
            aired_count = 0

        if aired_count == 0 and total == 0:
            lbl = QLabel("No episodes available yet.")
            lbl.setStyleSheet("font-size:12px;color:#4a5070;")
            self.ep_vbox.addWidget(lbl)
            return

        watched_data = {e["episode_num"]: e for e in self.db.get_episodes(aid)}
        ratings_data = {r["episode_num"]: r for r in self.db.get_ratings(aid)}

        # Lock ALL episodes if anime hasn't aired yet
        api_status = (anime.get("status") or "").upper()
        is_unreleased = (api_status == "NOT_YET_RELEASED" or
                         anime.get("watch_status") == "planned" and not aired_count)

        show_count = min(aired_count, 60)
        for ep_n in range(1, show_count + 1):
            ep_data = watched_data.get(ep_n, {})
            ep_rating = ratings_data.get(ep_n)
            row = _EpRow(aid, ep_n, ep_n + offset, ep_data, ep_rating, self.db)
            row.changed.connect(self._on_ep_changed)
            if is_unreleased:
                row.set_locked(True)
            self.ep_vbox.addWidget(row)
            self._ep_rows[ep_n] = row

        if aired_count > 60:
            self.ep_vbox.addWidget(
                self._dim_label(f"+ {aired_count - 60} more aired episodes")
            )

        # Show upcoming (not yet aired) episodes as locked — only makes sense
        # for a show that's still actually releasing episodes. A finished/
        # cancelled show's stale next_episode_num equals its last aired
        # episode, which would otherwise get listed twice.
        if (next_ep and total and next_ep <= total
                and api_status not in ("FINISHED", "CANCELLED")):
            self.ep_vbox.addWidget(self._dim_label("── Upcoming (not yet aired) ──"))
            for ep_n in range(next_ep, min(next_ep + 3, total + 1)):
                locked = _LockedEpRow(ep_n, ep_n + offset)
                self.ep_vbox.addWidget(locked)
            remaining = total - (next_ep - 1) - 3
            if remaining > 0:
                self.ep_vbox.addWidget(
                    self._dim_label(f"+ {remaining} more upcoming episodes")
                )

    def _dim_label(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet("font-size:11px;color:#3b4260;padding:4px 0;")
        return l

    def _on_ep_changed(self, aid: int):
        # Update per-ep ratings average display
        avg = self.db.get_average_rating(aid)
        self.overall_rating.refresh_average(avg)
        self.episode_changed.emit(aid)

    def _on_overall_rated(self, aid: int):
        self.episode_changed.emit(aid)

    # ── Actions ────────────────────────────────────────────────────────────────

    def _cycle_status(self):
        """
        Status state machine — enforces business rules based on AniList status.

        Rules:
          NOT_YET_RELEASED → planned only (locked)
          RELEASING        → watching ↔ planned only (cannot complete a running show)
          FINISHED         → watching ↔ completed ↔ planned (all allowed)
          Unknown/empty    → watching ↔ planned (conservative)

        Special case: if user has watched >= 1 episode and tries to move
        to planned, we warn them but allow it (they may be re-watching or
        pausing). This is the correct UX — never block, just inform.
        """
        if not self._anime:
            return

        api_s = (self._anime.get("status") or "").upper()
        cur   = self._anime.get("watch_status", "watching")
        aid   = self._anime["id"]

        # ── NOT_YET_RELEASED — hard lock to planned ──────────────────────
        if api_s == "NOT_YET_RELEASED":
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Not Released Yet",
                "This anime has not aired yet.\n"
                "It can only be set as Plan to Watch until it begins airing."
            )
            return

        # ── Determine allowed transitions ────────────────────────────────
        if api_s == "RELEASING":
            # Airing: watching ↔ planned. Cannot mark completed.
            if cur == "watching":
                # Warn if trying to step away while episodes remain
                watched = self.db.get_watched_count(aid)
                if watched > 0:
                    from PyQt6.QtWidgets import QMessageBox
                    res = QMessageBox.question(
                        self, "Move to Plan to Watch?",
                        f"You have already watched {watched} episode(s).\n"
                        "Move this to Plan to Watch anyway?\n\n"
                        "(You can move it back to Watching at any time.)",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if res != QMessageBox.StandardButton.Yes:
                        return
                new = "planned"
            elif cur == "planned":
                new = "watching"
            else:
                new = "watching"

        elif api_s in ("FINISHED", "CANCELLED"):
            # Finished: full cycle watching → completed → planned → watching
            order = ["watching", "completed", "planned"]
            idx   = order.index(cur) if cur in order else 0
            new   = order[(idx + 1) % len(order)]

        else:
            # Unknown status: watching ↔ planned only (conservative)
            new = "planned" if cur == "watching" else "watching"

        self.db.update_anime(aid, {"watch_status": new})
        self._anime["watch_status"] = new
        self.status_btn.setText(WATCH_STATUS_LABELS.get(new, new.title()))
        self.watch_status_changed.emit(aid, new)
        self.stats_changed.emit()
        from ui.toast import Toast
        Toast.show(
            self.window(),
            f"'{self._anime.get('romaji_title','Anime')}' moved to {new.replace('_', ' ').title()}.",
            kind="success",
        )

    def _drop(self):
        if not self._anime: return
        # Already dropped
        if self._anime.get("watch_status") == "dropped" or self._anime.get("_dropped_id"):
            QMessageBox.information(self, "Already Dropped",
                "This anime is already in your Dropped list.")
            return
        # Cannot drop unreleased anime
        api_s = (self._anime.get("status") or "").upper()
        if api_s == "NOT_YET_RELEASED":
            QMessageBox.information(
                self, "Not Released Yet",
                "You cannot drop an anime that has not aired yet. Use Delete instead.",
            )
            return
        if QMessageBox.question(
            self, "Drop Anime",
            f"Move '{self._anime.get('romaji_title','')}' to Dropped?\n"
            "You can restore it later.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            name = self._anime.get("romaji_title", "Anime")
            self.db.delete_anime(self._anime["id"], drop=True)
            self.anime_dropped.emit(self._anime["id"])
            self.stats_changed.emit()
            from ui.toast import Toast
            Toast.show(self.window(), f"'{name}' moved to Dropped.", kind="success")

    def _delete(self):
        if not self._anime: return
        name = self._anime.get("romaji_title","")
        if QMessageBox.question(
            self, "Delete",
            f"Permanently delete '{name}'?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        # Dropped anime have a _dropped_id key and negative id
        dropped_id = self._anime.get("_dropped_id")
        if dropped_id:
            self.db.delete_dropped_anime(dropped_id)
            self.anime_deleted.emit(self._anime["id"])
        else:
            self.db.delete_anime(self._anime["id"])
            self.anime_deleted.emit(self._anime["id"])
        self.stats_changed.emit()
        from ui.toast import Toast
        Toast.show(self.window(), f"'{name}' deleted.", kind="success")

    def _mark_all(self):
        if not self._anime: return
        api_s = (self._anime.get("status") or "").upper()
        if api_s == "NOT_YET_RELEASED":
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Not Released",
                "Cannot mark episodes watched — this anime has not aired yet.")
            return
        next_ep = self._anime.get("next_episode_num") or 0
        total   = self._anime.get("total_episodes") or 0
        count   = total if api_s in ("FINISHED", "CANCELLED") and total else (
            next_ep - 1 if next_ep > 1 else total
        )
        if count == 0: return
        for ep in range(1, count + 1):
            self.db.set_episode_watched(self._anime["id"], ep, True)
        self._build_episodes(self._anime)
        self.episode_changed.emit(self._anime["id"])
        from ui.toast import Toast
        Toast.show(
            self.window(),
            f"Marked {count} episode{'s' if count != 1 else ''} watched.",
            kind="success",
        )


# ── Episode Row ────────────────────────────────────────────────────────────────

class _EpRow(QFrame):
    changed = pyqtSignal(int)

    def __init__(self, anime_id, ep_num, display_num, ep_data, ep_rating, db):
        super().__init__()
        self.anime_id   = anime_id
        self.ep_num     = ep_num
        self.db         = db
        self._watched   = bool(ep_data.get("watched"))
        self._rating    = float(ep_rating["score"]) if ep_rating else 0.0

        self.setObjectName("episodeRow")
        self.setFixedHeight(44)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            "QFrame#episodeRow{background:#0d0f14;border:1px solid #1a1d28;"
            "border-radius:7px;}"
            "QFrame#episodeRow:hover{border-color:#2a3150;}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 8, 4)
        lay.setSpacing(6)

        self.num_lbl = QLabel(f"Ep {display_num}")
        self.num_lbl.setObjectName("epNum")
        self.num_lbl.setFixedWidth(46)
        lay.addWidget(self.num_lbl)

        lay.addStretch()

        # Per-episode star rating (1–6, only if watched)
        self.stars_row = QHBoxLayout()
        self.stars_row.setSpacing(1)
        self._star_btns: List[QPushButton] = []
        for v in range(1, 7):
            b = QPushButton("★")
            b.setObjectName("starBtn")
            b.setFlat(True)
            b.setFixedSize(18, 18)
            b.setStyleSheet("font-size:11px;")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _, val=v: self._rate(val))
            b.enterEvent = lambda e, val=v: self._hover_stars(val)
            b.leaveEvent = lambda e: self._render_stars(self._rating)
            self.stars_row.addWidget(b)
            self._star_btns.append(b)
        lay.addLayout(self.stars_row)
        lay.addSpacing(4)

        # Download
        # Watch
        self.watch_btn = QPushButton()
        self.watch_btn.setFixedSize(26, 26)
        self.watch_btn.setObjectName("iconBtn")
        self.watch_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.watch_btn.clicked.connect(self._toggle_watch)
        lay.addWidget(self.watch_btn)

        self._refresh()

    def mousePressEvent(self, event):
        """Clicking anywhere on the row toggles watched state."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_watch()
        super().mousePressEvent(event)

    def set_locked(self, locked: bool):
        """Lock this row — prevents toggling for unreleased anime."""
        self._locked = locked
        if locked:
            self.setCursor(Qt.CursorShape.ForbiddenCursor)
            self.setStyleSheet(
                "QFrame#episodeRow{background:#0d0f14;border:1px solid #141720;"
                "border-radius:7px;opacity:0.55;}"
            )
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self._refresh()

    def _refresh(self):
        # Row style
        if self._watched:
            self.watch_btn.setText("✓")
            self.watch_btn.setStyleSheet(
                "QPushButton{background:#0e2a1f;color:#34d399;border-radius:6px;"
                "font-size:13px;font-weight:700;border:1px solid #1f4b35;}"
            )
            self.setStyleSheet(
                "QFrame#episodeRow{background:#0c1a14;border:1px solid #1a3a28;"
                "border-radius:7px;}"
                "QFrame#episodeRow:hover{border-color:#2b6346;}"
            )
        else:
            self.watch_btn.setText("○")
            self.watch_btn.setStyleSheet(
                "QPushButton{background:#111420;color:#7c849b;border:1px solid #1e2235;"
                "border-radius:6px;font-size:13px;font-weight:700;}"
            )
            self.setStyleSheet(
                "QFrame#episodeRow{background:#0d0f14;border:1px solid #1a1d28;"
                "border-radius:7px;}"
                "QFrame#episodeRow:hover{border-color:#2a3150;}"
            )


        # Stars only visible when watched
        for b in self._star_btns:
            b.setVisible(self._watched)
        self._render_stars(self._rating)

    def _render_stars(self, score: float):
        for i, b in enumerate(self._star_btns):
            filled = (i + 1) <= score
            b.setStyleSheet(
                f"font-size:11px;color:{'#fbbf24' if filled else '#2a2d42'};"
                "background:transparent;border:none;"
            )

    def _hover_stars(self, val: int):
        if self._watched:
            self._render_stars(float(val))

    def _rate(self, val: int):
        if not self._watched:
            return
        # Toggle off: clicking same star removes rating
        if val == int(self._rating):
            self._rating = 0.0
            self.db.set_rating(self.anime_id, self.ep_num, 0.0, "")
            self._render_stars(0.0)
            self.changed.emit(self.anime_id)
            from ui.toast import Toast
            Toast.show(self.window(), f"Episode {self.ep_num} rating removed.", kind="info")
            return
        self._rating = float(val)
        self.db.set_rating(self.anime_id, self.ep_num, self._rating,
                           RATING_LABELS.get(val, ""))
        self._render_stars(self._rating)
        self.changed.emit(self.anime_id)
        from ui.toast import Toast
        Toast.show(self.window(), f"Episode {self.ep_num} rated {val}/6.", kind="success")

    def _toggle_watch(self):
        if getattr(self, "_locked", False):
            return
        self._watched = not self._watched
        self.db.set_episode_watched(self.anime_id, self.ep_num, self._watched)
        if not self._watched:
            self._rating = 0.0
        self._refresh()
        self.changed.emit(self.anime_id)
        from ui.toast import Toast
        Toast.show(
            self.window(),
            f"Episode {self.ep_num} marked {'watched' if self._watched else 'unwatched'}.",
            kind="success" if self._watched else "info",
        )




class _LockedEpRow(QFrame):
    """Greyed-out row for episodes not yet aired."""
    def __init__(self, ep_num: int, display_num: int, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setStyleSheet(
            "QFrame{background:#0d0f14;border:1px solid #141720;border-radius:7px;}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        nl = QLabel(f"Ep {display_num}")
        nl.setStyleSheet("font-size:12px;color:#2a2d42;")
        lay.addWidget(nl)
        lay.addStretch()
        ll = QLabel("🔒 Not aired yet")
        ll.setStyleSheet("font-size:11px;color:#2a2d42;")
        lay.addWidget(ll)


# ── Rating widget (overall) ───────────────────────────────────────────────────

class _RatingWidget(QWidget):
    rated = pyqtSignal(int)   # anime_id

    def __init__(self, db: DatabaseManager, overall: bool = False, parent=None):
        super().__init__(parent)
        self.db      = db
        self.overall = overall
        self._aid    = None
        self._cur    = 0.0

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._stars: List[QPushButton] = []
        for v in range(1, 7):
            b = QPushButton("★")
            b.setObjectName("starBtn")
            b.setFlat(True)
            b.setFixedSize(32, 32)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setToolTip(RATING_LABELS.get(v, str(v)))
            b.clicked.connect(lambda _, val=v: self._rate(val))
            b.enterEvent = lambda e, val=v: self._render(float(val))
            b.leaveEvent = lambda e: self._render(self._cur)
            lay.addWidget(b)
            self._stars.append(b)

        self.avg_lbl = QLabel()
        self.avg_lbl.setObjectName("detailRatingHint")
        lay.addWidget(self.avg_lbl)
        lay.addStretch()

    def load(self, anime_id: int, episode_num: int = 0):
        self._aid = anime_id
        avg = self.db.get_average_rating(anime_id)
        self.refresh_average(avg)

    def refresh_average(self, avg: Optional[float]):
        if avg is not None:
            self._cur = avg
            self.avg_lbl.setText(f"avg {avg:.1f} / 6")
        else:
            self._cur = 0.0
            self.avg_lbl.setText("Not rated yet")
        self._render(self._cur)

    def _rate(self, val: int):
        if not self._aid: return
        # Block rating of anime that has not aired yet
        anime = self.db.get_anime_by_id(self._aid)
        if anime:
            api_s = (anime.get("status") or "").upper()
            ws    = anime.get("watch_status","")
            if api_s == "NOT_YET_RELEASED" or ws == "planned":
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self, "Cannot Rate Yet",
                    "You can only rate anime you have started watching."
                )
                self._render(self._cur)
                return
        # Toggle off: clicking same star again removes rating
        if val == int(self._cur):
            self._cur = 0.0
            self.db.set_rating(self._aid, 0, 0.0, "")
            self.avg_lbl.setText("Not rated — click a star to rate")
            self._render(0.0)
            self.rated.emit(self._aid)
            from ui.toast import Toast
            Toast.show(self.window(), "Overall rating removed.", kind="info")
            return
        real  = float(val)
        label = RATING_LABELS.get(val, "")
        self.db.set_rating(self._aid, 0, real, label)
        self._cur = real
        self.avg_lbl.setText(f"{real:.1f} / 6  —  {label}")
        self._render(real)
        self.rated.emit(self._aid)
        from ui.toast import Toast
        Toast.show(self.window(), f"Overall rating saved: {val}/6.", kind="success")
        self._maybe_sync_to_anilist(val)

    def _maybe_sync_to_anilist(self, our_score: int):
        """If logged into AniList, offer to sync the rating."""
        from core.anilist_auth import SCORE_MAP, get_anilist_auth
        auth = get_anilist_auth()
        if not auth.is_logged_in():
            return
        # Get anilist_id for this anime
        anime = self.db.get_anime_by_id(self._aid)
        if not anime or not anime.get("anilist_id"):
            return
        anilist_score = SCORE_MAP.get(our_score, our_score * 16)
        from PyQt6.QtWidgets import QMessageBox
        res = QMessageBox.question(
            self, "Sync to AniList?",
            f"Submit your rating ({RATING_LABELS.get(our_score, '')}) "
            f"to AniList as {anilist_score}/100?\n\n"
            "This contributes to the community score on AniList.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res == QMessageBox.StandardButton.Yes:
            auth.score_synced.connect(
                lambda _: self.avg_lbl.setText(
                    self.avg_lbl.text() + "  ✓ Synced to AniList"
                )
            )
            auth.score_failed.connect(
                lambda e: QMessageBox.warning(self, "Sync Failed", e)
            )
            auth.submit_score(anime["anilist_id"], our_score)

    def _render(self, score: float):
        for i, b in enumerate(self._stars):
            filled = (i + 1) <= score
            b.setProperty("rated", "true" if filled else "false")
            b.style().unpolish(b)
            b.style().polish(b)

from typing import List   # re-import for use inside methods
Optional = Optional       # keep type checker happy
