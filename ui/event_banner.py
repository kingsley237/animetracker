"""
Raikō - the event welcome banner (top of Home) and the Settings coach mark.

Shown once per event per year, inline (never a dialog). Wording and buttons
follow the intensity in use (core/events.py):

  full         "Raikō dressed up for Christmas."      Keep it · Switch back · Other looks ▾
  decorations  "A little Christmas on top of <theme>." Nice · Go full Christmas · No decorations
  ask first    "It's Christmas! Dress Raikō up?"       Yes, dress up · Just decorations · No thanks

Closing it (✕) keeps things as they are and, once, points at the Settings
button: "Changed your mind? Settings → Appearance → Event themes…".
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QRect, Qt, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from core import events
from ui.anim_emoji import AnimatedEmoji
from ui.theme import ThemeManager
from ui.themes_catalog import info


def _btn(text: str, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("primaryBtn" if primary else "secondaryBtn")
    b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    b.setFixedHeight(34)
    return b


class EventBanner(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("eventBanner")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.ev = None
        self.hide()

    def refresh(self):
        """One row per event on today you haven't answered yet (a holiday and a
        premiere can share a day: the holiday keeps the look, the show still
        gets its moment)."""
        tm = ThemeManager.get()
        if self.layout() is None:
            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)
        old = getattr(self, "_inner", None)
        if old is not None:
            self.layout().removeWidget(old)
            old.deleteLater()
            self._inner = None
        evs = [e for e in (getattr(tm, "events", None) or ([tm.event] if tm.event else []))
               if not events.choice(e)]
        if tm.event_level == "off" and tm.event is not None and tm.event in evs:
            evs.remove(tm.event)
        if not evs:
            self.hide()
            return
        self.ev = evs[0]
        self._art = None
        self._inner = QWidget()
        self._inner.setObjectName("eventBannerInner")
        self.layout().addWidget(self._inner)
        col = QVBoxLayout(self._inner)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        for i, ev in enumerate(evs):
            if i:
                line = QFrame()
                line.setObjectName("eventBannerSep")
                line.setFixedHeight(1)
                col.addWidget(line)
            row = QWidget()
            col.addWidget(row)
            self._row(row, ev, tm.event_level if ev is tm.event else "secondary")
        self._inner.show()
        self.setMinimumHeight(max(72, self._inner.sizeHint().height()))
        self.show()

    def _row(self, host: QWidget, ev, level: str):
        tm = ThemeManager.get()
        lay = QHBoxLayout(host)
        lay.setContentsMargins(16, 12, 12, 12)
        lay.setSpacing(14)
        if ev.get("portraits"):
            lay.addWidget(_Portraits(ev["portraits"], ev.get("color") or "#8b7bff"))
            if self._art is None:
                self._load_art((ev.get("backdrops") or [""])[0] or ev.get("banner") or ev.get("cover") or "")
        else:
            lay.addWidget(AnimatedEmoji(ev["anim"], 44))
        col = QVBoxLayout()
        col.setSpacing(2)
        own = info(tm.saved_id)["name"]
        from ui.event_message import moment_label
        note = (moment_label(ev), False, lambda _b=None, e=ev: self._moment(e))
        if level == "secondary":
            title, sub = ev["line"], (ev.get("tagline") or "") + f"  ·  {tm.event['name']} keeps today's look."
            buttons = [("Nice", True, self._keep), note]
        elif ev.get("dynamic") and level == "full":
            title, sub = ev["line"], f"Raikō is wearing {ev['name']}'s colours today."
            buttons = [("Keep it", True, self._keep), ("Switch back", False, self._off)]
        elif ev.get("dynamic"):
            title, sub = ev["line"], ev.get("tagline") or ""
            buttons = [("Nice", True, self._keep), ("Wear its colours", False, self._full),
                       ("No decorations", False, self._off)]
        elif level == "full":
            title, sub = ev["line"], f"Showing the “{info(events.variant(ev))['name']}” look until the event ends."
            buttons = [("Keep it", True, self._keep), ("Switch back", False, self._off),
                       ("Try the other looks ▾", False, self._looks)]
        elif level == "decorations" and not ev.get("variants"):
            title, sub = ev["line"], "A few details for the occasion — your theme stays as it is."
            buttons = [("Nice", True, self._keep), ("No decorations", False, self._off)]
        elif level == "decorations":
            title = f"A little {ev['name']} on top of {own}."
            sub = "Your theme stays — the event adds a few festive details."
            buttons = [("Nice", True, self._keep), (f"Go full {ev['name']}", False, self._full),
                       ("No decorations", False, self._off)]
        else:
            title, sub = f"It's {ev['name']}! Dress Raikō up?", "You asked to be asked first."
            buttons = [("Yes, dress up", True, self._full), ("Just decorations", False, self._deco),
                       ("No thanks", False, self._off)]
        if level != "secondary" and len(buttons) < 4:
            buttons.insert(1, note)
        t = QLabel(f"<b>{ev['greeting']}</b>  ·  {title}")
        t.setObjectName("eventBannerTitle")
        t.setWordWrap(True)
        s = QLabel(sub)
        s.setObjectName("eventBannerSub")
        s.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(s)
        lay.addLayout(col, 1)
        for text, primary, cb in buttons:
            b = _btn(text, primary)
            b.clicked.connect(lambda _=False, cb=cb, b=b, e=ev: self._on(e, cb, b))
            lay.addWidget(b)
        x = QPushButton("✕")
        x.setObjectName("eventBannerClose")
        x.setFixedSize(28, 28)
        x.setToolTip("Close — the event stays as it is")
        x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x.clicked.connect(lambda _=False, e=ev: self._close(e))
        lay.addWidget(x, alignment=Qt.AlignmentFlag.AlignTop)

    def _on(self, ev, cb, b):
        self.ev = ev
        cb(b)

    def _moment(self, ev):
        from ui.event_message import show_moment
        show_moment(self.window(), ev, force=True)

    # ── the show's key art, faintly behind the banner ────────────────────────

    def _load_art(self, url: str):
        self._art = None
        if not url:
            return
        from workers.workers import ImageWorker, run_worker
        w = ImageWorker(url, url)
        w.signals.result.connect(self._on_art)
        run_worker(w)

    def _on_art(self, result):
        from PyQt6 import sip
        from PyQt6.QtGui import QPixmap
        if sip.isdeleted(self):
            return
        _k, _s, path = result
        if path:
            self._art = QPixmap(str(path))
            self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        art = getattr(self, "_art", None)
        if art is None or art.isNull():
            return
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QLinearGradient, QPainter, QPainterPath
        from ui.theme import QColor
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 16, 16)
        p.setClipPath(path)
        sc = art.scaled(int(r.width()), int(r.height()), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation)
        p.setOpacity(0.28)
        p.drawPixmap(int(r.x()), int(r.y()), sc, (sc.width() - int(r.width())) // 2,
                     (sc.height() - int(r.height())) // 3, int(r.width()), int(r.height()))
        p.setOpacity(1.0)
        g = QLinearGradient(0, 0, r.width(), 0)
        g.setColorAt(0, QColor(9, 10, 16, 120))
        g.setColorAt(0.6, QColor(9, 10, 16, 200))
        g.setColorAt(1, QColor(9, 10, 16, 235))
        p.fillRect(r, g)
        p.end()

    # ── choices ──────────────────────────────────────────────────────────────

    def _done(self, msg: Optional[str] = None):
        self.refresh()                       # the next event on today (if any) stays
        if msg:
            from ui.toast import Toast
            Toast.show(self.window(), msg, kind="info", duration=6000)

    def _keep(self, _b=None):
        events.set_choice(self.ev, "kept")
        self._done()

    def _full(self, _b=None):
        events.set_choice(self.ev, "full")
        ThemeManager.get().reapply()
        self._done()

    def _deco(self, _b=None):
        events.set_choice(self.ev, "decorations")
        ThemeManager.get().reapply()
        self._done()

    def _off(self, _b=None):
        events.set_choice(self.ev, "off")
        ThemeManager.get().reapply()
        self._done(f"Back to your usual look. You can bring {self.ev['name']} back in "
                   "Settings → Appearance → Event themes.")

    def _looks(self, anchor: QPushButton):
        m = QMenu(self)
        cur = events.variant(self.ev)
        for vid in self.ev["variants"]:
            a = m.addAction(("✓  " if vid == cur else "     ") + info(vid)["name"] + f"  —  {info(vid)['tagline']}")
            a.triggered.connect(lambda _=False, v=vid: self._pick(v))
        m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _pick(self, vid: str):
        events.set_variant(self.ev, vid)
        events.set_choice(self.ev, "full")
        ThemeManager.get().reapply()
        self._done(f"{info(vid)['name']} it is. Change looks any time in Settings → Appearance → Event themes.")

    def _close(self, ev=None):
        events.set_choice(ev or self.ev, "kept")
        self.refresh()
        show_coach_mark(self.window())


# ── coach mark ────────────────────────────────────────────────────────────────

class CoachMark(QWidget):
    """A ring around the Settings button + a short note. Once."""

    def __init__(self, window, target: QWidget, text: str):
        host = window.centralWidget() or window
        super().__init__(host)
        from ui.theme_preview import _Ring
        self.ring = _Ring(host)
        tl = target.mapTo(host, target.rect().topLeft())
        self.ring.set_target(QRect(tl, target.size()))
        self.ring.show()
        self.setObjectName("coachMark")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 12, 12)
        lay.setSpacing(8)
        lab = QLabel(text)
        lab.setObjectName("coachText")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        ok = _btn("Got it", True)
        ok.clicked.connect(self.close_mark)
        lay.addWidget(ok, alignment=Qt.AlignmentFlag.AlignRight)
        self.setFixedWidth(330)
        self.adjustSize()
        x = tl.x() + target.width() + 18
        y = max(12, tl.y() + target.height() // 2 - self.height() + 20)
        self.move(min(x, host.width() - self.width() - 12), y)
        self.show()
        self.raise_()
        QTimer.singleShot(15_000, self.close_mark)

    def close_mark(self):
        from PyQt6 import sip
        if sip.isdeleted(self):
            return
        if not sip.isdeleted(self.ring):
            self.ring.deleteLater()
        self.deleteLater()


def show_coach_mark(window) -> Optional[CoachMark]:
    from core.app_settings import app_settings
    st = app_settings()
    if str(st.value("event_coach_shown", "false")).lower() == "true":
        return None
    target = getattr(window, "_settings_btn", None)
    if target is None:
        return None
    st.setValue("event_coach_shown", "true")
    return CoachMark(window, target, "Changed your mind? <b>Settings → Appearance → Event themes</b> lets you switch "
                                     "back, pick another look, or turn events off.")


class _Portraits(QWidget):
    """The show's characters, overlapping circles in its colour."""

    def __init__(self, urls, color: str, parent=None):
        super().__init__(parent)
        self.urls = list(urls)[:4]
        self.color = color
        self.pix = {}
        self.setFixedSize(30 + 34 * len(self.urls), 52)
        from workers.workers import ImageWorker, run_worker
        for u in self.urls:
            w = ImageWorker(u, u)
            w.signals.result.connect(self._on)
            run_worker(w)

    def _on(self, res):
        from PyQt6 import sip
        from PyQt6.QtGui import QPixmap
        if sip.isdeleted(self):
            return
        k, _s, path = res
        if path:
            self.pix[k] = QPixmap(str(path))
            self.update()

    def paintEvent(self, _):
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QPainter, QPainterPath, QPen
        from core.events import readable_accent
        from ui.theme import QColor
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        ring = QColor(readable_accent(self.color))
        for i, u in reversed(list(enumerate(self.urls))):
            r = QRectF(2 + i * 34, 3, 46, 46)
            path = QPainterPath()
            path.addEllipse(r)
            p.save()
            p.setClipPath(path)
            pm = self.pix.get(u)
            if pm is not None and not pm.isNull():
                sc = pm.scaled(46, 46, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
                p.drawPixmap(int(r.x()), int(r.y()), sc, (sc.width() - 46) // 2, 0, 46, 46)
            else:
                p.fillRect(r, QColor(30, 32, 46))
            p.restore()
            p.setPen(QPen(ring, 2.5))
            p.drawEllipse(r)
        p.end()
