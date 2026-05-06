"""
AnimeTracker — Hall of Fame
Your personal ranked list of all-time favourite anime.
Features: drag-to-reorder ranking, AniList score display, latest news fetch,
          personal notes, cover art, add from library.
"""
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QDialog, QLineEdit, QTextEdit,
    QMessageBox, QComboBox, QSizePolicy, QProgressBar,
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QMimeData, QPoint, QTimer,
)
from PyQt6.QtGui import QPixmap, QColor, QCursor, QPainter, QPainterPath, QDrag

from core.database import DatabaseManager
from workers.workers import Worker, ImageWorker, run_worker


# ─── DB helpers (stored as JSON in a simple key-value table) ──────────────────

def _load_hof(db: DatabaseManager) -> List[Dict]:
    conn = db._get_conn()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS hall_of_fame "
        "(rank INTEGER PRIMARY KEY, anime_id INTEGER, note TEXT, added_at INTEGER)"
    )
    conn.commit()
    rows = conn.execute(
        "SELECT h.rank, h.note, h.added_at, a.* "
        "FROM hall_of_fame h JOIN anime a ON h.anime_id = a.id "
        "ORDER BY h.rank"
    ).fetchall()
    result = []
    for r in rows:
        import json
        d = dict(r)
        for k in ("genres", "studios"):
            if isinstance(d.get(k), str):
                try: d[k] = json.loads(d[k])
                except: d[k] = []
        result.append(d)
    return result


def _save_hof_order(db: DatabaseManager, ordered_anime_ids: List[int]):
    conn = db._get_conn()
    conn.execute("DELETE FROM hall_of_fame")
    now = int(datetime.now(timezone.utc).timestamp())
    for rank, aid in enumerate(ordered_anime_ids, 1):
        conn.execute(
            "INSERT OR IGNORE INTO hall_of_fame (rank, anime_id, added_at) VALUES (?,?,?)",
            (rank, aid, now)
        )
    conn.commit()


def _add_to_hof(db: DatabaseManager, anime_id: int, note: str = ""):
    conn = db._get_conn()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS hall_of_fame "
        "(rank INTEGER PRIMARY KEY, anime_id INTEGER, note TEXT, added_at INTEGER)"
    )
    max_rank = conn.execute("SELECT MAX(rank) FROM hall_of_fame").fetchone()[0] or 0
    conn.execute(
        "INSERT OR IGNORE INTO hall_of_fame (rank, anime_id, note, added_at) VALUES (?,?,?,?)",
        (max_rank + 1, anime_id, note, int(datetime.now(timezone.utc).timestamp()))
    )
    conn.commit()


def _remove_from_hof(db: DatabaseManager, anime_id: int):
    conn = db._get_conn()
    conn.execute("DELETE FROM hall_of_fame WHERE anime_id=?", (anime_id,))
    conn.commit()


def _update_hof_note(db: DatabaseManager, anime_id: int, note: str):
    conn = db._get_conn()
    conn.execute("UPDATE hall_of_fame SET note=? WHERE anime_id=?", (note, anime_id))
    conn.commit()


def _in_hof(db: DatabaseManager, anime_id: int) -> bool:
    conn = db._get_conn()
    r = conn.execute("SELECT 1 FROM hall_of_fame WHERE anime_id=?", (anime_id,)).fetchone()
    return bool(r)


# ─── Page ─────────────────────────────────────────────────────────────────────

class HallOfFamePage(QWidget):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self._entries: List[Dict] = []
        self._row_widgets: List["HofRow"] = []
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 12)
        lay.setSpacing(0)

        # Header
        hr = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(4)
        t = QLabel("🏆  Hall of Fame")
        t.setObjectName("pageTitle")
        col.addWidget(t)
        sub = QLabel(
            "Your personal all-time greatest anime — ranked, remembered, celebrated."
        )
        sub.setStyleSheet("font-size:13px;color:#4a5070;")
        col.addWidget(sub)
        hr.addLayout(col)
        hr.addStretch()

        self.add_btn = QPushButton("+ Add from Library")
        self.add_btn.setObjectName("primaryBtn")
        self.add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.add_btn.clicked.connect(self._open_add)
        hr.addWidget(self.add_btn)
        lay.addLayout(hr)
        lay.addSpacing(20)

        # Instructions
        self.tip = QLabel("Drag rows to reorder your ranking.")
        self.tip.setStyleSheet("font-size:12px;color:#3b4260;font-style:italic;")
        lay.addWidget(self.tip)
        lay.addSpacing(12)

        # Scroll list
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.list_w = QWidget()
        self.list_w.setStyleSheet("background:transparent;")
        self.list_lay = QVBoxLayout(self.list_w)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(10)
        self.list_lay.addStretch()

        self.scroll.setWidget(self.list_w)
        lay.addWidget(self.scroll)

        # Empty state
        self.empty = QLabel(
            "🏆\n\nYour Hall of Fame is empty.\n\n"
            "Add your all-time favourite anime from your library\n"
            "and rank them in order of greatness."
        )
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet("font-size:14px;color:#3b4260;line-height:1.8;")
        self.empty.setWordWrap(True)
        lay.addWidget(self.empty)

    def load(self):
        self._entries = _load_hof(self.db)
        self._render()

    def _render(self):
        # Clear
        for rw in self._row_widgets:
            rw.setParent(None)
        self._row_widgets = []
        for i in reversed(range(self.list_lay.count())):
            w = self.list_lay.itemAt(i).widget()
            if w: w.setParent(None)

        has = bool(self._entries)
        self.empty.setVisible(not has)
        self.tip.setVisible(has)
        self.scroll.setVisible(has)

        if not has:
            return

        for i, entry in enumerate(self._entries):
            row = HofRow(i + 1, entry, self.db)
            row.remove_requested.connect(self._remove)
            row.note_edited.connect(self._edit_note)
            row.move_up.connect(self._move_up)
            row.move_down.connect(self._move_down)
            self.list_lay.insertWidget(i, row)
            self._row_widgets.append(row)
            # Load cover
            url = entry.get("cover_local") or entry.get("cover_url", "")
            if url and url.startswith("http"):
                from core.image_cache import get_cached_path
                cached = get_cached_path(url)
                if cached:
                    row.set_cover(str(cached))
                else:
                    iw = ImageWorker(url, i)
                    iw.signals.result.connect(
                        lambda r, rw=row: rw.set_cover(r[2]) if r and r[2] else None
                    )
                    run_worker(iw)
            elif url:
                row.set_cover(url)

    def _open_add(self):
        dlg = _AddToHofDialog(self.db, self)
        if dlg.exec():
            self.load()

    def _remove(self, anime_id: int):
        name = next(
            (e.get("romaji_title","?") for e in self._entries if e["id"] == anime_id), "?"
        )
        if QMessageBox.question(
            self, "Remove from Hall of Fame",
            f"Remove '{name}' from your Hall of Fame?\n(It stays in your library.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            _remove_from_hof(self.db, anime_id)
            self.load()

    def _edit_note(self, anime_id: int, note: str):
        _update_hof_note(self.db, anime_id, note)

    def _save_order(self):
        ids = [e["id"] for e in self._entries]
        _save_hof_order(self.db, ids)

    def _move_up(self, anime_id: int):
        idx = next((i for i, e in enumerate(self._entries) if e["id"] == anime_id), -1)
        if idx <= 0: return
        self._entries[idx], self._entries[idx-1] = self._entries[idx-1], self._entries[idx]
        self._save_order()
        self.load()

    def _move_down(self, anime_id: int):
        idx = next((i for i, e in enumerate(self._entries) if e["id"] == anime_id), -1)
        if idx < 0 or idx >= len(self._entries) - 1: return
        self._entries[idx], self._entries[idx+1] = self._entries[idx+1], self._entries[idx]
        self._save_order()
        self.load()


# ─── Row widget ───────────────────────────────────────────────────────────────

class HofRow(QFrame):
    remove_requested = pyqtSignal(int)
    note_edited      = pyqtSignal(int, str)
    move_up          = pyqtSignal(int)
    move_down        = pyqtSignal(int)

    def __init__(self, rank: int, entry: Dict, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self._aid   = entry["id"]
        self._entry = entry
        self.db     = db
        self.rank   = rank

        self.setObjectName("animeCard")
        self.setFixedHeight(112)
        self.setStyleSheet(
            "QFrame#animeCard{background:#111420;border:1px solid #1a1d28;border-radius:10px;}"
            "QFrame#animeCard:hover{border-color:#2e3354;}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 16, 0)
        lay.setSpacing(0)

        # Rank badge
        rank_w = QWidget()
        rank_w.setFixedWidth(56)
        rank_w.setStyleSheet("background:transparent;")
        rl = QVBoxLayout(rank_w)
        rl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rank_col = "#fbbf24" if rank == 1 else "#9da5c0" if rank == 2 else "#fb923c" if rank == 3 else "#4a5070"
        rank_lbl = QLabel(f"#{rank}")
        rank_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rank_lbl.setStyleSheet(
            f"font-size:{'18' if rank <= 3 else '15'}px;"
            f"font-weight:700;color:{rank_col};"
        )
        rl.addWidget(rank_lbl)
        lay.addWidget(rank_w)

        # Cover
        self.cover_lbl = QLabel()
        self.cover_lbl.setFixedSize(62, 90)
        self.cover_lbl.setStyleSheet("background:#1a1d28;border-radius:6px;margin:10px 0;")
        self.cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.cover_lbl)
        lay.addSpacing(14)

        # Info
        info = QVBoxLayout()
        info.setSpacing(4)
        info.setContentsMargins(0, 14, 0, 10)

        title = entry.get("english_title") or entry.get("romaji_title", "")
        tl = QLabel(title[:60])
        tl.setStyleSheet("font-size:15px;font-weight:700;color:#f0f1f5;")
        info.addWidget(tl)

        # Meta: score, season, genres
        sc    = entry.get("average_score")
        sea   = (entry.get("season") or "").title()
        yr    = entry.get("season_year") or ""
        genres = ", ".join((entry.get("genres") or [])[:3])
        meta_parts = []
        if sc:     meta_parts.append(f"★ {sc/10:.1f}")
        if sea or yr: meta_parts.append(f"{sea} {yr}".strip())
        if genres: meta_parts.append(genres)
        ml = QLabel("   ·   ".join(meta_parts))
        ml.setStyleSheet("font-size:12px;color:#6b7280;")
        info.addWidget(ml)

        # Note (click to edit)
        note_txt = entry.get("note") or ""
        self.note_lbl = QLabel(note_txt if note_txt else "Click to add a personal note…")
        self.note_lbl.setStyleSheet(
            f"font-size:12px;color:{'#9da5c0' if note_txt else '#3b4260'};"
            "font-style:italic;cursor:pointer;"
        )
        self.note_lbl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.note_lbl.setWordWrap(True)
        self.note_lbl.mousePressEvent = lambda e: self._edit_note()
        info.addWidget(self.note_lbl)

        lay.addLayout(info)
        lay.addStretch()

        # Up/down/remove buttons
        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)
        btn_col.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_col.setContentsMargins(0, 8, 0, 8)

        up_btn = self._icon_btn("▲", "Move up")
        up_btn.clicked.connect(lambda: self.move_up.emit(self._aid))
        btn_col.addWidget(up_btn)

        dn_btn = self._icon_btn("▼", "Move down")
        dn_btn.clicked.connect(lambda: self.move_down.emit(self._aid))
        btn_col.addWidget(dn_btn)

        rm_btn = self._icon_btn("✕", "Remove")
        rm_btn.setStyleSheet(rm_btn.styleSheet() + "color:#f87171;")
        rm_btn.clicked.connect(lambda: self.remove_requested.emit(self._aid))
        btn_col.addWidget(rm_btn)

        lay.addLayout(btn_col)

    def _icon_btn(self, text: str, tip: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("iconBtn")
        b.setFixedSize(26, 26)
        b.setToolTip(tip)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        return b

    def set_cover(self, path: str):
        if not path: return
        px = QPixmap(path)
        if px.isNull(): return
        sc = px.scaled(62, 90,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation)
        x = (sc.width()  - 62) // 2
        y = (sc.height() - 90) // 2
        self.cover_lbl.setPixmap(sc.copy(x, y, 62, 90))

    def _edit_note(self):
        dlg = _NoteDialog(self._entry.get("note") or "", self)
        if dlg.exec():
            note = dlg.get_note()
            self.note_lbl.setText(note if note else "Click to add a personal note…")
            self.note_lbl.setStyleSheet(
                f"font-size:12px;color:{'#9da5c0' if note else '#3b4260'};"
                "font-style:italic;"
            )
            self.note_edited.emit(self._aid, note)


# ─── Add to HoF dialog ────────────────────────────────────────────────────────

class _AddToHofDialog(QDialog):
    """
    Search AniList (any anime — not just library) and add to Hall of Fame.
    If the anime is not in the library it is saved there too so cover art
    and metadata are available.
    """
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Add to Hall of Fame")
        self.setMinimumSize(660, 560)
        self.setStyleSheet("background:#0f1118;")
        self._selected_media: Optional[Dict] = None
        self._results: List[Dict] = []
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)
        self._row_refs: List[QFrame] = []
        self._build_ui()

    def _build_ui(self):
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

        # Tab row: My Library | Search AniList
        tab_row = QHBoxLayout()
        tab_row.setSpacing(6)
        self.lib_tab_btn = QPushButton("My Library")
        self.lib_tab_btn.setObjectName("filterPill")
        self.lib_tab_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.lib_tab_btn.clicked.connect(lambda: self._switch_tab("library"))
        tab_row.addWidget(self.lib_tab_btn)

        self.anilist_tab_btn = QPushButton("Search AniList")
        self.anilist_tab_btn.setObjectName("filterPill")
        self.anilist_tab_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.anilist_tab_btn.clicked.connect(lambda: self._switch_tab("anilist"))
        tab_row.addWidget(self.anilist_tab_btn)
        tab_row.addStretch()
        lay.addLayout(tab_row)

        self.search = QLineEdit()
        self.search.setObjectName("searchBar")
        self.search.setPlaceholderText("Search by title…")
        self.search.setFixedHeight(36)
        self.search.textChanged.connect(self._on_search_text)
        lay.addWidget(self.search)

        from PyQt6.QtWidgets import QProgressBar
        self.bar = QProgressBar()
        self.bar.setFixedHeight(2)
        self.bar.setRange(0,0)
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
        self._list_lay.setContentsMargins(0,0,0,0)
        self._list_lay.setSpacing(5)
        self._list_lay.addStretch()
        scroll.setWidget(self._list_w)
        lay.addWidget(scroll)

        # Preview
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

    # ── Tab switching ──────────────────────────────────────────────────────

    def _switch_tab(self, tab: str):
        self._tab = tab
        self._selected_media = None
        self.ok_btn.setEnabled(False)
        self.preview_lbl.setText("")

        for btn, t in [(self.lib_tab_btn,"library"),(self.anilist_tab_btn,"anilist")]:
            btn.setProperty("active","true" if tab==t else "false")
            btn.style().unpolish(btn); btn.style().polish(btn)

        if tab == "library":
            self.search.setPlaceholderText("Filter library by title…")
            self._load_library()
        else:
            self.search.setPlaceholderText("Search any anime on AniList…")
            self._clear_list()

    def _on_search_text(self, text: str):
        if self._tab == "library":
            self._filter_library(text)
        else:
            self._search_timer.start(380)

    # ── Library tab ────────────────────────────────────────────────────────

    def _load_library(self):
        self._all_anime = self.db.get_all_anime()
        self._render_library(self._all_anime)

    def _filter_library(self, text: str):
        q = text.lower()
        filtered = [
            a for a in self._all_anime
            if q in (a.get("romaji_title","")).lower()
            or q in (a.get("english_title","")).lower()
        ] if q else self._all_anime
        self._render_library(filtered)

    def _render_library(self, anime_list: List[Dict]):
        self._clear_list()
        for i, anime in enumerate(anime_list):
            in_hof = _in_hof(self.db, anime["id"])
            row = _LibRow(anime, in_hof)
            row.selected.connect(self._on_lib_sel)
            self._list_lay.insertWidget(i, row)
            self._row_refs.append(row)

    def _on_lib_sel(self, anime_id: int):
        for r in self._row_refs:
            if hasattr(r, '_aid'):
                r.set_selected(r._aid == anime_id)
        # Build a media-like dict from library anime
        anime = self.db.get_anime_by_id(anime_id)
        if anime:
            self._selected_media = {
                "_from_library": True,
                "_lib_id": anime_id,
                "id": anime.get("anilist_id"),
                "title": {
                    "romaji": anime.get("romaji_title",""),
                    "english": anime.get("english_title",""),
                },
            }
            self.ok_btn.setEnabled(True)
            self.preview_lbl.setText(
                f"✓  Selected: {anime.get('romaji_title','')}"
            )

    # ── AniList search tab ─────────────────────────────────────────────────

    def _do_search(self):
        q = self.search.text().strip()
        if len(q) < 2:
            return
        self.bar.setVisible(True)
        from workers.workers import SearchWorker, run_worker
        w = SearchWorker(q)
        w.signals.result.connect(self._on_anilist_results)
        w.signals.finished.connect(lambda: self.bar.setVisible(False))
        run_worker(w)

    def _on_anilist_results(self, results: List[Dict]):
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
            from workers.workers import ImageWorker, run_worker
            url = (media.get("coverImage") or {}).get("medium","")
            if url:
                iw = ImageWorker(url, i)
                iw.signals.result.connect(
                    lambda r, rw=row: rw.set_cover(r[2]) if r and r[2] else None
                )
                run_worker(iw)

    def _on_anilist_sel(self, idx: int):
        for r in self._row_refs:
            if hasattr(r, 'idx'):
                r.set_selected(r.idx == idx)
        media = self._results[idx]
        self._selected_media = media
        self.ok_btn.setEnabled(True)
        title = (media.get("title") or {}).get("romaji","")
        status = (media.get("status") or "").replace("_"," ").title()
        self.preview_lbl.setText(f"✓  Selected: {title}  ({status})")

    # ── Shared ─────────────────────────────────────────────────────────────

    def _clear_list(self):
        for r in self._row_refs:
            r.setParent(None)
        self._row_refs = []
        for i in reversed(range(self._list_lay.count())):
            w = self._list_lay.itemAt(i).widget()
            if w: w.setParent(None)

    def _add(self):
        if not self._selected_media:
            return

        m = self._selected_media

        # Case 1: from library — use existing anime id
        if m.get("_from_library"):
            lib_id = m["_lib_id"]
            if _in_hof(self.db, lib_id):
                QMessageBox.information(self, "Already Added",
                    "This anime is already in your Hall of Fame.")
                return
            _add_to_hof(self.db, lib_id)
            self.accept()
            return

        # Case 2: from AniList — may or may not be in library
        anilist_id = m.get("id")
        existing = self.db.get_anime_by_anilist_id(anilist_id) if anilist_id else None

        if existing:
            # Already in library
            if _in_hof(self.db, existing["id"]):
                QMessageBox.information(self, "Already Added",
                    "This anime is already in your Hall of Fame.")
                return
            _add_to_hof(self.db, existing["id"])
            self.accept()
            return

        # Not in library — fetch full data and save as a special "hof_only" entry
        self.ok_btn.setEnabled(False)
        self.ok_btn.setText("Adding…")

        from workers.workers import Worker, run_worker
        from core.api import get_anime_by_id, format_air_date

        def fetch():
            return get_anime_by_id(anilist_id) if anilist_id else m

        def commit(full_media):
            t   = full_media.get("title", {})
            cov = full_media.get("coverImage") or {}
            sd  = full_media.get("startDate") or {}
            nae = full_media.get("nextAiringEpisode") or {}
            api_s = (full_media.get("status") or "").upper()
            ws  = "completed" if api_s == "FINISHED" else (
                  "planned"   if api_s == "NOT_YET_RELEASED" else "watching")
            new_id = self.db.add_anime({
                "hof_only":       1,
                "anilist_id":     full_media.get("id"),
                "romaji_title":   t.get("romaji","Unknown"),
                "english_title":  t.get("english") or "",
                "watch_status":   ws,
                "status":         full_media.get("status",""),
                "cover_url":      cov.get("large") or cov.get("medium") or "",
                "banner_url":     full_media.get("bannerImage") or "",
                "description":    full_media.get("description") or "",
                "genres":         full_media.get("genres") or [],
                "studios":        [s["name"] for s in (full_media.get("studios",{}).get("nodes") or [])],
                "total_episodes": full_media.get("episodes"),
                "season":         full_media.get("season") or "",
                "season_year":    full_media.get("seasonYear"),
                "average_score":  full_media.get("averageScore"),
                "start_date":     format_air_date(sd),
                "next_episode_at":  nae.get("airingAt"),
                "next_episode_num": nae.get("episode"),
            })
            _add_to_hof(self.db, new_id)
            self.accept()

        w = Worker(fetch)
        w.signals.result.connect(commit)
        def _on_err(e):
            self.ok_btn.setEnabled(True)
            self.ok_btn.setText("Add to Hall of Fame")
            QMessageBox.critical(self, "Error", "Could not fetch data: " + str(e))
        w.signals.error.connect(_on_err)
        run_worker(w)


class _LibRow(QFrame):
    selected = pyqtSignal(int)
    _BASE = "QFrame{background:#111420;border:1px solid #1a1d28;border-radius:8px;}"
    _SEL  = "QFrame{background:#151929;border:1px solid #4b3fa8;border-radius:8px;}"
    _HOF  = "QFrame{background:#0e1620;border:1px solid #1e2d45;border-radius:8px;}"

    def __init__(self, anime: Dict, in_hof: bool, parent=None):
        super().__init__(parent)
        self._aid    = anime["id"]
        self._in_hof = in_hof
        self.setFixedHeight(56)
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
            hof_lbl = QLabel("🏆 Already added")
            hof_lbl.setStyleSheet("font-size:11px;color:#4a5070;")
            lay.addWidget(hof_lbl)

        ws = anime.get("watch_status","")
        if ws:
            wl = QLabel(ws.title())
            wl.setStyleSheet("font-size:11px;color:#4a5070;")
            lay.addWidget(wl)

    def set_selected(self, sel: bool):
        if self._in_hof: return
        self.setStyleSheet(self._SEL if sel else self._BASE)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._in_hof:
            self.selected.emit(self._aid)
        super().mousePressEvent(e)


class _AniListRow(QFrame):
    """Row widget for AniList search results inside HoF add dialog."""
    selected = pyqtSignal(int)
    _BASE = "QFrame{background:#111420;border:1px solid #1a1d28;border-radius:8px;}"
    _SEL  = "QFrame{background:#151929;border:1px solid #4b3fa8;border-radius:8px;}"

    def __init__(self, media: Dict, idx: int, parent=None):
        super().__init__(parent)
        self.idx = idx
        self.setFixedHeight(68)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(self._BASE)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 12, 8)
        lay.setSpacing(12)

        self.cover = QLabel()
        self.cover.setFixedSize(38, 52)
        self.cover.setStyleSheet("background:#1a1d28;border-radius:4px;")
        lay.addWidget(self.cover)

        info = QVBoxLayout()
        info.setSpacing(2)
        t = media.get("title", {})
        tl = QLabel((t.get("romaji") or t.get("english") or "")[:60])
        tl.setStyleSheet("font-size:13px;font-weight:600;color:#dde0ed;")
        info.addWidget(tl)

        api_s = (media.get("status") or "").upper()
        s_col = {"RELEASING":"#34d399","FINISHED":"#a594f9","NOT_YET_RELEASED":"#fbbf24"}.get(api_s,"#6b7280")
        s_lbl_text = {"RELEASING":"● AIRING","FINISHED":"● FINISHED","NOT_YET_RELEASED":"● UPCOMING"}.get(api_s, api_s)
        sl = QLabel(s_lbl_text)
        sl.setStyleSheet(f"font-size:10px;font-weight:700;color:{s_col};")
        info.addWidget(sl)
        lay.addLayout(info)
        lay.addStretch()

        sc = media.get("averageScore")
        if sc:
            scl = QLabel(f"★ {sc/10:.1f}")
            scl.setStyleSheet("font-size:12px;color:#7c6af7;font-weight:600;")
            lay.addWidget(scl)

    def set_cover(self, path: str):
        if not path: return
        px = QPixmap(path).scaled(38, 52,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation)
        self.cover.setPixmap(px)

    def set_selected(self, sel: bool):
        self.setStyleSheet(self._SEL if sel else self._BASE)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.idx)
        super().mousePressEvent(e)


class _NoteDialog(QDialog):
    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Personal Note")
        self.setMinimumSize(400, 220)
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