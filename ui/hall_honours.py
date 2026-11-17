"""
Raikō - Honours: the awards wall in the Hall of Fame.

Each award card shows the category, the winner (art, name, your reason) and
up to two runners-up. Pickers know what each category holds: groups for
trilogies/duologies (found from TMDB collections and AniList sequel chains,
or assembled by hand), seasons, episodes, characters, themes, titles, names.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QCompleter, QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from core.honours import PLACES, TEMPLATES, Honours
from ui.hall_rank import GOLD, WING_COLORS, _PickTile, _title, _year
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
        self.sub.setText("Found from your library: AniList sequel chains and TMDB collections. "
                         "Can't see it? Look online, or put one together by hand.")
        self.extra_btn.setText("Assemble by hand…")
        self.extra_btn.show()
        self.extra_btn.clicked.connect(self._assemble)
        self.online = QPushButton("Look online for more")
        self.online.setObjectName("hallGhost")
        self.online.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.online.clicked.connect(self._refresh_online)
        self.top.addStretch()
        self.top.addWidget(self.online)
        self._fill_groups()

    def _fill_groups(self):
        size = self.award.get("size") or 0
        gs = self.h.groups(size)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setSpacing(8)
        if not gs:
            e = QLabel("No matching groups in your library yet." +
                       (" Try “Look online for more”." if size else ""))
            e.setObjectName("homeEmpty")
            v.addWidget(e)
        for g in gs:
            r = _GroupRow(g)
            r.chosen.connect(lambda g: self._finish(self.h.group_entry(g)))
            v.addWidget(r)
        v.addStretch()
        self._set_page(0, self._scroll(inner))
        self._go(0)

    def _refresh_online(self):
        self.online.setEnabled(False)
        self.online.setText("Looking…")
        h = self.h

        def job():
            from core.database import DatabaseManager
            return Honours(DatabaseManager(h.db.db_path)).refresh_groups(max_age_days=0)
        w = Worker(job)
        w.signals.result.connect(lambda _r: self._online_done())
        w.signals.error.connect(lambda _e: self._online_done())
        run_worker(w)

    def _online_done(self):
        try:
            self.online.setText("Look online for more")
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
        self.search.setPlaceholderText("Filter by title")
        self.search.setFixedSize(240, 36)
        self.search.textChanged.connect(lambda _t: self._fill_titles())
        self.top.addWidget(self.search)
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
            e = QLabel("Nothing matches." if q or year else "Nothing watched here yet.")
            e.setObjectName("homeEmpty")
            v.addWidget(e)
            v.addStretch()
        else:
            flow = FlowLayout(inner, 14, 14)
            for r in rows:
                t = _PickTile(r, WING_COLORS[self._media])
                t.picked.connect(self._title_chosen)
                flow.addWidget(t)
        self._set_page(0, self._scroll(inner))
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
            chars = row.get("characters") or []
            if not chars:
                name, ok = QInputDialog.getText(self, "Character", f"Character from {_title(row)}:")
                if ok and name.strip():
                    self._finish(self.h.character_entry(lib_id, {"name": name.strip()}))
                return
            inner = QWidget()
            flow = FlowLayout(inner, 14, 14)
            for ch in chars:
                b = _CharTile(ch, media)
                b.chosen.connect(lambda ch: self._finish(self.h.character_entry(lib_id, ch)))
                flow.addWidget(b)
            self._set_page(1, self._scroll(inner))
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
