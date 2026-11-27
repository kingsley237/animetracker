"""
Raikō - Honours: the awards wall in the Hall of Fame.

Each award card shows the category, the winner (art, name, your reason) and
up to two runners-up. Pickers know what each category holds: groups for
trilogies/duologies (found from TMDB collections and AniList sequel chains,
or assembled by hand), seasons, episodes, characters, themes, titles, names.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QPixmap
from ui.theme import QColor  # noqa: E402,F811  (theme-aware colours)
from PyQt6.QtWidgets import (
    QCompleter, QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from core.honours import PLACES, TEMPLATES, Honours
from ui.hall_rank import GOLD, WING_COLORS, OnlineFinder, _PickTile, _title, _year
from ui.layout_helpers import FlowLayout
from workers.workers import ImageWorker, Worker, run_worker

STARTER = ["trilogy", "duology", "finale", "villain", "soundtrack", "year"]


class _Art(QWidget):
    """One image, or a fan of up to three posters for a group."""

    def __init__(self, urls: List[str], w: int, h: int, fan: bool = False, parent=None):
        super().__init__(parent)
        self.urls = [u for u in urls if u][:3]
        self.fan = fan and len(self.urls) > 1
        self.pix: Dict[str, QPixmap] = {}
        self.setFixedSize(w, h)
        for u in self.urls:
            wk = ImageWorker(u, u)
            wk.signals.result.connect(self._on_img)
            run_worker(wk)

    def _on_img(self, res):
        try:
            key, _s, path = res
            if path:
                self.pix[key] = QPixmap(str(path))
                self.update()
        except RuntimeError:
            pass

    def _draw(self, p: QPainter, url: str, r: QRectF, rad: float):
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)
        p.save()
        p.setClipPath(path)
        pm = self.pix.get(url)
        if pm and not pm.isNull():
            sc = pm.scaled(int(r.width()), int(r.height()), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int(r.x()), int(r.y()), sc, (sc.width() - int(r.width())) // 2,
                         (sc.height() - int(r.height())) // 3, int(r.width()), int(r.height()))
        else:
            p.fillRect(r, QColor("#161a2a"))
        p.restore()
        p.setPen(QPen(QColor(8, 9, 14, 220), 2))
        p.drawPath(path)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        W, H = self.width(), self.height()
        if not self.urls:
            r = QRectF(1, 1, W - 2, H - 2)
            p.setPen(QPen(QColor("#2a2f45"), 1))
            p.setBrush(QColor("#141724"))
            p.drawRoundedRect(r, 10, 10)
            f = QFont(self.font())
            f.setPixelSize(int(H * 0.3))
            p.setFont(f)
            p.setPen(QColor(GOLD))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "🏆")
        elif not self.fan:
            self._draw(p, self.urls[0], QRectF(1, 1, W - 2, H - 2), 10)
        else:
            n = len(self.urls)
            pw = W * (0.62 if n == 3 else 0.7)
            step = (W - pw) / (n - 1)
            for i in reversed(range(n)):
                inset = (n - 1 - i) * 0
                self._draw(p, self.urls[i], QRectF(i * step + 1, inset + (n - 1 - i) * 4 + 1, pw - 2,
                                                   H - (n - 1 - i) * 8 - 2), 9)
        p.end()


class _AwardCard(QFrame):
    pick = pyqtSignal(int, int)           # award id, place
    menu = pyqtSignal(int, int)           # award id, place (-1: the card)
    W = 420

    def __init__(self, award: Dict, parent=None):
        super().__init__(parent)
        self.award = award
        self.setObjectName("hallAward")
        self.setFixedWidth(self.W)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 16, 18)
        lay.setSpacing(10)
        top = QHBoxLayout()
        cat = QLabel(award["label"].upper())
        cat.setObjectName("hallAwardCat")
        top.addWidget(cat)
        top.addStretch()
        more = QPushButton("⋯")
        more.setObjectName("hallIcon")
        more.setFixedSize(28, 24)
        more.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        more.clicked.connect(lambda: self.menu.emit(award["id"], -1))
        top.addWidget(more)
        lay.addLayout(top)

        win = award["entries"][0]
        if win:
            row = QHBoxLayout()
            row.setSpacing(14)
            fan = win["kind"] == "group"
            urls = [p.get("poster") for p in (win.get("extra") or {}).get("parts", [])] if fan else [win["image"]]
            wide = win["kind"] == "episode"
            art = _Art(urls, 150 if wide else (118 if fan else 96), 96 if wide else 144, fan=fan)
            art.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            art.mousePressEvent = lambda e, a=award["id"]: self.menu.emit(a, 0)
            row.addWidget(art, alignment=Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(4)
            tag = QLabel("★  WINNER")
            tag.setObjectName("hallWinnerTag")
            col.addWidget(tag)
            name = QLabel(win["label"])
            name.setObjectName("hallAwardName")
            name.setWordWrap(True)
            col.addWidget(name)
            if win.get("sub"):
                s = QLabel(win["sub"])
                s.setObjectName("homeDate")
                s.setWordWrap(True)
                col.addWidget(s)
            if fan:
                parts = (win.get("extra") or {}).get("parts", [])
                pl = QLabel("  ·  ".join(f"{i}. {p['title']}" for i, p in enumerate(parts, 1)))
                pl.setObjectName("hallParts")
                pl.setWordWrap(True)
                col.addWidget(pl)
            rs = QLabel(f"“{win['reason']}”" if win.get("reason") else "Add why it won…")
            rs.setObjectName("hallReason" if win.get("reason") else "hallReasonEmpty")
            rs.setWordWrap(True)
            rs.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            rs.mousePressEvent = lambda e, a=award["id"]: self.menu.emit(a, 100)   # 100: edit reason
            col.addWidget(rs)
            col.addStretch()
            row.addLayout(col, 1)
            lay.addLayout(row)
        else:
            b = QPushButton("+   Choose the winner")
            b.setObjectName("hallPickEmpty")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setMinimumHeight(120)
            b.clicked.connect(lambda: self.pick.emit(award["id"], 0))
            lay.addWidget(b)

        if win:
            ru = QHBoxLayout()
            ru.setSpacing(8)
            for place in (1, 2):
                e = award["entries"][place]
                if e:
                    chip = QPushButton(f"{place + 1}.  {e['label']}")
                    chip.setObjectName("hallRunner")
                    chip.setToolTip(f"{PLACES[place]}: {e['label']}" + (f" — {e['sub']}" if e.get("sub") else ""))
                    chip.clicked.connect(lambda _=False, pl=place: self.menu.emit(award["id"], pl))
                elif award["entries"][place - 1]:
                    chip = QPushButton("+  Runner-up")
                    chip.setObjectName("hallRunnerAdd")
                    chip.clicked.connect(lambda _=False, pl=place: self.pick.emit(award["id"], pl))
                else:
                    continue
                chip.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                chip.setMaximumWidth(200)
                ru.addWidget(chip)
            ru.addStretch()
            lay.addLayout(ru)


class HonoursView(QWidget):
    changed = pyqtSignal()
    open_title = pyqtSignal(int)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.h = Honours(db)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        head = QHBoxLayout()
        sub = QLabel("Your own awards night — best trilogy, best villain, best finale… "
                     "a winner and up to two runners-up each.")
        sub.setObjectName("homeDate")
        sub.setWordWrap(True)
        head.addWidget(sub, 1)
        add = QPushButton("+  New award")
        add.setObjectName("hallGhost")
        add.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add.clicked.connect(lambda: self._new_menu(add))
        head.addWidget(add)
        lay.addLayout(head)
        cats = self.h.categories()
        if not cats:
            box = QFrame()
            box.setObjectName("hallEmpty")
            v = QVBoxLayout(box)
            v.setContentsMargins(30, 30, 30, 30)
            t = QLabel("Start your awards")
            t.setObjectName("homeSection")
            t.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            v.addWidget(t)
            s = QLabel("Add a starter set — Best trilogy, Best duology, Best finale, Best villain, Best soundtrack "
                       "and Best of this year — or create your own.")
            s.setObjectName("homeDate")
            s.setWordWrap(True)
            s.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            v.addWidget(s)
            b = QPushButton("Add the starter set")
            b.setObjectName("hallPrimary")
            b.setStyleSheet(f"QPushButton#hallPrimary{{background:{GOLD};}}")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(self._starter)
            v.addWidget(b, alignment=Qt.AlignmentFlag.AlignHCenter)
            lay.addWidget(box)
            return
        host = QWidget()
        flow = FlowLayout(host, 18, 18)
        for a in cats:
            c = _AwardCard(a)
            c.pick.connect(self._pick)
            c.menu.connect(self._menu)
            flow.addWidget(c)
        lay.addWidget(host)

    # ── categories ────────────────────────────────────────────────────────────

    def _starter(self):
        for k in STARTER:
            self.h.add_category(k)
        self.changed.emit()

    def _new_menu(self, anchor):
        m = QMenu(self)
        have = {a["key"] for a in self.h.categories()}
        fam = None
        for t in TEMPLATES:
            if t["family"] != fam:
                fam = t["family"]
                sm = m.addMenu(fam)
            label = t["label"].replace("{year}", "a year")
            act = sm.addAction(label + ("  ✓" if t["key"] in have else ""),
                               lambda k=t["key"]: self._add_template(k))
            act.setEnabled(t["key"] not in have or t["key"] == "year")
        m.addSeparator()
        m.addAction("Custom award…", self._custom)
        m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _add_template(self, key: str):
        label = None
        if key == "year":
            import time as _t
            y, ok = QInputDialog.getInt(self, "Best of a year", "Which year?", _t.localtime().tm_year, 1950, 2100)
            if not ok:
                return
            label = f"Best of {y}"
        self.h.add_category(key, label)
        self.changed.emit()

    def _custom(self):
        name, ok = QInputDialog.getText(self, "Custom award", "Award name (e.g. Best rivalry, Most rewatchable):")
        if not ok or not name.strip():
            return
        kinds = ["A title", "A group of titles (trilogy, saga…)", "An episode", "A character", "A name (studio, "
                 "director…)"]
        k, ok = QInputDialog.getItem(self, "Custom award", "What does it hold?", kinds, 0, False)
        if not ok:
            return
        kind = {0: "title", 1: "group", 2: "episode", 3: "character", 4: "name"}[kinds.index(k)]
        self.h.add_category(None, name, kind)
        self.changed.emit()

    def _menu(self, award_id: int, place: int):
        a = self.h.category(award_id)
        if not a:
            return
        if place == 100:
            return self._reason(award_id, 0)
        m = QMenu(self)
        if place == -1:
            m.addAction("Rename…", lambda: self._rename(a))
            m.addAction("Move earlier", lambda: (self.h.move_category(award_id, -1), self.changed.emit()))
            m.addAction("Move later", lambda: (self.h.move_category(award_id, 1), self.changed.emit()))
            m.addSeparator()
            m.addAction("Delete award", lambda: self._delete(a))
        else:
            e = a["entries"][place]
            m.addAction("Change…", lambda: self._pick(award_id, place))
            m.addAction("Write why…", lambda: self._reason(award_id, place))
            if place > 0:
                m.addAction("Make it the winner", lambda: (self.h.swap(award_id, 0, place), self.changed.emit()))
            if e and e.get("lib_ids"):
                if len(e["lib_ids"]) == 1:
                    m.addAction("Open details", lambda: self.open_title.emit(e["lib_ids"][0]))
                else:
                    sm = m.addMenu("Open details")
                    for p in (e.get("extra") or {}).get("parts", []):
                        if p.get("lib_id"):
                            sm.addAction(p["title"], lambda i=p["lib_id"]: self.open_title.emit(i))
            m.addSeparator()
            m.addAction("Remove", lambda: (self.h.clear_entry(award_id, place), self.changed.emit()))
        m.exec(QCursor.pos())

    def _rename(self, a):
        name, ok = QInputDialog.getText(self, "Rename award", "Award name:", text=a["label"])
        if ok and name.strip():
            self.h.rename(a["id"], name)
            self.changed.emit()

    def _delete(self, a):
        if QMessageBox.question(self, "Delete award", f"Delete “{a['label']}” and its winners?"
                                ) == QMessageBox.StandardButton.Yes:
            self.h.remove_category(a["id"])
            self.changed.emit()

    def _reason(self, award_id: int, place: int):
        e = self.h.entries(award_id)[place]
        if not e:
            return
        text, ok = QInputDialog.getMultiLineText(self, "Why it won", e["label"], e.get("reason") or "")
        if ok:
            self.h.set_reason(award_id, place, text)
            self.changed.emit()

    def _pick(self, award_id: int, place: int):
        a = self.h.category(award_id)
        dlg = PickDialog(self.h, a, self)
        if dlg.exec() and dlg.result_entry:
            self.h.set_entry(award_id, place, dlg.result_entry)
            self.changed.emit()


# ── pickers ───────────────────────────────────────────────────────────────────

class _GroupRow(QWidget):
    chosen = pyqtSignal(dict)

    def __init__(self, g: Dict, parent=None):
        super().__init__(parent)
        self.g = g
        self.setObjectName("hallGroupRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 8, 12, 8)
        h.setSpacing(14)
        h.addWidget(_Art([p.get("poster") for p in g["parts"]], 92, 92, fan=True))
        col = QVBoxLayout()
        col.setSpacing(3)
        n = QLabel(g["name"])
        n.setObjectName("hallAwardName")
        col.addWidget(n)
        seen = sum(1 for p in g["parts"] if p.get("watched"))
        word = {2: "Duology", 3: "Trilogy"}.get(len(g["parts"]), f"{len(g['parts'])} parts")
        color = WING_COLORS.get(g["media"], GOLD)
        meta = QLabel(f"<span style='color:{color}'>{word}</span>  ·  {seen} of {len(g['parts'])} watched"
                      f"  ·  via {g.get('source', '')}")
        meta.setObjectName("homeDate")
        col.addWidget(meta)
        parts = QLabel("  ·  ".join(f"{i}. {p['title']}" + (f" ({p['year']})" if p.get("year") else "")
                                    for i, p in enumerate(g["parts"], 1)))
        parts.setObjectName("hallParts")
        parts.setWordWrap(True)
        col.addWidget(parts)
        h.addLayout(col, 1)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(self.g)


class PickDialog(QDialog):
    """Choose what wins an award. After exec(): self.result_entry."""

    def __init__(self, h: Honours, award: Dict, parent=None):
        super().__init__(parent)
        self.h = h
        self.db = h.db
        self.award = award
        self.result_entry: Optional[Dict] = None
        self.setWindowTitle(award["label"])
        self.setObjectName("hallDialog")
        self.resize(860, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 20)
        lay.setSpacing(10)
        kick = QLabel(award["label"].upper())
        kick.setObjectName("hallKicker")
        kick.setStyleSheet(f"color:{GOLD};")
        lay.addWidget(kick)
        self.heading = QLabel()
        self.heading.setObjectName("hallAsk")
        lay.addWidget(self.heading)
        self.sub = QLabel()
        self.sub.setObjectName("hallAskSub")
        self.sub.setWordWrap(True)
        lay.addWidget(self.sub)
        self.top = QHBoxLayout()
        lay.addLayout(self.top)
        self.pages = QStackedWidget()
        lay.addWidget(self.pages, 1)
        foot = QHBoxLayout()
        self.back = QPushButton("←  Back")
        self.back.setObjectName("hallGhost")
        self.back.clicked.connect(lambda: self._go(0))
        foot.addWidget(self.back)
        foot.addStretch()
        self.extra_btn = QPushButton()
        self.extra_btn.setObjectName("hallGhost")
        self.extra_btn.hide()
        foot.addWidget(self.extra_btn)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("hallGhost")
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        for b in (self.back, self.extra_btn, cancel):
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setAutoDefault(False)
        lay.addLayout(foot)
        self.step2 = QWidget()
        self.pages.addWidget(QWidget())
        self.pages.addWidget(self.step2)
        kind = award["kind"]
        {"group": self._groups, "name": self._name}.get(kind, self._titles)()
        self._go(0)

    def _go(self, i: int):
        self.pages.setCurrentIndex(i)
        self.back.setVisible(i == 1)
        for k in range(self.top.count()):
            w = self.top.itemAt(k).widget()
            if w is not None and self.award["kind"] != "group":
                w.setVisible(i == 0)
        if i == 0 and self.award["kind"] != "group":
            for m, b in getattr(self, "_tabs", {}).items():
                b.setVisible(True)

    def _set_page(self, i: int, w: QWidget):
        old = self.pages.widget(i)
        self.pages.removeWidget(old)
        old.deleteLater()
        self.pages.insertWidget(i, w)

    def _scroll(self, inner: QWidget) -> QScrollArea:
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setFrameShape(QScrollArea.Shape.NoFrame)
        s.setWidget(inner)
        return s

    def _finish(self, entry: Dict):
        self.result_entry = entry
        self.accept()

    # ── groups ────────────────────────────────────────────────────────────────

    def _groups(self):
        size = self.award.get("size") or 0
        word = {2: "duology", 3: "trilogy"}.get(size, "saga or franchise")
        self.heading.setText(f"Which {word} wins?")
        self.sub.setText("Search any series or collection — it doesn't need to be in your library (parts you've "
                         "seen can be added as watched). Or pick one Raikō found in your library, or put one "
                         "together by hand.")
        self.extra_btn.setText("Assemble by hand…")
        self.extra_btn.show()
        self.extra_btn.clicked.connect(self._assemble)
        self.gsearch = QLineEdit()
        self.gsearch.setObjectName("homeSearch")
        self.gsearch.setPlaceholderText("Search any series or collection — e.g. The Lord of the Rings")
        self.gsearch.setFixedHeight(36)
        self.gsearch.returnPressed.connect(self._search_groups)
        self._gtimer = QTimer(self)
        self._gtimer.setSingleShot(True)
        self._gtimer.timeout.connect(self._search_groups)
        self.gsearch.textChanged.connect(lambda _t: self._gtimer.start(600))
        self.top.addWidget(self.gsearch, 1)
        self.online = QPushButton("Refresh from your library")
        self.online.setObjectName("hallGhost")
        self.online.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.online.clicked.connect(self._refresh_online)
        self.top.addWidget(self.online)
        self._online_groups: List[Dict] = []
        self._gtok = 0
        self._fill_groups()
        self._refresh_online(force=False)

    def _fill_groups(self):
        size = self.award.get("size") or 0
        mine = self.h.groups()
        exact = [g for g in mine if not size or len(g["parts"]) == size]
        other = [g for g in mine if size and len(g["parts"]) != size]
        online = sorted(self._online_groups, key=lambda g: (bool(size) and len(g["parts"]) != size))
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setSpacing(8)

        def section(text):
            lab = QLabel(text)
            lab.setObjectName("hallKicker")
            lab.setStyleSheet(f"color:{GOLD};padding-top:8px;")
            v.addWidget(lab)

        def rows(gs, limit=None):
            shown = gs if limit is None else gs[:limit]
            for g in shown:
                r = _GroupRow(g)
                r.chosen.connect(self._choose_group)
                v.addWidget(r)
            if limit is not None and len(gs) > limit:
                more = QPushButton(f"Show {len(gs) - limit} more")
                more.setObjectName("hallGhost")
                more.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                more.clicked.connect(lambda: (more.hide(), [v.insertWidget(v.indexOf(more), _row(g))
                                                            for g in gs[limit:]]))
                v.addWidget(more, alignment=Qt.AlignmentFlag.AlignLeft)

        def _row(g):
            r = _GroupRow(g)
            r.chosen.connect(self._choose_group)
            return r

        word = {2: "duologies", 3: "trilogies"}.get(size, "groups")
        if self.gsearch.text().strip():
            section(f"ONLINE · “{self.gsearch.text().strip().upper()}”")
            if online:
                rows(online, 6)
            else:
                e = QLabel("Searching…" if self._gtok and not getattr(self, "_gdone", True)
                           else "Nothing found online for that.")
                e.setObjectName("homeEmpty")
                v.addWidget(e)
        section(f"{word.upper()} IN YOUR LIBRARY" if size else "IN YOUR LIBRARY")
        if exact:
            rows(exact, 8)
        else:
            e = QLabel(f"No {word} found in your library yet — search for one above "
                       "(it doesn't need to be in your library).")
            e.setObjectName("homeEmpty")
            e.setWordWrap(True)
            v.addWidget(e)
        if other:
            section("OTHER GROUPS IN YOUR LIBRARY")
            rows(other, 4)
        v.addStretch()
        self._set_page(0, self._scroll(inner))
        self._go(0)

    def _search_groups(self):
        q = self.gsearch.text().strip()
        self._gtok += 1
        tok = self._gtok
        self._online_groups = []
        if not q:
            self._fill_groups()
            return
        self._gdone = False
        self._fill_groups()
        path = self.h.db.db_path

        def job():
            from core.database import DatabaseManager
            return Honours(DatabaseManager(path)).search_groups(q)

        def done(gs, t=tok):
            from PyQt6 import sip
            if sip.isdeleted(self) or t != self._gtok:
                return
            self._gdone = True
            self._online_groups = gs or []
            self._fill_groups()

        w = Worker(job)
        w.signals.result.connect(done)
        w.signals.error.connect(lambda _e, t=tok: done([], t))
        run_worker(w)

    def _choose_group(self, g: Dict):
        missing = [p for p in g["parts"] if not p.get("lib_id") and (p.get("tmdb_id") or p.get("anilist_id"))]
        if not missing:
            return self._finish(self.h.group_entry(g))
        lib = "Miroku" if g["media"] == "anime" else "Kinema"
        box = QMessageBox(self)
        box.setWindowTitle(g["name"])
        n = len(missing)
        box.setText(f"{n} of its {len(g['parts'])} parts {'is' if n == 1 else 'are'} not in your library.")
        box.setInformativeText("Seen them? Raikō can add them to " + lib + " as watched, so they count everywhere "
                               "(and can join the Hall of Fame too).")
        add = box.addButton(f"Add {n} to {lib} as watched", QMessageBox.ButtonRole.AcceptRole)
        just = box.addButton("Just award it", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is just:
            return self._finish(self.h.group_entry(g))
        if box.clickedButton() is not add:
            return
        self.heading.setText(f"Adding {n} to {lib}…")
        self.setEnabled(False)
        path = self.h.db.db_path
        media = "anime" if g["media"] == "anime" else "movie"

        def job():
            from core.database import DatabaseManager
            from core.quick_add import add_watched
            dbx = DatabaseManager(path)
            out = {}
            for p in missing:
                pid = p.get("anilist_id") if media == "anime" else p.get("tmdb_id")
                out[pid] = add_watched(dbx, {"media_type": media, "provider_id": pid})
            return out

        def done(ids):
            from PyQt6 import sip
            if sip.isdeleted(self):
                return
            self.setEnabled(True)
            for p in g["parts"]:
                pid = p.get("anilist_id") if media == "anime" else p.get("tmdb_id")
                if not p.get("lib_id") and (ids or {}).get(pid):
                    p["lib_id"] = ids[pid]
                    p["watched"] = True
            self._finish(self.h.group_entry(g))

        w = Worker(job)
        w.signals.result.connect(done)
        w.signals.error.connect(lambda _e: done({}))
        run_worker(w)

    def _refresh_online(self, force: bool = True):
        self.online.setEnabled(False)
        self.online.setText("Looking…")
        h = self.h

        def job():
            from core.database import DatabaseManager
            return Honours(DatabaseManager(h.db.db_path)).refresh_groups(max_age_days=0 if force else 7)
        w = Worker(job)
        w.signals.result.connect(lambda _r: self._online_done())
        w.signals.error.connect(lambda _e: self._online_done())
        run_worker(w)

    def _online_done(self):
        try:
            self.online.setText("Refresh from your library")
            self.online.setEnabled(True)
            self._fill_groups()
        except RuntimeError:
            pass

    def _assemble(self):
        size = self.award.get("size") or 0
        picked: List[int] = []
        inner = QWidget()
        v = QVBoxLayout(inner)
        status = QLabel()
        status.setObjectName("hallAskSub")
        v.addWidget(status)
        done = QPushButton("Use these")
        done.setObjectName("hallPrimary")
        done.setStyleSheet(f"QPushButton#hallPrimary{{background:{GOLD};}}")

        def refresh():
            names = [_title(self.db.get_anime_by_id(i) or {}) for i in picked]
            need = f" (pick {size})" if size else " (pick 2 or more)"
            status.setText(("In order: " + "  ·  ".join(f"{n + 1}. {t}" for n, t in enumerate(names))
                            if names else "Click titles in order") + need)
            done.setEnabled(len(picked) == size if size else len(picked) >= 2)

        def toggle(lib_id):
            if lib_id in picked:
                picked.remove(lib_id)
            else:
                picked.append(lib_id)
            refresh()

        grid = QWidget()
        flow = FlowLayout(grid, 12, 12)
        for media in ("anime", "movie", "tv"):
            for r in self.db.get_all_anime(media_type=media, sort_by="title"):
                if r.get("watch_status") == "planned":
                    continue
                t = _PickTile(r, WING_COLORS[media])
                t.picked.connect(toggle)
                flow.addWidget(t)
        v.addWidget(grid)

        def use():
            name, ok = QInputDialog.getText(self, "Name it", "What should this group be called?",
                                            text=_title(self.db.get_anime_by_id(picked[0]) or {}).split(":")[0])
            if not ok:
                return
            parts = [self.h._part(self.db.get_anime_by_id(i)) for i in picked]
            media = (self.db.get_anime_by_id(picked[0]) or {}).get("media_type") or "anime"
            self._finish(self.h.group_entry({"name": name.strip() or "My collection", "media": media,
                                             "parts": parts}))
        done.clicked.connect(use)
        self.extra_btn.hide()
        holder = QWidget()
        hv = QVBoxLayout(holder)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.addWidget(self._scroll(inner), 1)
        hv.addWidget(done, alignment=Qt.AlignmentFlag.AlignRight)
        refresh()
        self._set_page(1, holder)
        self.heading.setText("Put a group together")
        self._go(1)
        self.back.clicked.connect(lambda: (self.extra_btn.show(), self.heading.setText("Pick the winner")))

    # ── names ─────────────────────────────────────────────────────────────────

    def _name(self):
        self.heading.setText("Who wins?")
        self.sub.setText("A studio, director, network… type a name (suggestions come from your library).")
        inner = QWidget()
        v = QVBoxLayout(inner)
        edit = QLineEdit()
        edit.setObjectName("hallField")
        edit.setPlaceholderText("e.g. MAPPA, Denis Villeneuve, HBO")
        comp = QCompleter(self.h.studios())
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        edit.setCompleter(comp)
        v.addWidget(edit)
        ok = QPushButton("Award it")
        ok.setObjectName("hallPrimary")
        ok.setStyleSheet(f"QPushButton#hallPrimary{{background:{GOLD};}}")
        ok.clicked.connect(lambda: edit.text().strip() and self._finish(self.h.name_entry(edit.text())))
        v.addWidget(ok, alignment=Qt.AlignmentFlag.AlignLeft)
        v.addStretch()
        self._set_page(0, inner)

    # ── titles, then the specific thing ───────────────────────────────────────

    def _titles(self):
        kind = self.award["kind"]
        media_only = self.award.get("media")
        self.heading.setText({"title": "Which title wins?", "season": "Which season wins?",
                              "episode": "First, which title?", "character": "First, which title?",
                              "theme": "Which anime's song?"}.get(kind, "Pick the winner"))
        self.sub.setText({"episode": "Then pick the episode.", "character": "Then pick the character.",
                          "theme": "Then type the song's name."}.get(kind, "Titles you've watched or are watching."))
        self._media = media_only or "anime"
        self._tabs = {}
        if not media_only:
            for m, name in (("anime", "Anime"), ("movie", "Movies"), ("tv", "TV")):
                if kind == "episode" and m == "movie":
                    continue
                b = QPushButton(name)
                b.setObjectName("hallTab")
                b.setCheckable(True)
                b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                b.clicked.connect(lambda _=False, m=m: self._set_media(m))
                self._tabs[m] = b
                self.top.addWidget(b)
        self.top.addStretch()
        self.search = QLineEdit()
        self.search.setObjectName("homeSearch")
        self.search.setPlaceholderText("Search your library — or anything online")
        self.search.setFixedSize(300, 36)
        self.search.textChanged.connect(lambda _t: self._fill_titles())
        self.top.addWidget(self.search)
        self._tcontainer = QWidget()
        self._tcv = QVBoxLayout(self._tcontainer)
        self._tcv.setContentsMargins(0, 0, 0, 0)
        self._tcv.setSpacing(22)
        self._tlib = QWidget()
        self._tcv.addWidget(self._tlib)
        self.finder = OnlineFinder(self.db)
        self.finder.added.connect(self._title_chosen)
        self._tcv.addWidget(self.finder)
        self._tcv.addStretch()
        self._set_page(0, self._scroll(self._tcontainer))
        self._set_media(self._media)

    def _set_media(self, m: str):
        self._media = m
        for k, b in self._tabs.items():
            b.setChecked(k == m)
            b.setStyleSheet(f"QPushButton#hallTab:checked{{color:#0b0d12;background:{WING_COLORS[k]};}}")
        self._fill_titles()

    def _fill_titles(self):
        q = self.search.text().strip().lower()
        year = None
        if self.award.get("key") == "year":
            import re
            m = re.search(r"(19|20)\d\d", self.award["label"])
            year = m.group(0) if m else None
        rows = [r for r in self.db.get_all_anime(media_type=self._media, sort_by="title")
                if r.get("watch_status") in ("completed", "watching", "dropped")
                and (not q or q in _title(r).lower() or q in (r.get("romaji_title") or "").lower())
                and (not year or _year(r) == year)]
        inner = QWidget()
        if not rows:
            v = QVBoxLayout(inner)
            v.setContentsMargins(0, 0, 0, 0)
            e = QLabel("Nothing in your library matches." if q or year else "Nothing watched here yet.")
            e.setObjectName("homeEmpty")
            v.addWidget(e)
        else:
            flow = FlowLayout(inner, 14, 14)
            for r in rows:
                t = _PickTile(r, WING_COLORS[self._media])
                t.picked.connect(self._title_chosen)
                flow.addWidget(t)
        self._tcv.replaceWidget(self._tlib, inner)
        self._tlib.deleteLater()
        self._tlib = inner
        self.finder.set_query(self._media, q)
        self._go(0)

    def _title_chosen(self, lib_id: int):
        kind = self.award["kind"]
        row = self.db.get_anime_by_id(lib_id) or {}
        media = row.get("media_type") or "anime"
        if kind == "title":
            return self._finish(self.h.title_entry(lib_id))
        if kind == "season":
            if media != "tv":
                return self._finish(self.h.season_entry(lib_id))
            return self._list_step(f"Which season of {_title(row)}?", [
                (s.get("name") or f"Season {s['season_number']}",
                 f"{s.get('episode_count') or '?'} episodes · {(s.get('air_date') or '')[:4]}",
                 lambda s=s: self._finish(self.h.season_entry(lib_id, s["season_number"])))
                for s in self.db.get_tv_seasons(lib_id) if s["season_number"] > 0])
        if kind == "episode":
            if media == "tv":
                items = [(f"S{e['season_number']:02d}E{e['episode_number']:02d}  {e.get('name') or ''}",
                          ("★ " + f"{e['rating']:.0f}/6  ·  " if e.get("rating") else "") + (e.get("air_date") or ""),
                          lambda e=e: self._finish(self.h.episode_entry(lib_id, e["episode_number"],
                                                                         e["season_number"])))
                         for e in self.db.get_tv_episodes(lib_id) if e["season_number"] > 0]
            else:
                ratings = {r["episode_num"]: r.get("score") for r in self.db.get_ratings(lib_id)}
                total = row.get("total_episodes") or len(self.db.get_episodes(lib_id)) or 1
                items = [(f"Episode {n}", f"★ {ratings[n]:.0f}/6" if ratings.get(n) else "",
                          lambda n=n: self._finish(self.h.episode_entry(lib_id, n)))
                         for n in range(int(total), 0, -1)]
            return self._list_step(f"Which episode of {_title(row)}?", items)
        if kind == "character":
            picker = _CharPicker(self.h, lib_id, media, row.get("characters") or [],
                                 order="role" if self.award.get("key") == "protagonist" else "loved")
            picker.chosen.connect(lambda ch: self._finish(self.h.character_entry(lib_id, ch)))
            self._set_page(1, picker)
            self.heading.setText(f"Who from {_title(row)}?")
            return self._go(1)
        if kind == "theme":
            song, ok = QInputDialog.getText(self, "Song", f"Which song from {_title(row)}? (e.g. “Unravel”)")
            if ok:
                self._finish(self.h.theme_entry(lib_id, song))

    def _list_step(self, heading: str, items: List):
        lst = QListWidget()
        lst.setObjectName("hallPickList")
        for text, sub, cb in items:
            it = QListWidgetItem(text + (f"     {sub}" if sub else ""))
            it.setData(Qt.ItemDataRole.UserRole, cb)
            lst.addItem(it)
        lst.itemClicked.connect(lambda it: it.data(Qt.ItemDataRole.UserRole)())
        self._set_page(1, lst)
        self.heading.setText(heading)
        self._go(1)


class _CharPicker(QWidget):
    """Every character of a title: the few the library knows show at once,
    then the full cast arrives from AniList / TMDB. Filter, Show more, or
    type a name."""
    chosen = pyqtSignal(dict)
    STEP = 48

    def __init__(self, h: Honours, lib_id: int, media: str, known: List[Dict], parent=None,
                 order: str = "loved"):
        super().__init__(parent)
        self.h, self.lib_id, self.media, self.order = h, lib_id, media, order
        self.chars: List[Dict] = list(known)
        self.shown = self.STEP
        self.role = ""                     # '' = everyone, else Main / Supporting / Background
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        bar = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setObjectName("homeSearch")
        self.filter.setPlaceholderText("Filter by character or actor")
        self.filter.setFixedHeight(36)
        self.filter.textChanged.connect(lambda _t: self._reset())
        bar.addWidget(self.filter, 1)
        other = QPushButton("Someone else…")
        other.setObjectName("hallGhost")
        other.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        other.clicked.connect(self._type_name)
        bar.addWidget(other)
        lay.addLayout(bar)
        self.role_btns: Dict[str, QPushButton] = {}
        if media == "anime":
            chips = QHBoxLayout()
            chips.setSpacing(6)
            for key, label in (("", "Everyone"), ("Main", "Main"), ("Supporting", "Supporting"),
                               ("Background", "Background")):
                b = QPushButton(label)
                b.setObjectName("hallSeg")
                b.setCheckable(True)
                b.setChecked(key == "")
                b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                b.clicked.connect(lambda _=False, k=key: self._set_role(k))
                self.role_btns[key] = b
                chips.addWidget(b)
            chips.addStretch()
            lay.addLayout(chips)
        self.status = QLabel("Loading the full cast…")
        self.status.setObjectName("hallAskSub")
        lay.addWidget(self.status)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        lay.addWidget(self.scroll, 1)
        self.more = QPushButton("Show more")
        self.more.setObjectName("hallGhost")
        self.more.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.more.clicked.connect(self._more)
        lay.addWidget(self.more, alignment=Qt.AlignmentFlag.AlignLeft)
        self._render()
        self._online: List[Dict] = []
        self._fetch(1)

    def _fetch(self, page: int):
        path = self.h.db.db_path
        lib_id = self.lib_id

        order = self.order

        def job():
            from core.database import DatabaseManager
            return Honours(DatabaseManager(path)).character_page(lib_id, page, order)

        w = Worker(job)
        w.signals.result.connect(lambda res, p=page: self._got(p, *res))
        w.signals.error.connect(lambda _e, p=page: self._got(p, None, False))
        run_worker(w)

    def _got(self, page: int, chars, more: bool):
        """A page of the cast arrived: show it right away, keep loading."""
        from PyQt6 import sip
        if sip.isdeleted(self):
            return
        if chars is None and not self._online:
            self.status.setText("Couldn't load the full cast — showing what Raikō already knows."
                                if self.chars else "No cast found — use “Someone else…” to type a name.")
            return
        self._online += chars or []
        have = {(c.get("name"), c.get("role")) for c in self._online}
        known = [c for c in self.chars if (c.get("name"), c.get("role")) not in have and c not in self._online]
        self.chars = self._online + known
        loading = bool(more) and page < 20
        how = ("main characters first" if self.order == "role" else "most-loved first") \
            if self.media == "anime" else "in billing order"
        self.status.setText(f"{len(self.chars)} characters, {how}" + (" — loading more…" if loading else ""))
        pos = self.scroll.verticalScrollBar().value()
        self._render()
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(pos))
        if loading:
            self._fetch(page + 1)

    def _set_role(self, key: str):
        self.role = key
        for k, b in self.role_btns.items():
            b.setChecked(k == key)
        self._reset()

    def _matches(self) -> List[Dict]:
        q = self.filter.text().strip().lower()
        out = self.chars
        if self.role:
            out = [c for c in out if (c.get("role") or "").lower() == self.role.lower()]
        if q:
            out = [c for c in out if q in (c.get("name") or "").lower() or q in (c.get("role") or "").lower()]
        return out

    def _reset(self):
        self.shown = self.STEP
        self._render()

    def _more(self):
        self.shown += self.STEP
        pos = self.scroll.verticalScrollBar().value()
        self._render()
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(pos))

    def _render(self):
        items = self._matches()
        inner = QWidget()
        flow = FlowLayout(inner, 14, 14)
        for ch in items[:self.shown]:
            b = _CharTile(ch, self.media)
            b.chosen.connect(self.chosen.emit)
            flow.addWidget(b)
        if not items and self.filter.text().strip():
            v = QLabel(f"No one called “{self.filter.text().strip()}” — use “Someone else…” to type it.")
            v.setObjectName("homeEmpty")
            flow.addWidget(v)
        self.scroll.setWidget(inner)
        left = len(items) - self.shown
        self.more.setVisible(left > 0)
        self.more.setText(f"Show more ({left})")

    def _type_name(self):
        name, ok = QInputDialog.getText(self, "Character", "Character's name:", text=self.filter.text().strip())
        if ok and name.strip():
            self.chosen.emit({"name": name.strip(), "role": ""})


class _CharTile(QWidget):
    chosen = pyqtSignal(dict)
    W, H = 110, 150

    def __init__(self, ch: Dict, media: str, parent=None):
        super().__init__(parent)
        self.ch = ch
        self.media = media
        self.pix: Optional[QPixmap] = None
        self._hover = False
        self.setFixedSize(self.W, self.H + 40)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if ch.get("image"):
            w = ImageWorker(ch["image"], ch["image"])
            w.signals.result.connect(self._on_img)
            run_worker(w)

    def _on_img(self, res):
        try:
            _k, _s, path = res
            if path:
                self.pix = QPixmap(str(path))
                self.update()
        except RuntimeError:
            pass

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(self.ch)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(1, 1, self.W - 2, self.H - 2)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.save()
        p.setClipPath(path)
        if self.pix and not self.pix.isNull():
            sc = self.pix.scaled(self.W, self.H, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                 Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(0, 0, sc, (sc.width() - self.W) // 2, 0, self.W, self.H)
        else:
            p.fillRect(r, QColor("#161a2a"))
        p.restore()
        p.setPen(QColor(GOLD) if self._hover else QColor(255, 255, 255, 30))
        p.drawPath(path)
        f = QFont(self.font())
        f.setPixelSize(12)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#e8eaf2"))
        main = self.ch.get("role") if self.media != "anime" and self.ch.get("role") else self.ch.get("name", "")
        p.drawText(QRectF(0, self.H + 4, self.W, 18), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(main or "", Qt.TextElideMode.ElideRight, self.W))
        f.setBold(False)
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor("#7f87a3"))
        sub = self.ch.get("name") if self.media != "anime" else self.ch.get("role", "")
        p.drawText(QRectF(0, self.H + 21, self.W, 16), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(sub or "", Qt.TextElideMode.ElideRight, self.W))
        p.end()
