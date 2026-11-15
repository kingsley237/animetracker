"""
Kinema - movie section of the detail panel.

Watchlist  release dates (cinema / digital, your country) with a countdown,
           Mark as watched, where to watch, trailers, facts, cast, franchise.
Watched    when you watched it, your verdict vs the community, rewatch log,
           Hall of Fame, plus where to watch / trailers / franchise.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ui.layout_helpers import FlowLayout
from workers.workers import ImageWorker, Worker, run_worker

_LABELS = {1: "Terrible", 2: "Bad", 3: "Fair", 4: "Good", 5: "Great", 6: "Masterpiece"}


def _card(title: str) -> QFrame:
    card = QFrame()
    card.setObjectName("detailCard")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(8)
    if title:
        lbl = QLabel(title)
        lbl.setObjectName("detailSectionLabel")
        lay.addWidget(lbl)
    return card


def _date_label(s: Optional[str]) -> str:
    try:
        d = datetime.strptime((s or "")[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    return d.strftime("%b ") + f"{d.day}, {d.year}"


def _span(seconds: int) -> str:
    d, rem = divmod(max(0, seconds), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return f"{d}d {h:02d}h" if d else f"{h}h {m:02d}m"


def _runtime(mins) -> str:
    if not mins:
        return ""
    h, m = divmod(int(mins), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def _chip(text: str, kind: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName({"stream": "providerChipStream", "rent": "providerChip",
                       "buy": "providerChip"}.get(kind, "providerChip"))
    return lbl


class MovieSection(QWidget):
    changed = pyqtSignal(int)              # library id: status / rating / rewatch changed
    open_hall_of_fame = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._row: Optional[Dict] = None
        self._token = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # Status / release
        self.status_card = _card("")
        sl = self.status_card.layout()
        chip_row = QHBoxLayout()
        self.stamp = QLabel()
        self.stamp.setObjectName("movieStamp")
        chip_row.addWidget(self.stamp)
        chip_row.addStretch()
        sl.addLayout(chip_row)
        self.main = QLabel()
        self.main.setObjectName("plannedReleaseMain")
        self.main.setWordWrap(True)
        self.count = QLabel()
        self.count.setObjectName("movieCountdown")
        self.sub = QLabel()
        self.sub.setObjectName("plannedReleaseHint")
        self.sub.setWordWrap(True)
        for w in (self.main, self.count, self.sub):
            sl.addWidget(w)
        self.actions_host = QWidget()
        self.actions = FlowLayout(self.actions_host, h_spacing=8, v_spacing=8)
        sl.addWidget(self.actions_host)
        self.rw_history = QLabel()
        self.rw_history.setObjectName("plannedReleaseHint")
        self.rw_history.setTextFormat(Qt.TextFormat.RichText)
        self.rw_history.setWordWrap(True)
        sl.addWidget(self.rw_history)
        lay.addWidget(self.status_card)

        # Verdict (watched)
        self.verdict_card = _card("Your verdict")
        vl = self.verdict_card.layout()
        from ui.completed_details import _StatTile
        row = QHBoxLayout()
        row.setSpacing(10)
        self.you = _StatTile("You")
        self.you.value.setObjectName("verdictYou")
        self.comm = _StatTile("Community")
        self.comm.value.setObjectName("verdictCommunity")
        row.addWidget(self.you, 1)
        row.addWidget(self.comm, 1)
        vl.addLayout(row)
        self.verdict_line = QLabel()
        self.verdict_line.setObjectName("verdictLine")
        self.verdict_line.setWordWrap(True)
        vl.addWidget(self.verdict_line)
        from ui.detail_panel import _RatingWidget
        self.rating = _RatingWidget(db, overall=True)
        self.rating.rated.connect(self._on_rated)
        vl.addWidget(self.rating)
        lay.addWidget(self.verdict_card)

        # Where to watch
        self.where_card = _card("Where to watch")
        wl = self.where_card.layout()
        self.where_host = QWidget()
        self.where_lay = QVBoxLayout(self.where_host)
        self.where_lay.setContentsMargins(0, 0, 0, 0)
        self.where_lay.setSpacing(8)
        wl.addWidget(self.where_host)
        self.where_credit = QLabel("Availability by JustWatch")
        self.where_credit.setObjectName("plannedReleaseHint")
        wl.addWidget(self.where_credit)
        lay.addWidget(self.where_card)

        # Trailers
        from ui.video_gallery import VideoGallery
        self.videos_card = _card("Trailers & videos")
        self.gallery = VideoGallery("No trailers yet. You'll get a notification when one drops.")
        self.videos_card.layout().addWidget(self.gallery)
        lay.addWidget(self.videos_card)

        # Facts
        self.facts_card = _card("At a glance")
        self.facts = QGridLayout()
        self.facts.setHorizontalSpacing(14)
        self.facts.setVerticalSpacing(8)
        self.facts_card.layout().addLayout(self.facts)
        lay.addWidget(self.facts_card)

        # Cast
        self.cast_card = _card("Cast")
        self.cast = QGridLayout()
        self.cast.setHorizontalSpacing(6)
        self.cast.setVerticalSpacing(10)
        self.cast_card.layout().addLayout(self.cast)
        lay.addWidget(self.cast_card)
        self._avatars = {}

        # Franchise
        self.coll_card = _card("Collection")
        self.coll_host = QWidget()
        self.coll_lay = QVBoxLayout(self.coll_host)
        self.coll_lay.setContentsMargins(0, 0, 0, 0)
        self.coll_lay.setSpacing(6)
        self.coll_card.layout().addWidget(self.coll_host)
        lay.addWidget(self.coll_card)

        # Hall of Fame (watched)
        self.hof_card = _card("Hall of Fame")
        self.hof_text = QLabel()
        self.hof_text.setObjectName("plannedFactValue")
        self.hof_text.setWordWrap(True)
        self.hof_btn = QPushButton()
        self.hof_btn.setObjectName("secondaryBtn")
        self.hof_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.hof_btn.clicked.connect(self._hof_action)
        self.hof_card.layout().addWidget(self.hof_text)
        self.hof_card.layout().addWidget(self.hof_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.hof_card)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    # ── load ──────────────────────────────────────────────────────────────────

    def load(self, row: Dict):
        self._row = row
        self._token += 1
        watched = row.get("watch_status") == "completed"
        self.verdict_card.setVisible(watched)
        self.hof_card.setVisible(watched)
        self._render_status()
        self._render_facts()
        self._render_cast()
        from core.videos import build_playlist
        self.gallery.load(build_playlist(row), row.get("romaji_title") or "")
        self._clear(self.where_lay)
        self.where_lay.addWidget(QLabel("Checking availability…"))
        self.coll_card.setVisible(False)
        if watched:
            self.rating.load(row["id"], episode_num=0)
            self._render_verdict()
            self._render_hof()
        self._fetch_live(row)

    def stop(self):
        self._timer.stop()

    # ── status / release ──────────────────────────────────────────────────────

    def _render_status(self):
        r = self._row
        self._clear_flow(self.actions)
        now = int(datetime.now().timestamp())
        if r.get("watch_status") == "completed":
            self.stamp.setText("✓  WATCHED")
            self.stamp.setProperty("kind", "watched")
            when = r.get("completed_at")
            self.main.setText(
                "Watched " + (datetime.fromtimestamp(when).strftime("%A, %b ") +
                              f"{datetime.fromtimestamp(when).day}, {datetime.fromtimestamp(when).year}")
                if when else "Watched")
            times = 1 + self.db.rewatch_count(r["id"])
            self.sub.setText(f"Seen {times} times." if times > 1 else "Seen once.")
            self.count.setVisible(False)
            self._timer.stop()
            self._add_action("↻  Log a rewatch", "secondaryBtn", self._log_rewatch)
            self._add_action("Move to Watchlist", "secondaryBtn", self._to_watchlist)
            self._render_rewatches()
        else:
            upcoming = (r.get("status") == "NOT_YET_RELEASED")
            self.stamp.setText("COMING SOON" if upcoming else "ON YOUR WATCHLIST")
            self.stamp.setProperty("kind", "soon" if upcoming else "watchlist")
            start = r.get("start_ts") or 0
            if upcoming and start:
                self.main.setText(f"In theaters {r.get('start_date')}")
            elif upcoming:
                self.main.setText("Release date not announced yet")
            else:
                self.main.setText(f"Released {r.get('start_date')}" if r.get("start_date") else "Released")
            self.sub.setText("")
            self.count.setVisible(upcoming and start > now)
            self._tick()
            self._timer.start(30_000)
            self._add_action("✓  Mark as watched", "primaryBtn", self._mark_watched)
            self.rw_history.setVisible(False)
        self.stamp.style().unpolish(self.stamp)
        self.stamp.style().polish(self.stamp)

    def _tick(self):
        r = self._row or {}
        start = r.get("start_ts") or 0
        now = int(datetime.now().timestamp())
        if start > now:
            self.count.setText(f"in {_span(start - now)}")

    def _add_action(self, text, obj, cb):
        b = QPushButton(text)
        b.setObjectName(obj)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setMinimumHeight(34)
        b.clicked.connect(cb)
        self.actions.addWidget(b)

    def _render_rewatches(self):
        rows = [x for x in self.db.get_rewatches(self._row["id"]) if x.get("finished_at")]
        lines = []
        for x in reversed(rows):
            d = datetime.fromtimestamp(x["finished_at"])
            lines.append(f"<span style='color:#fbbf24'>Viewing #{x['number'] + 1}</span>&nbsp;&nbsp;"
                         f"{d.strftime('%b')} {d.day}, {d.year}")
        self.rw_history.setText("<br>".join(lines))
        self.rw_history.setVisible(bool(lines))

    # ── actions ───────────────────────────────────────────────────────────────

    def _mark_watched(self):
        r = self._row
        self.db.update_anime(r["id"], {"watch_status": "completed"})
        self._reload()
        from ui.toast import Toast
        Toast.show(self.window(), f"'{r.get('romaji_title')}' marked as watched. How was it?", kind="success")

    def _to_watchlist(self):
        r = self._row
        self.db.update_anime(r["id"], {"watch_status": "planned", "completed_at": None})
        self._reload()

    def _log_rewatch(self):
        r = self._row
        rid = self.db.start_rewatch(r["id"])
        self.db.finish_rewatch(rid, 1)
        self._reload()
        from ui.toast import Toast
        Toast.show(self.window(), "Rewatch logged.", kind="success")

    def _reload(self):
        fresh = self.db.get_anime_by_id(self._row["id"])
        if fresh:
            self.load(fresh)
        self.changed.emit(self._row["id"])

    # ── verdict / hall of fame ────────────────────────────────────────────────

    def _render_verdict(self):
        r = self._row
        mine = self.db.get_overall_rating(r["id"])
        comm = r.get("average_score")
        self.you.value.setText(f"{mine:.0f}/6" if mine else "—")
        self.comm.value.setText(f"★ {comm / 10:.1f}" if comm else "—")
        if mine and comm:
            diff = mine / 6 * 10 - comm / 10
            lbl = _LABELS.get(int(mine), "").lower()
            line = (f"You rated it {lbl}, higher than most viewers." if diff >= 1 else
                    f"Viewers liked it more than you did ({lbl} for you)." if diff <= -1 else
                    f"Right in line with everyone else: {lbl}.")
        else:
            line = "You haven't rated it yet. How was it?" if not mine else _LABELS.get(int(mine), "")
        self.verdict_line.setText(line)

    def _on_rated(self, *_):
        self._render_verdict()
        self.changed.emit(self._row["id"])

    def _render_hof(self):
        from ui.hall_of_fame import _migrate
        _migrate(self.db)
        hrow = self.db._get_conn().execute(
            "SELECT rank, tier FROM hall_of_fame WHERE anime_id=?", (self._row["id"],)).fetchone()
        if hrow:
            tier = f" · Tier {hrow['tier']}" if hrow["tier"] else ""
            self.hof_text.setText(f"★  In your Hall of Fame at #{hrow['rank']}{tier}.")
            self.hof_btn.setText("Open Hall of Fame")
        else:
            self.hof_text.setText("Not in your Hall of Fame.")
            self.hof_btn.setText("＋  Add to Hall of Fame")

    def _hof_action(self):
        from ui.hall_of_fame import _add_to_hof, _in_hof
        if _in_hof(self.db, self._row["id"]):
            self.open_hall_of_fame.emit()
            return
        _add_to_hof(self.db, self._row["id"])
        self._render_hof()

    # ── facts / cast ──────────────────────────────────────────────────────────

    def _render_facts(self):
        r = self._row
        self._clear(self.facts)
        rel = []
        facts = [
            ("Runtime", _runtime(r.get("duration"))),
            ("Released", r.get("start_date") or ""),
            ("Genres", ", ".join((r.get("genres") or [])[:3])),
            ("Studio", ", ".join(r.get("studios") or [])),
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
        self._facts_row = i

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
            n = QLabel(c.get("name", ""))
            n.setObjectName("plannedCharName")
            n.setWordWrap(True)
            n.setFixedWidth(76)
            n.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            role = QLabel(c.get("role", ""))
            role.setObjectName("plannedCharRole")
            role.setWordWrap(True)
            role.setFixedWidth(76)
            role.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            cl.addWidget(n, alignment=Qt.AlignmentFlag.AlignHCenter)
            cl.addWidget(role, alignment=Qt.AlignmentFlag.AlignHCenter)
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

    # ── live data: where to watch, release dates, collection ─────────────────

    def _fetch_live(self, row: Dict):
        tid, tok = row.get("tmdb_id"), self._token
        if not tid:
            return

        def work():
            from core import tmdb
            from core.providers import get_provider, movie_row
            d = tmdb.movie_details(tid)
            if not d:
                return None
            mr = movie_row(d)
            parts = []
            if mr.get("_collection"):
                parts = get_provider("movie").collection_parts(mr["_collection"]["id"])
            return {"where": tmdb.watch_providers(d), "rel": mr.get("_release_dates") or {},
                    "collection": mr.get("_collection"), "parts": parts}

        from workers.workers import PRIORITY_INTERACTIVE
        w = Worker(work)
        w.signals.result.connect(lambda res, t=tok: self._on_live(res, t))
        w.signals.error.connect(lambda _e, t=tok: self._on_live(None, t))
        run_worker(w, PRIORITY_INTERACTIVE)

    def _on_live(self, res: Optional[Dict], token: int):
        if token != self._token or not self._row:
            return
        self._clear(self.where_lay)
        if not res:
            self.where_lay.addWidget(self._muted("Couldn't reach TMDB. Try again later."))
            return
        from core import tmdb
        w = res["where"]
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
            self.where_lay.addWidget(self._muted(
                f"Not available to stream, rent or buy in {tmdb.region()} yet."))

        rel = res["rel"]
        extra = []
        if rel.get("digital"):
            extra.append(f"Digital {_date_label(rel['digital'])}")
        if rel.get("physical"):
            extra.append(f"Disc {_date_label(rel['physical'])}")
        if extra and self._row.get("watch_status") != "completed":
            self.sub.setText("  ·  ".join(extra))

        parts = res.get("parts") or []
        self.coll_card.setVisible(len(parts) > 1)
        if len(parts) > 1:
            self._render_collection(res["collection"], parts)

    def _render_collection(self, coll: Dict, parts: List[Dict]):
        self._clear(self.coll_lay)
        title = self.coll_card.findChild(QLabel, "detailSectionLabel")
        if title:
            title.setText((coll.get("name") or "Collection").upper())
        for i, p in enumerate(parts, 1):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 2, 0, 2)
            h.setSpacing(10)
            num = QLabel(str(i))
            num.setObjectName("collectionNum")
            num.setFixedWidth(18)
            h.addWidget(num)
            name = QLabel(f"{p['title']}" + (f"  ({p['year']})" if p.get("year") else ""))
            name.setObjectName("plannedFactValue")
            name.setWordWrap(True)
            h.addWidget(name, 1)
            mine = self.db.get_title_by_tmdb("movie", p["provider_id"])
            if p["provider_id"] == self._row.get("tmdb_id"):
                tag = QLabel("THIS ONE")
                tag.setObjectName("collectionTagThis")
                h.addWidget(tag)
            elif mine:
                tag = QLabel("WATCHED" if mine.get("watch_status") == "completed" else "WATCHLIST")
                tag.setObjectName("collectionTag")
                h.addWidget(tag)
            else:
                b = QPushButton("＋ Add")
                b.setObjectName("secondaryBtn")
                b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                b.clicked.connect(lambda _=False, pid=p["provider_id"], btn=b: self._add_part(pid, btn))
                h.addWidget(b)
            self.coll_lay.addWidget(row)

    def _add_part(self, pid: int, btn: QPushButton):
        btn.setEnabled(False)
        btn.setText("Adding…")

        def work():
            from core.providers import get_provider
            return get_provider("movie").details(pid)

        def done(row):
            if not row:
                btn.setEnabled(True)
                btn.setText("＋ Add")
                return
            self.db.save_tmdb_title(row, "planned")
            btn.setText("Added")
            from ui.toast import Toast
            Toast.show(self.window(), f"'{row['romaji_title']}' added to your Watchlist.", kind="success")
            self.changed.emit(-1)

        w = Worker(work)
        w.signals.result.connect(done)
        run_worker(w)

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

    @staticmethod
    def _clear_flow(flow: FlowLayout):
        flow.clear()
