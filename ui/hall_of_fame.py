"""
Miroku — Hall of Fame  (v2 redesign)

Features
--------
A  Grid / List view toggle
B  Tier system  (S / A / B / C / D) — stored in DB, drag-assignable
C  Rich row card — banner blur bg, 88 px cover, genre chips, date inducted
D  #1 Hero card — full-width banner, gold crown, large title
E  Trailer button — opens existing TrailerPlayer
F  AniList score vs your rating side by side
G  Export as image — saves a PNG of your full Hall of Fame grid

DB note
-------
The `hall_of_fame` table gains a `tier` TEXT column (NULL = untiered).
Migration runs safely on first load via ALTER TABLE … ADD COLUMN IF NOT EXISTS.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import (
    Qt, QSize, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QPainter, QPainterPath, QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QTextEdit, QVBoxLayout, QWidget,
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

RANK_COLORS = {1: "#fbbf24", 2: "#c0c0c0", 3: "#cd7f32"}   # gold / silver / bronze


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _migrate(db: DatabaseManager) -> None:
    """Ensure hall_of_fame table exists with tier column."""
    conn = db._get_conn()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS hall_of_fame "
        "(rank INTEGER PRIMARY KEY, anime_id INTEGER UNIQUE, "
        " note TEXT, tier TEXT, added_at INTEGER)"
    )
    # Safe migration — add tier column to existing tables
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
    now = int(datetime.now(timezone.utc).timestamp())
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


# ── Main page ──────────────────────────────────────────────────────────────────

class HallOfFamePage(QWidget):
    """Hall of Fame — full redesign with grid/list views, tiers, export."""

    def __init__(self, db: DatabaseManager, parent=None) -> None:
        super().__init__(parent)
        self.db         = db
        self._entries:  List[Dict] = []
        self._view_mode = "list"   # "list" | "grid"
        self._build_ui()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 12)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(10)

        col = QVBoxLayout()
        col.setSpacing(4)
        title = QLabel("🏆  Hall of Fame")
        title.setObjectName("pageTitle")
        col.addWidget(title)
        sub = QLabel(
            "Your personal all-time greatest anime — ranked, tiered, celebrated."
        )
        sub.setStyleSheet("font-size:13px;color:#4a5070;")
        col.addWidget(sub)
        hdr.addLayout(col)
        hdr.addStretch()

        # View toggle
        self._list_btn = self._toolbar_btn("≡  List", "navBtn")
        self._list_btn.clicked.connect(lambda: self._set_view("list"))
        self._list_btn.setProperty("active", "true")
        hdr.addWidget(self._list_btn)

        self._grid_btn = self._toolbar_btn("⊞  Grid", "navBtn")
        self._grid_btn.clicked.connect(lambda: self._set_view("grid"))
        hdr.addWidget(self._grid_btn)

        # Export
        exp_btn = self._toolbar_btn("↓  Export", "secondaryBtn")
        exp_btn.clicked.connect(self._export_image)
        hdr.addWidget(exp_btn)

        # Add
        add_btn = QPushButton("+ Add Anime")
        add_btn.setObjectName("primaryBtn")
        add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_btn.clicked.connect(self._open_add)
        hdr.addWidget(add_btn)

        root.addLayout(hdr)
        root.addSpacing(20)

        # ── Tier legend strip ─────────────────────────────────────────────
        self._tier_strip = self._make_tier_strip()
        root.addWidget(self._tier_strip)
        root.addSpacing(16)

        # ── Scroll area (holds either list or grid content) ───────────────
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self._content_w = QWidget()
        self._content_w.setStyleSheet("background:transparent;")
        self._content_lay = QVBoxLayout(self._content_w)
        self._content_lay.setContentsMargins(0, 0, 0, 0)
        self._content_lay.setSpacing(0)

        self.scroll.setWidget(self._content_w)
        root.addWidget(self.scroll)

        # ── Empty state ───────────────────────────────────────────────────
        self.empty = QLabel(
            "🏆\n\nYour Hall of Fame is empty.\n\n"
            "Add your all-time favourite anime\n"
            "and rank them in order of greatness."
        )
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet(
            "font-size:14px;color:#3b4260;line-height:1.8;"
        )
        self.empty.setWordWrap(True)
        root.addWidget(self.empty)

    def _toolbar_btn(self, text: str, obj: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName(obj)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setFixedHeight(34)
        return b

    def _make_tier_strip(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        for key, label, color in TIERS:
            pill = QLabel(f"  {key}  {label}  ")
            pill.setStyleSheet(
                f"background:rgba(0,0,0,0.3);color:{color};"
                f"border:1px solid {color}44;border-radius:8px;"
                "font-size:11px;font-weight:700;padding:3px 0;"
            )
            lay.addWidget(pill)
        lay.addStretch()
        return w

    # ── Public API ─────────────────────────────────────────────────────────────

    def load(self) -> None:
        self._entries = _load_hof(self.db)
        self._render()

    # ── View switching ─────────────────────────────────────────────────────────

    def _set_view(self, mode: str) -> None:
        self._view_mode = mode
        for btn, m in [(self._list_btn, "list"), (self._grid_btn, "grid")]:
            btn.setProperty("active", "true" if m == mode else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._render()

    # ── Render dispatcher ──────────────────────────────────────────────────────

    def _render(self) -> None:
        # Clear content
        while self._content_lay.count():
            item = self._content_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        has = bool(self._entries)
        self.empty.setVisible(not has)
        self._tier_strip.setVisible(has)
        self.scroll.setVisible(has)

        if not has:
            return

        if self._view_mode == "grid":
            self._render_grid()
        else:
            self._render_list()

    # ── List view ──────────────────────────────────────────────────────────────

    def _render_list(self) -> None:
        """Render tiered list. Entries without a tier go into 'Untiered'."""
        # Group by tier
        tiered: Dict[str, List[Dict]] = {k: [] for k in TIER_KEYS}
        untiered: List[Dict] = []
        for e in self._entries:
            t = (e.get("tier") or "").strip().upper()
            if t in tiered:
                tiered[t].append(e)
            else:
                untiered.append(e)

        rank_counter = 1

        # #1 hero card (always first entry regardless of tier)
        if self._entries:
            hero = self._entries[0]
            hero_w = _HeroCard(hero, self.db)
            hero_w.remove_requested.connect(self._remove)
            hero_w.note_edited.connect(self._edit_note)
            hero_w.tier_changed.connect(self._change_tier)
            hero_w.trailer_requested.connect(self._open_trailer)
            self._content_lay.addWidget(hero_w)
            self._content_lay.addSpacing(20)
            self._load_entry_images(hero, hero_w)
            rank_counter = 2
            # Remove hero from tiered/untiered so it doesn't appear twice
            hero_id = hero.get("id")
            for lst in tiered.values():
                lst[:] = [e for e in lst if e.get("id") != hero_id]
            untiered = [e for e in untiered if e.get("id") != hero_id]

        # Tiered sections
        for key, label, color in TIERS:
            members = tiered[key]
            if not members:
                continue
            self._content_lay.addWidget(
                self._tier_section_header(key, label, color, len(members))
            )
            self._content_lay.addSpacing(8)
            for entry in members:
                row = _HofRow(rank_counter, entry, self.db)
                row.remove_requested.connect(self._remove)
                row.note_edited.connect(self._edit_note)
                row.move_up.connect(self._move_up)
                row.move_down.connect(self._move_down)
                row.tier_changed.connect(self._change_tier)
                row.trailer_requested.connect(self._open_trailer)
                self._content_lay.addWidget(row)
                self._content_lay.addSpacing(8)
                self._load_entry_images(entry, row)
                rank_counter += 1
            self._content_lay.addSpacing(12)

        # Untiered section
        if untiered:
            hdr = QLabel("— UNTIERED —")
            hdr.setStyleSheet(
                "font-size:10px;color:#3b4260;font-weight:700;"
                "letter-spacing:1.5px;padding:8px 0 4px;"
            )
            self._content_lay.addWidget(hdr)
            self._content_lay.addSpacing(8)
            for entry in untiered:
                row = _HofRow(rank_counter, entry, self.db)
                row.remove_requested.connect(self._remove)
                row.note_edited.connect(self._edit_note)
                row.move_up.connect(self._move_up)
                row.move_down.connect(self._move_down)
                row.tier_changed.connect(self._change_tier)
                row.trailer_requested.connect(self._open_trailer)
                self._content_lay.addWidget(row)
                self._content_lay.addSpacing(8)
                self._load_entry_images(entry, row)
                rank_counter += 1

        self._content_lay.addStretch(1)

    def _tier_section_header(
        self, key: str, label: str, color: str, count: int
    ) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
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
        line.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        lay.addWidget(line, 1)
        return w

    # ── Grid view ──────────────────────────────────────────────────────────────

    def _render_grid(self) -> None:
        """Compact poster grid — 6 columns, rank badge overlay."""
        COLS   = 6
        CARD_W = 140
        CARD_H = 200

        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        for idx, entry in enumerate(self._entries):
            card = _GridCard(idx + 1, entry, self.db)
            card.clicked.connect(self._on_grid_card_clicked)
            grid.addWidget(card, idx // COLS, idx % COLS)
            # Load cover
            self._load_cover_for_widget(entry, card)

        w = QWidget()
        w.setStyleSheet("background:transparent;")
        w.setLayout(grid)
        self._content_lay.addWidget(w)
        self._content_lay.addStretch(1)

    # ── Image loading helpers ──────────────────────────────────────────────────

    def _load_entry_images(
        self, entry: Dict, widget: QWidget
    ) -> None:
        """Load cover + banner for a list row / hero card."""
        self._load_cover_for_widget(entry, widget)
        banner_url = entry.get("banner_url", "")
        if banner_url and hasattr(widget, "set_banner"):
            from core.image_cache import get_cached_path
            bc = get_cached_path(banner_url)
            if bc:
                widget.set_banner(str(bc))
            else:
                bw = ImageWorker(banner_url, entry.get("id", 0), "banner")
                bw.signals.result.connect(
                    lambda r, w=widget: (
                        w.set_banner(r[2])
                        if r and r[2] and hasattr(w, "set_banner")
                        else None
                    )
                )
                run_worker(bw)

    def _load_cover_for_widget(self, entry: Dict, widget: QWidget) -> None:
        local = entry.get("cover_local", "")
        url   = entry.get("cover_url", "")
        if local and Path(local).exists():
            if hasattr(widget, "set_cover"):
                widget.set_cover(local)
            return
        if url and url.startswith("http"):
            from core.image_cache import get_cached_path
            cached = get_cached_path(url)
            if cached:
                if hasattr(widget, "set_cover"):
                    widget.set_cover(str(cached))
                return
            iw = ImageWorker(url, entry.get("id", 0), "cover")
            iw.signals.result.connect(
                lambda r, w=widget: (
                    w.set_cover(r[2])
                    if r and r[2] and hasattr(w, "set_cover")
                    else None
                )
            )
            run_worker(iw)
        elif url:
            if hasattr(widget, "set_cover"):
                widget.set_cover(url)

    # ── Actions ────────────────────────────────────────────────────────────────

    def _open_add(self) -> None:
        dlg = _AddToHofDialog(self.db, self)
        if dlg.exec():
            self.load()
            if getattr(dlg, "added_title", ""):
                from ui.toast import Toast
                Toast.show(
                    self.window(),
                    f"'{dlg.added_title}' added to Hall of Fame.",
                    kind="success",
                )

    def _remove(self, anime_id: int) -> None:
        name = next(
            (e.get("romaji_title", "?") for e in self._entries
             if e["id"] == anime_id),
            "?",
        )
        if (
            QMessageBox.question(
                self,
                "Remove from Hall of Fame",
                f"Remove '{name}' from your Hall of Fame?\n"
                "(The anime stays in your library.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            _remove_from_hof(self.db, anime_id)
            self.load()
            from ui.toast import Toast
            Toast.show(
                self.window(),
                f"'{name}' removed from Hall of Fame.",
                kind="success",
            )

    def _edit_note(self, anime_id: int, note: str) -> None:
        _update_hof_note(self.db, anime_id, note)
        from ui.toast import Toast
        Toast.show(self.window(), "Note saved.", kind="success")

    def _change_tier(self, anime_id: int, tier: str) -> None:
        _update_hof_tier(self.db, anime_id, tier)
        self.load()
        from ui.toast import Toast
        name = next(
            (e.get("romaji_title", "") for e in self._entries
             if e["id"] == anime_id),
            "",
        )
        label = TIER_LABELS.get(tier, tier)
        Toast.show(
            self.window(),
            f"'{name}' moved to Tier {tier} — {label}.",
            kind="success",
        )

    def _move_up(self, anime_id: int) -> None:
        idx = next(
            (i for i, e in enumerate(self._entries) if e["id"] == anime_id), -1
        )
        if idx <= 0:
            return
        self._entries[idx], self._entries[idx - 1] = (
            self._entries[idx - 1],
            self._entries[idx],
        )
        _save_hof_order(self.db, [e["id"] for e in self._entries])
        self.load()

    def _move_down(self, anime_id: int) -> None:
        idx = next(
            (i for i, e in enumerate(self._entries) if e["id"] == anime_id), -1
        )
        if idx < 0 or idx >= len(self._entries) - 1:
            return
        self._entries[idx], self._entries[idx + 1] = (
            self._entries[idx + 1],
            self._entries[idx],
        )
        _save_hof_order(self.db, [e["id"] for e in self._entries])
        self.load()

    def _on_grid_card_clicked(self, anime_id: int) -> None:
        entry = next((e for e in self._entries if e["id"] == anime_id), None)
        if not entry:
            return
        dlg = _EntryDetailDialog(entry, self.db, self)
        dlg.tier_changed.connect(self._change_tier)
        dlg.note_edited.connect(self._edit_note)
        dlg.remove_requested.connect(lambda aid: (self._remove(aid), dlg.accept()))
        dlg.trailer_requested.connect(self._open_trailer)
        dlg.exec()

    def _open_trailer(self, trailer_id: str, trailer_site: str) -> None:
        try:
            from ui.trailer_player import TrailerPlayer
            dlg = TrailerPlayer(trailer_id, trailer_site, self)
            dlg.exec()
        except Exception as exc:
            QMessageBox.information(
                self, "Trailer",
                f"Could not open trailer: {exc}"
            )

    # ── Export (Feature G) ────────────────────────────────────────────────────

    def _export_image(self) -> None:
        if not self._entries:
            QMessageBox.information(
                self, "Export", "Add some anime to your Hall of Fame first!"
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Hall of Fame",
            str(Path.home() / "miroku_hall_of_fame.png"),
            "PNG Image (*.png)",
        )
        if not path:
            return

        # Build a temporary grid widget, grab it, save
        COLS   = 5
        CARD_W = 130
        CARD_H = 185
        PAD    = 16
        HEADER = 56

        n      = len(self._entries)
        rows   = (n + COLS - 1) // COLS
        width  = COLS * CARD_W + (COLS + 1) * PAD
        height = rows * CARD_H + (rows + 1) * PAD + HEADER

        px = QPixmap(width, height)
        px.fill(QColor("#0d0f14"))

        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Header text
        p.setPen(QColor("#f0f1f5"))
        f = QFont()
        f.setPointSize(14)
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(PAD, 0, width - PAD * 2, HEADER,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "🏆  My Hall of Fame — Miroku")

        f2 = QFont()
        f2.setPointSize(8)
        p.setFont(f2)
        p.setPen(QColor("#4a5070"))
        p.drawText(PAD, 0, width - PAD * 2, HEADER,
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   datetime.now().strftime("%d %b %Y"))

        for idx, entry in enumerate(self._entries):
            col_i = idx % COLS
            row_i = idx // COLS
            x = PAD + col_i * (CARD_W + PAD)
            y = HEADER + PAD + row_i * (CARD_H + PAD)

            # Card background
            p.setBrush(QColor("#111420"))
            p.setPen(QColor("#1a1d28"))
            path = QPainterPath()
            path.addRoundedRect(x, y, CARD_W, CARD_H, 8, 8)
            p.drawPath(path)

            # Cover art
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

            # Rank badge
            rank_col = RANK_COLORS.get(idx + 1, "#4a5070")
            p.setBrush(QColor(rank_col))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(x + 6, y + 6, 22, 22)
            p.setPen(QColor("#0d0f14"))
            f3 = QFont()
            f3.setPointSize(7)
            f3.setWeight(QFont.Weight.Bold)
            p.setFont(f3)
            p.drawText(x + 6, y + 6, 22, 22,
                       Qt.AlignmentFlag.AlignCenter, str(idx + 1))

            # Tier badge
            tier = (entry.get("tier") or "").strip().upper()
            if tier in TIER_COLORS:
                tc = QColor(TIER_COLORS[tier])
                tc.setAlpha(200)
                p.setBrush(tc)
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(x + CARD_W - 28, y + 6, 22, 16, 4, 4)
                p.setPen(QColor("#0d0f14"))
                f4 = QFont()
                f4.setPointSize(7)
                f4.setWeight(QFont.Weight.Bold)
                p.setFont(f4)
                p.drawText(x + CARD_W - 28, y + 6, 22, 16,
                           Qt.AlignmentFlag.AlignCenter, tier)

            # Title
            p.setPen(QColor("#e8eaf5"))
            f5 = QFont()
            f5.setPointSize(7)
            f5.setWeight(QFont.Weight.Bold)
            p.setFont(f5)
            title = (
                entry.get("english_title") or entry.get("romaji_title", "")
            )[:28]
            p.drawText(
                x + 4, y + CARD_H - 38, CARD_W - 8, 18,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                title,
            )

            # Score
            sc = entry.get("average_score")
            if sc:
                p.setPen(QColor("#7c6af7"))
                f6 = QFont()
                f6.setPointSize(6)
                p.setFont(f6)
                p.drawText(
                    x + 4, y + CARD_H - 20, CARD_W - 8, 16,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    f"★ {sc / 10:.1f}",
                )

        p.end()
        px.save(path)

        from ui.toast import Toast
        Toast.show(
            self.window(),
            f"Hall of Fame exported to {Path(path).name}",
            kind="success",
        )


# ── Hero card (#1 entry) ───────────────────────────────────────────────────────

class _HeroCard(QFrame):
    """Full-width hero card for the #1 ranked entry."""

    remove_requested = pyqtSignal(int)
    note_edited      = pyqtSignal(int, str)
    tier_changed     = pyqtSignal(int, str)
    trailer_requested = pyqtSignal(str, str)

    _H = 220

    def __init__(self, entry: Dict, db: DatabaseManager,
                 parent=None) -> None:
        super().__init__(parent)
        self._aid   = entry["id"]
        self._entry = entry
        self.db     = db
        self.setFixedHeight(self._H)
        self.setObjectName("hofHeroCard")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        # Banner as background label
        self._banner_lbl = QLabel(self)
        self._banner_lbl.setGeometry(0, 0, 9999, self._H)
        self._banner_lbl.setScaledContents(False)
        self._banner_lbl.setStyleSheet(
            "background:#0f1118;border-radius:12px;"
        )

        # Dark overlay so text is readable
        overlay = QWidget(self)
        overlay.setGeometry(0, 0, 9999, self._H)
        overlay.setStyleSheet(
            "background:qlineargradient("
            "x1:0,y1:0,x2:1,y2:0,"
            "stop:0 rgba(10,12,18,0.98),"
            "stop:0.45 rgba(10,12,18,0.85),"
            "stop:1 rgba(10,12,18,0.2));"
            "border-radius:12px;"
        )

        # Content layout on top of overlay
        content = QWidget(self)
        content.setGeometry(0, 0, 9999, self._H)
        content.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(content)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(20)

        # Cover
        self._cover_lbl = QLabel()
        self._cover_lbl.setFixedSize(118, 170)
        self._cover_lbl.setStyleSheet(
            "background:#1a1d28;border-radius:8px;"
            "border:2px solid #fbbf2455;"
        )
        self._cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._cover_lbl)

        # Info
        info = QVBoxLayout()
        info.setSpacing(8)
        info.setContentsMargins(0, 0, 0, 0)

        # Crown + rank
        crown_row = QHBoxLayout()
        crown_row.setSpacing(8)
        crown = QLabel("👑  #1")
        crown.setStyleSheet(
            "font-size:13px;font-weight:900;color:#fbbf24;"
            "background:transparent;letter-spacing:1px;"
        )
        crown_row.addWidget(crown)

        tier_val = (entry.get("tier") or "").strip().upper()
        if tier_val in TIER_COLORS:
            tb = QLabel(f" {tier_val} ")
            tb.setStyleSheet(
                f"background:{TIER_COLORS[tier_val]};"
                "color:#0d0f14;font-size:11px;font-weight:900;"
                "border-radius:4px;padding:1px 4px;"
            )
            crown_row.addWidget(tb)
        crown_row.addStretch()
        info.addLayout(crown_row)

        # Title
        title = entry.get("english_title") or entry.get("romaji_title", "")
        tl = QLabel(title)
        tl.setWordWrap(True)
        tl.setStyleSheet(
            "font-size:22px;font-weight:900;color:#f5f6ff;"
            "background:transparent;letter-spacing:-0.3px;"
        )
        info.addWidget(tl)

        # Meta: year · episodes · studio
        meta_parts = []
        yr = entry.get("season_year")
        if yr:
            meta_parts.append(str(yr))
        eps = entry.get("total_episodes")
        if eps:
            meta_parts.append(f"{eps} eps")
        studios = entry.get("studios") or []
        if studios:
            meta_parts.append(studios[0])
        ml = QLabel("  ·  ".join(meta_parts))
        ml.setStyleSheet("font-size:12px;color:#6b7280;background:transparent;")
        info.addWidget(ml)

        # Scores row: your rating + AniList score side by side
        scores_row = QHBoxLayout()
        scores_row.setSpacing(16)
        avg = db.get_average_rating(entry["id"])
        if avg is not None:
            yr_lbl = QLabel(f"★ {avg:.1f}/6")
            yr_lbl.setStyleSheet(
                "font-size:16px;font-weight:700;color:#fbbf24;"
                "background:transparent;"
            )
            yr_lbl.setToolTip("Your rating")
            scores_row.addWidget(yr_lbl)
        sc = entry.get("average_score")
        if sc:
            al_lbl = QLabel(f"AL {sc / 10:.1f}")
            al_lbl.setStyleSheet(
                "font-size:14px;font-weight:600;color:#7c6af7;"
                "background:transparent;"
            )
            al_lbl.setToolTip("AniList community score")
            scores_row.addWidget(al_lbl)
        scores_row.addStretch()
        info.addLayout(scores_row)

        # Genre chips
        chips_row = QHBoxLayout()
        chips_row.setSpacing(6)
        for g in (entry.get("genres") or [])[:4]:
            chip = QLabel(g)
            chip.setStyleSheet(
                "background:#151929;color:#7c6af7;"
                "border:1px solid #272060;border-radius:8px;"
                "font-size:10px;padding:2px 8px;"
            )
            chips_row.addWidget(chip)
        chips_row.addStretch()
        info.addLayout(chips_row)

        # Note
        note_txt = entry.get("note") or ""
        self._note_lbl = QLabel(
            f'"{note_txt}"' if note_txt else "Click to add a personal note…"
        )
        self._note_lbl.setStyleSheet(
            f"font-size:13px;color:{'#b8adff' if note_txt else '#3b4260'};"
            "font-style:italic;background:transparent;"
        )
        self._note_lbl.setWordWrap(True)
        self._note_lbl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._note_lbl.mousePressEvent = lambda e: self._edit_note_dlg()
        info.addWidget(self._note_lbl)

        info.addStretch()

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        if entry.get("trailer_id"):
            t_btn = QPushButton("▶  Trailer")
            t_btn.setObjectName("secondaryBtn")
            t_btn.setFixedHeight(30)
            t_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            t_btn.clicked.connect(
                lambda: self.trailer_requested.emit(
                    entry.get("trailer_id", ""),
                    entry.get("trailer_site", "youtube"),
                )
            )
            btn_row.addWidget(t_btn)

        # Tier picker
        tier_combo = QComboBox()
        tier_combo.setFixedHeight(30)
        tier_combo.setFixedWidth(120)
        tier_combo.addItem("Set Tier…", "")
        for k, lbl, _ in TIERS:
            tier_combo.addItem(f"{k} — {lbl}", k)
        cur_tier = (entry.get("tier") or "").strip().upper()
        if cur_tier:
            for i in range(tier_combo.count()):
                if tier_combo.itemData(i) == cur_tier:
                    tier_combo.setCurrentIndex(i)
                    break
        tier_combo.currentIndexChanged.connect(
            lambda idx, c=tier_combo: (
                self.tier_changed.emit(self._aid, c.itemData(idx))
                if c.itemData(idx) else None
            )
        )
        btn_row.addWidget(tier_combo)

        rm_btn = QPushButton("Remove")
        rm_btn.setObjectName("dangerBtn")
        rm_btn.setFixedHeight(30)
        rm_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        rm_btn.clicked.connect(
            lambda: self.remove_requested.emit(self._aid)
        )
        btn_row.addWidget(rm_btn)
        btn_row.addStretch()
        info.addLayout(btn_row)

        lay.addLayout(info, 1)

    def set_cover(self, path: str) -> None:
        if not path:
            return
        px = QPixmap(path)
        if px.isNull():
            return
        w, h = 118, 170
        px = px.scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        cx = (px.width() - w) // 2
        cy = (px.height() - h) // 2
        px = px.copy(cx, cy, w, h)
        # Rounded clip
        rounded = QPixmap(w, h)
        rounded.fill(QColor(0, 0, 0, 0))
        pt = QPainter(rounded)
        pt.setRenderHint(QPainter.RenderHint.Antialiasing)
        pp = QPainterPath()
        pp.addRoundedRect(0, 0, w, h, 8, 8)
        pt.setClipPath(pp)
        pt.drawPixmap(0, 0, px)
        pt.end()
        self._cover_lbl.setPixmap(rounded)

    def set_banner(self, path: str) -> None:
        if not path:
            return
        px = QPixmap(path)
        if px.isNull():
            return
        w = self.width() or 900
        px = px.scaled(
            w, self._H,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._banner_lbl.setPixmap(px.copy(0, 0, w, self._H))
        self._banner_lbl.setGeometry(0, 0, w, self._H)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        # Re-stretch all child overlays to new width
        for child in (self._banner_lbl,):
            child.setGeometry(0, 0, self.width(), self._H)

    def _edit_note_dlg(self) -> None:
        dlg = _NoteDialog(self._entry.get("note") or "", self)
        if dlg.exec():
            note = dlg.get_note()
            self._note_lbl.setText(
                f'"{note}"' if note else "Click to add a personal note…"
            )
            self._note_lbl.setStyleSheet(
                f"font-size:13px;color:{'#b8adff' if note else '#3b4260'};"
                "font-style:italic;background:transparent;"
            )
            self.note_edited.emit(self._aid, note)


# ── Rich list row ──────────────────────────────────────────────────────────────

class _HofRow(QFrame):
    """Rich row card for list view (ranks 2+)."""

    remove_requested  = pyqtSignal(int)
    note_edited       = pyqtSignal(int, str)
    move_up           = pyqtSignal(int)
    move_down         = pyqtSignal(int)
    tier_changed      = pyqtSignal(int, str)
    trailer_requested = pyqtSignal(str, str)

    def __init__(self, rank: int, entry: Dict, db: DatabaseManager,
                 parent=None) -> None:
        super().__init__(parent)
        self._aid   = entry["id"]
        self._entry = entry
        self.db     = db
        self.rank   = rank

        self.setObjectName("hofRowCard")
        self.setMinimumHeight(120)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 16, 0)
        lay.setSpacing(0)

        # Rank badge
        rank_col = RANK_COLORS.get(rank, "#4a5070")
        rank_w = QWidget()
        rank_w.setFixedWidth(52)
        rank_w.setStyleSheet("background:transparent;")
        rl = QVBoxLayout(rank_w)
        rl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rl.setContentsMargins(0, 0, 0, 0)
        rnk = QLabel(f"#{rank}")
        rnk.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rnk.setStyleSheet(
            f"font-size:{'17' if rank <= 3 else '14'}px;"
            f"font-weight:800;color:{rank_col};background:transparent;"
        )
        rl.addWidget(rnk)
        lay.addWidget(rank_w)

        # Cover
        self._cover_lbl = QLabel()
        self._cover_lbl.setFixedSize(72, 104)
        self._cover_lbl.setStyleSheet(
            "background:#1a1d28;border-radius:6px;margin:8px 0;"
        )
        self._cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._cover_lbl)
        lay.addSpacing(14)

        # Info column
        info = QVBoxLayout()
        info.setSpacing(5)
        info.setContentsMargins(0, 12, 0, 10)

        # Title + tier badge
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = entry.get("english_title") or entry.get("romaji_title", "")
        tl = QLabel(title[:70])
        tl.setStyleSheet(
            "font-size:15px;font-weight:700;color:#f0f1f5;background:transparent;"
        )
        title_row.addWidget(tl)

        tier_val = (entry.get("tier") or "").strip().upper()
        if tier_val in TIER_COLORS:
            tb = QLabel(f" {tier_val} ")
            tb.setStyleSheet(
                f"background:{TIER_COLORS[tier_val]};color:#0d0f14;"
                "font-size:10px;font-weight:900;border-radius:4px;"
                "padding:1px 4px;"
            )
            title_row.addWidget(tb)
        title_row.addStretch()
        info.addLayout(title_row)

        # Scores: your rating + AniList
        scores_row = QHBoxLayout()
        scores_row.setSpacing(14)
        avg = db.get_average_rating(entry["id"])
        if avg is not None:
            yr_lbl = QLabel(f"★ {avg:.1f}/6  yours")
            yr_lbl.setStyleSheet(
                "font-size:12px;font-weight:700;color:#fbbf24;"
                "background:transparent;"
            )
            scores_row.addWidget(yr_lbl)
        sc = entry.get("average_score")
        if sc:
            al_lbl = QLabel(f"AL {sc / 10:.1f}")
            al_lbl.setStyleSheet(
                "font-size:12px;color:#7c6af7;background:transparent;"
            )
            scores_row.addWidget(al_lbl)
        yr = entry.get("season_year")
        eps = entry.get("total_episodes")
        if yr or eps:
            meta = "  ·  ".join(
                filter(None, [str(yr) if yr else "", f"{eps} eps" if eps else ""])
            )
            ml = QLabel(meta)
            ml.setStyleSheet(
                "font-size:12px;color:#4a5070;background:transparent;"
            )
            scores_row.addWidget(ml)
        scores_row.addStretch()
        info.addLayout(scores_row)

        # Genre chips
        chips = QHBoxLayout()
        chips.setSpacing(5)
        for g in (entry.get("genres") or [])[:4]:
            chip = QLabel(g)
            chip.setStyleSheet(
                "background:#151929;color:#7c6af7;"
                "border:1px solid #272060;border-radius:7px;"
                "font-size:10px;padding:2px 7px;"
            )
            chips.addWidget(chip)
        chips.addStretch()
        info.addLayout(chips)

        # Note
        note_txt = entry.get("note") or ""
        self._note_lbl = QLabel(
            f'"{note_txt}"' if note_txt else "Click to add a note…"
        )
        self._note_lbl.setStyleSheet(
            f"font-size:12px;color:{'#9da5c0' if note_txt else '#3b4260'};"
            "font-style:italic;background:transparent;"
        )
        self._note_lbl.setWordWrap(True)
        self._note_lbl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._note_lbl.mousePressEvent = lambda e: self._edit_note_dlg()
        info.addWidget(self._note_lbl)

        # Date inducted
        added = entry.get("added_at")
        if added:
            try:
                date_str = datetime.fromtimestamp(added).strftime("Added %d %b %Y")
                dl = QLabel(date_str)
                dl.setStyleSheet(
                    "font-size:10px;color:#2a3048;background:transparent;"
                )
                info.addWidget(dl)
            except Exception:
                pass

        lay.addLayout(info, 1)

        # Right-side controls
        ctrl = QVBoxLayout()
        ctrl.setSpacing(4)
        ctrl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        ctrl.setContentsMargins(0, 8, 0, 8)

        if entry.get("trailer_id"):
            tr_btn = QPushButton("▶")
            tr_btn.setObjectName("iconBtn")
            tr_btn.setFixedSize(28, 28)
            tr_btn.setToolTip("Watch trailer")
            tr_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            tr_btn.clicked.connect(
                lambda: self.trailer_requested.emit(
                    entry.get("trailer_id", ""),
                    entry.get("trailer_site", "youtube"),
                )
            )
            ctrl.addWidget(tr_btn)

        # Tier combo
        tc = QComboBox()
        tc.setFixedWidth(54)
        tc.setFixedHeight(26)
        tc.setToolTip("Set tier")
        tc.addItem("–", "")
        for k, _, _ in TIERS:
            tc.addItem(k, k)
        cur_tier = (entry.get("tier") or "").strip().upper()
        if cur_tier:
            for i in range(tc.count()):
                if tc.itemData(i) == cur_tier:
                    tc.setCurrentIndex(i)
                    break
        tc.currentIndexChanged.connect(
            lambda idx, c=tc: (
                self.tier_changed.emit(self._aid, c.itemData(idx))
                if c.itemData(idx) else None
            )
        )
        ctrl.addWidget(tc)

        up_btn = self._icon_btn("▲", "Move up")
        up_btn.clicked.connect(lambda: self.move_up.emit(self._aid))
        ctrl.addWidget(up_btn)

        dn_btn = self._icon_btn("▼", "Move down")
        dn_btn.clicked.connect(lambda: self.move_down.emit(self._aid))
        ctrl.addWidget(dn_btn)

        rm_btn = self._icon_btn("✕", "Remove")
        rm_btn.setStyleSheet(
            rm_btn.styleSheet() + "color:#f87171;"
        )
        rm_btn.clicked.connect(
            lambda: self.remove_requested.emit(self._aid)
        )
        ctrl.addWidget(rm_btn)

        lay.addLayout(ctrl)

    def _icon_btn(self, text: str, tip: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("iconBtn")
        b.setFixedSize(28, 28)
        b.setToolTip(tip)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        return b

    def set_cover(self, path: str) -> None:
        if not path:
            return
        px = QPixmap(path)
        if px.isNull():
            return
        w, h = 72, 104
        px = px.scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        cx = (px.width() - w) // 2
        cy = (px.height() - h) // 2
        self._cover_lbl.setPixmap(px.copy(cx, cy, w, h))

    def set_banner(self, path: str) -> None:
        pass   # rows don't use banner

    def _edit_note_dlg(self) -> None:
        dlg = _NoteDialog(self._entry.get("note") or "", self)
        if dlg.exec():
            note = dlg.get_note()
            self._note_lbl.setText(
                f'"{note}"' if note else "Click to add a note…"
            )
            self._note_lbl.setStyleSheet(
                f"font-size:12px;color:{'#9da5c0' if note else '#3b4260'};"
                "font-style:italic;background:transparent;"
            )
            self.note_edited.emit(self._aid, note)


# ── Grid card ──────────────────────────────────────────────────────────────────

class _GridCard(QFrame):
    """Compact poster card for grid view."""

    clicked = pyqtSignal(int)

    CARD_W = 140
    CARD_H = 200

    def __init__(self, rank: int, entry: Dict, db: DatabaseManager,
                 parent=None) -> None:
        super().__init__(parent)
        self._aid   = entry["id"]
        self._entry = entry
        self.setObjectName("hofGridCard")
        self.setFixedSize(self.CARD_W, self.CARD_H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        # Cover
        self._cover_lbl = QLabel(self)
        self._cover_lbl.setFixedSize(self.CARD_W, self.CARD_H)
        self._cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_lbl.setStyleSheet("background:#111420;border-radius:10px;")

        # Bottom gradient overlay
        grad = QWidget(self)
        grad.setFixedSize(self.CARD_W, 72)
        grad.move(0, self.CARD_H - 72)
        grad.setStyleSheet(
            "background:qlineargradient("
            "x1:0,y1:0,x2:0,y2:1,"
            "stop:0 rgba(0,0,0,0),"
            "stop:1 rgba(0,0,0,0.95));"
        )
        grad.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # Rank badge
        rank_col = RANK_COLORS.get(rank, "#4a5070")
        rank_lbl = QLabel(f"#{rank}", self)
        rank_lbl.setFixedSize(30, 22)
        rank_lbl.move(7, 7)
        rank_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rank_lbl.setStyleSheet(
            f"background:rgba(10,12,18,0.88);color:{rank_col};"
            "font-size:11px;font-weight:800;border-radius:5px;"
        )
        rank_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # Tier badge
        tier = (entry.get("tier") or "").strip().upper()
        if tier in TIER_COLORS:
            tb = QLabel(f" {tier} ", self)
            tb.setFixedHeight(20)
            tb.adjustSize()
            tb.move(self.CARD_W - tb.width() - 7, 7)
            tb.setStyleSheet(
                f"background:{TIER_COLORS[tier]};color:#0d0f14;"
                "font-size:10px;font-weight:900;border-radius:4px;padding:0 4px;"
            )
            tb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # Title label
        title = (
            entry.get("english_title") or entry.get("romaji_title", "")
        )
        tl = QLabel(title[:22], self)
        tl.setWordWrap(True)
        tl.setFixedWidth(self.CARD_W - 12)
        tl.move(6, self.CARD_H - 52)
        tl.setStyleSheet(
            "font-size:11px;font-weight:700;color:#f0f1f5;"
            "background:transparent;"
        )
        tl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # Score
        sc = entry.get("average_score")
        if sc:
            sl = QLabel(f"★ {sc / 10:.1f}", self)
            sl.move(6, self.CARD_H - 22)
            sl.setStyleSheet(
                "font-size:10px;font-weight:600;color:#a594f9;"
                "background:transparent;"
            )
            sl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # Apply rounded clip
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QRegion
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(0, 0, self.CARD_W, self.CARD_H), 10, 10
        )
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

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
        self._cover_lbl.setPixmap(px.copy(cx, cy, self.CARD_W, self.CARD_H))

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._aid)
        super().mousePressEvent(ev)


# ── Entry detail dialog (opened from grid view click) ─────────────────────────

class _EntryDetailDialog(QDialog):
    """Full detail dialog for a HoF entry, opened from grid card click."""

    tier_changed      = pyqtSignal(int, str)
    note_edited       = pyqtSignal(int, str)
    remove_requested  = pyqtSignal(int)
    trailer_requested = pyqtSignal(str, str)

    def __init__(self, entry: Dict, db: DatabaseManager,
                 parent=None) -> None:
        super().__init__(parent)
        self._aid   = entry["id"]
        self._entry = entry
        self.db     = db
        self.setWindowTitle(
            entry.get("english_title") or entry.get("romaji_title", "")
        )
        self.setMinimumSize(540, 420)
        self.setStyleSheet("background:#0f1118;")
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 20)
        lay.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(20)

        self._cover_lbl = QLabel()
        self._cover_lbl.setFixedSize(110, 158)
        self._cover_lbl.setStyleSheet(
            "background:#1a1d28;border-radius:8px;"
        )
        top.addWidget(self._cover_lbl, 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(8)

        title = (
            self._entry.get("english_title")
            or self._entry.get("romaji_title", "")
        )
        tl = QLabel(title)
        tl.setWordWrap(True)
        tl.setStyleSheet(
            "font-size:18px;font-weight:800;color:#f0f1f5;"
        )
        info.addWidget(tl)

        scores_row = QHBoxLayout()
        avg = self.db.get_average_rating(self._entry["id"])
        if avg is not None:
            yl = QLabel(f"★ {avg:.1f}/6  your rating")
            yl.setStyleSheet("font-size:13px;color:#fbbf24;font-weight:700;")
            scores_row.addWidget(yl)
        sc = self._entry.get("average_score")
        if sc:
            al = QLabel(f"AniList: {sc / 10:.1f}")
            al.setStyleSheet("font-size:13px;color:#7c6af7;")
            scores_row.addWidget(al)
        scores_row.addStretch()
        info.addLayout(scores_row)

        # Genre chips
        chips = QHBoxLayout()
        chips.setSpacing(5)
        for g in (self._entry.get("genres") or [])[:5]:
            c = QLabel(g)
            c.setStyleSheet(
                "background:#151929;color:#7c6af7;"
                "border:1px solid #272060;border-radius:8px;"
                "font-size:11px;padding:3px 9px;"
            )
            chips.addWidget(c)
        chips.addStretch()
        info.addLayout(chips)

        # Tier selector
        tier_row = QHBoxLayout()
        tier_row.setSpacing(8)
        tier_row.addWidget(QLabel("Tier:"))
        tc = QComboBox()
        tc.addItem("No tier", "")
        for k, lbl, _ in TIERS:
            tc.addItem(f"{k} — {lbl}", k)
        cur = (self._entry.get("tier") or "").strip().upper()
        for i in range(tc.count()):
            if tc.itemData(i) == cur:
                tc.setCurrentIndex(i)
                break
        tc.currentIndexChanged.connect(
            lambda idx, c=tc: (
                self.tier_changed.emit(self._aid, c.itemData(idx))
            )
        )
        tier_row.addWidget(tc)
        tier_row.addStretch()
        info.addLayout(tier_row)

        info.addStretch()
        top.addLayout(info, 1)
        lay.addLayout(top)

        # Note
        note_lbl = QLabel("Personal note:")
        note_lbl.setStyleSheet("font-size:11px;color:#4a5070;")
        lay.addWidget(note_lbl)
        self._note_edit = QTextEdit()
        self._note_edit.setPlaceholderText("What made this special for you?")
        self._note_edit.setPlainText(self._entry.get("note") or "")
        self._note_edit.setFixedHeight(70)
        lay.addWidget(self._note_edit)

        # Buttons
        btns = QHBoxLayout()
        if self._entry.get("trailer_id"):
            tr = QPushButton("▶  Watch Trailer")
            tr.setObjectName("secondaryBtn")
            tr.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            tr.clicked.connect(
                lambda: self.trailer_requested.emit(
                    self._entry.get("trailer_id", ""),
                    self._entry.get("trailer_site", "youtube"),
                )
            )
            btns.addWidget(tr)

        btns.addStretch()

        rm = QPushButton("Remove from HoF")
        rm.setObjectName("dangerBtn")
        rm.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        rm.clicked.connect(lambda: self.remove_requested.emit(self._aid))
        btns.addWidget(rm)

        save = QPushButton("Save Note")
        save.setObjectName("primaryBtn")
        save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save.clicked.connect(self._save_note)
        btns.addWidget(save)

        lay.addLayout(btns)

        # Load cover
        local = self._entry.get("cover_local", "")
        url   = self._entry.get("cover_url", "")
        if local and Path(local).exists():
            self._set_cover(local)
        elif url:
            from core.image_cache import get_cached_path
            cached = get_cached_path(url)
            if cached:
                self._set_cover(str(cached))

    def _set_cover(self, path: str) -> None:
        px = QPixmap(path)
        if px.isNull():
            return
        w, h = 110, 158
        px = px.scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        cx = (px.width() - w) // 2
        cy = (px.height() - h) // 2
        self._cover_lbl.setPixmap(px.copy(cx, cy, w, h))

    def _save_note(self) -> None:
        note = self._note_edit.toPlainText().strip()
        self.note_edited.emit(self._aid, note)
        self.accept()


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
        for btn, t in [
            (self.lib_tab_btn, "library"), (self.al_tab_btn, "anilist")
        ]:
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
            if q
            else self._all_anime
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
            self.preview_lbl.setText(
                f"✓  Selected: {anime.get('romaji_title', '')}"
            )

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
                    lambda r, rw=row: (
                        rw.set_cover(r[2]) if r and r[2] else None
                    )
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
                Toast.show(
                    self.window(),
                    "Already in your Hall of Fame.",
                    kind="info",
                )
                return
            _add_to_hof(self.db, lib_id)
            anime = self.db.get_anime_by_id(lib_id)
            self.added_title = (anime or {}).get("romaji_title", "Anime")
            self.accept()
            return

        anilist_id = m.get("id")
        existing   = (
            self.db.get_anime_by_anilist_id(anilist_id) if anilist_id else None
        )
        if existing:
            if _in_hof(self.db, existing["id"]):
                from ui.toast import Toast
                Toast.show(
                    self.window(), "Already in your Hall of Fame.", kind="info"
                )
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
                Toast.show(
                    self.window(), "Already in your Hall of Fame.", kind="info"
                )
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
            f"font-size:13px;font-weight:600;"
            f"color:{'#4a5070' if in_hof else '#dde0ed'};"
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
            scl.setStyleSheet(
                "font-size:12px;color:#7c6af7;font-weight:600;"
            )
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


# ── Note dialog ────────────────────────────────────────────────────────────────

class _NoteDialog(QDialog):
    def __init__(self, current: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Personal Note")
        self.setMinimumSize(420, 230)
        self.setStyleSheet("background:#0f1118;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        t = QLabel("Your note about this anime")
        t.setObjectName("dialogTitle")
        lay.addWidget(t)

        self.edit = QTextEdit()
        self.edit.setPlaceholderText(
            "e.g. 'The ending changed my life.' or 'Best OST ever made.'"
        )
        self.edit.setPlainText(current)
        self.edit.setFixedHeight(90)
        lay.addWidget(self.edit)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondaryBtn")
        cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        save = QPushButton("Save Note")
        save.setObjectName("primaryBtn")
        save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save.clicked.connect(self.accept)
        btns.addWidget(save)
        lay.addLayout(btns)

    def get_note(self) -> str:
        return self.edit.toPlainText().strip()