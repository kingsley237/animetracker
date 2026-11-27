"""
Raikō - the Music page (sidebar ♪, Ctrl+M).

  ♥ Liked      every opening / ending / intro / soundtrack you liked:
               Play all, Shuffle, filter by kind, play from any row,
               ♥ / ⬇ / rank on each row. Newest first.
  🏆 Rankings  Openings & intros · Endings · Soundtracks - ranked by
               "which do you love more?", drag to fine-tune.
  ⬇ Downloads  what you saved (and what's downloading), Show in folder.

Search box at the top: find any anime / show / movie's songs right away.
"""
from __future__ import annotations

import os
import random
from datetime import datetime
from typing import Dict

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidgetItem, QMenu, QProgressBar, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from core.music_library import KIND_LABEL, LISTS, MusicLibrary, list_for, song_title
from ui.hall_rank import GOLD
from ui.music_actions import LikeButton, MusicHub, download_menu, reveal
from ui.music_rank import LIST_COLOR, SongFinder, play, rank_flow
from workers.workers import ImageWorker, run_worker

KIND_COLOR = {"opening": "#8b7bff", "intro": "#8b7bff", "ending": "#38bdf8", "soundtrack": "#f5c451"}


def _clear(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            _clear(it.layout())


class _Thumb(QLabel):
    def __init__(self, url: str, w: int = 96, h: int = 54, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, h)
        self.setObjectName("musicThumb")
        self._w, self._h = w, h
        if url:
            wk = ImageWorker(url, url)
            wk.signals.result.connect(self._on)
            run_worker(wk)

    def _on(self, res):
        try:
            _k, _s, path = res
            if path:
                pm = QPixmap(str(path)).scaled(self._w, self._h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                              Qt.TransformationMode.SmoothTransformation)
                self.setPixmap(pm.copy((pm.width() - self._w) // 2, (pm.height() - self._h) // 2, self._w, self._h))
        except RuntimeError:
            pass


class _Row(QFrame):
    """One song: # · thumb · title / source + kind · actions."""
    play = pyqtSignal()

    def __init__(self, n: int, item: Dict, page: "MusicPage", rank_badge: str = "", parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("musicRow")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(12)
        num = QLabel(str(n))
        num.setObjectName("musicRowNum")
        num.setFixedWidth(28)
        num.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if rank_badge:
            num.setStyleSheet(f"color:{GOLD};" if n <= 3 else "")
        h.addWidget(num)
        h.addWidget(_Thumb(item.get("thumb") or ""))
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(song_title(item))
        t.setObjectName("musicRowTitle")
        col.addWidget(t)
        kind = item.get("kind") or ""
        sub = QLabel(f"<span style='color:{KIND_COLOR.get(kind, '#9da5c0')};font-weight:800'>"
                     f"{KIND_LABEL.get(kind, '').upper()}</span>&nbsp;&nbsp;{item.get('source') or ''}")
        sub.setObjectName("musicRowSub")
        col.addWidget(sub)
        h.addLayout(col, 1)
        lib = page.lib
        if not rank_badge:
            r = lib.rank_of(item["id"], list_for(kind))
            if r:
                b = QLabel(f"#{r}")
                b.setObjectName("musicRankBadge")
                b.setToolTip(f"#{r} in your {LISTS[list_for(kind)]}")
                h.addWidget(b, alignment=Qt.AlignmentFlag.AlignVCenter)
        when = item.get("liked_at")
        if when:
            d = datetime.fromtimestamp(when)
            w = QLabel(d.strftime("%b ") + str(d.day))
            w.setObjectName("musicRowWhen")
            h.addWidget(w)
        for text, tip, cb in (("▶", "Play from here", self.play.emit),):
            b = QPushButton(text)
            b.setObjectName("musicAction")
            b.setToolTip(tip)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(cb)
            h.addWidget(b)
        like = LikeButton(compact=True)
        like.set_item(item)
        h.addWidget(like)
        dl = QPushButton("⬇")
        dl.setObjectName("musicAction")
        dl.setToolTip("Download as audio or video")
        dl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        dl.clicked.connect(lambda: download_menu(item, dl))
        h.addWidget(dl)
        more = QPushButton("⋯")
        more.setObjectName("musicAction")
        more.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        more.clicked.connect(lambda: page._row_menu(item, more))
        h.addWidget(more)

    def mouseDoubleClickEvent(self, e):
        self.play.emit()


class MusicPage(QWidget):
    open_title = pyqtSignal(int)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.lib = MusicLibrary(db)
        self.tab = "liked"
        self.filter = ""
        self.rank_list = "op"
        self.setObjectName("contentArea")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)
        content = QWidget()
        content.setObjectName("contentArea")
        self.scroll.setWidget(content)
        self.lay = QVBoxLayout(content)
        self.lay.setContentsMargins(40, 30, 40, 40)
        self.lay.setSpacing(14)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        k = QLabel("RAIKŌ")
        k.setObjectName("hallKicker")
        k.setStyleSheet("color:#8b7bff;")
        col.addWidget(k)
        t = QLabel("Music")
        t.setObjectName("hallTitle")
        col.addWidget(t)
        self.sub = QLabel()
        self.sub.setObjectName("homeDate")
        col.addWidget(self.sub)
        head.addLayout(col)
        head.addStretch()
        self.search = QLineEdit()
        self.search.setObjectName("homeSearch")
        self.search.setPlaceholderText("Find a song — search any anime, show or movie…")
        self.search.setFixedSize(360, 40)
        self.search.returnPressed.connect(self._find)
        head.addWidget(self.search, alignment=Qt.AlignmentFlag.AlignBottom)
        self.lay.addLayout(head)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.tab_btns: Dict[str, QPushButton] = {}
        for key, label in (("liked", "♥  Liked"), ("ranks", "🏆  Rankings"), ("downloads", "⬇  Downloads")):
            b = QPushButton(label)
            b.setObjectName("hallTab")
            b.setCheckable(True)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _=False, k=key: self.set_tab(k))
            self.tab_btns[key] = b
            bar.addWidget(b)
        bar.addStretch()
        self.lay.addSpacing(6)
        self.lay.addLayout(bar)
        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        self.lay.addLayout(self.body)
        self.lay.addStretch()

        hub = MusicHub.get()
        hub.likes_changed.connect(self._changed)
        hub.ranks_changed.connect(self._changed)
        hub.downloads_changed.connect(self._changed)
        hub.progress.connect(self._on_progress)
        self._bars: Dict[str, QProgressBar] = {}

    # ── state ────────────────────────────────────────────────────────────────

    def load(self):
        n = self.lib.count()
        r = sum(len(self.lib.ranked(k)) for k in LISTS)
        self.sub.setText(f"{n} liked  ·  {r} ranked  ·  your openings, endings & soundtracks"
                         if n or r else "Your openings, endings & soundtracks — like them anywhere they play.")
        for k, b in self.tab_btns.items():
            b.setChecked(k == self.tab)
            b.setStyleSheet("QPushButton#hallTab:checked{color:#0b0d12;background:#8b7bff;border-color:#8b7bff;}")
        _clear(self.body)
        self._bars = {}
        getattr(self, "_view_" + self.tab)()

    def set_tab(self, key: str):
        self.tab = key
        self.load()

    def _changed(self):
        try:
            if self.isVisible():
                self.load()
        except RuntimeError:
            pass

    def focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    # ── Liked ────────────────────────────────────────────────────────────────

    def _view_liked(self):
        items = self.lib.liked(self.filter or None)
        top = QHBoxLayout()
        top.setSpacing(8)
        playall = QPushButton("▶  Play all")
        playall.setObjectName("hallPrimary")
        playall.setStyleSheet("QPushButton#hallPrimary{background:#8b7bff;}")
        shuffle = QPushButton("⤮  Shuffle")
        shuffle.setObjectName("hallGhost")
        for b in (playall, shuffle):
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setEnabled(bool(items))
        playall.clicked.connect(lambda: play(items, 0, self, "Liked music"))
        shuffle.clicked.connect(lambda: play(random.sample(items, len(items)), 0, self, "Liked music · shuffle"))
        top.addWidget(playall)
        top.addWidget(shuffle)
        top.addSpacing(14)
        for key, label in (("", "All"), ("op", "Openings && intros"), ("ending", "Endings"),
                           ("soundtrack", "Soundtracks")):
            c = QPushButton(label)
            c.setObjectName("hallSeg")
            c.setCheckable(True)
            c.setChecked(self.filter == key)
            c.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            c.clicked.connect(lambda _=False, k=key: (setattr(self, "filter", k), self.load()))
            top.addWidget(c)
        top.addStretch()
        self.body.addLayout(top)
        self.body.addSpacing(6)
        if not items:
            self._empty("Nothing liked yet" if not self.filter else "Nothing liked here yet",
                        "Tap ♡ on any opening, ending or soundtrack — in a title's Videos & music card, while it "
                        "plays, or after searching above — and it lands here, ready to play in one click.")
            return
        for i, it in enumerate(items):
            row = _Row(i + 1, it, self)
            row.play.connect(lambda i=i: play(items, i, self, "Liked music"))
            self.body.addWidget(row)

    def _empty(self, title: str, text: str):
        box = QFrame()
        box.setObjectName("hallEmpty")
        v = QVBoxLayout(box)
        v.setContentsMargins(30, 30, 30, 30)
        v.setSpacing(8)
        t = QLabel(title)
        t.setObjectName("homeSection")
        t.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(t)
        s = QLabel(text)
        s.setObjectName("homeDate")
        s.setWordWrap(True)
        s.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(s)
        b = QPushButton("Find a song")
        b.setObjectName("hallGhost")
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.clicked.connect(self._find)
        v.addWidget(b, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.body.addWidget(box)

    # ── Rankings ─────────────────────────────────────────────────────────────

    def _view_ranks(self):
        top = QHBoxLayout()
        top.setSpacing(6)
        for key, label in LISTS.items():
            c = QPushButton(f"{label.replace('&', '&&')}  {len(self.lib.ranked(key))}")
            c.setObjectName("hallTab")
            c.setCheckable(True)
            c.setChecked(self.rank_list == key)
            col = LIST_COLOR[key]
            c.setStyleSheet(f"QPushButton#hallTab:checked{{color:#0b0d12;background:{col};border-color:{col};}}")
            c.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            c.clicked.connect(lambda _=False, k=key: (setattr(self, "rank_list", k), self.load()))
            top.addWidget(c)
        top.addStretch()
        add = QPushButton("+  Rank a song")
        add.setObjectName("hallPrimary")
        add.setStyleSheet(f"QPushButton#hallPrimary{{background:{GOLD};}}")
        add.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add.clicked.connect(lambda: rank_flow(self.db, self, self.rank_list))
        top.addWidget(add)
        self.body.addLayout(top)
        items = self.lib.ranked(self.rank_list)
        if not items:
            self._empty(f"Rank your {LISTS[self.rank_list].lower()}",
                        "Search an anime, show or movie, pick a song, and answer a few “which do you love more?” "
                        "questions — with a ▶ preview on both sides — to find its exact place.")
            return
        hint = QLabel("Drag to reorder  ·  click ▶ to play from there  ·  ⋯ to re-rank or remove")
        hint.setObjectName("homeDate")
        self.body.addWidget(hint)
        from ui.hall_page import _RankList
        lst = _RankList()
        lst.setObjectName("musicRankList")
        for i, it in enumerate(items):
            qi = QListWidgetItem()
            qi.setData(Qt.ItemDataRole.UserRole, it["id"])
            qi.setSizeHint(QSize(100, 68))
            lst.addItem(qi)
            row = _Row(it["rank"], it, self, rank_badge="yes")
            row.play.connect(lambda i=i: play(items, i, self, LISTS[self.rank_list]))
            lst.setItemWidget(qi, row)
        lst.fit()
        lst.moved.connect(lambda vid, rank: (self.lib.move(vid, self.rank_list, rank), MusicHub.get().ranks_changed.emit()))
        self.body.addWidget(lst)

    # ── Downloads ────────────────────────────────────────────────────────────

    def _view_downloads(self):
        hub = MusicHub.get()
        top = QHBoxLayout()
        from core.downloader import downloads_dir
        folder = QPushButton("Open Downloads folder")
        folder.setObjectName("hallGhost")
        folder.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        folder.clicked.connect(lambda: os.startfile(str(downloads_dir())))
        note = QLabel("Downloads are for personal use. Audio is MP3, video is MP4 up to 1080p.")
        note.setObjectName("homeDate")
        top.addWidget(note, 1)
        top.addWidget(folder)
        self.body.addLayout(top)
        for key, frac in hub.active.items():
            vid, mode = key.split(":")
            item = hub._items.get(key, {"id": vid})
            fr = QFrame()
            fr.setObjectName("musicRow")
            h = QHBoxLayout(fr)
            h.setContentsMargins(12, 10, 12, 10)
            lab = QLabel(f"{'♪ Audio' if mode == 'audio' else '▶ Video'}  ·  {song_title(item) or vid}")
            lab.setObjectName("musicRowTitle")
            h.addWidget(lab, 1)
            bar = QProgressBar()
            bar.setObjectName("musicProgress")
            bar.setRange(0, 100)
            bar.setValue(int(frac * 100))
            bar.setFixedWidth(220)
            bar.setTextVisible(False)
            self._bars[key] = bar
            h.addWidget(bar)
            self.body.addWidget(fr)
        done = self.lib.downloads()
        if not done and not hub.active:
            self._empty("No downloads yet", "Use ⬇ on any opening, ending or soundtrack to save it as audio (MP3) "
                                            "or video (MP4) to your Downloads folder.")
            return
        for d in done:
            fr = QFrame()
            fr.setObjectName("musicRow")
            h = QHBoxLayout(fr)
            h.setContentsMargins(12, 8, 12, 8)
            h.setSpacing(12)
            chip = QLabel("MP3" if d["mode"] == "audio" else "MP4")
            chip.setObjectName("musicRankBadge")
            h.addWidget(chip, alignment=Qt.AlignmentFlag.AlignVCenter)
            col = QVBoxLayout()
            col.setSpacing(2)
            t = QLabel(d["title"] or os.path.basename(d["path"]))
            t.setObjectName("musicRowTitle")
            col.addWidget(t)
            exists = os.path.exists(d["path"])
            s = QLabel(f"{d['source'] or ''}  ·  {os.path.basename(d['path'])}" + ("" if exists else "  ·  moved or deleted"))
            s.setObjectName("musicRowSub")
            col.addWidget(s)
            h.addLayout(col, 1)
            for text, cb, ok in (("▶  Play", lambda p=d["path"]: os.startfile(p), exists),
                                 ("Show in folder", lambda p=d["path"]: reveal(p), True),
                                 ("✕", lambda i=d["id"]: (self.lib.forget_download(i), self.load()), True)):
                b = QPushButton(text)
                b.setObjectName("musicAction")
                b.setEnabled(ok)
                b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                b.clicked.connect(cb)
                if text == "✕":
                    b.setToolTip("Remove from this list (the file stays)")
                h.addWidget(b)
            self.body.addWidget(fr)

    def _on_progress(self, vid, mode, frac, _text):
        bar = self._bars.get(f"{vid}:{mode}")
        if bar is not None:
            try:
                bar.setValue(int(frac * 100))
            except RuntimeError:
                pass

    # ── actions ──────────────────────────────────────────────────────────────

    def _find(self):
        q = self.search.text().strip()
        f = SongFinder(self.db, self.rank_list if self.tab == "ranks" else "op", self, query=q)
        f.heading.setText("Find a song")
        f.exec()
        if f.chosen:
            rank_flow(self.db, self, f.lst, f.chosen)
        self.load()

    def _row_menu(self, item: Dict, anchor):
        m = QMenu(self)
        lst = list_for(item.get("kind") or "")
        r = self.lib.rank_of(item["id"], lst)
        m.addAction(("Re-rank" if r else "Rank it") + f" in {LISTS[lst]}", lambda: rank_flow(self.db, self, lst, item))
        if r:
            m.addAction(f"Remove from {LISTS[lst]}", lambda: (self.lib.unrank(item["id"], lst),
                                                            MusicHub.get().ranks_changed.emit()))
        if item.get("lib_id") and self.db.get_anime_by_id(item["lib_id"]):
            m.addAction(f"Open {item.get('source') or 'title'}", lambda: self.open_title.emit(item["lib_id"]))
        m.addSeparator()
        import webbrowser
        m.addAction("Open on YouTube ↗", lambda: webbrowser.open(f"https://www.youtube.com/watch?v={item['id']}"))
        m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
