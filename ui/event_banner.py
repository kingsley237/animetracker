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
        """Show the banner if an event is on and you haven't answered yet this year."""
        tm = ThemeManager.get()
        ev = getattr(tm, "event", None)
        if self.layout() is None:
            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
        old = getattr(self, "_inner", None)
        if old is not None:
            self.layout().removeWidget(old)
            old.deleteLater()
            self._inner = None
        if ev is None or events.choice(ev):
            self.hide()
            return
        self.ev = ev
        level = tm.event_level
        self._inner = QWidget()
        self._inner.setObjectName("eventBannerInner")
        self.layout().addWidget(self._inner)
        lay = QHBoxLayout(self._inner)
        lay.setContentsMargins(16, 12, 12, 12)
        lay.setSpacing(14)
        lay.addWidget(AnimatedEmoji(ev["anim"], 44))
        col = QVBoxLayout()
        col.setSpacing(2)
        own = info(tm.saved_id)["name"]
        if level == "full":
            title, sub = ev["line"], f"Showing the “{info(events.variant(ev))['name']}” look until the event ends."
            buttons = [("Keep it", True, self._keep), ("Switch back", False, self._off),
                       ("Try the other looks ▾", False, self._looks)]
        elif level == "decorations":
            title = f"A little {ev['name']} on top of {own}."
            sub = "Your theme stays — the event adds a few festive details."
            buttons = [("Nice", True, self._keep), (f"Go full {ev['name']}", False, self._full),
                       ("No decorations", False, self._off)]
        else:
            title, sub = f"It's {ev['name']}! Dress Raikō up?", "You asked to be asked first."
            buttons = [("Yes, dress up", True, self._full), ("Just decorations", False, self._deco),
                       ("No thanks", False, self._off)]
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
            b.clicked.connect(lambda _=False, cb=cb, b=b: cb(b))
            lay.addWidget(b)
        x = QPushButton("✕")
        x.setObjectName("eventBannerClose")
        x.setFixedSize(28, 28)
        x.setToolTip("Close — the event stays as it is")
        x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x.clicked.connect(self._close)
        lay.addWidget(x, alignment=Qt.AlignmentFlag.AlignTop)
        self._inner.show()
        self.setMinimumHeight(max(72, self._inner.sizeHint().height()))
        self.show()

    # ── choices ──────────────────────────────────────────────────────────────

    def _done(self, msg: Optional[str] = None):
        self.hide()
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

    def _close(self):
        events.set_choice(self.ev, "kept")
        self.hide()
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
