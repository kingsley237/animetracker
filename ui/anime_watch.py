"""
Miroku - the Watching section of the anime detail panel, in the Kinema
layout (same reading order as TV shows):

Where you are   WATCHING stamp + airing state, up next with one-click mark,
                progress bar, next episode with a live countdown, actions
                (watched / mark completed / plan to watch / drop).
Episodes        tick each episode; right-click for "watched up to here" or a
                rating. Long shows are split into blocks of 50 (like season
                tabs). Episodes that haven't aired are locked; the next one
                shows when it airs.
Trailers        promo videos and trailers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

from ui.layout_helpers import FlowLayout
from ui.movie_details import _LABELS, _card, _span

BLOCK = 50


def _when(ts: int) -> str:
    d = datetime.fromtimestamp(ts)
    return d.strftime("%a, %b ") + f"{d.day} · " + d.strftime("%H:%M")


class _EpRow(QWidget):
    toggled = pyqtSignal(int, bool)
    through = pyqtSignal(int)
    rate = pyqtSignal(int, object)

    def __init__(self, n: int, display: int, watched: bool, rating: float,
                 aired: bool, is_next: bool, airs_at: Optional[int] = None, parent=None):
        super().__init__(parent)
        self.n, self.watched, self.rating, self.aired = n, watched, rating, aired
        self.setObjectName("tvEpRowNext" if is_next else "tvEpRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 5, 8, 5)
        h.setSpacing(10)
        self.tick = QPushButton("✓" if watched else "")
        self.tick.setObjectName("animeEpTick")
        self.tick.setProperty("watched", "true" if watched else "false")
        self.tick.setFixedSize(24, 24)
        self.tick.setEnabled(aired)
        self.tick.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.tick.setToolTip("Mark unwatched" if watched else "Mark watched")
        self.tick.clicked.connect(lambda: self.toggled.emit(n, not watched))
        h.addWidget(self.tick)
        num = QLabel(f"E{display:02d}" if display < 100 else f"E{display}")
        num.setObjectName("tvEpNum")
        num.setFixedWidth(34)
        h.addWidget(num)
        name = QLabel(f"Episode {display}")
        name.setObjectName("tvEpName" if aired else "tvEpNameDim")
        h.addWidget(name, 1)
        if rating:
            r = QLabel(f"★ {int(rating)}")
            r.setObjectName("tvEpRating")
            r.setToolTip(_LABELS.get(int(rating), ""))
            h.addWidget(r)
        if not aired:
            when = QLabel(("Airs " + _when(airs_at)) if airs_at else "Not aired yet")
            when.setObjectName("animeEpAirs" if airs_at else "tvEpDate")
            h.addWidget(when)

    def contextMenuEvent(self, e):
        if not self.aired:
            return
        m = QMenu(self)
        m.addAction("Watched up to here", lambda: self.through.emit(self.n))
        m.addAction("Mark unwatched" if self.watched else "Mark watched",
                    lambda: self.toggled.emit(self.n, not self.watched))
        rm = m.addMenu("Rate episode")
        for v in range(6, 0, -1):
            rm.addAction(f"{'★' * v}  {_LABELS[v]}", lambda v=v: self.rate.emit(self.n, v))
        if self.rating:
            rm.addSeparator()
            rm.addAction("Clear rating", lambda: self.rate.emit(self.n, None))
        m.exec(e.globalPos())


class AnimeWatchSection(QWidget):
    changed = pyqtSignal(int)                 # episodes / rating changed
    status_requested = pyqtSignal(str)        # "completed" | "planned"
    drop_requested = pyqtSignal()
    export_requested = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._row: Optional[Dict] = None
        self._block: Optional[int] = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self.status_card = _card("")
        sl = self.status_card.layout()
        chips = QHBoxLayout()
        self.stamp = QLabel("WATCHING")
        self.stamp.setObjectName("animeStamp")
        self.state = QLabel()
        self.state.setObjectName("tvShowState")
        chips.addWidget(self.stamp)
        chips.addWidget(self.state)
        chips.addStretch()
        sl.addLayout(chips)
        self.main = QLabel()
        self.main.setObjectName("plannedReleaseMain")
        self.main.setWordWrap(True)
        self.sub = QLabel()
        self.sub.setObjectName("plannedReleaseHint")
        self.sub.setWordWrap(True)
        self.bar = QWidget()
        self.bar.setObjectName("tvProgressTrack")
        self.bar.setFixedHeight(6)
        self.bar_fill = QWidget(self.bar)
        self.bar_fill.setObjectName("animeProgressFill")
        self.next_air = QLabel()
        self.next_air.setObjectName("animeNextAir")
        self.next_air.setWordWrap(True)
        self.count = QLabel()
        self.count.setObjectName("movieCountdown")
        for w in (self.main, self.sub, self.bar, self.next_air, self.count):
            sl.addWidget(w)
        self.actions_host = QWidget()
        self.actions = FlowLayout(self.actions_host, h_spacing=8, v_spacing=8)
        sl.addWidget(self.actions_host)
        lay.addWidget(self.status_card)

        self.eps_card = _card("Episodes")
        el = self.eps_card.layout()
        tabs_host = QWidget()
        self.tabs = FlowLayout(tabs_host, h_spacing=6, v_spacing=6)
        el.addWidget(tabs_host)
        self.tabs_host = tabs_host
        head = QHBoxLayout()
        self.eps_meta = QLabel()
        self.eps_meta.setObjectName("plannedReleaseHint")
        self.eps_meta.setWordWrap(True)
        head.addWidget(self.eps_meta, 1)
        self.export_btn = QPushButton("Export ratings")
        self.export_btn.setObjectName("secondaryBtn")
        self.export_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.export_btn.clicked.connect(self.export_requested.emit)
        head.addWidget(self.export_btn)
        self.all_btn = QPushButton("✓  Mark all")
        self.all_btn.setObjectName("secondaryBtn")
        self.all_btn.setToolTip("Mark every aired episode watched")
        self.all_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.all_btn.clicked.connect(self._mark_all)
        head.addWidget(self.all_btn)
        el.addLayout(head)
        self.eps_host = QWidget()
        self.eps = QVBoxLayout(self.eps_host)
        self.eps.setContentsMargins(0, 4, 0, 0)
        self.eps.setSpacing(2)
        el.addWidget(self.eps_host)
        hint = QLabel("Right-click an episode: watched up to here, rate it.")
        hint.setObjectName("plannedReleaseHint")
        el.addWidget(hint)
        lay.addWidget(self.eps_card)

        from ui.video_gallery import VideoGallery
        self.videos_card = _card("Trailers & videos")
        self.gallery = VideoGallery("No trailers or promos yet.")
        self.videos_card.layout().addWidget(self.gallery)
        lay.addWidget(self.videos_card)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    # ── numbers ───────────────────────────────────────────────────────────────

    def _counts(self):
        r = self._row
        total = r.get("total_episodes") or 0
        nxt = r.get("next_episode_num")
        api = (r.get("status") or "").upper()
        ended = api in ("FINISHED", "CANCELLED")
        if total and (ended or not nxt):
            aired = total
        elif nxt and nxt > 1:
            aired = nxt - 1
        else:
            aired = 0
        watched_set = {e["episode_num"] for e in self.db.get_episodes(r["id"]) if e.get("watched")}
        watched = len([n for n in watched_set if n > 0])
        nxt_up = next((n for n in range(1, aired + 1) if n not in watched_set), None)
        return total, aired, watched, watched_set, nxt_up, ended, api

    # ── load ──────────────────────────────────────────────────────────────────

    def load(self, row: Dict, keep_block: bool = False):
        same = self._row and self._row.get("id") == row.get("id")
        self._row = row
        if not (keep_block and same):
            self._block = None
            from core.videos import build_playlist
            self.gallery.load(build_playlist(row), row.get("romaji_title") or "")
        self._render()

    def stop(self):
        self._timer.stop()

    def _render(self):
        r = self._row
        total, aired, watched, wset, nxt, ended, api = self._counts()
        self.state.setText({"RELEASING": "Airing", "FINISHED": "Finished airing",
                            "CANCELLED": "Cancelled", "HIATUS": "On hiatus",
                            "NOT_YET_RELEASED": "Not aired yet"}.get(api, ""))
        offset = r.get("episode_offset") or 0
        if nxt:
            self.main.setText(f"Up next: Episode {nxt + offset}")
        elif watched:
            self.main.setText("You're caught up." if not ended else "You've seen every episode.")
        else:
            self.main.setText("Ready to start.")
        left = max(0, aired - len([n for n in wset if 0 < n <= aired]))
        if aired:
            mins = left * (r.get("duration") or 24)
            h, m = divmod(mins, 60)
            tail = (f" · {left} to go (about {h}h {m:02d}m)" if h else f" · {left} to go (about {m}m)") if left else ""
            of = f"{watched} of {aired} aired episodes watched" if not ended or not total else \
                f"{watched} of {total} episodes watched"
            self.sub.setText(of + tail)
        else:
            self.sub.setText("")
        self.sub.setVisible(bool(self.sub.text()))
        self.bar.setVisible(aired > 0)
        self._frac = (watched / (total or aired)) if (total or aired) else 0
        QTimer.singleShot(0, self._size_bar)

        at = None if ended else r.get("next_episode_at")
        self._target = at or 0
        if at and r.get("next_episode_num"):
            n = r["next_episode_num"] + offset
            of_total = f" of {total}" if total else ""
            self.next_air.setText(f"Episode {n}{of_total} airs {_when(at)}")
        elif api == "RELEASING":
            self.next_air.setText("Next episode date not announced yet.")
        else:
            self.next_air.setText("")
        self.next_air.setVisible(bool(self.next_air.text()))
        self._tick()
        live = self._target > int(datetime.now(timezone.utc).timestamp())
        self.count.setVisible(live)
        if live:
            self._timer.start(30_000)
        else:
            self._timer.stop()

        self.actions.clear()
        if nxt:
            self._action(f"✓  Watched Ep {nxt + offset}", "primaryBtn",
                         lambda: self._toggle(nxt, True))
        if ended:
            self._action("Mark completed", "secondaryBtn", lambda: self.status_requested.emit("completed"))
        self._action("Plan to Watch", "secondaryBtn", lambda: self.status_requested.emit("planned"))
        self._action("Drop", "dangerBtn", self.drop_requested.emit)

        self._render_episodes(total, aired, wset, nxt)

    def _size_bar(self):
        try:
            self.bar_fill.setGeometry(0, 0, int(self.bar.width() * max(0.0, min(1.0, self._frac))), 6)
        except RuntimeError:
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._row:
            self._size_bar()

    def _tick(self):
        now = int(datetime.now(timezone.utc).timestamp())
        if self._target > now:
            self.count.setText(f"in {_span(self._target - now)}")

    def _action(self, text, obj, cb):
        b = QPushButton(text)
        b.setObjectName(obj)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setMinimumHeight(34)
        b.clicked.connect(cb)
        self.actions.addWidget(b)

    # ── episodes ──────────────────────────────────────────────────────────────

    def _render_episodes(self, total, aired, wset, nxt):
        r = self._row
        shown_total = max(total, aired + (1 if r.get("next_episode_at") else 0))
        ratings = {x["episode_num"]: float(x.get("score") or 0) for x in self.db.get_ratings(r["id"])}
        self.export_btn.setVisible(any(v > 0 for k, v in ratings.items() if k > 0))
        self.all_btn.setVisible(aired > 0)
        all_done = aired > 0 and all(n in wset for n in range(1, aired + 1))
        self.all_btn.setText("Unmark all" if all_done else "✓  Mark all")
        self.tabs.clear()
        blocks = (shown_total + BLOCK - 1) // BLOCK if shown_total else 0
        self.tabs_host.setVisible(blocks > 1)
        if self._block is None:
            focus = nxt or max(1, min(aired, shown_total))
            self._block = (focus - 1) // BLOCK if focus else 0
        self._block = min(self._block, max(0, blocks - 1))
        if blocks > 1:
            for b in range(blocks):
                lo, hi = b * BLOCK + 1, min((b + 1) * BLOCK, shown_total)
                done = all(n in wset for n in range(lo, min(hi, aired) + 1)) and lo <= aired
                btn = QPushButton(f"{lo}–{hi}" + (" ✓" if done else ""))
                btn.setObjectName("animeBlockTab")
                btn.setProperty("active", "true" if b == self._block else "false")
                btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                btn.clicked.connect(lambda _=False, b=b: self._pick(b))
                self.tabs.addWidget(btn)
        bits = []
        if shown_total:
            bits.append(f"{total} episodes" if total else f"{aired} aired so far")
        if aired:
            bits.append(f"{len([n for n in wset if 0 < n <= aired])}/{aired} watched")
        self.eps_meta.setText("  ·  ".join(bits))
        while self.eps.count():
            it = self.eps.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if not shown_total:
            l = QLabel("No episodes have aired yet.")
            l.setObjectName("plannedReleaseHint")
            self.eps.addWidget(l)
            return
        offset = r.get("episode_offset") or 0
        nxt_air_n = r.get("next_episode_num")
        nxt_air_at = r.get("next_episode_at")
        lo = self._block * BLOCK + 1
        hi = min((self._block + 1) * BLOCK, shown_total)
        for n in range(lo, hi + 1):
            is_aired = n <= aired
            row = _EpRow(n, n + offset, n in wset, ratings.get(n, 0.0), is_aired,
                         is_next=(n == nxt),
                         airs_at=nxt_air_at if (not is_aired and n == nxt_air_n) else None)
            row.toggled.connect(self._toggle)
            row.through.connect(self._through)
            row.rate.connect(self._rate)
            self.eps.addWidget(row)

    def _pick(self, b: int):
        self._block = b
        self._render()

    # ── actions ───────────────────────────────────────────────────────────────

    def _after(self):
        r = self.db.get_anime_by_id(self._row["id"]) or self._row
        total, aired, watched, wset, nxt, ended, _api = self._counts()
        self._row = r
        if ended and total and all(n in wset for n in range(1, total + 1)):
            self.status_requested.emit("completed")
            return
        self._render()
        self.changed.emit(r["id"])

    def _toggle(self, n: int, on: bool):
        self.db.set_episode_watched(self._row["id"], n, on)
        if not on:
            self.db.set_rating(self._row["id"], n, 0.0, "")
        self._after()

    def _through(self, n: int):
        wset = {e["episode_num"] for e in self.db.get_episodes(self._row["id"]) if e.get("watched")}
        for k in range(1, n + 1):
            if k not in wset:
                self.db.set_episode_watched(self._row["id"], k, True)
        self._after()

    def _mark_all(self):
        total, aired, watched, wset, nxt, ended, _api = self._counts()
        all_done = aired > 0 and all(n in wset for n in range(1, aired + 1))
        for n in range(1, aired + 1):
            if all_done:
                self.db.set_episode_watched(self._row["id"], n, False)
            elif n not in wset:
                self.db.set_episode_watched(self._row["id"], n, True)
        self._after()

    def _rate(self, n: int, v):
        from ui.detail_panel import RATING_LABELS
        self.db.set_rating(self._row["id"], n, float(v or 0), RATING_LABELS.get(int(v or 0), ""))
        self._render()
        self.changed.emit(self._row["id"])
