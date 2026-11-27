"""
Raikō - a moment for each event, shown once (re-open from the banner).

  holidays   a letter from the Raikō team: the event's centrepiece, a heading
             in the event's display font, a message written for the day, Rai
             in costume and the team's signature
  premiere   a cinema ticket: the show's backdrop + title logo, ADMIT ONE ·
             EPISODE 1, date & time, a perforated stub - "Watch the trailer"
  farewell   end credits that roll: title logo, "a story in N episodes",
             starring <characters>, your own journey with it, "Thank you for
             the ride." - "Rank its songs"
  season     a season letter: what's arriving, where to find it
"""
from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor as _Raw, QCursor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

LETTERS = {
    "christmas": ("Merry Christmas",
                  "However you spend these days — with family, with friends, or with a stack of episodes and a warm "
                  "blanket — we hope they're full of the good kind of stories.\n\nThank you for tracking your year "
                  "with Raikō. We left a few festive picks on Home for you."),
    "new_year": ("Happy New Year",
                 "Another year of cliffhangers, finales and 3 a.m. “one more episode”s. Here's to every "
                 "story that made you laugh, cry and hit play again — and to everything you'll discover next.\n\n"
                 "May your watchlist be long and your spoilers few."),
    "halloween": ("Happy Halloween",
                  "Lock the doors, dim the lights, and choose something deliciously eerie. We've left a few picks on "
                  "Home — from cosy chills to proper scares.\n\nWatch at your own risk. We'll keep the lights on."),
    "season": ("A new season begins",
               "New worlds, new rivals, new openings to get stuck in your head. The season's most anticipated shows "
               "are on Home — add the ones that call to you, and Raikō will tell you the moment they air."),
}


def _font(px: int, bold=True, family: str = "") -> QFont:
    from ui.theme import ThemeManager
    f = QFont(family or ThemeManager.get().display_font())
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def _fit(p: QPainter, text: str, rect: QRectF, px: int, bold: bool, family: str = "",
         flags=Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap) -> None:
    """Draw text, shrinking the font until it fits the box (nothing ever cut off)."""
    size = px
    while size > 9:
        f = _font(size, bold, family)
        p.setFont(f)
        br = p.fontMetrics().boundingRect(rect.toAlignedRect(), int(flags), text)
        if br.height() <= rect.height() and br.width() <= rect.width() + 1:
            break
        size -= 1
    p.drawText(rect, int(flags), text)


class _Card(QWidget):
    """The painted card; content depends on the moment."""
    closed = pyqtSignal()

    def __init__(self, ev: Dict, parent=None):
        super().__init__(parent)
        self.ev = ev
        self.kind = ev.get("kind") or ("season" if ev.get("category") == "anime" else ev["id"])
        self.t0 = time.monotonic()
        self.pix: Dict[str, QPixmap] = {}
        self.portraits: List[Optional[QPixmap]] = []
        self.roll = 0.0
        self._first_roll = True
        sizes = {"premiere": (680, 330), "farewell": (620, 480)}
        w, h = sizes.get(self.kind, (580, 470))
        self.setFixedSize(w, h)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        from ui.decor import motion_level
        self._still = motion_level() == "off"
        if not self._still:
            self._timer.start(40)
        for key in ("logo", "backdrop", "cover"):
            url = ev.get("backdrops", [""])[0] if key == "backdrop" and ev.get("backdrops") else \
                (ev.get("banner") if key == "backdrop" else ev.get(key))
            if url:
                self._load(key, url)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 0, 24, 20)
        lay.addStretch()
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch()
        self.buttons = row
        lay.addLayout(row)

    def _load(self, key: str, url: str):
        from workers.workers import ImageWorker, run_worker
        w = ImageWorker(url, key)
        w.signals.result.connect(self._on_img)
        run_worker(w)

    def _on_img(self, res):
        from PyQt6 import sip
        if sip.isdeleted(self):
            return
        key, _s, path = res
        if path:
            self.pix[key] = QPixmap(str(path))
            self.update()

    def add_button(self, text: str, cb, primary: bool = False):
        b = QPushButton(text)
        b.setObjectName("primaryBtn" if primary else "secondaryBtn")
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setFixedHeight(36)
        b.clicked.connect(cb)
        self.buttons.addWidget(b)

    def _tick(self):
        if self.kind == "farewell":
            self.roll += 0.9
        self.update()

    # ── painting ─────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        t = 0.0 if self._still else time.monotonic() - self.t0
        getattr(self, f"_paint_{self.kind}" if self.kind in ("premiere", "farewell") else "_paint_letter")(p, t)
        p.end()

    def _cover(self, p: QPainter, key: str, r: QRectF, opacity: float = 1.0, y_bias: float = 0.35):
        pm = self.pix.get(key) or self.pix.get("cover")
        if pm is None or pm.isNull():
            return
        sc = pm.scaled(int(r.width()), int(r.height()), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation)
        p.setOpacity(opacity)
        p.drawPixmap(int(r.x()), int(r.y()), sc, (sc.width() - int(r.width())) // 2,
                     int((sc.height() - r.height()) * y_bias), int(r.width()), int(r.height()))
        p.setOpacity(1.0)

    def _logo(self, p: QPainter, r: QRectF):
        pm = self.pix.get("logo")
        if pm is None or pm.isNull():
            p.setPen(_Raw("#ffffff"))
            _fit(p, self.ev["name"], r, 30, True, flags=Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap)
            return
        sc = pm.scaled(int(r.width()), int(r.height()), Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
        p.drawPixmap(int(r.center().x() - sc.width() / 2), int(r.center().y() - sc.height() / 2), sc)

    def _paint_letter(self, p: QPainter, t: float):
        from ui.decor import draw_hero, draw_rai
        from ui.theme import ThemeManager
        tm = ThemeManager.get()
        surf, text, muted, accent = (_Raw(tm.hex(h)) for h in ("#12141d", "#f4f5fa", "#9da5c0", "#8b7bff"))
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(r, 20, 20)
        p.fillPath(path, surf)
        top = QRectF(r.left(), r.top(), r.width(), 150)
        g = QLinearGradient(top.topLeft(), top.bottomLeft())
        a1 = _Raw(accent)
        a1.setAlpha(70)
        a2 = _Raw(accent)
        a2.setAlpha(0)
        g.setColorAt(0, a1)
        g.setColorAt(1, a2)
        p.save()
        p.setClipPath(path)
        p.fillRect(top, g)
        p.restore()
        eid = self.ev["id"] if self.kind != "season" else "season"
        draw_hero(p, QRectF(r.center().x() - 70, 12, 140, 140), t, eid)
        heading, body = LETTERS.get(eid, LETTERS["season"])
        if eid == "season":
            heading = self.ev.get("greeting") or heading
        p.setPen(text)
        _fit(p, heading, QRectF(40, 160, r.width() - 80, 48), 32, True,
             flags=Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap)
        p.setPen(muted)
        _fit(p, body, QRectF(48, 214, r.width() - 96, 150), 14, False, family="Segoe UI",
             flags=Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap)
        p.setPen(accent)
        p.setFont(_font(14, True))
        p.drawText(QRectF(40, 368, r.width() - 140, 24), Qt.AlignmentFlag.AlignRight, "— The Raikō team  ✦")
        outfit = {"christmas": "santa", "halloween": "witch", "new_year": "party"}.get(eid, "party")
        draw_rai(p, QRectF(r.right() - 96, 344, 64, 64), t, outfit, still=self._still)
        p.setPen(QPen(_Raw(255, 255, 255, 24), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _paint_premiere(self, p: QPainter, t: float):
        from core.events import readable_accent
        acc = _Raw(readable_accent(self.ev.get("color") or "#8b7bff"))
        W, H = self.width(), self.height() - 60
        stub = 190
        body = QRectF(0.5, 0.5, W - stub - 1, H)
        right = QRectF(W - stub, 0.5, stub - 0.5, H)
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(0.5, 0.5, W - 1, H), 18, 18)
        for cy in (0.5, H):                                  # ticket notches
            notch = QPainterPath()
            notch.addEllipse(QPointF(W - stub, cy), 14, 14)
            shape = shape.subtracted(notch)
        p.save()
        p.setClipPath(shape)
        p.fillRect(QRectF(0, 0, W, H), _Raw(14, 15, 22))
        self._cover(p, "backdrop", body, 0.9)
        g = QLinearGradient(0, 0, body.width(), 0)
        g.setColorAt(0, _Raw(8, 9, 14, 120))
        g.setColorAt(1, _Raw(8, 9, 14, 220))
        p.fillRect(body, g)
        p.fillRect(right, _Raw(acc.red(), acc.green(), acc.blue(), 235))
        p.restore()
        self._logo(p, QRectF(30, 34, body.width() - 60, 120))
        p.setPen(_Raw("#ffffff"))
        p.setFont(_font(13, True, "Segoe UI"))
        when = datetime.fromtimestamp(self.ev["airing_at"])
        p.drawText(QRectF(30, H - 92, body.width() - 60, 22), Qt.AlignmentFlag.AlignLeft,
                   "PREMIERE  ·  EPISODE 1")
        p.setFont(_font(12, False, "Segoe UI"))
        p.setPen(_Raw(230, 232, 240))
        p.drawText(QRectF(30, H - 66, body.width() - 60, 40), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                   self.ev.get("tagline") or "")
        # stub
        p.setPen(QPen(_Raw(255, 255, 255, 140), 2, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(W - stub, 18), QPointF(W - stub, H - 18))
        ink = _Raw("#0b0d12")
        p.setPen(ink)
        p.setFont(_font(11, True, "Segoe UI"))
        p.drawText(QRectF(W - stub, 26, stub, 18), Qt.AlignmentFlag.AlignHCenter, "ADMIT ONE")
        p.setFont(_font(34, True))
        p.drawText(QRectF(W - stub, 50, stub, 48), Qt.AlignmentFlag.AlignHCenter, when.strftime("%d"))
        p.setFont(_font(13, True, "Segoe UI"))
        p.drawText(QRectF(W - stub, 98, stub, 20), Qt.AlignmentFlag.AlignHCenter, when.strftime("%b %Y").upper())
        p.drawText(QRectF(W - stub, 122, stub, 20), Qt.AlignmentFlag.AlignHCenter, f"{when.strftime('%H:%M')}")
        p.setFont(_font(10, True, "Segoe UI"))
        p.drawText(QRectF(W - stub, 150, stub, 16), Qt.AlignmentFlag.AlignHCenter, "SEAT  FRONT ROW")
        x = W - stub + 30
        rnd = (self.ev.get("anilist_id") or 7) * 7919
        while x < W - 30:                                   # barcode
            w = 1 + (rnd % 3)
            rnd = (rnd * 1103515245 + 12345) % 2147483648
            p.fillRect(QRectF(x, H - 70, w, 44), ink)
            x += w + 1 + (rnd % 3)
        shine = (math.sin(t * 1.2) + 1) / 2
        p.fillRect(QRectF(0, H * shine - 40, W - stub, 2), _Raw(255, 255, 255, 30))

    def _paint_farewell(self, p: QPainter, t: float):
        W, H = self.width(), self.height() - 60
        r = QRectF(0.5, 0.5, W - 1, H)
        path = QPainterPath()
        path.addRoundedRect(r, 18, 18)
        p.save()
        p.setClipPath(path)
        p.fillRect(r, _Raw(6, 6, 10))
        self._cover(p, "backdrop", r, 0.5)
        p.fillRect(r, _Raw(6, 6, 10, 170))
        lines: List[tuple] = [("logo", None)]
        lines += [("big", f"A story in {self.ev.get('episodes') or '?'} episodes"), ("gap", None),
                  ("small", "STARRING")]
        lines += [("name", n) for n in (self.ev.get("characters") or [])[:5]]
        lines += [("gap", None)]
        st = self.ev.get("lib_status")
        if st in ("watching", "completed"):
            lines += [("small", "AND YOU"), ("name", "every step of the way" if st == "completed" else
                                                    "right up to the final episode")]
            lines += [("gap", None)]
        lines += [("big", "Thank you for the ride."), ("gap", None), ("small", "— The Raikō team")]
        start = H * 0.42 if self._first_roll else H      # open on the title, then roll from below
        y = start - (self.roll if not self._still else start - 30)
        for kind, txt in lines:
            if kind == "logo":
                self._logo(p, QRectF(W * 0.15, y, W * 0.7, 110))
                y += 130
            elif kind == "gap":
                y += 26
            else:
                f = {"big": _font(22, True), "small": _font(11, True, "Segoe UI"),
                     "name": _font(17, False, "Segoe UI")}[kind]
                p.setFont(f)
                p.setPen(_Raw(255, 255, 255, 235 if kind != "small" else 150))
                p.drawText(QRectF(20, y, W - 40, 30), Qt.AlignmentFlag.AlignHCenter, txt)
                y += 34 if kind != "small" else 24
        if y < 0 and not self._still:
            self.roll = 0.0                                  # roll again
            self._first_roll = False
        fade = QLinearGradient(0, 0, 0, H)
        fade.setColorAt(0, _Raw(6, 6, 10, 255))
        fade.setColorAt(0.14, _Raw(6, 6, 10, 0))
        fade.setColorAt(0.86, _Raw(6, 6, 10, 0))
        fade.setColorAt(1, _Raw(6, 6, 10, 255))
        p.fillRect(r, fade)
        p.restore()
        p.setPen(QPen(_Raw(255, 255, 255, 30), 1))
        p.drawPath(path)


class EventMoment(QWidget):
    """Dimmed backdrop + the card, centred over the window. Click outside / Esc closes."""

    def __init__(self, window, ev: Dict):
        host = window.centralWidget() or window
        super().__init__(host)
        self.window_ = window
        self.ev = ev
        self.setGeometry(host.rect())
        self.card = _Card(ev, self)
        kind = self.card.kind
        if kind == "premiere":
            tr = ev.get("trailer") or {}
            if tr.get("id"):
                self.card.add_button("▶  Watch the trailer", lambda: self._trailer(tr), True)
            self.card.add_button("Open details" if ev.get("lib_id") else "Add to my list", self._details)
        elif kind == "farewell":
            self.card.add_button("🏆  Rank its songs", self._rank, True)
        self.card.add_button("Close" if kind in ("premiere", "farewell") else "Thank you!", self.close_moment,
                             kind not in ("premiere", "farewell"))
        if kind not in ("premiere", "farewell"):
            self.card.buttons.addStretch()             # a letter: its button centred under the signature
        self.card.move((self.width() - self.card.width()) // 2, (self.height() - self.card.height()) // 2)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.show()
        self.raise_()
        self.setFocus()
        if getattr(window, "_decor", None) is not None and kind not in ("farewell",):
            window._decor.burst(2.5)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), _Raw(4, 5, 9, 170))
        p.end()

    def mousePressEvent(self, e):
        if not self.card.geometry().contains(e.position().toPoint()):
            self.close_moment()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close_moment()

    def resizeEvent(self, e):
        self.card.move((self.width() - self.card.width()) // 2, (self.height() - self.card.height()) // 2)

    def close_moment(self):
        self.hide()
        self.deleteLater()

    def _trailer(self, tr):
        from ui.trailer_player import show_trailer
        show_trailer(tr["id"], tr.get("site") or "youtube", self.ev["name"], self.window_)

    def _details(self):
        self.close_moment()
        if self.ev.get("lib_id"):
            self.window_._open_title(self.ev["lib_id"])
        elif hasattr(self.window_, "_open_pick"):
            self.window_._open_pick({"media_type": "anime", "provider_id": self.ev["anilist_id"],
                                     "title": self.ev["name"], "poster_url": self.ev.get("cover") or "", "raw": {}})

    def _rank(self):
        self.close_moment()
        hp = getattr(self.window_, "_home_page", None)
        if hp is not None:
            hp._rank_songs(self.ev["name"])


def show_moment(window, ev: Dict, force: bool = False) -> Optional[EventMoment]:
    """Show the event's moment once per event (per year / per day for anime)."""
    from core import events
    from core.app_settings import app_settings
    st = app_settings()
    key = f"event_moment/{events.season_key(ev)}"
    if not force and str(st.value(key, "")) == "1":
        return None
    st.setValue(key, "1")
    host = window.centralWidget() or window
    host.resize(host.size())
    return EventMoment(window, ev)


def moment_label(ev: Dict) -> str:
    k = ev.get("kind")
    return {"premiere": "🎟  Your ticket", "farewell": "🎬  Roll the credits"}.get(k, "✉  Read our note")
