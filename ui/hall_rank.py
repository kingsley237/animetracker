"""
Raikō - Hall of Fame: "Which do you love more?" and the induct picker.

RankDialog places a title in its wing by binary insertion: two posters side
by side, click the one you love more (or ← / →). "Too close to call" (Space)
puts them side by side, Skip (S) asks about a different title, Undo
(Backspace) steps back. Re-ranking a title already in the Hall uses the same
flow against the others.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QLinearGradient, QPainter, QPainterPath
from ui.theme import QColor  # noqa: E402,F811  (theme-aware colours)
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from core.hall import WING_NAMES, Hall, InsertionSession
from ui.home_page import _Img
from ui.layout_helpers import FlowLayout

WING_COLORS = {"anime": "#8b7bff", "movie": "#fbbf24", "tv": "#38bdf8"}
GOLD = "#f5c451"


def _title(row: Dict) -> str:
    return row.get("english_title") or row.get("romaji_title") or "Untitled"


def _year(row: Dict) -> str:
    y = row.get("season_year") or (row.get("release_date") or "")[:4]
    return str(y) if y else ""


class _Contender(QWidget, _Img):
    """A big clickable poster in the head-to-head."""
    chosen = pyqtSignal()
    W, H = 220, 330

    def __init__(self, color: str, key_hint: str, parent=None):
        super().__init__(parent)
        self.color = color
        self.key_hint = key_hint
        self.row: Dict = {}
        self.rank_text = ""
        self._hover = False
        self._pix = None
        self.setFixedSize(self.W, self.H + 58)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def set_row(self, row: Dict, rank_text: str = ""):
        self.row = row
        self.rank_text = rank_text
        self._load_img(row.get("cover_url") or "")
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(4, 4, self.W - 8, self.H - 8)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.save()
        p.setClipPath(path)
        self._draw_cover(p, r, 0.3)
        g = QLinearGradient(0, r.bottom() - 90, 0, r.bottom())
        g.setColorAt(0, QColor(8, 9, 14, 0))
        g.setColorAt(1, QColor(8, 9, 14, 220))
        p.fillRect(r, g)
        p.restore()
        pen = QColor(self.color) if self._hover else QColor(255, 255, 255, 34)
        p.setPen(pen)
        if self._hover:
            for i, a in ((3, 60), (2, 120), (1, 255)):
                c = QColor(self.color)
                c.setAlpha(a)
                p.setPen(c)
                p.drawRoundedRect(r.adjusted(-i, -i, i, i), 14 + i, 14 + i)
        else:
            p.drawPath(path)
        f = QFont(self.font())
        if self.rank_text:
            f.setPointSizeF(9)
            f.setBold(True)
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(self.rank_text) + 16
            chip = QRectF(14, 14, tw, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(8, 9, 14, 200))
            p.drawRoundedRect(chip, 8, 8)
            p.setPen(QColor(GOLD))
            p.drawText(chip, Qt.AlignmentFlag.AlignCenter, self.rank_text)
        f.setPointSizeF(8)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 150))
        p.drawText(QRectF(r.left(), r.bottom() - 26, r.width() - 12, 20),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self.key_hint)
        f.setPointSizeF(11)
        p.setFont(f)
        p.setPen(QColor("#f4f5fa"))
        p.drawText(QRectF(0, self.H + 4, self.W, 22), Qt.AlignmentFlag.AlignHCenter,
                   p.fontMetrics().elidedText(_title(self.row), Qt.TextElideMode.ElideRight, self.W))
        f.setBold(False)
        f.setPointSizeF(9)
        p.setFont(f)
        p.setPen(QColor("#7f87a3"))
        p.drawText(QRectF(0, self.H + 28, self.W, 20), Qt.AlignmentFlag.AlignHCenter, _year(self.row))
        p.end()


class RankDialog(QDialog):
    """Place `lib_id` in its wing. After exec(): self.position (1-based) or 0."""

    def __init__(self, hall: Hall, lib_id: int, parent=None, tier: Optional[str] = None):
        super().__init__(parent)
        self.hall = hall
        self.lib_id = lib_id
        self.tier = tier
        self.position = 0
        self.row = hall.db.get_anime_by_id(lib_id) or {}
        self.wing = hall.wing_of(self.row)
        self.color = WING_COLORS.get(self.wing, GOLD)
        self.rerank = hall.entry(lib_id) is not None
        others = [e for e in hall.entries(self.wing) if e["lib_id"] != lib_id]
        self._rows = {e["lib_id"]: e["row"] for e in others}
        self._ranks = {e["lib_id"]: e["rank"] for e in others}
        self.session = InsertionSession([e["lib_id"] for e in others])
        self.setWindowTitle("Hall of Fame")
        self.setObjectName("hallDialog")
        self.setModal(True)
        self.setMinimumWidth(640)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 26, 32, 24)
        lay.setSpacing(6)
        kicker = QLabel(("RE-RANK · " if self.rerank else "INDUCTING INTO ") + WING_NAMES[self.wing].upper())
        kicker.setObjectName("hallKicker")
        kicker.setStyleSheet(f"color:{self.color};")
        kicker.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(kicker)
        self.heading = QLabel("Which do you love more?")
        self.heading.setObjectName("hallAsk")
        self.heading.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.heading)
        self.progress = QLabel()
        self.progress.setObjectName("hallAskSub")
        self.progress.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.progress)
        lay.addSpacing(12)

        self.pages = QStackedWidget()
        duel = QWidget()
        dl = QHBoxLayout(duel)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(18)
        dl.addStretch()
        self.left = _Contender(self.color, "←")
        self.left.set_row(self.row, "NEW" if not self.rerank else "RE-RANKING")
        self.left.chosen.connect(lambda: self._answer("new"))
        dl.addWidget(self.left)
        vs = QLabel("vs")
        vs.setObjectName("hallVs")
        dl.addWidget(vs, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.right = _Contender(self.color, "→")
        self.right.chosen.connect(lambda: self._answer("existing"))
        dl.addWidget(self.right)
        dl.addStretch()
        self.pages.addWidget(duel)

        done = QWidget()
        dn = QVBoxLayout(done)
        dn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.done_rank = QLabel()
        self.done_rank.setObjectName("hallDoneRank")
        self.done_rank.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.done_text = QLabel()
        self.done_text.setObjectName("hallAskSub")
        self.done_text.setWordWrap(True)
        self.done_text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        dn.addWidget(self.done_rank)
        dn.addWidget(self.done_text)
        self.pages.addWidget(done)
        lay.addWidget(self.pages)
        lay.addSpacing(14)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.undo_btn = self._btn("↶  Undo", "hallGhost", self._undo)
        self.tie_btn = self._btn("Too close to call", "hallGhost", lambda: self._answer("tie"))
        self.skip_btn = self._btn("Skip", "hallGhost", lambda: self._answer("skip"))
        self.ok_btn = self._btn("Done", "hallPrimary", self.accept)
        self.ok_btn.setStyleSheet(f"QPushButton#hallPrimary{{background:{self.color};}}")
        self.cancel_btn = self._btn("Cancel", "hallGhost", self.reject)
        btns.addWidget(self.undo_btn)
        btns.addStretch()
        btns.addWidget(self.tie_btn)
        btns.addWidget(self.skip_btn)
        btns.addWidget(self.cancel_btn)
        btns.addWidget(self.ok_btn)
        lay.addLayout(btns)
        hint = QLabel("Keys:  ←  →  choose   ·   Space  too close   ·   S  skip   ·   Backspace  undo")
        hint.setObjectName("hallHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(hint)
        self._refresh()

    def _btn(self, text, name, cb):
        b = QPushButton(text)
        b.setObjectName(name)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setAutoDefault(False)
        b.clicked.connect(cb)
        return b

    # ── flow ──────────────────────────────────────────────────────────────────

    def _refresh(self):
        q = None if self.session.done else self.session.question()
        if q is None:
            self._finish()
            return
        self.right.set_row(self._rows[q], f"#{self._ranks[q]}")
        left = self.session.estimate()
        n = self.session.asked + 1
        self.progress.setText(f"Question {n}  ·  about {left} to go" if left > 1 else f"Question {n}  ·  last one")
        self.undo_btn.setEnabled(bool(self.session._stack))
        self.ok_btn.hide()
        self.cancel_btn.show()

    def _answer(self, choice: str):
        if self.pages.currentIndex() != 0:
            return
        self.session.answer(choice)
        self._refresh()

    def _undo(self):
        if self.pages.currentIndex() == 1:
            # undo from the result screen: take the placement back
            self._unplace()
            self.pages.setCurrentIndex(0)
            for b in (self.tie_btn, self.skip_btn):
                b.show()
        self.session.undo()
        self._refresh()

    def _unplace(self):
        if not self.rerank:
            self.hall.remove(self.lib_id)
        elif self._old_rank:
            self.hall.move(self.lib_id, self._old_rank)
        self.position = 0

    def _finish(self):
        pos = self.session.position
        if self.rerank:
            self._old_rank = (self.hall.entry(self.lib_id) or {}).get("rank")
            self.position = self.hall.move(self.lib_id, pos)
        else:
            self._old_rank = None
            self.position = self.hall.insert_at(self.lib_id, pos, self.tier)
        n = self.hall.count(self.wing)
        self.done_rank.setText(f"#{self.position}")
        self.done_rank.setStyleSheet(f"color:{GOLD if self.position <= 3 else self.color};")
        wing = WING_NAMES[self.wing]
        if self.rerank and self._old_rank == self.position:
            msg = f"{_title(self.row)} stays at #{self.position}."
        elif self.rerank:
            msg = f"{_title(self.row)} moves from #{self._old_rank} to #{self.position} in {wing}."
        elif n == 1:
            msg = f"{_title(self.row)} opens your {wing} Hall of Fame."
        else:
            msg = f"{_title(self.row)} takes its place at #{self.position} of {n} in {wing}."
        self.done_text.setText(msg)
        self.heading.setText("Your Hall has spoken" if self.session.asked else "Inducted")
        self.progress.setText(f"after {self.session.asked} question{'s' if self.session.asked != 1 else ''}"
                              if self.session.asked else "")
        self.pages.setCurrentIndex(1)
        for b in (self.tie_btn, self.skip_btn, self.cancel_btn):
            b.hide()
        self.ok_btn.show()
        self.ok_btn.setFocus()
        self.undo_btn.setEnabled(bool(self.session._stack))

    def keyPressEvent(self, e):
        k = e.key()
        if self.pages.currentIndex() == 0:
            if k == Qt.Key.Key_Left:
                return self._answer("new")
            if k == Qt.Key.Key_Right:
                return self._answer("existing")
            if k == Qt.Key.Key_Space:
                return self._answer("tie")
            if k == Qt.Key.Key_S:
                return self._answer("skip")
        if k == Qt.Key.Key_Backspace and self.undo_btn.isEnabled():
            return self._undo()
        super().keyPressEvent(e)

    def exec(self):
        if self.session.done:          # empty wing: no question to ask
            QTimer.singleShot(0, self._refresh)
        return super().exec()


# ── Induct picker ─────────────────────────────────────────────────────────────

class _PickTile(QWidget, _Img):
    picked = pyqtSignal(int)
    W, H = 118, 177

    def __init__(self, row: Dict, color: str, parent=None):
        super().__init__(parent)
        self.row = row
        self.color = color
        self._hover = False
        self.setFixedSize(self.W, self.H + 40)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(_title(row))
        self._load_img(row.get("cover_url") or "")

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.row["id"])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(1, 1, self.W - 2, self.H - 2)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.save()
        p.setClipPath(path)
        self._draw_cover(p, r)
        p.restore()
        p.setPen(QColor(self.color) if self._hover else QColor(255, 255, 255, 30))
        p.drawPath(path)
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#e8eaf2"))
        p.drawText(QRectF(0, self.H + 4, self.W, 18), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(_title(self.row), Qt.TextElideMode.ElideRight, self.W))
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor("#7f87a3"))
        p.drawText(QRectF(0, self.H + 21, self.W, 16), Qt.AlignmentFlag.AlignLeft, _year(self.row))
        p.end()


class InductDialog(QDialog):
    """Pick a finished title to induct. After exec(): self.chosen (lib id) or None."""

    def __init__(self, hall: Hall, wing: str, parent=None):
        super().__init__(parent)
        self.hall = hall
        self.chosen: Optional[int] = None
        self.setWindowTitle("Induct into the Hall of Fame")
        self.setObjectName("hallDialog")
        self.resize(820, 620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 20)
        lay.setSpacing(10)
        h = QLabel("Induct a title")
        h.setObjectName("hallAsk")
        lay.addWidget(h)
        sub = QLabel("Anything you've finished can join: completed anime and shows, watched movies, "
                     "and TV shows with a fully watched season.")
        sub.setObjectName("hallAskSub")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        top = QHBoxLayout()
        self.tabs: Dict[str, QPushButton] = {}
        for w in ("anime", "movie", "tv"):
            b = QPushButton(f"{WING_NAMES[w]}  {len(hall.candidates(w))}")
            b.setObjectName("hallTab")
            b.setCheckable(True)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _=False, w=w: self._set_wing(w))
            self.tabs[w] = b
            top.addWidget(b)
        top.addStretch()
        self.search = QLineEdit()
        self.search.setObjectName("homeSearch")
        self.search.setPlaceholderText("Search your library — or anything online")
        self.search.setFixedSize(300, 36)
        self.search.textChanged.connect(lambda _t: self._fill())
        top.addWidget(self.search)
        lay.addLayout(top)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        lay.addWidget(self.scroll, 1)
        self.container = QWidget()
        self._cv = QVBoxLayout(self.container)
        self._cv.setContentsMargins(0, 0, 0, 0)
        self._cv.setSpacing(22)
        self.lib_host = QWidget()
        self._cv.addWidget(self.lib_host)
        self.finder = OnlineFinder(hall.db)
        self.finder.added.connect(self._pick)
        self._cv.addWidget(self.finder)
        self._cv.addStretch()
        self.scroll.setWidget(self.container)
        self.wing = wing
        self._set_wing(wing)

    def _set_wing(self, wing: str):
        self.wing = wing
        for w, b in self.tabs.items():
            b.setChecked(w == wing)
            b.setStyleSheet(f"QPushButton#hallTab:checked{{color:#0b0d12;background:{WING_COLORS[w]};}}")
        self._fill()

    def _fill(self):
        q = self.search.text().strip().lower()
        rows: List[Dict] = [r for r in self.hall.candidates(self.wing)
                            if not q or q in _title(r).lower() or q in (r.get("romaji_title") or "").lower()]
        host = QWidget()
        if not rows:
            v = QVBoxLayout(host)
            v.setContentsMargins(0, 0, 0, 0)
            e = QLabel("Nothing finished here yet." if not q else "Nothing finished in your library matches that.")
            e.setObjectName("homeEmpty")
            v.addWidget(e)
        else:
            flow = FlowLayout(host, 14, 14)
            for r in rows:
                t = _PickTile(r, WING_COLORS[self.wing])
                t.picked.connect(self._pick)
                flow.addWidget(t)
        self._cv.replaceWidget(self.lib_host, host)
        self.lib_host.deleteLater()
        self.lib_host = host
        self.finder.set_query(self.wing, q)

    def _pick(self, lib_id: int):
        self.chosen = lib_id
        self.accept()


class OnlineFinder(QWidget):
    """'Not in your library yet': online results for what you typed, with
    Show more. Picking one adds it to its library as watched, then emits
    `added(lib_id)`."""
    added = pyqtSignal(int)
    LIB = {"anime": "Miroku", "movie": "Kinema · Movies", "tv": "Kinema · TV shows"}

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.kind = "anime"
        self.q = ""
        self.page = 1
        self.hits: List[Dict] = []
        self._tok = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.head = QLabel()
        self.head.setObjectName("hallKicker")
        self.head.setStyleSheet(f"color:{GOLD};")
        lay.addWidget(self.head)
        self.status = QLabel()
        self.status.setObjectName("hallAskSub")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.grid_host = QWidget()
        self.flow = FlowLayout(self.grid_host, 14, 14)
        lay.addWidget(self.grid_host)
        self.more = QPushButton("Show more")
        self.more.setObjectName("hallGhost")
        self.more.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.more.clicked.connect(self._more)
        self.more.hide()
        lay.addWidget(self.more, alignment=Qt.AlignmentFlag.AlignLeft)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._run)
        self.set_query("anime", "")

    def set_query(self, kind: str, q: str):
        self.kind, self.q = kind, (q or "").strip()
        self.head.setText(f"NOT IN {self.LIB[kind].upper()} YET?")
        if len(self.q) < 2:
            self._tok += 1
            self._clear()
            self.status.setText("Watched something Raikō doesn't know about? Type its name above — "
                                f"pick it and it's added to {self.LIB[kind]} as watched.")
            self.more.hide()
            return
        self.status.setText(f"Searching online for “{self.q}”…")
        self._timer.start(380)

    def _clear(self):
        while self.flow.count():
            it = self.flow.takeAt(0)
            if it and it.widget():
                it.widget().deleteLater()
        self.hits = []

    def _run(self, page: int = 1):
        from workers.workers import Worker, run_worker
        self._tok += 1
        tok, kind, q = self._tok, self.kind, self.q
        self.page = page

        def work():
            from core.quick_add import search
            return search(kind, q, page)

        w = Worker(work)
        w.signals.result.connect(lambda hits, t=tok, p=page: self._show(hits, t, p))
        w.signals.error.connect(lambda _e, t=tok: t == self._tok and self.status.setText(
            "Couldn't search online. Check your connection."))
        run_worker(w)

    def _show(self, hits, tok, page):
        from PyQt6 import sip
        if sip.isdeleted(self) or tok != self._tok:
            return
        from core.quick_add import in_library
        fresh = [h for h in (hits or []) if h.get("provider_id") and not in_library(self.db, h)
                 and h.get("provider_id") not in {x.get("provider_id") for x in self.hits}]
        if page == 1:
            self._clear()
        start = len(self.hits)
        self.hits += fresh
        for i, h in enumerate(fresh, start=start):
            row = {"id": i, "cover_url": h.get("poster_url") or "", "english_title": h.get("title") or "",
                   "season_year": h.get("year") or ""}
            t = _PickTile(row, WING_COLORS.get(self.kind, GOLD))
            t.setToolTip(f"{h.get('title')} — add to {self.LIB[self.kind]} as watched")
            t.picked.connect(self._pick)
            self.flow.addWidget(t)
        if not self.hits:
            self.status.setText(f"Nothing online called “{self.q}”.")
        else:
            self.status.setText(f"Pick one to add it to {self.LIB[self.kind]} as watched.")
        self.more.setVisible(bool(fresh))

    def _more(self):
        self.more.hide()
        self._run(self.page + 1)

    def _pick(self, i: int):
        h = self.hits[i]
        from PyQt6.QtWidgets import QMessageBox
        lib = self.LIB[self.kind]
        if QMessageBox.question(self, "Add to your library",
                                f"Add “{h.get('title')}” to {lib} as watched?\n\n"
                                "It's saved to your library with its details, then you carry on here."
                                ) != QMessageBox.StandardButton.Yes:
            return
        self.status.setText(f"Adding “{h.get('title')}” to {lib}…")
        self.setEnabled(False)
        from workers.workers import Worker, run_worker
        path = self.db.db_path

        def work():
            from core.database import DatabaseManager
            from core.quick_add import add_watched
            return add_watched(DatabaseManager(path), h)

        def done(lib_id):
            from PyQt6 import sip
            if sip.isdeleted(self):
                return
            self.setEnabled(True)
            if not lib_id:
                self.status.setText("Couldn't reach the server — try again in a moment.")
                return
            self.status.setText(f"Added to {lib}.")
            self.added.emit(int(lib_id))

        w = Worker(work)
        w.signals.result.connect(done)
        w.signals.error.connect(lambda _e: done(None))
        run_worker(w)


def induct(hall: Hall, parent, wing: str = "anime", lib_id: Optional[int] = None) -> int:
    """Full flow: pick (unless given) then rank. Returns the rank, or 0."""
    if lib_id is None:
        dlg = InductDialog(hall, wing, parent)
        if not dlg.exec() or dlg.chosen is None:
            return 0
        lib_id = dlg.chosen
    rd = RankDialog(hall, lib_id, parent)
    rd.exec()
    return rd.position
