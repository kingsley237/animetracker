"""
Raikō — onboarding.

1. Welcome (full-window, centred): the Raikō mark, what Home, Miroku and
   Kinema are, and your country for release dates & streaming. New users
   get "Welcome to Raikō"; people upgrading from Miroku get "What's new".
2. Spotlight tour: dims the window except one element, with a card that
   explains it. Steps can switch pages first (Home → Library → Discover…).

Shown once (setting 'onboarding_v3_seen'). Settings can replay it.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from PyQt6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

RES = Path(__file__).parent.parent / "resources"

# (page to open first or "", target on MainWindow, title, description)
# target: attribute path ("_home_page.search") or "nav:<page id>"
TOUR_STEPS: List[Tuple[str, str, str, str]] = [
    ("home", "_home_page.hero", "Home — your hub",
     "What to watch next across anime, shows and movies. The spotlight is your most pressing title: "
     "one click marks the episode watched."),
    ("home", "_home_page.search", "Search everything  ·  Ctrl+K",
     "One box for your whole library. Nothing there yet? Jump straight to AniList or TMDB from the results."),
    ("home", "nav:library", "Miroku — anime",
     "Library, Dropped and Discover for anime, powered by AniList: airing countdowns, episodes, ratings "
     "and new-season alerts."),
    ("home", "nav:movies", "Kinema — movies & TV",
     "Movies and TV shows from TMDB: seasons and episodes, release and \"out in HD\" dates, where to "
     "watch, trailers."),
    ("home", "_add_btn", "Add anything  ·  Ctrl+N",
     "Adds to the library you're in. Browse lists and recommendations or search; the preview shows the "
     "official trailer and the cast."),
    ("library", "_cards_area", "Cards & the detail panel",
     "Hover a card for a one-click ✓ on the next episode. Click it for the full panel: up next, episodes "
     "(right-click for 'watched up to here'), trailers, where to watch."),
    ("home", "_settings_btn", "Settings & Data Doctor",
     "Your country, alerts, backups and AniList. If anything ever looks wrong, a Data Doctor alert offers "
     "to check and fix your library in one click."),
]


def _resolve(mw, target: str) -> Optional[QWidget]:
    if target.startswith("nav:"):
        return getattr(mw, "_nav_buttons", {}).get(target[4:])
    if target == "_cards_area":
        return getattr(mw, "scroll_area", None) or getattr(mw, "grid_container", None)
    obj = mw
    for part in target.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj if isinstance(obj, QWidget) else None


class _FollowParent:
    """Mixin: an overlay that always covers its parent, whatever the window does
    (maximize, resize) after it was created."""

    def _follow_parent(self):
        self.setGeometry(self.parentWidget().rect())
        self.parentWidget().installEventFilter(self)

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if obj is self.parentWidget() and ev.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return False


# ── welcome ───────────────────────────────────────────────────────────────────

class _Tile(QWidget):
    def __init__(self, icon: str, color: str, title: str, body: str, parent=None):
        super().__init__(parent)
        self.setObjectName("welcomeTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        l = QVBoxLayout(self)
        l.setContentsMargins(18, 16, 18, 16)
        l.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(10)
        ic = QLabel()
        ic.setFixedSize(30, 30)
        px = RES / icon
        if px.exists():
            ic.setPixmap(QPixmap(str(px)).scaled(30, 30, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))
        else:
            ic.setText("●")
            ic.setStyleSheet(f"color:{color};font-size:18px;")
        top.addWidget(ic)
        t = QLabel(title)
        t.setStyleSheet(f"color:{color};font-size:15px;font-weight:800;background:transparent;")
        top.addWidget(t)
        top.addStretch()
        l.addLayout(top)
        b = QLabel(body)
        b.setWordWrap(True)
        b.setStyleSheet("color:#a8aec6;font-size:12px;background:transparent;")
        l.addWidget(b)
        l.addStretch()


class WelcomeOverlay(_FollowParent, QWidget):
    tour = pyqtSignal()
    done = pyqtSignal()

    def __init__(self, parent: QWidget, upgrading: bool):
        super().__init__(parent)
        self._follow_parent()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        card = QWidget(self)
        card.setObjectName("welcomeCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setFixedWidth(760)
        self.card = card
        lay = QVBoxLayout(card)
        lay.setContentsMargins(40, 34, 40, 30)
        lay.setSpacing(12)

        mark = QLabel()
        wm = RES / "raiko_wordmark_1600x600.png"
        if wm.exists():
            mark.setPixmap(QPixmap(str(wm)).scaledToWidth(300, Qt.TransformationMode.SmoothTransformation))
        else:
            mark.setText("Raikō")
            mark.setStyleSheet("color:#f4f5fa;font-size:34px;font-weight:900;")
        lay.addWidget(mark, alignment=Qt.AlignmentFlag.AlignHCenter)

        head = QLabel("Miroku is now Raikō" if upgrading else "Welcome to Raikō")
        head.setObjectName("welcomeHead")
        head.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(head)
        sub = QLabel(
            "Your anime library is all here, now joined by TV shows and movies, in one app."
            if upgrading else
            "Everything you watch, in one light: anime, TV shows and movies, tracked in one place.")
        sub.setObjectName("welcomeSub")
        sub.setWordWrap(True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(8)

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        tiles.addWidget(_Tile("raiko_glyph_64.png", "#f4f5fa", "Home",
                              "Continue watching, this week's schedule and movies ready in HD. "
                              "Ctrl+K searches everything."), 1)
        tiles.addWidget(_Tile("miroku_mark_64.png", "#b8adff", "Miroku",
                              "Anime from AniList: airing countdowns, episodes, ratings, new-season alerts."), 1)
        tiles.addWidget(_Tile("kinema_mark_64.png", "#fde68a", "Kinema",
                              "Movies & TV from TMDB: seasons, release and HD dates, where to watch."), 1)
        lay.addLayout(tiles)
        lay.addSpacing(6)

        region = QHBoxLayout()
        rl = QLabel("Your country, for release dates and where to watch")
        rl.setStyleSheet("color:#c7cbe0;font-size:12px;background:transparent;")
        region.addWidget(rl)
        region.addStretch()
        self.country = QComboBox()
        self.country.setFixedWidth(220)
        try:
            from ui.settings_dialog import REGIONS  # type: ignore
        except Exception:
            REGIONS = [("United States", "US"), ("United Kingdom", "GB"), ("Canada", "CA"),
                       ("Australia", "AU"), ("Germany", "DE"), ("France", "FR"), ("Spain", "ES"),
                       ("Italy", "IT"), ("Japan", "JP"), ("Brazil", "BR"), ("Mexico", "MX"),
                       ("India", "IN"), ("Nigeria", "NG"), ("Cameroon", "CM"), ("South Africa", "ZA")]
        try:
            from core import tmdb
            cur = tmdb.region()
        except Exception:
            cur = "US"
        for name, code in REGIONS:
            self.country.addItem(name, code)
        idx = self.country.findData(cur)
        self.country.setCurrentIndex(max(0, idx))
        region.addWidget(self.country)
        lay.addLayout(region)
        lay.addSpacing(10)

        btns = QHBoxLayout()
        skip = QPushButton("Skip")
        skip.setObjectName("welcomeSkip")
        go = QPushButton("Take the 1-minute tour  →")
        go.setObjectName("welcomeGo")
        for b in (skip, go):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(42)
        btns.addWidget(skip)
        btns.addStretch()
        btns.addWidget(go)
        lay.addLayout(btns)
        skip.clicked.connect(lambda: self._close(False))
        go.clicked.connect(lambda: self._close(True))
        self._place()
        self.show()
        self.raise_()

    def _save_region(self):
        code = self.country.currentData()
        if not code:
            return
        try:
            from core.app_settings import app_settings
            app_settings().setValue("tmdb_region", code)
        except Exception:
            pass

    def _close(self, tour: bool):
        self._save_region()
        self.hide()
        (self.tour if tour else self.done).emit()
        self.deleteLater()

    def _place(self):
        self.card.adjustSize()
        self.card.move((self.width() - self.card.width()) // 2,
                       max(20, (self.height() - self.card.height()) // 2))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(4, 5, 9, 215))
        p.end()


# ── spotlight tour ────────────────────────────────────────────────────────────

class OnboardingOverlay(_FollowParent, QWidget):
    finished = pyqtSignal()

    def __init__(self, main_window, parent: QWidget, steps=None):
        super().__init__(parent)
        self._mw = main_window
        self._steps = steps or TOUR_STEPS
        self._current = 0
        self._spotlight = QRect()
        self._follow_parent()
        self._card = _TourCard(self)
        self._card.next_clicked.connect(self._next)
        self._card.back_clicked.connect(self._back)
        self._card.skip_clicked.connect(self._finish)
        self.show()
        self.raise_()
        self._show_step(0)

    def _show_step(self, idx: int):
        if idx >= len(self._steps):
            self._finish()
            return
        self._current = max(0, idx)
        page, target, title, desc = self._steps[self._current]
        if page and getattr(self._mw, "current_page", None) != page:
            self._mw._navigate(page)
            self.raise_()
        self._card.set_content(self._current + 1, len(self._steps), title, desc,
                               is_last=self._current == len(self._steps) - 1,
                               first=self._current == 0)
        QTimer.singleShot(30, lambda t=target: self._bring_into_view(t))
        # re-measure as the page settles (scrolling, a library that just loaded, images…)
        for ms in (60, 450, 1200):
            QTimer.singleShot(ms, lambda t=target: self._spot(t))

    def _bring_into_view(self, target: str):
        """Scroll whatever page holds the target so it's on screen - e.g. the
        search bar when the tour is replayed with Home scrolled down."""
        from PyQt6 import sip
        from PyQt6.QtWidgets import QScrollArea
        if sip.isdeleted(self) or target != self._steps[self._current][1]:
            return
        w = _resolve(self._mw, target)
        if w is None:
            return
        if isinstance(w, QScrollArea):            # a whole list: show it from the top
            w.verticalScrollBar().setValue(0)
            return
        p = w.parentWidget()
        while p is not None and not isinstance(p, QScrollArea):
            p = p.parentWidget()
        if p is not None:
            if w.mapTo(p.widget(), QPoint(0, 0)).y() < 300:
                p.verticalScrollBar().setValue(0)  # header items: go right to the top
            else:
                p.ensureWidgetVisible(w, 40, 80)

    def _spot(self, target: str):
        from PyQt6 import sip
        if sip.isdeleted(self) or target != self._steps[self._current][1]:
            return                      # a late update for a step we've already left
        w = _resolve(self._mw, target)
        if w is not None and w.isVisible():
            tl = self.mapFromGlobal(w.mapToGlobal(QPoint(0, 0)))
            r = QRect(tl, w.size())
            if r.height() > self.height() * 0.6:          # a big area: spotlight its top part
                r.setHeight(int(self.height() * 0.45))
            # never point outside the window
            self._spotlight = r.adjusted(-8, -8, 8, 8).intersected(self.rect().adjusted(4, 4, -4, -4))
        else:
            self._spotlight = QRect()
        self._position_card()
        self.update()

    def _position_card(self):
        cw = 360
        self._card.setFixedWidth(cw)
        self._card.adjustSize()
        ch = self._card.height()
        if self._spotlight.isNull():
            cx, cy = (self.width() - cw) // 2, (self.height() - ch) // 2
        else:
            s = self._spotlight
            if s.right() + cw + 24 < self.width() and s.width() < self.width() * 0.4:
                cx, cy = s.right() + 18, s.top()               # to the right of small targets
            else:
                cx, cy = s.left(), s.bottom() + 16
                if cy + ch > self.height() - 16:
                    cy = s.top() - ch - 16
            cx = max(16, min(cx, self.width() - cw - 16))
            cy = max(16, min(cy, self.height() - ch - 16))
        self._card.move(cx, cy)
        self._card.show()
        self._card.raise_()

    def _next(self):
        self._show_step(self._current + 1)

    def _back(self):
        self._show_step(self._current - 1)

    def _finish(self):
        self.hide()
        self.finished.emit()
        self.deleteLater()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        full = QPainterPath()
        full.addRect(QRectF(self.rect()))
        if not self._spotlight.isNull():
            cut = QPainterPath()
            cut.addRoundedRect(QRectF(self._spotlight), 14, 14)
            full = full.subtracted(cut)
        p.fillPath(full, QColor(3, 4, 8, 190))
        if not self._spotlight.isNull():
            for i, a in ((6, 40), (3, 90)):
                p.setPen(QPen(QColor(139, 123, 255, a), i))
                p.drawRoundedRect(QRectF(self._spotlight), 14, 14)
            p.setPen(QPen(QColor("#b8adff"), 1.5))
            p.drawRoundedRect(QRectF(self._spotlight), 14, 14)
        p.end()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._steps:
            QTimer.singleShot(0, lambda: self._spot(self._steps[self._current][1]))


class _TourCard(QWidget):
    next_clicked = pyqtSignal()
    back_clicked = pyqtSignal()
    skip_clicked = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("tourCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(8)
        top = QHBoxLayout()
        self._counter = QLabel()
        self._counter.setObjectName("tourCounter")
        top.addWidget(self._counter)
        top.addStretch()
        self._dots = QLabel()
        self._dots.setObjectName("tourDots")
        top.addWidget(self._dots)
        lay.addLayout(top)
        self._title = QLabel()
        self._title.setObjectName("tourTitle")
        self._title.setWordWrap(True)
        lay.addWidget(self._title)
        self._desc = QLabel()
        self._desc.setObjectName("tourDesc")
        self._desc.setWordWrap(True)
        lay.addWidget(self._desc)
        lay.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(8)
        self._skip = QPushButton("Skip tour")
        self._skip.setObjectName("tourSkip")
        self._back = QPushButton("Back")
        self._back.setObjectName("tourBack")
        self._next = QPushButton("Next  →")
        self._next.setObjectName("tourNext")
        for b in (self._skip, self._back, self._next):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip.clicked.connect(self.skip_clicked)
        self._back.clicked.connect(self.back_clicked)
        self._next.clicked.connect(self.next_clicked)
        row.addWidget(self._skip)
        row.addStretch()
        row.addWidget(self._back)
        row.addWidget(self._next)
        lay.addLayout(row)

    def set_content(self, step: int, total: int, title: str, description: str,
                    is_last: bool, first: bool = False):
        self._counter.setText(f"STEP {step} OF {total}")
        self._dots.setText("".join("●" if i == step else "○" for i in range(1, total + 1)))
        self._title.setText(title)
        self._desc.setText(description)
        self._next.setText("Start watching  ✓" if is_last else "Next  →")
        self._skip.setVisible(not is_last)
        self._back.setVisible(not first)
