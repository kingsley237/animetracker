"""
Miroku — Add Anime Dialog

Library is for currently airing and upcoming anime only.
Finished or cancelled titles can be added to Hall of Fame instead.
"""
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QFrame, QWidget, QComboBox,
    QProgressBar, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QCursor

from core.database import DatabaseManager
from core.api import search_anime, get_anime_by_id, format_air_date
from workers.workers import SearchWorker, ImageWorker, Worker, run_worker

STATUS_MAP = {"Watching": "watching", "Plan to Watch": "planned"}


def _api_finished(media: Dict) -> bool:
    return (media.get("status") or "").upper() in ("FINISHED", "CANCELLED")


def _smart_default(media: Dict) -> str:
    s = (media.get("status") or "").upper()
    return "planned" if s == "NOT_YET_RELEASED" else "watching"


def _allowed_labels(media: Dict) -> List[str]:
    s = (media.get("status") or "").upper()
    if s == "NOT_YET_RELEASED":
        return ["Plan to Watch"]
    return ["Watching", "Plan to Watch"]


class AddAnimeDialog(QDialog):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self._results: List[Dict] = []
        self._selected: Optional[Dict] = None
        self._hof_mode = False
        self.added_title = ""
        self.added_status = ""
        self.added_to_hof = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._do_search)

        self.setWindowTitle("Add Anime")
        self.setMinimumSize(700, 560)
        self.setStyleSheet("background:#0f1118;")
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        title = QLabel("Add Anime to Library")
        title.setObjectName("dialogTitle")
        lay.addWidget(title)

        note = QLabel(
            "Miroku tracks currently airing and upcoming anime in your library.\n"
            "Finished titles can be saved to Hall of Fame — your all-time favorites list."
        )
        note.setStyleSheet("font-size:12px;color:#4a5070;line-height:1.5;")
        note.setWordWrap(True)
        lay.addWidget(note)

        row = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setObjectName("searchBar")
        self.search_bar.setPlaceholderText("Search by title…")
        self.search_bar.setFixedHeight(38)
        self.search_bar.textChanged.connect(lambda: self._timer.start(380))
        row.addWidget(self.search_bar)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["Watching", "Plan to Watch"])
        self.status_combo.setFixedWidth(150)
        row.addWidget(self.status_combo)
        lay.addLayout(row)

        self.hint = QLabel("")
        self.hint.setStyleSheet("font-size:11px;color:#fbbf24;min-height:16px;")
        lay.addWidget(self.hint)

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
        scroll.setFixedHeight(310)

        self.results_w = QWidget()
        self.results_w.setStyleSheet("background:transparent;")
        self.results_vbox = QVBoxLayout(self.results_w)
        self.results_vbox.setContentsMargins(0, 0, 0, 0)
        self.results_vbox.setSpacing(5)
        self.results_vbox.addStretch()
        scroll.setWidget(self.results_w)
        lay.addWidget(scroll)

        self.preview = _PreviewStrip()
        self.preview.setVisible(False)
        lay.addWidget(self.preview)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondaryBtn")
        cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)

        self.add_btn = QPushButton("Add to Library")
        self.add_btn.setObjectName("primaryBtn")
        self.add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self._add)
        btns.addWidget(self.add_btn)
        lay.addLayout(btns)

    def _do_search(self):
        q = self.search_bar.text().strip()
        if len(q) < 2:
            return
        self.bar.setVisible(True)
        w = SearchWorker(q)
        w.signals.result.connect(self._on_results)
        w.signals.finished.connect(lambda: self.bar.setVisible(False))
        run_worker(w)

    def _on_results(self, results: List[Dict]):
        self._results = results
        for i in reversed(range(self.results_vbox.count())):
            w = self.results_vbox.itemAt(i).widget()
            if w:
                w.setParent(None)

        if not results:
            lbl = QLabel("No results found.")
            lbl.setStyleSheet("color:#4a5070;padding:12px;")
            self.results_vbox.insertWidget(0, lbl)
            return

        for i, media in enumerate(results[:15]):
            row = _ResultRow(media, i)
            row.selected.connect(self._on_selected)
            self.results_vbox.insertWidget(i, row)
            url = (media.get("coverImage") or {}).get("medium", "")
            if url:
                iw = ImageWorker(url, i)
                iw.signals.result.connect(
                    lambda r, rw=row: rw.set_cover(r[2]) if r and r[2] else None
                )
                run_worker(iw)

    def _on_selected(self, idx: int):
        for i in range(self.results_vbox.count()):
            w = self.results_vbox.itemAt(i).widget()
            if isinstance(w, _ResultRow):
                w.set_selected(w.idx == idx)

        media = self._results[idx]
        self._selected = media
        finished = _api_finished(media)

        if finished:
            self._hof_mode = True
            self.status_combo.setVisible(False)
            anilist_id = media.get("id")
            in_hof = False
            if anilist_id:
                existing = self.db.get_anime_by_anilist_id(anilist_id)
                if existing:
                    from ui.hall_of_fame import _in_hof
                    in_hof = _in_hof(self.db, existing["id"])
            self.add_btn.setText("Add to Hall of Fame")
            self.add_btn.setEnabled(not in_hof)
            if in_hof:
                self.hint.setText("🏆  Already in your Hall of Fame.")
                self.hint.setStyleSheet("font-size:11px;color:#4a5070;")
            else:
                self.hint.setText(
                    "🏆  Finished airing — add to Hall of Fame, not your active library."
                )
                self.hint.setStyleSheet("font-size:11px;color:#a594f9;")
            self.preview.load(media, finished=True)
            self.preview.setVisible(True)
            return

        self._hof_mode = False
        self.status_combo.setVisible(True)
        self.add_btn.setText("Add to Library")
        self.add_btn.setEnabled(True)

        allowed = _allowed_labels(media)
        default = _smart_default(media)
        self.status_combo.blockSignals(True)
        self.status_combo.clear()
        self.status_combo.addItems(allowed)
        for i, lbl in enumerate(allowed):
            if STATUS_MAP.get(lbl) == default:
                self.status_combo.setCurrentIndex(i)
                break
        self.status_combo.blockSignals(False)

        hints = {
            "RELEASING": ("⚡ Currently airing — added as Watching", "#34d399"),
            "NOT_YET_RELEASED": ("⏳ Not yet released — added as Plan to Watch", "#fbbf24"),
        }
        api_s = (media.get("status") or "").upper()
        txt, col = hints.get(api_s, ("", "#9da5c0"))
        self.hint.setText(txt)
        self.hint.setStyleSheet(f"font-size:11px;color:{col};")

        self.preview.load(media, finished=False)
        self.preview.setVisible(True)

    def _add(self):
        if not self._selected:
            return
        media = self._selected

        if self._hof_mode:
            self._add_to_hof(media)
            return

        if _api_finished(media):
            QMessageBox.warning(
                self,
                "Use Hall of Fame",
                "This anime has finished airing.\n"
                "Add it from Hall of Fame instead of your active library.",
            )
            return

        watch_status = STATUS_MAP.get(self.status_combo.currentText(), "watching")
        api_s = (media.get("status") or "").upper()
        if api_s == "NOT_YET_RELEASED" and watch_status == "watching":
            QMessageBox.warning(self, "Not Released", "You cannot watch an unreleased anime.")
            return

        anilist_id = media.get("id")
        if anilist_id and self.db.get_anime_by_anilist_id(anilist_id):
            from ui.toast import Toast
            Toast.show(
                self.window(),
                f"'{(media.get('title') or {}).get('romaji', '')}' is already in your library.",
                kind="info",
            )
            return

        self.add_btn.setEnabled(False)
        self.add_btn.setText("Adding…")

        def fetch():
            return get_anime_by_id(anilist_id) if anilist_id else media

        w = Worker(fetch)
        w.signals.result.connect(lambda m: self._commit_library(m, watch_status))
        w.signals.error.connect(
            lambda e: (
                self.add_btn.setEnabled(True),
                self.add_btn.setText("Add to Library"),
            )
        )
        run_worker(w)

    def _add_to_hof(self, media: Dict):
        anilist_id = media.get("id")
        self.add_btn.setEnabled(False)
        self.add_btn.setText("Adding…")

        def fetch():
            return get_anime_by_id(anilist_id) if anilist_id else media

        def done(full_media):
            from ui.hall_of_fame import add_anilist_media_to_hof
            ok, title = add_anilist_media_to_hof(self.db, full_media)
            if not ok:
                from ui.toast import Toast
                if title == "already_in_hof":
                    Toast.show(
                        self.window(),
                        "This anime is already in your Hall of Fame.",
                        kind="info",
                    )
                self.add_btn.setEnabled(True)
                self.add_btn.setText("Add to Hall of Fame")
                return
            self.added_title = title
            self.added_to_hof = True
            self.accept()

        w = Worker(fetch)
        w.signals.result.connect(done)
        w.signals.error.connect(
            lambda e: (
                self.add_btn.setEnabled(True),
                self.add_btn.setText("Add to Hall of Fame"),
                QMessageBox.critical(self, "Error", str(e)),
            )
        )
        run_worker(w)

    def _commit_library(self, media: Dict, watch_status: str):
        t = media.get("title", {})
        cov = media.get("coverImage") or {}
        nae = media.get("nextAiringEpisode") or {}
        sd = media.get("startDate") or {}
        stud = [s["name"] for s in (media.get("studios", {}).get("nodes") or [])]

        self.db.add_anime({
            "anilist_id": media.get("id"),
            "romaji_title": t.get("romaji", "Unknown"),
            "english_title": t.get("english") or "",
            "native_title": t.get("native") or "",
            "watch_status": watch_status,
            "status": media.get("status", ""),
            "cover_url": cov.get("extraLarge") or cov.get("large") or cov.get("medium") or "",
            "banner_url": media.get("bannerImage") or "",
            "description": media.get("description") or "",
            "genres": media.get("genres") or [],
            "studios": stud,
            "total_episodes": media.get("episodes"),
            "season": media.get("season") or "",
            "season_year": media.get("seasonYear"),
            "average_score": media.get("averageScore"),
            "popularity": media.get("popularity"),
            "trailer_id": (media.get("trailer") or {}).get("id"),
            "trailer_site": (media.get("trailer") or {}).get("site"),
            "start_date": format_air_date(sd),
            "next_episode_at": nae.get("airingAt"),
            "next_episode_num": nae.get("episode"),
        })
        self.added_title = t.get("romaji", "Unknown")
        self.added_status = "Plan to Watch" if watch_status == "planned" else "Watching"
        self.accept()


class _ResultRow(QFrame):
    selected = pyqtSignal(int)

    _BASE = (
        "QFrame{background:#111420;border:1px solid #1a1d28;border-radius:8px;}"
        "QFrame:hover{background:#141828;border-color:#252a40;}"
    )
    _SEL = "QFrame{background:#151929;border-radius:8px;}"

    def __init__(self, media: Dict, idx: int, parent=None):
        super().__init__(parent)
        self.idx = idx
        self.setFixedHeight(72)
        self.setObjectName("animeCard")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(self._BASE)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 12, 8)
        row.setSpacing(12)

        self.cover = QLabel()
        self.cover.setFixedSize(38, 54)
        self.cover.setStyleSheet("background:#1a1d28;border-radius:4px;")
        row.addWidget(self.cover)

        info = QVBoxLayout()
        info.setSpacing(2)
        t = media.get("title", {})
        romaji = t.get("romaji", "")
        english = t.get("english", "")

        t1 = QLabel(romaji[:58])
        t1.setStyleSheet("font-size:13px;font-weight:600;color:#dde0ed;")
        info.addWidget(t1)
        if english and english != romaji:
            t2 = QLabel(english[:58])
            t2.setStyleSheet("font-size:11px;color:#4a5070;")
            info.addWidget(t2)

        api_s = (media.get("status") or "").upper()
        s_cols = {"RELEASING": "#34d399", "FINISHED": "#6b7280", "NOT_YET_RELEASED": "#fbbf24"}
        s_lbls = {
            "RELEASING": "● AIRING",
            "FINISHED": "● FINISHED",
            "NOT_YET_RELEASED": "● UPCOMING",
        }
        sl = QLabel(s_lbls.get(api_s, api_s))
        sl.setStyleSheet(f"font-size:10px;font-weight:700;color:{s_cols.get(api_s, '#6b7280')};")
        info.addWidget(sl)
        row.addLayout(info)
        row.addStretch()

        meta = QVBoxLayout()
        meta.setSpacing(3)
        meta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        sc = media.get("averageScore")
        if sc:
            sl2 = QLabel(f"★ {sc/10:.1f}")
            sl2.setStyleSheet("font-size:12px;color:#7c6af7;font-weight:600;")
            meta.addWidget(sl2, alignment=Qt.AlignmentFlag.AlignRight)
        yr = str(media.get("seasonYear") or "")
        ep = str(media.get("episodes") or "")
        parts = [p for p in [yr, (f"{ep} eps") if ep else ""] if p]
        if parts:
            ml = QLabel("  ·  ".join(parts))
            ml.setStyleSheet("font-size:11px;color:#4a5070;")
            meta.addWidget(ml, alignment=Qt.AlignmentFlag.AlignRight)
        row.addLayout(meta)

    def set_cover(self, path: str):
        if not path:
            return
        px = QPixmap(path).scaled(
            38, 54,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.cover.setPixmap(px)

    def set_selected(self, s: bool):
        self.setStyleSheet(self._SEL if s else self._BASE)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.idx)
        super().mousePressEvent(e)


class _PreviewStrip(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(50)
        self.setStyleSheet("background:#0e1620;border-radius:8px;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(10)
        self.icon = QLabel("✓")
        self.icon.setStyleSheet("font-size:14px;color:#34d399;")
        lay.addWidget(self.icon)
        self.text = QLabel()
        self.text.setStyleSheet("font-size:13px;color:#9da5c0;")
        lay.addWidget(self.text)
        lay.addStretch()
        self.genres = QLabel()
        self.genres.setStyleSheet("font-size:11px;color:#4a5070;")
        lay.addWidget(self.genres)

    def load(self, media: Dict, finished: bool = False):
        t = (media.get("title") or {}).get("romaji", "")
        eps = media.get("episodes") or "?"
        if finished:
            self.icon.setText("🏆")
            self.icon.setStyleSheet("font-size:14px;color:#a594f9;")
        else:
            self.icon.setText("✓")
            self.icon.setStyleSheet("font-size:14px;color:#34d399;")
        self.text.setText(f"{t}  ·  {eps} episodes")
        self.genres.setText("  ·  ".join((media.get("genres") or [])[:3]))
