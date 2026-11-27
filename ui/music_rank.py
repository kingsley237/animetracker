"""
Raikō - rank your music: Openings & intros, Endings, Soundtracks.

SongFinder   search any anime / show / movie (your library first, then
             online), see its openings / endings / soundtrack, ▶ to listen,
             pick one.
SongRankDialog  "Which do you love more?" - two 16:9 cards with ▶ Listen,
             binary insertion (about log2 n questions), Too close / Skip /
             Undo, keyboard ← → Space S Backspace.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from ui.theme import QColor  # noqa: E402,F811  (theme-aware colours)
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from core.hall import InsertionSession
from core.music_library import KIND_LABEL, LISTS, MusicLibrary, list_for, song_title
from ui.hall_rank import GOLD, WING_COLORS, _PickTile
from ui.home_page import _Img
from ui.layout_helpers import FlowLayout

LIST_COLOR = {"op": "#8b7bff", "ed": "#38bdf8", "ost": "#f5c451"}


def play(items: List[Dict], index: int, parent, title: str = "Music"):
    from ui.trailer_player import show_trailer
    if not items:
        return
    it = items[index]
    show_trailer(it["id"], it.get("site") or "youtube", title, parent, playlist=items, index=index)


class SongCard(QWidget, _Img):
    """16:9 thumbnail with title, source and kind; click = choose."""
    chosen = pyqtSignal()
    listen = pyqtSignal()

    def __init__(self, w: int = 300, color: str = GOLD, hint: str = "", parent=None):
        super().__init__(parent)
        self.W, self.H = w, int(w * 9 / 16)
        self.color = color
        self.hint = hint
        self.item: Dict = {}
        self.badge = ""
        self._hover = False
        self._pix = None
        self.setFixedSize(self.W, self.H + 62)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.listen_btn = QPushButton("▶  Listen", self)
        self.listen_btn.setObjectName("songListen")
        self.listen_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.listen_btn.clicked.connect(self.listen.emit)
        self.listen_btn.adjustSize()
        self.listen_btn.move(self.W - self.listen_btn.width() - 10, self.H - self.listen_btn.height() - 10)

    def set_item(self, item: Dict, badge: str = ""):
        self.item = item
        self.badge = badge
        self._load_img(item.get("thumb") or "")
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
        r = QRectF(2, 2, self.W - 4, self.H - 4)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.save()
        p.setClipPath(path)
        self._draw_cover(p, r, 0.5)
        g = QLinearGradient(0, r.top(), 0, r.top() + 60)
        g.setColorAt(0, QColor(8, 9, 14, 160))
        g.setColorAt(1, QColor(8, 9, 14, 0))
        p.fillRect(r, g)
        p.restore()
        if self._hover:
            p.setPen(QPen(QColor(self.color), 2.5))
        else:
            p.setPen(QColor(255, 255, 255, 34))
        p.drawPath(path)
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(10)
        p.setFont(f)
        chips = [x for x in (self.badge, KIND_LABEL.get(self.item.get("kind"), "")) if x]
        x = 12
        for i, c in enumerate(chips):
            tw = p.fontMetrics().horizontalAdvance(c) + 14
            rr = QRectF(x, 12, tw, 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(GOLD) if i == 0 and self.badge else QColor(8, 9, 14, 210))
            p.drawRoundedRect(rr, 7, 7)
            p.setPen(QColor("#0b0d12") if i == 0 and self.badge else QColor("#e8eaf2"))
            p.drawText(rr, Qt.AlignmentFlag.AlignCenter, c)
            x += tw + 6
        if self.hint:
            f.setPixelSize(11)
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, 170))
            p.drawText(QRectF(12, self.H - 30, 40, 20), Qt.AlignmentFlag.AlignLeft, self.hint)
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(QColor("#f4f5fa"))
        title = song_title(self.item)
        p.drawText(QRectF(2, self.H + 6, self.W - 4, 20), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, self.W - 4))
        f.setBold(False)
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(QColor("#8c93ad"))
        p.drawText(QRectF(2, self.H + 28, self.W - 4, 20), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.item.get("source") or "", Qt.TextElideMode.ElideRight, self.W - 4))
        p.end()


class SongRankDialog(QDialog):
    """Place a song in its list. After exec(): self.position or 0."""

    def __init__(self, item: Dict, lst: str, parent=None):
        super().__init__(parent)
        from ui.music_actions import MusicHub
        self.lib = MusicLibrary(MusicHub.get().db)
        self.item = item
        self.lst = lst
        self.position = 0
        self.color = LIST_COLOR.get(lst, GOLD)
        self.rerank = bool(self.lib.rank_of(item["id"], lst))
        others = [s for s in self.lib.ranked(lst) if s["id"] != item["id"]]
        self._by = {s["id"]: s for s in others}
        self.session = InsertionSession([s["id"] for s in others])
        self.setWindowTitle("Rank a song")
        self.setObjectName("hallDialog")
        self.setMinimumWidth(720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 24, 30, 22)
        lay.setSpacing(6)
        k = QLabel(("RE-RANK · " if self.rerank else "RANKING · ") + LISTS[lst].upper())
        k.setObjectName("hallKicker")
        k.setStyleSheet(f"color:{self.color};")
        k.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(k)
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
        dl.setSpacing(16)
        dl.addStretch()
        self.left = SongCard(300, self.color, "←")
        self.left.set_item(item, "NEW" if not self.rerank else "RE-RANKING")
        self.left.chosen.connect(lambda: self._answer("new"))
        self.left.listen.connect(lambda: play([self.item], 0, self, self.item.get("source") or "Music"))
        dl.addWidget(self.left)
        vs = QLabel("vs")
        vs.setObjectName("hallVs")
        dl.addWidget(vs, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.right = SongCard(300, self.color, "→")
        self.right.chosen.connect(lambda: self._answer("existing"))
        self.right.listen.connect(lambda: play([self.right.item], 0, self, self.right.item.get("source") or "Music"))
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
        lay.addSpacing(12)
        btns = QHBoxLayout()
        self.undo_btn = self._btn("↶  Undo", self._undo)
        self.tie_btn = self._btn("Too close to call", lambda: self._answer("tie"))
        self.skip_btn = self._btn("Skip", lambda: self._answer("skip"))
        self.cancel_btn = self._btn("Cancel", self.reject)
        self.ok_btn = self._btn("Done", self.accept, primary=True)
        btns.addWidget(self.undo_btn)
        btns.addStretch()
        for b in (self.tie_btn, self.skip_btn, self.cancel_btn, self.ok_btn):
            btns.addWidget(b)
        lay.addLayout(btns)
        hint = QLabel("Click a card to choose  ·  ▶ Listen to hear it first  ·  ← → Space S Backspace")
        hint.setObjectName("hallHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(hint)
        self._old = self.lib.rank_of(item["id"], lst) or None
        self._refresh()

    def _btn(self, text, cb, primary=False):
        b = QPushButton(text)
        b.setObjectName("hallPrimary" if primary else "hallGhost")
        if primary:
            b.setStyleSheet(f"QPushButton#hallPrimary{{background:{self.color};}}")
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setAutoDefault(False)
        b.clicked.connect(cb)
        return b

    def _refresh(self):
        q = None if self.session.done else self.session.question()
        if q is None:
            return self._finish()
        s = self._by[q]
        self.right.set_item(s, f"#{s.get('rank')}")
        left = self.session.estimate()
        n = self.session.asked + 1
        self.progress.setText(f"Question {n}  ·  about {left} to go" if left > 1 else f"Question {n}  ·  last one")
        self.undo_btn.setEnabled(bool(self.session._stack))
        self.ok_btn.hide()
        self.cancel_btn.show()

    def _answer(self, choice):
        if self.pages.currentIndex() != 0:
            return
        self.session.answer(choice)
        self._refresh()

    def _undo(self):
        if self.pages.currentIndex() == 1:
            if self.rerank and self._old:
                self.lib.move(self.item["id"], self.lst, self._old)
            elif not self.rerank:
                self.lib.unrank(self.item["id"], self.lst)
            self.position = 0
            self.pages.setCurrentIndex(0)
            self.tie_btn.show()
            self.skip_btn.show()
        self.session.undo()
        self._refresh()

    def _finish(self):
        pos = self.session.position
        self.position = self.lib.insert_at(self.item, self.lst, pos)
        n = len(self.lib.ranked(self.lst))
        self.done_rank.setText(f"#{self.position}")
        self.done_rank.setStyleSheet(f"color:{GOLD if self.position <= 3 else self.color};")
        name = song_title(self.item)
        self.done_text.setText(f"“{name}” takes #{self.position} of {n} in your {LISTS[self.lst]}."
                               if n > 1 else f"“{name}” opens your {LISTS[self.lst]} ranking.")
        self.heading.setText("Ranked")
        self.progress.setText(f"after {self.session.asked} question{'s' if self.session.asked != 1 else ''}"
                              if self.session.asked else "")
        self.pages.setCurrentIndex(1)
        for b in (self.tie_btn, self.skip_btn, self.cancel_btn):
            b.hide()
        self.ok_btn.show()
        self.ok_btn.setFocus()
        self.undo_btn.setEnabled(bool(self.session._stack))
        from ui.music_actions import MusicHub
        MusicHub.get().ranks_changed.emit()

    def keyPressEvent(self, e):
        k = e.key()
        if self.pages.currentIndex() == 0:
            m = {Qt.Key.Key_Left: "new", Qt.Key.Key_Right: "existing", Qt.Key.Key_Space: "tie", Qt.Key.Key_S: "skip"}
            if k in m:
                return self._answer(m[k])
        if k == Qt.Key.Key_Backspace and self.undo_btn.isEnabled():
            return self._undo()
        super().keyPressEvent(e)

    def exec(self):
        if self.session.done:
            QTimer.singleShot(0, self._refresh)
        return super().exec()


class _SongRow(QWidget, _Img):
    """A found song: thumb, title, channel; ▶ listen, ♥, choose."""
    chosen = pyqtSignal(dict)
    listen = pyqtSignal(dict)

    def __init__(self, item: Dict, action: str = "Rank it", parent=None):
        super().__init__(parent)
        from ui.music_actions import LikeButton
        self.item = item
        self.setObjectName("songRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 6, 10, 6)
        h.setSpacing(12)
        self.thumb = QLabel()
        self.thumb.setFixedSize(112, 63)
        h.addWidget(self.thumb)
        self._load_img(item.get("thumb") or "")
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(song_title(item))
        t.setObjectName("songRowTitle")
        t.setWordWrap(True)
        col.addWidget(t)
        sub = QLabel("  ·  ".join(x for x in (KIND_LABEL.get(item.get("kind"), ""),
                                              (item.get("title") or "").split("  ·  ")[1]
                                              if "  ·  " in (item.get("title") or "") else item.get("channel") or "")
                                  if x))
        sub.setObjectName("homeDate")
        col.addWidget(sub)
        h.addLayout(col, 1)
        lb = QPushButton("▶")
        lb.setObjectName("musicAction")
        lb.setToolTip("Listen")
        lb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        lb.clicked.connect(lambda: self.listen.emit(self.item))
        h.addWidget(lb)
        like = LikeButton(compact=True)
        like.set_item(item)
        h.addWidget(like)
        go = QPushButton(action)
        go.setObjectName("hallPrimary")
        go.setStyleSheet(f"QPushButton#hallPrimary{{background:{GOLD};}}")
        go.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        go.clicked.connect(lambda: self.chosen.emit(self.item))
        h.addWidget(go)

    def _on_img(self, result):
        try:
            from PyQt6.QtGui import QPixmap
            _k, _s, path = result
            if path:
                pm = QPixmap(str(path)).scaled(112, 63, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                              Qt.TransformationMode.SmoothTransformation)
                self.thumb.setPixmap(pm.copy((pm.width() - 112) // 2, (pm.height() - 63) // 2, 112, 63))
        except RuntimeError:
            pass


class SongFinder(QDialog):
    """Search any anime / show / movie, pick one of its songs.
    After exec(): self.chosen (song dict) and self.lst."""

    def __init__(self, db, lst: str = "op", parent=None, query: str = ""):
        super().__init__(parent)
        self.db = db
        self.lst = lst
        self.chosen: Optional[Dict] = None
        self.kind = "anime"
        self._tok = 0
        self.setWindowTitle("Find a song")
        self.setObjectName("hallDialog")
        self.resize(900, 700)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 18)
        lay.setSpacing(10)
        self.heading = QLabel("Find a song")
        self.heading.setObjectName("hallAsk")
        lay.addWidget(self.heading)
        sub = QLabel("Search an anime, show or movie — then pick its opening, ending or a soundtrack track.")
        sub.setObjectName("hallAskSub")
        lay.addWidget(sub)
        top = QHBoxLayout()
        self.list_btns: Dict[str, QPushButton] = {}
        for k, label in LISTS.items():
            b = QPushButton(label.replace("&", "&&"))
            b.setObjectName("hallTab")
            b.setCheckable(True)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _=False, k=k: self._set_list(k))
            self.list_btns[k] = b
            top.addWidget(b)
        top.addStretch()
        self.kind_btns: Dict[str, QPushButton] = {}
        for k, label in (("anime", "Anime"), ("tv", "TV"), ("movie", "Movies")):
            b = QPushButton(label)
            b.setObjectName("hallSeg")
            b.setCheckable(True)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _=False, k=k: self._set_kind(k))
            self.kind_btns[k] = b
            top.addWidget(b)
        lay.addLayout(top)
        self.search = QLineEdit(query)
        self.search.setObjectName("homeSearch")
        self.search.setPlaceholderText("e.g. Bleach, Frieren, Arcane, Interstellar…")
        self.search.setFixedHeight(40)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._search)
        self.search.textChanged.connect(lambda _t: self._timer.start(350))
        lay.addWidget(self.search)
        self.pages = QStackedWidget()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.pages.addWidget(self.scroll)
        self.songs_scroll = QScrollArea()
        self.songs_scroll.setWidgetResizable(True)
        self.songs_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.pages.addWidget(self.songs_scroll)
        lay.addWidget(self.pages, 1)
        foot = QHBoxLayout()
        self.back = QPushButton("←  Back")
        self.back.setObjectName("hallGhost")
        self.back.clicked.connect(lambda: (self.pages.setCurrentIndex(0), self.back.hide()))
        self.back.hide()
        foot.addWidget(self.back)
        self.status = QLabel()
        self.status.setObjectName("hallAskSub")
        foot.addWidget(self.status, 1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("hallGhost")
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        for b in (self.back, cancel):
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setAutoDefault(False)
        lay.addLayout(foot)
        self._set_list(lst)
        self._set_kind("anime")
        self.search.setFocus()

    def _set_list(self, k: str):
        self.lst = k
        for kk, b in self.list_btns.items():
            b.setChecked(kk == k)
            c = LIST_COLOR[kk]
            b.setStyleSheet(f"QPushButton#hallTab:checked{{color:#0b0d12;background:{c};border-color:{c};}}")
        if self.pages.currentIndex() == 1 and getattr(self, "_title_row", None):
            self._open_title(self._title_row)

    def _set_kind(self, k: str):
        self.kind = k
        for kk, b in self.kind_btns.items():
            b.setChecked(kk == k)
        self._search()

    def _search(self):
        q = self.search.text().strip()
        self.pages.setCurrentIndex(0)
        self.back.hide()
        lib = [r for r in self.db.get_all_anime(media_type=self.kind, sort_by="title")
               if r.get("watch_status") != "planned"
               and (not q or q.lower() in (r.get("english_title") or "").lower()
                    or q.lower() in (r.get("romaji_title") or "").lower())]
        self._render_titles(lib[:60], [])
        if len(q) < 2:
            self.status.setText("Your library is shown — type to search anything.")
            return
        self.status.setText(f"Searching for “{q}”…")
        self._tok += 1
        tok, kind = self._tok, self.kind
        from workers.workers import Worker, run_worker

        def job():
            from core.quick_add import search
            return search(kind, q)

        w = Worker(job)
        w.signals.result.connect(lambda hits, t=tok, l=lib[:60]: self._online(hits, t, l))
        w.signals.error.connect(lambda _e: self.status.setText("Couldn't search online."))
        run_worker(w)

    def _online(self, hits, tok, lib):
        from PyQt6 import sip
        if sip.isdeleted(self) or tok != self._tok:
            return
        have = {(r.get("anilist_id") if self.kind == "anime" else r.get("tmdb_id")) for r in lib}
        online = [h for h in (hits or []) if h.get("provider_id") not in have][:30]
        self.status.setText("")
        self._render_titles(lib, online)

    def _render_titles(self, lib: List[Dict], online: List[Dict]):
        host = QWidget()
        v = QVBoxLayout(host)
        v.setSpacing(10)
        v.setContentsMargins(0, 0, 0, 0)
        for label, rows, is_online in (("IN YOUR LIBRARY", lib, False), ("EVERYTHING ELSE", online, True)):
            if not rows:
                continue
            h = QLabel(label)
            h.setObjectName("hallKicker")
            h.setStyleSheet(f"color:{GOLD};")
            v.addWidget(h)
            grid = QWidget()
            flow = FlowLayout(grid, 12, 12)
            for r in rows:
                row = r if not is_online else {
                    "id": 0, "_online": True, "media_type": self.kind, "cover_url": r.get("poster_url") or "",
                    "english_title": r.get("title") or "", "romaji_title": r.get("original_title") or r.get("title"),
                    "season_year": r.get("year") or "",
                    ("anilist_id" if self.kind == "anime" else "tmdb_id"): r.get("provider_id")}
                t = _PickTile(row, WING_COLORS.get(self.kind, GOLD))
                t.picked.connect(lambda _i, row=row: self._open_title(row))
                flow.addWidget(t)
            v.addWidget(grid)
        v.addStretch()
        self.scroll.setWidget(host)

    def _tab(self) -> Optional[str]:
        media = self.kind
        if self.lst == "op":
            return "op" if media == "anime" else ("intro" if media == "tv" else None)
        if self.lst == "ed":
            return "ed" if media == "anime" else None
        return "ost"

    def _open_title(self, row: Dict):
        self._title_row = row
        name = row.get("english_title") or row.get("romaji_title") or ""
        tab = self._tab()
        self.pages.setCurrentIndex(1)
        self.back.show()
        self._tok += 1
        self.status.setText("")
        if not tab:
            self._render_songs([], f"{LISTS[self.lst]} aren't a thing for {'movies' if self.kind == 'movie' else 'TV'} "
                                   "— try Soundtracks.")
            return
        self._render_songs(None, f"Finding {LISTS[self.lst].lower()} for {name}…")
        self._tok += 1
        tok = self._tok
        from workers.workers import Worker, run_worker

        def job():
            from core.music import find
            return find(row, tab)

        w = Worker(job)
        w.signals.result.connect(lambda items, t=tok: t == self._tok and self._render_songs(
            items, f"Nothing found for {name}."))
        w.signals.error.connect(lambda _e: self._render_songs([], "Couldn't search right now."))
        run_worker(w)

    def _render_songs(self, items, empty: str):
        from PyQt6 import sip
        if sip.isdeleted(self):
            return
        host = QWidget()
        v = QVBoxLayout(host)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        if not items:
            e = QLabel(empty)
            e.setObjectName("homeEmpty")
            e.setWordWrap(True)
            v.addWidget(e)
        for it in items or []:
            r = _SongRow(it)
            r.listen.connect(lambda s, all_=items: play(all_, all_.index(s), self, s.get("source") or "Music"))
            r.chosen.connect(self._pick)
            v.addWidget(r)
        v.addStretch()
        self.songs_scroll.setWidget(host)

    def _pick(self, item: Dict):
        self.chosen = item
        self.accept()


def rank_flow(db, parent, lst: Optional[str] = None, item: Optional[Dict] = None) -> int:
    """Find (unless given) then rank. Returns the rank or 0."""
    if item is None:
        f = SongFinder(db, lst or "op", parent)
        if not f.exec() or not f.chosen:
            return 0
        item, lst = f.chosen, f.lst
    lst = lst or list_for(item.get("kind") or "")
    d = SongRankDialog(item, lst, parent)
    d.exec()
    return d.position
