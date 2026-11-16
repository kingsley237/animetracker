"""
Miroku - full anime info dialog (synopsis, studios, score, genres, release,
trailer, characters). Opened from the new-season spotlight.
"""
import re
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QPushButton, QGridLayout, QComboBox, QProgressBar,
    QMessageBox, QSizePolicy, QDialog, QTextEdit, QApplication,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QColor, QCursor, QPainter, QPainterPath

from core.api import format_air_date, get_anime_by_id
from workers.workers import Worker, ImageWorker, run_worker


def _center_on_parent_screen(dialog: QDialog, parent: Optional[QWidget]) -> None:
    """Place dialogs on the same screen as the parent window."""
    parent_window = parent.window() if parent else None
    screen = parent_window.screen() if parent_window else QApplication.primaryScreen()
    if not screen:
        return
    avail = screen.availableGeometry()
    dialog.adjustSize()
    width = dialog.width() or dialog.sizeHint().width()
    height = dialog.height() or dialog.sizeHint().height()
    dialog.move(
        avail.left() + max(0, (avail.width() - width) // 2),
        avail.top() + max(0, (avail.height() - height) // 2),
    )


def _strip_html(txt: str) -> str:
    return re.sub(r"<[^>]+>", "", txt or "")


class _InfoDialog(QDialog):
    """Full-detail popup — fetches complete data from AniList before showing."""

    def __init__(self, media: Dict, parent=None):
        super().__init__(parent)
        t = (media.get("title") or {})
        self.setWindowTitle(t.get("romaji") or t.get("english") or "Info")

        # Bigger dialog — 680px wide, capped at 90% screen height
        self.setFixedWidth(680)
        parent_window = parent.window() if parent else None
        screen = parent_window.screen() if parent_window else QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            self.setMaximumHeight(int(avail.height() * 0.90))
            # Center on the same screen as the main window.
            self.move(
                avail.left() + (avail.width()  - 680) // 2,
                avail.top()  + int(avail.height() * 0.05),
            )
        self.setMinimumHeight(560)
        self.setStyleSheet("background:#0f1118;")
        self._build(media)

    def _build(self, media: Dict):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scroll area — vertical only, horizontal completely disabled
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Disable mouse-based horizontal panning (touchpad two-finger swipe)
        scroll.horizontalScrollBar().setEnabled(False)
        scroll.setStyleSheet(
            "QScrollArea{border:none;background:transparent;}"
            "QScrollBar:horizontal{height:0px;}"
        )

        body_w = QWidget()
        body_w.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(body_w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        scroll.setWidget(body_w)
        outer.addWidget(scroll)

        t     = media.get("title") or {}
        sc    = media.get("averageScore")
        eps   = media.get("episodes")
        sea   = (media.get("season") or "").title()
        yr    = media.get("seasonYear") or ""
        api_s = (media.get("status") or "").replace("_", " ").title()
        sd    = format_air_date(media.get("startDate") or {})
        pop   = media.get("popularity", 0)
        studios = [s["name"] for s in
                   (media.get("studios", {}).get("nodes") or [])] if media.get("studios") else []
        banner_url = media.get("bannerImage") or ""
        cover_url  = (media.get("coverImage") or {}).get("large") or                      (media.get("coverImage") or {}).get("medium") or ""

        # ── Banner image ─────────────────────────────────────────────────
        self.banner_lbl = QLabel()
        self.banner_lbl.setFixedHeight(160)
        self.banner_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner_lbl.setStyleSheet("background:#1a1d28;")
        lay.addWidget(self.banner_lbl)

        # Skeleton overlay — shown while full data loads
        self._skeleton = QFrame()
        self._skeleton.setObjectName("skeletonOverlay")
        self._skeleton.setStyleSheet(
            "QFrame#skeletonOverlay{background:#0f1118;border:none;}"
        )
        sk_lay = QVBoxLayout(self._skeleton)
        sk_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sk_lay.setSpacing(14)
        _spin_lbl = QLabel("⏳  Loading details…")
        _spin_lbl.setStyleSheet(
            "font-size:14px;color:#4a5070;background:transparent;"
        )
        _spin_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sk_lay.addWidget(_spin_lbl)
        _sub_lbl = QLabel("Fetching synopsis, characters & trailer")
        _sub_lbl.setStyleSheet(
            "font-size:11px;color:#2e3250;background:transparent;"
        )
        _sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sk_lay.addWidget(_sub_lbl)

        # Animated progress bar
        self._sk_bar = QProgressBar()
        self._sk_bar.setRange(0, 0)   # indeterminate
        self._sk_bar.setFixedWidth(220)
        self._sk_bar.setFixedHeight(3)
        self._sk_bar.setTextVisible(False)
        self._sk_bar.setStyleSheet(
            "QProgressBar{background:#1a1d28;border:none;border-radius:2px;}"
            "QProgressBar::chunk{background:#7c6af7;border-radius:2px;}"
        )
        sk_lay.addWidget(self._sk_bar, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._skeleton)

        if banner_url:
            from workers.workers import ImageWorker, run_worker
            iw = ImageWorker(banner_url, 0, "banner")
            iw.signals.result.connect(self._set_banner)
            run_worker(iw)
        elif cover_url:
            from workers.workers import ImageWorker, run_worker
            iw = ImageWorker(cover_url, 0, "cover_fallback")
            iw.signals.result.connect(self._set_banner)
            run_worker(iw)

        # ── Body ─────────────────────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        body_lay = QVBoxLayout(body)
        self._body_widget = body   # store ref for skeleton hide/show
        body_lay.setContentsMargins(24, 16, 24, 20)
        body_lay.setSpacing(10)
        lay.addWidget(body)

        # Cover + title row
        header_row = QHBoxLayout()
        header_row.setSpacing(16)

        # Small cover thumbnail
        self.cover_lbl = QLabel()
        self.cover_lbl.setFixedSize(72, 102)
        self.cover_lbl.setStyleSheet(
            "background:#1a1d28;border-radius:6px;"
            "border:2px solid #0a0c10;margin-top:-40px;"
        )
        self.cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if cover_url:
            from workers.workers import ImageWorker, run_worker
            iw2 = ImageWorker(cover_url, 0, "cover_thumb")
            iw2.signals.result.connect(self._set_cover)
            run_worker(iw2)
        header_row.addWidget(self.cover_lbl, 0, Qt.AlignmentFlag.AlignBottom)

        # Title block
        title_col = QVBoxLayout()
        title_col.setSpacing(3)
        romaji  = t.get("romaji", "")
        english = t.get("english", "")
        title_lbl = QLabel(romaji)
        title_lbl.setStyleSheet(
            "font-size:17px;font-weight:700;color:#f0f1f5;letter-spacing:-0.2px;"
            "background:transparent;"
        )
        title_lbl.setWordWrap(True)
        title_col.addWidget(title_lbl)
        if english and english != romaji:
            eng_lbl = QLabel(english)
            eng_lbl.setStyleSheet("font-size:12px;color:#4a5070;background:transparent;")
            eng_lbl.setWordWrap(True)
            title_col.addWidget(eng_lbl)
        if studios:
            studio_lbl = QLabel(", ".join(studios))
            studio_lbl.setStyleSheet("font-size:11px;color:#4a5070;background:transparent;")
            title_col.addWidget(studio_lbl)
        header_row.addLayout(title_col)
        body_lay.addLayout(header_row)

        lay = body_lay   # continue adding to body_lay
        self._body_lay = body_lay   # keep reference for _update_with_full

        if studios:
            pass  # already added above

        # ── Score + meta row ─────────────────────────────────────────────
        score_row = QHBoxLayout()
        score_row.setSpacing(20)

        if sc:
            score_box = QFrame()
            score_box.setStyleSheet(
                "background:#151929;border-radius:8px;padding:4px;"
            )
            sb_lay = QVBoxLayout(score_box)
            sb_lay.setContentsMargins(14, 8, 14, 8)
            sb_lay.setSpacing(2)
            sv = QLabel(f"{sc / 10:.1f}")
            sv.setStyleSheet("font-size:26px;font-weight:700;color:#7c6af7;")
            sb_lay.addWidget(sv)
            sl = QLabel("ANILIST SCORE")
            sl.setStyleSheet("font-size:9px;color:#4a5070;letter-spacing:1px;font-weight:700;")
            sb_lay.addWidget(sl)
            score_row.addWidget(score_box)

        meta_col = QVBoxLayout()
        meta_col.setSpacing(4)
        for icon, val in [
            ("📅", f"{sea} {yr}".strip() or sd),
            ("📺", f"{eps} episodes" if eps else "Episodes TBA"),
            ("📊", f"{pop:,} popularity" if pop else ""),
            ("⚡", api_s),
        ]:
            if val:
                ml = QLabel(f"{icon}  {val}")
                ml.setStyleSheet("font-size:12px;color:#6b7280;")
                meta_col.addWidget(ml)
        score_row.addLayout(meta_col)
        score_row.addStretch()
        lay.addLayout(score_row)

        # ── Genres ───────────────────────────────────────────────────────
        genres = (media.get("genres") or [])[:8]
        if genres:
            gw = QWidget()
            gw.setStyleSheet("background:transparent;")
            gl = QHBoxLayout(gw)
            gl.setContentsMargins(0, 2, 0, 2)
            gl.setSpacing(6)
            for g in genres:
                chip = QLabel(g)
                chip.setObjectName("genreChip")
                gl.addWidget(chip)
            gl.addStretch()
            lay.addWidget(gw)

        # ── Synopsis ─────────────────────────────────────────────────────
        syn_header = QLabel("SYNOPSIS")
        syn_header.setStyleSheet(
            "font-size:10px;color:#3b4260;font-weight:700;letter-spacing:1.5px;"
        )
        lay.addWidget(syn_header)

        raw_desc  = _strip_html(media.get("description") or "")
        desc_text = raw_desc if raw_desc else "No synopsis available for this title yet."

        self._syn_edit = QTextEdit()
        self._syn_edit.setReadOnly(True)
        self._syn_edit.setPlainText(desc_text)
        self._syn_edit.setFixedHeight(170)
        self._syn_edit.setStyleSheet(
            "QTextEdit{background:#111420;border:1px solid #1a1d28;border-radius:8px;"
            "color:#9da5c0;font-size:12px;padding:10px;line-height:1.6;}"
        )
        lay.addWidget(self._syn_edit)

        # ── Release date highlight for upcoming ──────────────────────────
        raw_api_s = (media.get("status") or "").upper()
        if raw_api_s == "NOT_YET_RELEASED":
            rel_frame = QFrame()
            rel_frame.setStyleSheet(
                "background:#1f1a0d;border-radius:8px;"
            )
            rfl = QHBoxLayout(rel_frame)
            rfl.setContentsMargins(14, 10, 14, 10)
            rl = QLabel(f"📅  Expected premiere:  {sd}")
            rl.setStyleSheet("font-size:13px;color:#fbbf24;font-weight:600;")
            rfl.addWidget(rl)
            lay.addWidget(rel_frame)

        # ── Close ────────────────────────────────────────────────────────
        # ── Characters strip (anime-specific art) ───────────────────────
        chars = (media.get("characters") or {}).get("nodes") or []
        if chars:
            char_header = QLabel("CHARACTERS")
            char_header.setStyleSheet(
                "font-size:10px;color:#3b4260;font-weight:700;"
                "letter-spacing:1.5px;background:transparent;"
            )
            lay.addWidget(char_header)

            char_scroll = QScrollArea()
            char_scroll.setFixedHeight(110)
            char_scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            char_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            char_scroll.setFrameShape(QFrame.Shape.NoFrame)
            char_scroll.setStyleSheet("background:transparent;border:none;")

            char_w = QWidget()
            char_w.setStyleSheet("background:transparent;")
            char_lay = QHBoxLayout(char_w)
            char_lay.setContentsMargins(0, 0, 0, 0)
            char_lay.setSpacing(10)

            self._char_labels = []
            for ch in chars[:10]:
                col = QVBoxLayout()
                col.setSpacing(3)
                col.setAlignment(Qt.AlignmentFlag.AlignTop)

                img_lbl = QLabel()
                img_lbl.setFixedSize(56, 76)
                img_lbl.setStyleSheet(
                    "background:#1a1d28;border-radius:6px;"
                )
                img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

                ch_img = (ch.get("image") or {}).get("medium") or ""
                if ch_img:
                    from workers.workers import ImageWorker, run_worker as rw
                    iw = ImageWorker(ch_img, id(img_lbl), "char")
                    iw.signals.result.connect(
                        lambda r, l=img_lbl: self._set_char_img(l, r)
                    )
                    rw(iw)

                name = (ch.get("name") or {}).get("first") or ""
                name_lbl = QLabel(name[:10])
                name_lbl.setStyleSheet(
                    "font-size:9px;color:#6b7280;background:transparent;"
                )
                name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                name_lbl.setWordWrap(False)

                col.addWidget(img_lbl)
                col.addWidget(name_lbl)

                cw2 = QWidget()
                cw2.setStyleSheet("background:transparent;")
                cw2.setLayout(col)
                char_lay.addWidget(cw2)
                self._char_labels.append(img_lbl)

            char_lay.addStretch()
            char_scroll.setWidget(char_w)
            lay.addWidget(char_scroll)

        # ── Trailer button — opens in-app player ─────────────────────────
        trailer      = media.get("trailer") or {}
        trailer_id   = trailer.get("id", "")
        trailer_site = (trailer.get("site") or "").lower()
        anime_title  = (media.get("title") or {}).get("romaji", "")

        if trailer_id and trailer_site in ("youtube", "dailymotion"):
            trailer_btn = QPushButton("▶  Watch Trailer")
            trailer_btn.setStyleSheet(
                "QPushButton{"
                "background:#0e2a1f;color:#34d399;"
                "border:1px solid #1a5c3a;border-radius:8px;"
                "padding:10px 20px;font-size:13px;font-weight:600;"
                "}"
                "QPushButton:hover{background:#134d2e;border-color:#34d399;}"
            )
            trailer_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            trailer_btn.clicked.connect(
                lambda checked=False, tid=trailer_id, tsite=trailer_site, ttitle=anime_title:
                    self._open_trailer(tid, tsite, ttitle)
            )
            lay.addWidget(trailer_btn)

        btn_row = QHBoxLayout()
        close = QPushButton("Close")
        close.setObjectName("secondaryBtn")
        close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(close)
        lay.addLayout(btn_row)
        lay.addSpacing(8)
                # Show skeleton overlay, hide body until _update_with_full fires
        self._body_widget.setVisible(False)
        self._skeleton.setVisible(True)

    def _open_trailer(self, trailer_id: str, trailer_site: str, title: str):
        from ui.trailer_player import show_trailer
        show_trailer(trailer_id, trailer_site, title, self)

    def _update_with_full(self, full: Dict):
        """Update synopsis, characters, and trailer after full data arrives."""
        # Dismiss skeleton, reveal body
        if hasattr(self, '_skeleton'):
            self._skeleton.setVisible(False)
        if hasattr(self, '_body_widget'):
            self._body_widget.setVisible(True)
        # Update synopsis
        if hasattr(self, '_syn_edit'):
            desc = _strip_html(full.get("description") or "")
            if desc:
                self._syn_edit.setPlainText(desc)

        # Update banner if not loaded yet
        banner_url = full.get("bannerImage") or ""
        if banner_url and hasattr(self, 'banner_lbl'):
            from core.image_cache import get_cached_path
            cached = get_cached_path(banner_url)
            if cached:
                self._set_banner((0, "banner", str(cached)))
            else:
                from workers.workers import ImageWorker, run_worker
                iw = ImageWorker(banner_url, 0, "banner")
                iw.signals.result.connect(self._set_banner)
                run_worker(iw)

        if not hasattr(self, '_body_lay'):
            return
        lay = self._body_lay

        # ── Inject characters strip if not already present ────────────────
        chars = (full.get("characters") or {}).get("nodes") or []
        if chars and not hasattr(self, '_chars_injected'):
            self._chars_injected = True
            char_header = QLabel("CHARACTERS")
            char_header.setStyleSheet(
                "font-size:10px;color:#3b4260;font-weight:700;"
                "letter-spacing:1.5px;background:transparent;"
            )
            lay.addWidget(char_header)

            char_scroll = QScrollArea()
            char_scroll.setFixedHeight(110)
            char_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            char_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            char_scroll.setFrameShape(QFrame.Shape.NoFrame)
            char_scroll.setStyleSheet("background:transparent;border:none;")

            char_w = QWidget()
            char_w.setStyleSheet("background:transparent;")
            char_lay = QHBoxLayout(char_w)
            char_lay.setContentsMargins(0, 0, 0, 0)
            char_lay.setSpacing(10)

            for ch in chars[:10]:
                col = QVBoxLayout()
                col.setSpacing(3)
                col.setAlignment(Qt.AlignmentFlag.AlignTop)

                img_lbl = QLabel()
                img_lbl.setFixedSize(56, 76)
                img_lbl.setStyleSheet("background:#1a1d28;border-radius:6px;")
                img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

                ch_img = (ch.get("image") or {}).get("medium") or ""
                if ch_img:
                    from workers.workers import ImageWorker, run_worker as rw
                    iw = ImageWorker(ch_img, id(img_lbl), "char")
                    iw.signals.result.connect(
                        lambda r, l=img_lbl: self._set_char_img(l, r)
                    )
                    rw(iw)

                name = (ch.get("name") or {}).get("first") or ""
                name_lbl = QLabel(name[:10])
                name_lbl.setStyleSheet("font-size:9px;color:#6b7280;background:transparent;")
                name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

                col.addWidget(img_lbl)
                col.addWidget(name_lbl)

                cw2 = QWidget()
                cw2.setStyleSheet("background:transparent;")
                cw2.setLayout(col)
                char_lay.addWidget(cw2)

            char_lay.addStretch()
            char_scroll.setWidget(char_w)
            lay.addWidget(char_scroll)

        # ── Inject trailer button if not already present ──────────────────
        trailer      = full.get("trailer") or {}
        trailer_id   = trailer.get("id", "")
        trailer_site = (trailer.get("site") or "").lower()
        anime_title  = (full.get("title") or {}).get("romaji", "")

        if trailer_id and trailer_site in ("youtube", "dailymotion") and not hasattr(self, '_trailer_injected'):
            self._trailer_injected = True
            trailer_btn = QPushButton("▶  Watch Trailer")
            trailer_btn.setStyleSheet(
                "QPushButton{"
                "background:#0e2a1f;color:#34d399;"
                "border:1px solid #1a5c3a;border-radius:8px;"
                "padding:10px 20px;font-size:13px;font-weight:600;"
                "}"
                "QPushButton:hover{background:#134d2e;border-color:#34d399;}"
            )
            trailer_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            trailer_btn.clicked.connect(
                lambda checked=False, tid=trailer_id, tsite=trailer_site, ttitle=anime_title:
                    self._open_trailer(tid, tsite, ttitle)
            )
            lay.addWidget(trailer_btn)

    def _set_char_img(self, label, result):
        if not result or not result[2]: return
        px = QPixmap(result[2])
        if px.isNull(): return
        sc = px.scaled(56, 76,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation)
        x = (sc.width()  - 56) // 2
        y = (sc.height() - 76) // 2
        label.setPixmap(sc.copy(x, y, 56, 76))

    def _set_banner(self, result):
        if not result or not result[2]: return
        px = QPixmap(result[2])
        if px.isNull(): return
        w = self.banner_lbl.width() or 680
        h = self.banner_lbl.height() or 180
        # Expand to fill entirely — center crop, no blank space
        sc = px.scaled(w, h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation)
        x = max(0, (sc.width()  - w) // 2)
        y = max(0, (sc.height() - h) // 2)
        self.banner_lbl.setPixmap(sc.copy(x, y, w, h))
        self.banner_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def _set_cover(self, result):
        if not result or not result[2]: return
        px = QPixmap(result[2])
        if px.isNull(): return
        w, h = 72, 102
        sc = px.scaled(w, h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation)
        x = max(0, (sc.width()  - w) // 2)
        y = max(0, (sc.height() - h) // 2)
        self.cover_lbl.setPixmap(sc.copy(x, y, w, h))
        self.cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)


# ─── Shared helpers (also used by the new-season spotlight) ──────────────────

def open_media_info(media: Dict, parent: Optional[QWidget] = None) -> "QDialog":
    """Open the Discover info dialog for an AniList media dict (non-modal).
    Shows a skeleton immediately and fills in once full data arrives."""
    dlg = _InfoDialog(media, parent)
    _center_on_parent_screen(dlg, parent)
    dlg.show()
    anilist_id = media.get("id")
    if anilist_id:
        def fetch():
            return get_anime_by_id(anilist_id)

        def update(full):
            try:
                if dlg.isVisible():
                    dlg._update_with_full(full or media)
            except RuntimeError:
                pass   # dialog already destroyed
        w = Worker(fetch)
        w.signals.result.connect(update)
        run_worker(w)
    else:
        dlg._update_with_full(media)
    return dlg
