"""
Kinema - TV show section of the detail panel.

Where you are   up next with one-click mark, progress, next airing with a
                countdown, status actions (start / finish / drop / resume).
Seasons         a tab per season: rate the season, mark it all, and an
                episode list where each episode can be ticked (or "watched
                up to here" from its menu) and rated. Unaired episodes are
                locked and show their air date.
Plus            your verdict (finished shows), where to watch, trailers,
                facts and cast.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QPixmap
from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget,
)

from ui.layout_helpers import FlowLayout
from ui.movie_details import _LABELS, _card, _chip, _date_label, _runtime, _span
from workers.workers import ImageWorker, Worker, run_worker

SKY = "#38bdf8"


def code(s: int, e: int) -> str:
    return f"S{s:02d}E{e:02d}"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _days_until(date: str) -> int:
    return (datetime.strptime(date, "%Y-%m-%d").date() - datetime.now().date()).days


class _Stars(QWidget):
    """Six small stars (the app's 1-6 scale). Click a star to rate, click
    the same one again to clear."""
    rated = pyqtSignal(object)          # int | None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value: Optional[int] = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self._btns = []
        for i in range(1, 7):
            b = QPushButton("★")
            b.setObjectName("tvStar")
            b.setFixedSize(20, 20)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setToolTip(_LABELS.get(i, ""))
            b.clicked.connect(lambda _=False, v=i: self._click(v))
            lay.addWidget(b)
            self._btns.append(b)

    def set_value(self, v):
        self._value = int(v) if v else None
        for i, b in enumerate(self._btns, 1):
            b.setProperty("on", "true" if self._value and i <= self._value else "false")
            b.style().unpolish(b)
            b.style().polish(b)

    def _click(self, v: int):
        v = None if v == self._value else v
        self.set_value(v)
        self.rated.emit(v)


class _EpisodeRow(QWidget):
    toggled = pyqtSignal(int, bool)          # episode, watched
    through = pyqtSignal(int)                # watched up to this episode
    rate = pyqtSignal(int, object)           # episode, score | None

    def __init__(self, ep: Dict, is_next: bool, parent=None):
        super().__init__(parent)
        self.ep = ep
        n = ep["episode_number"]
        aired = bool(ep.get("air_date")) and ep["air_date"] <= _today()
        self.setObjectName("tvEpRowNext" if is_next else "tvEpRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 5, 8, 5)
        h.setSpacing(10)

        self.tick = QPushButton("✓" if ep.get("watched") else "")
        self.tick.setObjectName("tvEpTick")
        self.tick.setProperty("watched", "true" if ep.get("watched") else "false")
        self.tick.setFixedSize(24, 24)
        self.tick.setEnabled(aired)
        self.tick.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.tick.setToolTip("Mark watched" if not ep.get("watched") else "Mark unwatched")
        self.tick.clicked.connect(lambda: self.toggled.emit(n, not ep.get("watched")))
        h.addWidget(self.tick)

        num = QLabel(f"E{n:02d}")
        num.setObjectName("tvEpNum")
        num.setFixedWidth(30)
        h.addWidget(num)
        name = QLabel(ep.get("name") or f"Episode {n}")
        name.setObjectName("tvEpNameDim" if not aired else "tvEpName")
        name.setToolTip(ep.get("name") or "")
        name.setMinimumWidth(60)
        h.addWidget(name, 1)

        if ep.get("rating"):
            r = QLabel(f"★ {int(ep['rating'])}")
            r.setObjectName("tvEpRating")
            h.addWidget(r)
        if not aired:
            d = ep.get("air_date")
            when = QLabel(("Airs " + _date_label(d)) if d else "Date TBA")
            when.setObjectName("tvEpAirs")
            h.addWidget(when)
        else:
            when = QLabel(_date_label(ep.get("air_date")).rsplit(",", 1)[0])
            when.setObjectName("tvEpDate")
            h.addWidget(when)
        self._aired = aired

    def contextMenuEvent(self, e):
        if not self._aired:
            return
        n = self.ep["episode_number"]
        m = QMenu(self)
        m.addAction("Watched up to here", lambda: self.through.emit(n))
        m.addAction("Mark unwatched" if self.ep.get("watched") else "Mark watched",
                    lambda: self.toggled.emit(n, not self.ep.get("watched")))
        rm = m.addMenu("Rate episode")
        for v in range(6, 0, -1):
            rm.addAction(f"{'★' * v}  {_LABELS[v]}", lambda v=v: self.rate.emit(n, v))
        if self.ep.get("rating"):
            rm.addSeparator()
            rm.addAction("Clear rating", lambda: self.rate.emit(n, None))
        m.exec(e.globalPos())


class TVSection(QWidget):
    changed = pyqtSignal(int)               # library id: progress / status / rating changed

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._row: Optional[Dict] = None
        self._season: Optional[int] = None
        self._token = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # Where you are
        self.status_card = _card("")
        sl = self.status_card.layout()
        chips = QHBoxLayout()
        self.stamp = QLabel()
        self.stamp.setObjectName("tvStamp")
        self.show_state = QLabel()
        self.show_state.setObjectName("tvShowState")
        chips.addWidget(self.stamp)
        chips.addWidget(self.show_state)
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
        self.bar_fill.setObjectName("tvProgressFill")
        self.next_air = QLabel()
        self.next_air.setObjectName("tvNextAir")
        self.next_air.setWordWrap(True)
        self.count = QLabel()
        self.count.setObjectName("movieCountdown")
        for w in (self.main, self.sub, self.bar, self.next_air, self.count):
            sl.addWidget(w)
        self.actions_host = QWidget()
        self.actions = FlowLayout(self.actions_host, h_spacing=8, v_spacing=8)
        sl.addWidget(self.actions_host)
        lay.addWidget(self.status_card)

        # Seasons
        self.seasons_card = _card("Seasons")
        ssl = self.seasons_card.layout()
        tabs_host = QWidget()
        self.tabs = FlowLayout(tabs_host, h_spacing=6, v_spacing=6)
        ssl.addWidget(tabs_host)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.season_title = QLabel()
        self.season_title.setObjectName("tvSeasonTitle")
        head.addWidget(self.season_title, 1)
        self.season_stars = _Stars()
        self.season_stars.setToolTip("Rate this season")
        self.season_stars.rated.connect(self._rate_season)
        head.addWidget(self.season_stars)
        ssl.addLayout(head)
        sub_row = QHBoxLayout()
        self.season_meta = QLabel()
        self.season_meta.setObjectName("plannedReleaseHint")
        self.season_meta.setWordWrap(True)
        sub_row.addWidget(self.season_meta, 1)
        self.season_btn = QPushButton()
        self.season_btn.setObjectName("secondaryBtn")
        self.season_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.season_btn.clicked.connect(self._toggle_season)
        sub_row.addWidget(self.season_btn)
        ssl.addLayout(sub_row)
        self.eps_host = QWidget()
        self.eps = QVBoxLayout(self.eps_host)
        self.eps.setContentsMargins(0, 4, 0, 0)
        self.eps.setSpacing(2)
        ssl.addWidget(self.eps_host)
        hint = QLabel("Right-click an episode: watched up to here, rate it.")
        hint.setObjectName("plannedReleaseHint")
        ssl.addWidget(hint)
        lay.addWidget(self.seasons_card)

        # Verdict (finished)
        self.verdict_card = _card("Your verdict")
        from ui.completed_details import _StatTile
        row = QHBoxLayout()
        row.setSpacing(10)
        self.you = _StatTile("You")
        self.you.value.setObjectName("verdictYou")
        self.comm = _StatTile("Community")
        self.comm.value.setObjectName("verdictCommunity")
        row.addWidget(self.you, 1)
        row.addWidget(self.comm, 1)
        self.verdict_card.layout().addLayout(row)
        self.verdict_line = QLabel()
        self.verdict_line.setObjectName("verdictLine")
        self.verdict_line.setWordWrap(True)
        self.verdict_card.layout().addWidget(self.verdict_line)
        from ui.detail_panel import _RatingWidget
        self.rating = _RatingWidget(db, overall=True)
        self.rating.rated.connect(self._on_rated)
        self.verdict_card.layout().addWidget(self.rating)
        lay.addWidget(self.verdict_card)

        # Where to watch
        self.where_card = _card("Where to watch")
        self.where_host = QWidget()
        self.where_lay = QVBoxLayout(self.where_host)
        self.where_lay.setContentsMargins(0, 0, 0, 0)
        self.where_lay.setSpacing(8)
        self.where_card.layout().addWidget(self.where_host)
        credit = QLabel("Availability by JustWatch")
        credit.setObjectName("plannedReleaseHint")
        self.where_card.layout().addWidget(credit)
        lay.addWidget(self.where_card)

        # Trailers
        from ui.video_gallery import VideoGallery
        self.videos_card = _card("Trailers & videos")
        self.gallery = VideoGallery("No trailers yet.")
        self.videos_card.layout().addWidget(self.gallery)
        lay.addWidget(self.videos_card)

        # Facts + cast
        self.facts_card = _card("At a glance")
        self.facts = QGridLayout()
        self.facts.setHorizontalSpacing(14)
        self.facts.setVerticalSpacing(8)
        self.facts_card.layout().addLayout(self.facts)
        lay.addWidget(self.facts_card)
        self.cast_card = _card("Cast")
        self.cast = QGridLayout()
        self.cast.setHorizontalSpacing(6)
        self.cast.setVerticalSpacing(10)
        self.cast_card.layout().addLayout(self.cast)
        lay.addWidget(self.cast_card)
        self._avatars = {}

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    # ── load ──────────────────────────────────────────────────────────────────

    def load(self, row: Dict, keep_season: bool = False):
        same = self._row and self._row.get("id") == row.get("id")
        self._row = row
        self._token += 1
        if not (keep_season and same):
            self._season = None
        self._render_status()
        self._render_seasons()
        finished = row.get("watch_status") == "completed"
        self.verdict_card.setVisible(finished)
        if finished:
            self.rating.load(row["id"], episode_num=0)
            self._render_verdict()
        if not keep_season or not same:
            self._render_facts()
            self._render_cast()
            from core.videos import build_playlist
            self.gallery.load(build_playlist(row), row.get("romaji_title") or "")
            self._clear(self.where_lay)
            self.where_lay.addWidget(self._muted("Checking availability…"))
            self._fetch_where(row)

    def stop(self):
        self._timer.stop()

    def reload(self, keep_season: bool = True):
        fresh = self.db.get_anime_by_id(self._row["id"])
        if fresh:
            self.load(fresh, keep_season=keep_season)

    # ── where you are ─────────────────────────────────────────────────────────

    def _render_status(self):
        r = self._row
        ws = r.get("watch_status")
        p = self.db.tv_progress(r["id"])
        self._p = p
        self._clear_flow()
        self.stamp.setText({"watching": "WATCHING", "planned": "WATCHLIST", "completed": "COMPLETED",
                            "dropped": "DROPPED"}.get(ws, (ws or "").upper()))
        self.stamp.setProperty("ws", ws or "")
        api = r.get("status")
        self.show_state.setText({"RELEASING": "Returning series", "FINISHED": "Ended",
                                 "CANCELLED": "Cancelled", "NOT_YET_RELEASED": "Not aired yet",
                                 "HIATUS": "On hiatus"}.get(api, ""))
        for w in (self.stamp,):
            w.style().unpolish(w)
            w.style().polish(w)

        nxt = p["next"]
        if ws == "planned":
            self.main.setText("On your Watchlist." if p["aired"] else "Hasn't premiered yet.")
        elif ws == "completed":
            self.main.setText(f"Finished · {p['watched']} episodes watched.")
        elif ws == "dropped":
            last = p["last"]
            self.main.setText(f"Dropped after {code(last['season_number'], last['episode_number'])}."
                              if last else "Dropped before starting.")
        elif nxt:
            name = f" · {nxt['name']}" if nxt.get("name") else ""
            self.main.setText(f"Up next: {code(nxt['season_number'], nxt['episode_number'])}{name}")
        elif p["watched"]:
            self.main.setText("You're caught up.")
        else:
            self.main.setText("Ready to start.")

        if p["aired"]:
            left = p["unwatched_aired"]
            mins = left * (r.get("duration") or 45)
            h, m = divmod(mins, 60)
            tail = (f" · {left} to go (about {h}h {m:02d}m)" if h else f" · {left} to go (about {m}m)") \
                if left and ws in ("watching", "dropped") else ""
            self.sub.setText(f"{p['watched']} of {p['aired']} aired episodes watched{tail}")
        else:
            self.sub.setText("")
        self.sub.setVisible(bool(self.sub.text()))
        frac = p["watched"] / p["aired"] if p["aired"] else 0
        self.bar.setVisible(ws in ("watching", "completed", "dropped") and p["aired"] > 0)
        QTimer.singleShot(0, lambda f=frac: self._size_bar(f))

        up = p["upcoming"]
        self._count_target = 0
        if up and up.get("air_date"):
            label = (f"Season {up['season_number']} premieres" if up["episode_number"] == 1
                     else f"{code(up['season_number'], up['episode_number'])} airs")
            name = f" · {up['name']}" if up.get("name") and not up["name"].startswith("Episode ") else ""
            self.next_air.setText(f"{label} {_date_label(up['air_date'])}{name}")
            self._count_target = int(datetime.strptime(up["air_date"], "%Y-%m-%d").timestamp())
        elif api == "RELEASING":
            self.next_air.setText("Next episode date not announced yet.")
        else:
            self.next_air.setText("")
        self.next_air.setVisible(bool(self.next_air.text()))
        self._tick()
        self.count.setVisible(self._count_target > int(datetime.now().timestamp()))
        if self.count.isVisible():
            self._timer.start(30_000)
        else:
            self._timer.stop()

        aired = p["aired"] > 0
        if ws == "planned":
            if aired:
                self._add_action("▶  Start watching", "primaryBtn", lambda: self._set_status("watching"))
                self._add_action("✓  I've finished it", "secondaryBtn", self._finish_all)
        elif ws == "watching":
            if nxt:
                self._add_action(f"✓  Watched {code(nxt['season_number'], nxt['episode_number'])}",
                                 "primaryBtn", lambda: self._toggle(nxt["season_number"],
                                                                     nxt["episode_number"], True))
            if api in ("FINISHED", "CANCELLED"):
                self._add_action("Mark completed", "secondaryBtn", self._finish_all)
            self._add_action("Drop", "dangerBtn", lambda: self._set_status("dropped"))
        elif ws == "completed":
            self._add_action("Back to Watching", "secondaryBtn", lambda: self._set_status("watching"))
        elif ws == "dropped":
            self._add_action("▶  Resume watching", "primaryBtn", lambda: self._set_status("watching"))

    def _size_bar(self, frac: float):
        try:
            self.bar_fill.setGeometry(0, 0, int(self.bar.width() * max(0.0, min(1.0, frac))), 6)
        except RuntimeError:
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        p = getattr(self, "_p", None)
        if p and p["aired"]:
            self._size_bar(p["watched"] / p["aired"])

    def _tick(self):
        now = int(datetime.now().timestamp())
        t = getattr(self, "_count_target", 0) or 0
        if t > now:
            self.count.setText(f"in {_span(t - now)}")

    def _add_action(self, text, obj, cb):
        b = QPushButton(text)
        b.setObjectName(obj)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setMinimumHeight(34)
        b.clicked.connect(cb)
        self.actions.addWidget(b)

    # ── seasons & episodes ────────────────────────────────────────────────────

    def _render_seasons(self):
        r = self._row
        seasons = self.db.get_tv_seasons(r["id"])
        self.tabs.clear()
        self.seasons_card.setVisible(bool(seasons))
        if not seasons:
            return
        p = self._p
        all_eps = self.db.get_tv_episodes(r["id"])
        if self._season is None or self._season not in {s["season_number"] for s in seasons}:
            self._season = self._current_season(seasons, all_eps, p)
        for s in seasons:
            n = s["season_number"]
            eps = [e for e in all_eps if e["season_number"] == n]
            done = eps and all(e.get("watched") for e in eps
                               if e.get("air_date") and e["air_date"] <= _today())
            started = any(e.get("watched") for e in eps)
            b = QPushButton(f"S{n}" + (" ✓" if done and started else ""))
            b.setObjectName("tvSeasonTab")
            b.setProperty("active", "true" if n == self._season else "false")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setToolTip(s.get("name") or f"Season {n}")
            b.clicked.connect(lambda _=False, n=n: self._pick_season(n))
            self.tabs.addWidget(b)
        self._render_episodes(seasons, all_eps)

    @staticmethod
    def _current_season(seasons: List[Dict], eps: List[Dict], p: Dict) -> int:
        """The season you're on: the one with your next episode; when you've
        finished a season, the one after it (even if it hasn't aired yet)."""
        nums = [s["season_number"] for s in seasons]
        if p["next"]:
            return p["next"]["season_number"]
        if p["last"]:
            n = p["last"]["season_number"]
            done = all(e.get("watched") for e in eps
                       if e["season_number"] == n and e.get("air_date") and e["air_date"] <= _today())
            later = [x for x in nums if x > n]
            return later[0] if done and later else n
        return nums[0]

    def _pick_season(self, n: int):
        self._season = n
        self._render_seasons()

    def _render_episodes(self, seasons: List[Dict], all_eps: List[Dict]):
        n = self._season
        s = next((x for x in seasons if x["season_number"] == n), {})
        eps = [e for e in all_eps if e["season_number"] == n]
        today = _today()
        aired = [e for e in eps if e.get("air_date") and e["air_date"] <= today]
        watched = sum(1 for e in eps if e.get("watched"))
        self.season_title.setText(s.get("name") or f"Season {n}")
        year = (s.get("air_date") or "")[:4]
        bits = [f"{len(eps) or s.get('episode_count') or 0} episodes"]
        if year:
            bits.append(year if (s.get("air_date") or "") <= today
                        else "premieres " + _date_label(s["air_date"]))
        if aired:
            bits.append(f"{watched}/{len(aired)} watched")
        self.season_meta.setText("  ·  ".join(bits))
        self.season_stars.set_value(s.get("rating"))
        self.season_stars.setVisible(bool(aired))
        all_done = bool(aired) and all(e.get("watched") for e in aired)
        self.season_btn.setText(f"Unmark S{n}" if all_done else f"✓  Mark S{n} watched")
        self.season_btn.setToolTip("Unmark this season" if all_done else "Mark every aired episode of this season watched")
        self.season_btn.setVisible(bool(aired))
        self._clear(self.eps)
        nxt = self._p["next"]
        for e in eps:
            is_next = bool(nxt) and (nxt["season_number"], nxt["episode_number"]) == (n, e["episode_number"])
            row = _EpisodeRow(e, is_next)
            row.toggled.connect(lambda ep, on, n=n: self._toggle(n, ep, on))
            row.through.connect(lambda ep, n=n: self._through(n, ep))
            row.rate.connect(lambda ep, v, n=n: self._rate_episode(n, ep, v))
            self.eps.addWidget(row)
        if not eps:
            self.eps.addWidget(self._muted("Episodes will appear once they're announced."))

    # ── actions ───────────────────────────────────────────────────────────────

    def _after_progress(self):
        """Starting an episode moves a Watchlist show to Watching; finishing
        every episode of an ended show completes it."""
        r = self.db.get_anime_by_id(self._row["id"])
        p = self.db.tv_progress(r["id"])
        from ui.toast import Toast
        if r.get("watch_status") in ("planned", "dropped") and p["watched"]:
            self.db.update_anime(r["id"], {"watch_status": "watching"})
        elif (r.get("watch_status") == "watching" and p["total"] and p["watched"] >= p["total"]
              and r.get("status") in ("FINISHED", "CANCELLED")):
            self.db.update_anime(r["id"], {"watch_status": "completed"})
            Toast.show(self.window(), f"You finished '{r.get('romaji_title')}'! How was it?", kind="success")
        self.reload()
        self.changed.emit(r["id"])

    def _toggle(self, season: int, ep: int, on: bool):
        self.db.set_tv_episode_watched(self._row["id"], season, ep, on)
        self._after_progress()

    def _through(self, season: int, ep: int):
        self.db.set_tv_watched_through(self._row["id"], season, ep)
        self._after_progress()

    def _toggle_season(self):
        n = self._season
        eps = [e for e in self.db.get_tv_episodes(self._row["id"], n)
               if e.get("air_date") and e["air_date"] <= _today()]
        all_done = bool(eps) and all(e.get("watched") for e in eps)
        self.db.set_tv_season_watched(self._row["id"], n, not all_done)
        if not all_done:
            later = [s["season_number"] for s in self.db.get_tv_seasons(self._row["id"])
                     if s["season_number"] > n]
            if later:
                self._season = later[0]
        self._after_progress()

    def _finish_all(self):
        r = self._row
        eps = self.db.get_tv_episodes(r["id"])
        last = max(((e["season_number"], e["episode_number"]) for e in eps
                    if e.get("air_date") and e["air_date"] <= _today()), default=None)
        if last:
            self.db.set_tv_watched_through(r["id"], *last)
        self.db.update_anime(r["id"], {"watch_status": "completed"})
        from ui.toast import Toast
        Toast.show(self.window(), f"'{r.get('romaji_title')}' marked as finished. How was it?", kind="success")
        self.reload(keep_season=False)
        self.changed.emit(r["id"])

    def _set_status(self, ws: str):
        upd = {"watch_status": ws}
        if ws != "completed":
            upd["completed_at"] = None
        self.db.update_anime(self._row["id"], upd)
        self.reload()
        self.changed.emit(self._row["id"])

    def _rate_episode(self, season: int, ep: int, v):
        self.db.set_tv_episode_rating(self._row["id"], season, ep, v)
        self.reload()

    def _rate_season(self, v):
        self.db.set_tv_season_rating(self._row["id"], self._season, v)
        self.changed.emit(self._row["id"])

    # ── verdict ───────────────────────────────────────────────────────────────

    def _render_verdict(self):
        r = self._row
        mine = self.db.get_overall_rating(r["id"])
        comm = r.get("average_score")
        self.you.value.setText(f"{mine:.0f}/6" if mine else "—")
        self.comm.value.setText(f"★ {comm / 10:.1f}" if comm else "—")
        seasons = [s for s in self.db.get_tv_seasons(r["id"]) if s.get("rating")]
        best = max(seasons, key=lambda s: s["rating"]) if len(seasons) > 1 else None
        if mine and comm:
            diff = mine / 6 * 10 - comm / 10
            lbl = _LABELS.get(int(mine), "").lower()
            line = (f"You rated it {lbl}, higher than most viewers." if diff >= 1 else
                    f"Viewers liked it more than you did ({lbl} for you)." if diff <= -1 else
                    f"Right in line with everyone else: {lbl}.")
        else:
            line = "You haven't rated it yet. How was it?" if not mine else _LABELS.get(int(mine), "")
        if best:
            line += f" Your favourite season: {best.get('name') or 'Season ' + str(best['season_number'])}."
        self.verdict_line.setText(line)

    def _on_rated(self, *_):
        self._render_verdict()
        self.changed.emit(self._row["id"])

    # ── facts / cast / where ──────────────────────────────────────────────────

    def _render_facts(self):
        r = self._row
        self._clear(self.facts)
        seasons = self.db.get_tv_seasons(r["id"])
        facts = [
            ("Network", ", ".join(r.get("studios") or [])),
            ("Seasons", str(len(seasons)) if seasons else ""),
            ("Episodes", str(r.get("total_episodes") or "")),
            ("Episode length", _runtime(r.get("duration"))),
            ("First aired", r.get("start_date") or ""),
            ("Genres", ", ".join((r.get("genres") or [])[:3])),
            ("Score", f"★ {r['average_score'] / 10:.1f} on TMDB" if r.get("average_score") else ""),
            ("Original title", r.get("native_title") if r.get("native_title") != r.get("romaji_title") else ""),
        ]
        i = 0
        for k, v in facts:
            if not v:
                continue
            kl = QLabel(k.upper())
            kl.setObjectName("plannedFactKey")
            vl = QLabel(v)
            vl.setObjectName("plannedFactValue")
            vl.setWordWrap(True)
            self.facts.addWidget(kl, i, 0, alignment=Qt.AlignmentFlag.AlignTop)
            self.facts.addWidget(vl, i, 1)
            i += 1
        self.facts.setColumnStretch(1, 1)

    def _render_cast(self):
        from ui.planned_details import _Avatar
        self._clear(self.cast)
        self._avatars = {}
        people = (self._row.get("characters") or [])[:8]
        self.cast_card.setVisible(bool(people))
        for i, c in enumerate(people):
            cell = QWidget()
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(3)
            av = _Avatar(52)
            cl.addWidget(av, alignment=Qt.AlignmentFlag.AlignHCenter)
            for text, obj in ((c.get("name", ""), "plannedCharName"), (c.get("role", ""), "plannedCharRole")):
                l = QLabel(text)
                l.setObjectName(obj)
                l.setWordWrap(True)
                l.setFixedWidth(76)
                l.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                cl.addWidget(l, alignment=Qt.AlignmentFlag.AlignHCenter)
            self.cast.addWidget(cell, i // 4, i % 4, alignment=Qt.AlignmentFlag.AlignTop)
            if c.get("image"):
                self._avatars[c["image"]] = av
                w = ImageWorker(c["image"], ("cast", self._token, c["image"]))
                w.signals.result.connect(self._on_avatar)
                run_worker(w)

    def _on_avatar(self, result):
        try:
            (_k, tok, url), _s, path = result
        except Exception:
            return
        av = self._avatars.get(url)
        if path and av is not None and tok == self._token:
            try:
                av.set_pixmap(QPixmap(str(path)))
            except RuntimeError:
                pass

    def _fetch_where(self, row: Dict):
        tid, tok = row.get("tmdb_id"), self._token
        if not tid:
            return

        def work():
            from core import tmdb
            d = tmdb.tv_details(tid)
            return tmdb.watch_providers(d) if d else None

        from workers.workers import PRIORITY_INTERACTIVE
        w = Worker(work)
        w.signals.result.connect(lambda res, t=tok: self._on_where(res, t))
        w.signals.error.connect(lambda _e, t=tok: self._on_where(None, t))
        run_worker(w, PRIORITY_INTERACTIVE)

    def _on_where(self, w: Optional[Dict], token: int):
        from PyQt6 import sip
        if sip.isdeleted(self) or token != self._token or not self._row:
            return
        self._clear(self.where_lay)
        if w is None:
            self.where_lay.addWidget(self._muted("Couldn't reach TMDB. Try again later."))
            return
        from core import tmdb
        shown = False
        for key, label in (("stream", "Stream"), ("rent", "Rent"), ("buy", "Buy")):
            names = w.get(key) or []
            if not names:
                continue
            shown = True
            k = QLabel(label.upper())
            k.setObjectName("plannedFactKey")
            self.where_lay.addWidget(k)
            host = QWidget()
            fl = FlowLayout(host, h_spacing=6, v_spacing=6)
            for n in names[:8]:
                fl.addWidget(_chip(n, key))
            self.where_lay.addWidget(host)
        if not shown:
            self.where_lay.addWidget(self._muted(f"Not available to stream in {tmdb.region()} right now."))

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _muted(text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("plannedReleaseHint")
        l.setWordWrap(True)
        return l

    @staticmethod
    def _clear(layout):
        while layout.count():
            it = layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _clear_flow(self):
        self.actions.clear()
