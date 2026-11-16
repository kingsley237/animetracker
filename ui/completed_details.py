"""
Miroku - Completed sections for the detail panel.

A finished show isn't about progress any more - it's about how it went and
what's next. Inspired by diary/recap views (Letterboxd entries, AniList's
completed view, year-in-review recaps):

  Finished      when you finished, how long it took, archived state
  Your verdict  your rating vs the community, in plain words (re-rate here)
  Your journey  episodes, watch time, days, pace, average episode rating
  Season curve  per-episode ratings as bars, best / weakest episode
  What's next   the sequel if one is known, else a promise to tell you
  Themes        OP/ED music videos and trailers (gallery + playlist)
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

_LABELS = {1: "Terrible", 2: "Bad", 3: "Fair", 4: "Good", 5: "Great", 6: "Masterpiece"}
_BAR_COLORS = {6: "#fbbf24", 5: "#34d399", 4: "#7c6af7", 3: "#9da5c0", 2: "#f59e0b", 1: "#f87171"}


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


def _fmt_date(ts: int, long: bool = False) -> str:
    if not ts:
        return ""
    d = datetime.fromtimestamp(ts)
    return d.strftime("%A, %b ") + f"{d.day}, {d.year}" if long else d.strftime("%b ") + f"{d.day}, {d.year}"


def _fmt_minutes(mins: int) -> str:
    if mins <= 0:
        return "—"
    h, m = divmod(int(mins), 60)
    if h >= 24:
        d, h = divmod(h, 24)
        return f"{d}d {h}h"
    return f"{h}h {m:02d}m" if h else f"{m}m"


class _StatTile(QFrame):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("statTile")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(1)
        self.value = QLabel("—")
        self.value.setObjectName("statTileValue")
        k = QLabel(label.upper())
        k.setObjectName("statTileLabel")
        v.addWidget(self.value)
        v.addWidget(k)


class _SeasonCurve(QWidget):
    """Per-episode rating bars (1-6). Unrated episodes are faint stubs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(96)
        self._scores: Dict[int, float] = {}
        self._total = 0
        self._best: Optional[int] = None

    def set_data(self, scores: Dict[int, float], total: int):
        self._scores = scores
        self._total = max(total, max(scores) if scores else 0)
        self._best = max(scores, key=lambda e: (scores[e], -e)) if scores else None
        self.update()

    def paintEvent(self, _):
        n = self._total
        if n <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height() - 16
        gap = 3 if n <= 26 else 1
        bw = max(2.0, (w - gap * (n - 1)) / n)
        # guide lines at 2, 4, 6
        p.setPen(QPen(QColor(255, 255, 255, 18), 1, Qt.PenStyle.DashLine))
        for lvl in (2, 4, 6):
            y = h - (lvl / 6) * (h - 4)
            p.drawLine(0, int(y), w, int(y))
        f = QFont(self.font())
        f.setPointSizeF(7)
        p.setFont(f)
        for i in range(n):
            ep = i + 1
            x = i * (bw + gap)
            sc = self._scores.get(ep)
            if sc:
                bh = max(4, (sc / 6) * (h - 4))
                col = QColor(_BAR_COLORS.get(int(round(sc)), "#7c6af7"))
                if ep != self._best:
                    col.setAlpha(200)
            else:
                bh = 4
                col = QColor(255, 255, 255, 30)
            path = QPainterPath()
            path.addRoundedRect(QRectF(x, h - bh, bw, bh), min(3, bw / 2), min(3, bw / 2))
            p.fillPath(path, col)
            if n <= 26 and (ep == 1 or ep == n or ep % 5 == 0):
                p.setPen(QColor("#5c6482"))
                p.drawText(QRectF(x - 6, h + 2, bw + 12, 14), Qt.AlignmentFlag.AlignHCenter, str(ep))
        p.end()


class CompletedTop(QWidget):
    rated = pyqtSignal(int)
    rewatch_changed = pyqtSignal(int)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._anime: Optional[Dict] = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # Finished
        self.finish_card = _card("")
        fl = self.finish_card.layout()
        top = QHBoxLayout()
        self.stamp = QLabel("✓  COMPLETED")
        self.stamp.setObjectName("completedStamp")
        top.addWidget(self.stamp)
        self.archived_chip = QLabel("ARCHIVED")
        self.archived_chip.setObjectName("archivedChip")
        top.addWidget(self.archived_chip)
        top.addStretch()
        fl.addLayout(top)
        self.finish_main = QLabel()
        self.finish_main.setObjectName("plannedReleaseMain")
        self.finish_main.setWordWrap(True)
        self.finish_sub = QLabel()
        self.finish_sub.setObjectName("plannedReleaseHint")
        self.finish_sub.setWordWrap(True)
        fl.addWidget(self.finish_main)
        fl.addWidget(self.finish_sub)
        lay.addWidget(self.finish_card)

        # Verdict
        self.verdict_card = _card("Your verdict")
        vl = self.verdict_card.layout()
        row = QHBoxLayout()
        row.setSpacing(10)
        self.you_box = _StatTile("You")
        self.you_box.value.setObjectName("verdictYou")
        self.comm_box = _StatTile("Community")
        self.comm_box.value.setObjectName("verdictCommunity")
        row.addWidget(self.you_box, 1)
        row.addWidget(self.comm_box, 1)
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

        # Journey
        self.journey_card = _card("Your journey")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.t_eps = _StatTile("Episodes")
        self.t_time = _StatTile("Watch time")
        self.t_days = _StatTile("Days taken")
        self.t_pace = _StatTile("Pace")
        self.t_start = _StatTile("Started")
        self.t_avg = _StatTile("Avg episode")
        for i, t in enumerate((self.t_eps, self.t_time, self.t_days,
                               self.t_pace, self.t_start, self.t_avg)):
            grid.addWidget(t, i // 3, i % 3)
        self.journey_card.layout().addLayout(grid)
        lay.addWidget(self.journey_card)

        # Rewatches
        self.rewatch_card = _card("Rewatches")
        rl = self.rewatch_card.layout()
        self.rw_status = QLabel()
        self.rw_status.setObjectName("plannedFactValue")
        self.rw_status.setWordWrap(True)
        rl.addWidget(self.rw_status)
        # active rewatch controls
        self.rw_active = QWidget()
        al = QVBoxLayout(self.rw_active)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        prow = QHBoxLayout()
        prow.setSpacing(8)
        self.rw_minus = QPushButton("−")
        self.rw_plus = QPushButton("+")
        for b, d in ((self.rw_minus, -1), (self.rw_plus, 1)):
            b.setObjectName("rewatchStep")
            b.setFixedSize(34, 30)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _=False, d=d: self._step_rewatch(d))
        self.rw_prog_lbl = QLabel()
        self.rw_prog_lbl.setObjectName("rewatchProgress")
        self.rw_prog_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prow.addWidget(self.rw_minus)
        prow.addWidget(self.rw_prog_lbl, 1)
        prow.addWidget(self.rw_plus)
        al.addLayout(prow)
        self.rw_bar = QProgressBar()
        self.rw_bar.setObjectName("rewatchBar")
        self.rw_bar.setTextVisible(False)
        self.rw_bar.setFixedHeight(6)
        al.addWidget(self.rw_bar)
        brow = QHBoxLayout()
        self.rw_finish = QPushButton("✓  Finish rewatch")
        self.rw_finish.setObjectName("primaryBtn")
        self.rw_finish.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.rw_finish.clicked.connect(lambda: self._finish_rewatch())
        self.rw_stop = QPushButton("Stop")
        self.rw_stop.setObjectName("secondaryBtn")
        self.rw_stop.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.rw_stop.clicked.connect(self._stop_rewatch)
        brow.addWidget(self.rw_finish)
        brow.addWidget(self.rw_stop)
        brow.addStretch()
        al.addLayout(brow)
        rl.addWidget(self.rw_active)
        self.rw_start = QPushButton("↻  Start a rewatch")
        self.rw_start.setObjectName("secondaryBtn")
        self.rw_start.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.rw_start.clicked.connect(self._start_rewatch)
        rl.addWidget(self.rw_start, alignment=Qt.AlignmentFlag.AlignLeft)
        self.rw_history = QLabel()
        self.rw_history.setObjectName("plannedReleaseHint")
        self.rw_history.setWordWrap(True)
        self.rw_history.setTextFormat(Qt.TextFormat.RichText)
        rl.addWidget(self.rw_history)
        lay.addWidget(self.rewatch_card)

        # Season curve
        self.curve_card = _card("Season curve")
        self.curve = _SeasonCurve()
        self.curve_note = QLabel()
        self.curve_note.setObjectName("plannedReleaseHint")
        self.curve_note.setWordWrap(True)
        self.curve_card.layout().addWidget(self.curve)
        self.curve_card.layout().addWidget(self.curve_note)
        lay.addWidget(self.curve_card)

    # ── data ──────────────────────────────────────────────────────────────────

    def load(self, anime: Dict):
        self._anime = anime
        aid = anime["id"]
        eps = self.db.get_episodes(aid)
        watched_eps = [e for e in eps if e.get("watched")]
        stamps = sorted(e["watched_at"] for e in watched_eps if e.get("watched_at"))
        finished = int(anime.get("completed_at") or (stamps[-1] if stamps else 0)
                       or anime.get("last_watched_at") or 0)
        started = stamps[0] if stamps else 0

        self.archived_chip.setVisible(bool(anime.get("archived")))
        self.finish_main.setText(
            f"Finished {_fmt_date(finished, long=True)}" if finished else "Finished")
        if started and finished and finished >= started:
            days = max(1, round((finished - started) / 86400))
            if days <= 1:
                self.finish_sub.setText("Watched in a single day. A proper binge.")
            else:
                self.finish_sub.setText(f"Took {days} days  ·  started {_fmt_date(started)}")
        else:
            self.finish_sub.setText("Start/finish dates weren't tracked for this one.")

        # Journey
        total = anime.get("total_episodes") or len(eps) or 0
        n = len(watched_eps)
        self.t_eps.value.setText(f"{n}/{total}" if total else str(n))
        dur = anime.get("duration") or 24
        self.t_time.value.setText(_fmt_minutes(n * dur) if n else "—")
        if started and finished and finished >= started:
            days = max(1, round((finished - started) / 86400))
            self.t_days.value.setText(str(days))
            per_week = n / max(days / 7, 1 / 7)
            self.t_pace.value.setText(f"{per_week:.1f}/wk" if per_week < 50 else "binge")
            self.t_start.value.setText(datetime.fromtimestamp(started).strftime("%b %d"))
        else:
            for t in (self.t_days, self.t_pace, self.t_start):
                t.value.setText("—")

        ratings = {r["episode_num"]: r["score"] for r in self.db.get_ratings(aid)
                   if r["episode_num"] and r["episode_num"] > 0}
        self.t_avg.value.setText(f"{sum(ratings.values()) / len(ratings):.1f}" if ratings else "—")

        # Curve
        self.curve.set_data(ratings, total)
        if ratings:
            best = max(ratings, key=lambda e: (ratings[e], -e))
            worst = min(ratings, key=lambda e: (ratings[e], e))
            txt = f"Peak: episode {best} ({ratings[best]:.0f}/6 · {_LABELS.get(int(ratings[best]), '')})"
            if worst != best and ratings[worst] < ratings[best]:
                txt += f"   ·   Low: episode {worst} ({ratings[worst]:.0f}/6)"
            self.curve_note.setText(txt)
        else:
            self.curve_note.setText("Rate episodes below to see how the season felt, episode by episode.")
        self.curve_card.setVisible(bool(total))

        # Verdict
        self.rating.load(aid, episode_num=0)
        self._render_verdict()
        self._render_rewatches()

    # ── rewatches ─────────────────────────────────────────────────────────────

    def _total(self) -> int:
        a = self._anime or {}
        return int(a.get("total_episodes") or 0) or len(self.db.get_episodes(a["id"])) or 0

    def _render_rewatches(self):
        a = self._anime
        if not a:
            return
        history = [r for r in self.db.get_rewatches(a["id"]) if r.get("finished_at")]
        active = self.db.get_active_rewatch(a["id"])
        times = 1 + len(history)
        self.rw_active.setVisible(bool(active))
        self.rw_start.setVisible(not active)
        total = self._total()
        if active:
            started = datetime.fromtimestamp(active["started_at"]).strftime("%b %d") if active.get("started_at") else ""
            self.rw_status.setText(
                f"Rewatch #{active['number']} in progress" + (f" · started {started}" if started else ""))
            prog = int(active.get("progress") or 0)
            self.rw_prog_lbl.setText(f"Episode {prog} / {total}" if total else f"Episode {prog}")
            self.rw_bar.setMaximum(max(total, 1))
            self.rw_bar.setValue(min(prog, total) if total else 0)
            self.rw_bar.setVisible(bool(total))
            self.rw_minus.setEnabled(prog > 0)
        else:
            self.rw_status.setText(
                "Watched once." if times == 1 else f"Watched {times} times.")
        rows = []
        for r in reversed(history):
            s = datetime.fromtimestamp(r["started_at"]) if r.get("started_at") else None
            f = datetime.fromtimestamp(r["finished_at"])
            span = ""
            if s:
                days = max(1, round((r["finished_at"] - r["started_at"]) / 86400))
                span = f" · {days} day{'s' if days != 1 else ''}"
            when = (s.strftime("%b %d") + " → " if s else "") + f.strftime("%b %d, %Y")
            rows.append(f"<span style='color:#c4b8ff'>#{r['number']}</span>&nbsp;&nbsp;{when}{span}")
        self.rw_history.setText("<br>".join(rows))
        self.rw_history.setVisible(bool(rows))
        # Finished card mentions repeat views too
        if times > 1 and self.finish_sub.text():
            base = self.finish_sub.text().split("  ·  Watched")[0]
            self.finish_sub.setText(f"{base}  ·  Watched {times}×")

    def _start_rewatch(self):
        a = self._anime
        if not a:
            return
        self.db.start_rewatch(a["id"])
        self._render_rewatches()
        self.rewatch_changed.emit(a["id"])

    def _step_rewatch(self, delta: int):
        a = self._anime
        active = self.db.get_active_rewatch(a["id"]) if a else None
        if not active:
            return
        total = self._total()
        prog = max(0, int(active.get("progress") or 0) + delta)
        if total:
            prog = min(prog, total)
        self.db.set_rewatch_progress(active["id"], prog)
        if total and prog >= total:
            self._finish_rewatch(auto=True)
            return
        self._render_rewatches()
        self.rewatch_changed.emit(a["id"])

    def _finish_rewatch(self, auto: bool = False):
        a = self._anime
        active = self.db.get_active_rewatch(a["id"]) if a else None
        if not active:
            return
        total = self._total()
        self.db.finish_rewatch(active["id"], progress=total or active.get("progress"))
        self._render_rewatches()
        self.rewatch_changed.emit(a["id"])
        from ui.toast import Toast
        Toast.show(self.window(), f"Rewatch #{active['number']} complete. "
                                  f"That's {1 + self.db.rewatch_count(a['id'])} times watched.",
                   kind="success")

    def _stop_rewatch(self):
        a = self._anime
        active = self.db.get_active_rewatch(a["id"]) if a else None
        if not active:
            return
        res = QMessageBox.question(
            self, "Stop this rewatch?",
            f"Stop rewatch #{active['number']}? Its progress won't be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if res != QMessageBox.StandardButton.Yes:
            return
        self.db.abandon_rewatch(active["id"])
        self._render_rewatches()
        self.rewatch_changed.emit(a["id"])

    def _render_verdict(self):
        a = self._anime or {}
        mine = self.db.get_overall_rating(a["id"]) if a else None
        comm = a.get("average_score")
        if mine:
            self.you_box.value.setText(f"{mine:.0f}/6")
            self.you_box.value.setToolTip(_LABELS.get(int(mine), ""))
        else:
            self.you_box.value.setText("—")
        self.comm_box.value.setText(f"★ {comm / 10:.1f}" if comm else "—")
        if mine and comm:
            mine10 = mine / 6 * 10
            diff = mine10 - comm / 10
            if diff >= 1.0:
                line = f"You rated it {_LABELS.get(int(mine), '').lower()}, higher than most fans."
            elif diff <= -1.0:
                line = f"Fans liked it more than you did ({_LABELS.get(int(mine), '').lower()} for you)."
            else:
                line = f"Right in line with the community: {_LABELS.get(int(mine), '').lower()}."
        elif not mine:
            line = "You haven't rated it yet. How was it?"
        else:
            line = f"{_LABELS.get(int(mine), '')}."
        self.verdict_line.setText(line)

    def _on_rated(self, *_):
        self._render_verdict()
        if self._anime:
            self.rated.emit(self._anime["id"])


class CompletedBottom(QWidget):
    open_sequel = pyqtSignal(int)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._anime: Optional[Dict] = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # What's next
        self.next_card = _card("What's next")
        nl = self.next_card.layout()
        self.next_text = QLabel()
        self.next_text.setObjectName("plannedFactValue")
        self.next_text.setWordWrap(True)
        self.next_btn = QPushButton("View new season")
        self.next_btn.setObjectName("primaryBtn")
        self.next_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.next_btn.clicked.connect(lambda: self._anime and self.open_sequel.emit(self._anime["id"]))
        nl.addWidget(self.next_text)
        nl.addWidget(self.next_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.next_card)

        # Themes & trailers
        from ui.video_gallery import VideoGallery
        self.videos_card = _card("Openings, endings & trailers")
        self.gallery = VideoGallery("No themes or trailers found for this one yet.")
        self.videos_card.layout().addWidget(self.gallery)
        lay.addWidget(self.videos_card)

    def load(self, anime: Dict):
        self._anime = anime

        # What's next: an active new-season alert, else what the sequel
        # check last recorded on this anime.
        import json
        alert = next((n for n in self.db.get_active_notifications("new_season")
                      if n.get("anime_id") == anime["id"]), None)
        info = None
        try:
            info = json.loads(anime.get("sequel_info") or "null")
        except Exception:
            info = None
        labels = {"announced": "announced", "airing": "airing now", "complete": "fully out"}
        lists = {"watching": "Watching", "planned": "Plan to Watch", "completed": "Completed"}
        self.next_btn.setVisible(bool(alert))
        if alert:
            p = alert.get("payload") or {}
            s = p.get("sequel") or {}
            when = s.get("start_label") or ""
            self.next_text.setText(
                f"{s.get('title', 'A new season')} is {labels.get(p.get('phase'), 'on the way')}"
                + (f" · premieres {when}" if when and p.get("phase") == "announced" else "") + ".")
        elif info:
            title = info.get("title") or "A new season"
            if info.get("in_library"):
                self.next_text.setText(
                    f"{title} is already in your {lists.get(info['in_library'], 'library')} list.")
            elif info.get("phase") == "announced":
                when = info.get("start_label")
                self.next_text.setText(
                    f"{title} has been announced"
                    + (f" for {when}" if when else "")
                    + ". Exact date not confirmed yet. You'll be alerted when it is.")
            else:
                self.next_text.setText(f"{title} is {labels.get(info.get('phase'), 'out')}.")
        else:
            self.next_text.setText("No sequel announced yet. You'll be alerted the moment one is.")

        from core.videos import build_playlist
        items = build_playlist(anime)
        items.sort(key=lambda v: 0 if v.get("kind") == "music" else 1)   # themes first
        self.gallery.load(items, anime.get("english_title") or anime.get("romaji_title") or "")
