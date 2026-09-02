"""
Miroku — Episode Ratings Export

Renders a shareable ratings-grid image for a single anime: cover art,
title, overall score, and a tile per episode colored by the user's 1-6
rating (unrated aired episodes show as "?"). Styled with Miroku's own
dark slate + indigo/amber palette. Available whenever an anime has at
least one episode-level rating.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QFileDialog, QSizePolicy,
)

from core.database import DatabaseManager
from core.image_cache import get_cached_path

RATING_LABELS = {
    1: "Terrible",
    2: "Bad",
    3: "Fair",
    4: "Good",
    5: "Great",
    6: "Masterpiece",
}

TIER_COLORS = {
    1: QColor("#f87171"),
    2: QColor("#fb923c"),
    3: QColor("#fbbf24"),
    4: QColor("#34d399"),
    5: QColor("#38bdf8"),
    6: QColor("#a594f9"),
}

_UNRATED_BG   = QColor("#161a24")
_UNRATED_TXT  = QColor("#4a5070")
_CANVAS_BG    = QColor("#0a0c11")
_PANEL_BG     = QColor("#10131b")
_BORDER       = QColor("#1e2130")

_TILE_W, _TILE_H = 92, 62
_COL_GAP         = 14   # horizontal gap between tiles
_ROW_GAP         = 22   # vertical gap between tile rows
_LABEL_H         = 18   # space reserved above each tile for its "E#" label
_ROW_STRIDE      = _LABEL_H + _TILE_H + _ROW_GAP
_COLS            = 8
_LEFT_W          = 260
_MARGIN          = 24


def _tile_tier(score: float) -> int:
    return max(1, min(6, round(score)))


def has_episode_ratings(db: DatabaseManager, anime_id: int) -> bool:
    """True if this anime has at least one per-episode rating (episode_num > 0, score > 0)."""
    for r in db.get_ratings(anime_id):
        if r.get("episode_num", 0) > 0 and (r.get("score") or 0) > 0:
            return True
    return False


_TITLE_FONT = QFont(); _TITLE_FONT.setPointSize(13); _TITLE_FONT.setBold(True)

# Fixed left-panel layout offsets (relative to left_rect top), computed once
# so the canvas can be sized to fit before any painting happens.
_COVER_PAD_TOP   = 16
_COVER_H         = 260
_TITLE_GAP       = 26   # cover → title
_YEAR_GAP        = 14   # title → year
_YEAR_H          = 20
_BADGE_GAP       = 18   # year → avg score badge
_BADGE_H         = 34
_BADGE_LABEL_GAP = 6
_BADGE_LABEL_H   = 16
_FOOTER_GAP      = 28   # avg label → MIROKU footer
_FOOTER_H        = 20
_BOTTOM_PAD      = 16


def _title_height(title: str, box_w: int) -> int:
    fm_rect = QFont(_TITLE_FONT)
    from PyQt6.QtGui import QFontMetrics
    metrics = QFontMetrics(fm_rect)
    rect = metrics.boundingRect(QRect(0, 0, box_w, 1000),
                                 Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft, title)
    return max(rect.height(), metrics.height())


def render_ratings_card(db: DatabaseManager, anime: Dict) -> QPixmap:
    """Build the exportable ratings-grid image for one anime."""
    anime_id = anime["id"]
    ratings  = {r["episode_num"]: r["score"] for r in db.get_ratings(anime_id)
                if r.get("episode_num", 0) > 0}
    watched  = {e["episode_num"] for e in db.get_episodes(anime_id) if e.get("watched")}

    total = anime.get("total_episodes") or 0
    last_ep = max([total] + list(ratings.keys()) + list(watched)) if (total or ratings or watched) else 0
    last_ep = max(last_ep, 1)

    title = anime.get("english_title") or anime.get("romaji_title") or "Untitled"
    avg = db.get_average_rating(anime_id)

    # ── Pre-compute layout heights for both panels ──────────────────────
    title_h = _title_height(title, _LEFT_W - 32)
    left_content_h = _COVER_PAD_TOP + _COVER_H + _TITLE_GAP + title_h + _YEAR_GAP + _YEAR_H
    if avg:
        left_content_h += _BADGE_GAP + _BADGE_H + _BADGE_LABEL_GAP + _BADGE_LABEL_H
    left_content_h += _FOOTER_GAP + _FOOTER_H + _BOTTOM_PAD

    rows = -(-last_ep // _COLS)  # ceil
    grid_h = rows * _ROW_STRIDE - _ROW_GAP

    header_h = 46   # legend row + breathing room before the grid
    footer_h = 24   # bottom padding under the grid
    right_content_h = header_h + grid_h + footer_h

    canvas_h = max(left_content_h, right_content_h) + _MARGIN * 2
    canvas_w = _LEFT_W + _MARGIN * 3 + _COLS * _TILE_W + (_COLS - 1) * _COL_GAP

    pm = QPixmap(canvas_w, canvas_h)
    pm.fill(_CANVAS_BG)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # ── Left panel ───────────────────────────────────────────────────────
    left_rect = QRect(_MARGIN, _MARGIN, _LEFT_W, canvas_h - _MARGIN * 2)
    path = QPainterPath()
    path.addRoundedRect(float(left_rect.x()), float(left_rect.y()),
                         float(left_rect.width()), float(left_rect.height()), 12, 12)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_PANEL_BG)
    p.drawPath(path)
    p.setPen(QColor(_BORDER))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)

    cover_w, cover_h = _LEFT_W - 32, _COVER_H
    cover_x, cover_y = left_rect.x() + 16, left_rect.y() + _COVER_PAD_TOP
    cover_path = QPainterPath()
    cover_path.addRoundedRect(float(cover_x), float(cover_y), float(cover_w), float(cover_h), 8, 8)

    cover_local = anime.get("cover_local") or get_cached_path(anime.get("cover_url") or "")
    cover_px = QPixmap(str(cover_local)) if cover_local else QPixmap()
    p.save()
    p.setClipPath(cover_path)
    if not cover_px.isNull():
        sc = cover_px.scaled(cover_w, cover_h,
                              Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation)
        x = (sc.width() - cover_w) // 2
        y = (sc.height() - cover_h) // 2
        p.drawPixmap(cover_x, cover_y, sc, x, y, cover_w, cover_h)
    else:
        p.fillRect(QRect(cover_x, cover_y, cover_w, cover_h), QColor("#1a1d28"))
    p.restore()
    p.setPen(QColor(_BORDER))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(cover_path)

    ty = cover_y + cover_h + _TITLE_GAP
    p.setPen(QColor("#f0f1f5"))
    p.setFont(_TITLE_FONT)
    title_rect = QRect(left_rect.x() + 16, ty, _LEFT_W - 32, title_h)
    p.drawText(title_rect, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft, title)

    year_y = ty + title_h + _YEAR_GAP
    year = anime.get("season_year") or ""
    p.setPen(QColor("#6f768b"))
    f2 = QFont(); f2.setPointSize(9)
    p.setFont(f2)
    p.drawText(QRect(left_rect.x() + 16, year_y, _LEFT_W - 32, _YEAR_H),
               Qt.AlignmentFlag.AlignLeft, str(year))

    bottom_y = year_y + _YEAR_H
    if avg:
        badge_y = year_y + _YEAR_H + _BADGE_GAP
        p.setPen(QColor("#fbbf24"))
        f3 = QFont(); f3.setPointSize(20); f3.setBold(True)
        p.setFont(f3)
        p.drawText(QRect(left_rect.x() + 16, badge_y, 90, _BADGE_H),
                   Qt.AlignmentFlag.AlignLeft, f"{avg:.1f}")
        label_y = badge_y + _BADGE_H + _BADGE_LABEL_GAP
        p.setPen(QColor("#6f768b"))
        f4 = QFont(); f4.setPointSize(9)
        p.setFont(f4)
        p.drawText(QRect(left_rect.x() + 16, label_y, _LEFT_W - 32, _BADGE_LABEL_H),
                   Qt.AlignmentFlag.AlignLeft, "AVG. EPISODE SCORE / 6")
        bottom_y = label_y + _BADGE_LABEL_H

    p.setPen(QColor("#4a5070"))
    f5 = QFont(); f5.setPointSize(9); f5.setBold(True)
    p.setFont(f5)
    p.drawText(QRect(left_rect.x(), bottom_y + _FOOTER_GAP, _LEFT_W, _FOOTER_H),
               Qt.AlignmentFlag.AlignHCenter, "MIROKU")

    # ── Right panel: legend + grid ──────────────────────────────────────
    rx = left_rect.right() + _MARGIN
    ry = _MARGIN

    lx = rx
    legend_y = ry + 6
    for v in range(1, 7):
        color = TIER_COLORS[v]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(lx, legend_y + 4, 10, 10)
        p.setPen(QColor("#9da5c0"))
        f6 = QFont(); f6.setPointSize(9)
        p.setFont(f6)
        label = RATING_LABELS[v]
        p.drawText(QRect(lx + 16, legend_y, 110, 20), Qt.AlignmentFlag.AlignVCenter, label)
        lx += 16 + p.fontMetrics().horizontalAdvance(label) + 26

    gy = ry + header_h
    for ep in range(1, last_ep + 1):
        idx = ep - 1
        col = idx % _COLS
        row = idx // _COLS
        tx = rx + col * (_TILE_W + _COL_GAP)
        row_top = gy + row * _ROW_STRIDE
        tyy = row_top + _LABEL_H
        tile_rect = QRect(tx, tyy, _TILE_W, _TILE_H)

        p.setPen(QColor("#6f768b"))
        f8 = QFont(); f8.setPointSize(8)
        p.setFont(f8)
        p.drawText(QRect(tx, row_top, _TILE_W, _LABEL_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, f"E{ep}")

        score = ratings.get(ep)
        tpath = QPainterPath()
        tpath.addRoundedRect(float(tx), float(tyy), float(_TILE_W), float(_TILE_H), 8, 8)
        if score:
            tier = _tile_tier(score)
            p.setBrush(TIER_COLORS[tier])
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(tpath)
            p.setPen(QColor("#0d0f14"))
            f7 = QFont(); f7.setPointSize(15); f7.setBold(True)
            p.setFont(f7)
            p.drawText(tile_rect, Qt.AlignmentFlag.AlignCenter, f"{score:g}")
        else:
            p.setBrush(_UNRATED_BG)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(tpath)
            p.setPen(_UNRATED_TXT)
            f7 = QFont(); f7.setPointSize(15); f7.setBold(True)
            p.setFont(f7)
            p.drawText(tile_rect, Qt.AlignmentFlag.AlignCenter, "?")

    p.end()
    return pm


class EpisodeExportDialog(QDialog):
    """Preview + save dialog for the episode-ratings export image."""

    def __init__(self, db: DatabaseManager, anime: Dict, parent=None):
        super().__init__(parent)
        self.anime = anime
        self._pixmap = render_ratings_card(db, anime)

        title = anime.get("english_title") or anime.get("romaji_title") or "Anime"
        self.setWindowTitle(f"Export ratings — {title}")
        self.setStyleSheet("QDialog{background:#0a0c11;}")
        self.resize(min(self._pixmap.width() + 60, 1000),
                    min(self._pixmap.height() + 120, 800))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        preview = QLabel()
        preview.setPixmap(self._pixmap)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll.setWidget(preview)
        lay.addWidget(scroll, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setObjectName("secondaryBtn")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)

        save_btn = QPushButton("Save as image…")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        lay.addLayout(btn_row)

    def _save(self):
        title = self.anime.get("english_title") or self.anime.get("romaji_title") or "anime"
        safe = "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip() or "anime"
        default_name = f"{safe} - ratings.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save ratings image", default_name, "PNG Image (*.png)"
        )
        if not path:
            return
        self._pixmap.save(path, "PNG")
        from ui.toast import Toast
        Toast.show(self.window(), "Ratings image saved.", kind="success")
