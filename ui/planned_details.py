"""
Miroku - Plan-to-Watch sections for the detail panel.

A planned anime has no episodes to tick off or rate yet, so instead of the
watching layout the panel shows what you actually want to know while you
wait: when it premieres (live countdown), the trailer, the key facts and
the cast. Everything here reads from the anime row, which
core.metadata_sync keeps fresh.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QPolygonF,
)
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from workers.workers import ImageWorker, run_worker

_FORMATS = {"TV": "TV series", "TV_SHORT": "TV short", "ONA": "ONA", "OVA": "OVA",
            "MOVIE": "Movie", "SPECIAL": "Special", "MUSIC": "Music video"}
_SOURCES = {"MANGA": "Manga", "LIGHT_NOVEL": "Light novel", "ORIGINAL": "Original",
            "VIDEO_GAME": "Video game", "VISUAL_NOVEL": "Visual novel",
            "WEB_NOVEL": "Web novel", "NOVEL": "Novel", "GAME": "Game",
            "WEB_MANGA": "Web manga", "OTHER": "Other"}


def _span(seconds: int) -> str:
    d, rem = divmod(max(0, seconds), 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h:02d}h {m:02d}m"
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


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


class _TrailerThumb(QWidget):
    """16:9 trailer thumbnail with a play button; click to play in-app."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._pix: Optional[QPixmap] = None
        self._hover = False
        self.setToolTip("Play trailer")

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(330, 186)

    def resizeEvent(self, e):
        self.setFixedHeight(max(150, int(self.width() * 9 / 16)))
        super().resizeEvent(e)

    def set_pixmap(self, pix: Optional[QPixmap]):
        self._pix = pix
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.setClipPath(path)
        if self._pix and not self._pix.isNull():
            sc = self._pix.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(0, 0, sc, (sc.width() - self.width()) // 2,
                         (sc.height() - self.height()) // 2, self.width(), self.height())
        else:
            g = QLinearGradient(0, 0, self.width(), self.height())
            g.setColorAt(0, QColor("#1b1840"))
            g.setColorAt(1, QColor("#0f1118"))
            p.fillRect(self.rect(), g)
        shade = QLinearGradient(0, 0, 0, self.height())
        shade.setColorAt(0, QColor(0, 0, 0, 30))
        shade.setColorAt(1, QColor(0, 0, 0, 150 if not self._hover else 110))
        p.fillRect(self.rect(), shade)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 34), 1))
        p.drawPath(path)

        # Play button
        cx, cy, rad = self.width() / 2, self.height() / 2, 26 if not self._hover else 29
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(75, 63, 168, 235) if not self._hover else QColor(98, 84, 205, 245))
        p.drawEllipse(QPointF(cx, cy), rad, rad)
        p.setBrush(QColor("#ffffff"))
        tri = QPolygonF([QPointF(cx - 7, cy - 11), QPointF(cx - 7, cy + 11), QPointF(cx + 12, cy)])
        p.drawPolygon(tri)

        p.setPen(QColor("#e2e4ec"))
        f = QFont(self.font())
        f.setPointSizeF(9)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(12, self.height() - 28, self.width() - 24, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "▶  Watch trailer")
        p.end()


class _Avatar(QLabel):
    def __init__(self, size: int = 52, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.set_pixmap(None)

    def set_pixmap(self, pix: Optional[QPixmap]):
        s = self._size
        out = QPixmap(s, s)
        out.fill(QColor(0, 0, 0, 0))
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath()
        path.addEllipse(1, 1, s - 2, s - 2)
        p.setClipPath(path)
        if pix and not pix.isNull():
            sc = pix.scaled(s, s, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(0, 0, sc, (sc.width() - s) // 2, 0, s, s)
        else:
            p.fillRect(0, 0, s, s, QColor("#1e2236"))
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1.2))
        p.drawEllipse(QRectF(1, 1, s - 2, s - 2))
        p.end()
        self.setPixmap(out)


class PlannedTop(QWidget):
    """Release countdown + trailer, shown near the top for planned anime."""
    move_to_watching = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anime: Optional[Dict] = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # Release
        self.release_card = _card("Release")
        rl = self.release_card.layout()
        self.release_main = QLabel()
        self.release_main.setObjectName("plannedReleaseMain")
        self.release_main.setWordWrap(True)
        self.release_count = QLabel()
        self.release_count.setObjectName("plannedReleaseCount")
        self.release_hint = QLabel()
        self.release_hint.setObjectName("plannedReleaseHint")
        self.release_hint.setWordWrap(True)
        self.start_btn = QPushButton("＋  Move to Watching")
        self.start_btn.setObjectName("primaryBtn")
        self.start_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.start_btn.clicked.connect(
            lambda: self._anime and self.move_to_watching.emit(self._anime["id"]))
        for w in (self.release_main, self.release_count, self.release_hint, self.start_btn):
            rl.addWidget(w)
        lay.addWidget(self.release_card)

        # Trailer
        self.trailer_card = _card("Trailer")
        tl = self.trailer_card.layout()
        self.trailer_thumb = _TrailerThumb()
        self.trailer_thumb.clicked.connect(self._play)
        self.no_trailer = QLabel(
            "No trailer yet. You'll get a notification the moment one drops.")
        self.no_trailer.setObjectName("plannedEmpty")
        self.no_trailer.setWordWrap(True)
        tl.addWidget(self.trailer_thumb)
        tl.addWidget(self.no_trailer)
        lay.addWidget(self.trailer_card)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def load(self, anime: Dict):
        self._anime = anime
        api = (anime.get("status") or "").upper()
        start_ts = anime.get("start_ts") or 0
        exact = bool(anime.get("start_exact")) and start_ts
        next_at = anime.get("next_episode_at") or 0
        label = (anime.get("start_date") or "").strip()

        self.start_btn.setVisible(api in ("RELEASING", "FINISHED"))
        if api == "RELEASING":
            self.release_main.setText("Airing now")
            ep = anime.get("next_episode_num")
            self.release_hint.setText(
                f"Episode {ep - 1} is out. Ready when you are." if ep and ep > 1
                else "It has started. Move it to Watching to track episodes.")
        elif api == "FINISHED":
            self.release_main.setText("Fully released")
            eps = anime.get("total_episodes")
            self.release_hint.setText(f"All {eps} episodes are out." if eps else "Every episode is out.")
        elif exact or next_at:
            ts = next_at or start_ts
            dt = datetime.fromtimestamp(ts)
            self.release_main.setText("Premieres " + dt.strftime("%A, %b ") + f"{dt.day}, {dt.year}")
            self.release_hint.setText("Confirmed date.")
        elif label:
            self.release_main.setText(f"Expected {label}")
            self.release_hint.setText(
                "Exact day not confirmed yet. You'll be notified when it is.")
        else:
            self.release_main.setText("Release date TBA")
            self.release_hint.setText("You'll be notified as soon as a date is announced.")
        self._tick()
        self._timer.start(1000)

        has_trailer = bool(anime.get("trailer_id")) and (anime.get("trailer_site") or "youtube") in ("youtube", "dailymotion")
        self.trailer_thumb.setVisible(has_trailer)
        self.no_trailer.setVisible(not has_trailer)
        self.trailer_thumb.set_pixmap(None)
        if has_trailer:
            thumb = anime.get("trailer_thumb") or (
                f"https://i.ytimg.com/vi/{anime['trailer_id']}/hqdefault.jpg"
                if (anime.get("trailer_site") or "youtube") == "youtube" else "")
            if thumb:
                w = ImageWorker(thumb, ("trailer", anime["id"]))
                w.signals.result.connect(self._on_img)
                run_worker(w)

    def stop(self):
        self._timer.stop()

    def _tick(self):
        a = self._anime or {}
        api = (a.get("status") or "").upper()
        ts = a.get("next_episode_at") or (a.get("start_ts") if a.get("start_exact") else 0)
        now = int(datetime.now().timestamp())
        if api == "NOT_YET_RELEASED" and ts and ts > now:
            self.release_count.setText(f"in {_span(ts - now)}")
            self.release_count.setVisible(True)
        else:
            self.release_count.setVisible(False)

    def _on_img(self, result):
        try:
            (slot, aid), _s, path = result
        except Exception:
            return
        if path and self._anime and self._anime["id"] == aid:
            self.trailer_thumb.set_pixmap(QPixmap(str(path)))

    def _play(self):
        a = self._anime or {}
        if a.get("trailer_id"):
            from ui.trailer_player import show_trailer
            show_trailer(a["trailer_id"], a.get("trailer_site") or "youtube",
                         a.get("english_title") or a.get("romaji_title") or "", self.window())


class PlannedBottom(QWidget):
    """At-a-glance facts + characters, below the synopsis."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anime_id = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self.facts_card = _card("At a glance")
        self.facts_grid = QGridLayout()
        self.facts_grid.setHorizontalSpacing(14)
        self.facts_grid.setVerticalSpacing(8)
        self.facts_card.layout().addLayout(self.facts_grid)
        lay.addWidget(self.facts_card)

        self.chars_card = _card("Characters")
        self.chars_grid = QGridLayout()
        self.chars_grid.setHorizontalSpacing(6)
        self.chars_grid.setVerticalSpacing(10)
        self.chars_card.layout().addLayout(self.chars_grid)
        lay.addWidget(self.chars_card)
        self._avatars: Dict[str, _Avatar] = {}

    @staticmethod
    def _clear(grid: QGridLayout):
        while grid.count():
            it = grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def load(self, anime: Dict):
        self._anime_id = anime["id"]
        self._clear(self.facts_grid)
        eps = anime.get("total_episodes")
        dur = anime.get("duration")
        season = " ".join(x for x in ((anime.get("season") or "").title(),
                                      str(anime.get("season_year") or "")) if x)
        facts = [
            ("Format", _FORMATS.get(anime.get("format") or "", anime.get("format") or "")),
            ("Episodes", f"{eps}" if eps else "TBA"),
            ("Length", f"{dur} min per ep" if dur else ""),
            ("Season", season),
            ("Source", _SOURCES.get(anime.get("source") or "", (anime.get("source") or "").title())),
            ("Studio", ", ".join(anime.get("studios") or [])),
            ("Score", f"★ {anime['average_score'] / 10:.1f}" if anime.get("average_score") else ""),
            ("Popularity", f"{anime['popularity']:,} on AniList" if anime.get("popularity") else ""),
        ]
        row = 0
        for k, v in facts:
            if not v:
                continue
            kl = QLabel(k.upper())
            kl.setObjectName("plannedFactKey")
            vl = QLabel(v)
            vl.setObjectName("plannedFactValue")
            vl.setWordWrap(True)
            self.facts_grid.addWidget(kl, row, 0, alignment=Qt.AlignmentFlag.AlignTop)
            self.facts_grid.addWidget(vl, row, 1)
            row += 1
        self.facts_grid.setColumnStretch(1, 1)

        self._clear(self.chars_grid)
        self._avatars.clear()
        chars: List[Dict] = anime.get("characters") or []
        self.chars_card.setVisible(bool(chars))
        for i, c in enumerate(chars[:8]):
            cell = QWidget()
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(4)
            av = _Avatar(52)
            cl.addWidget(av, alignment=Qt.AlignmentFlag.AlignHCenter)
            name = QLabel(c.get("name", ""))
            name.setObjectName("plannedCharName")
            name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            name.setWordWrap(True)
            name.setFixedWidth(76)
            cl.addWidget(name, alignment=Qt.AlignmentFlag.AlignHCenter)
            role = QLabel(c.get("role", ""))
            role.setObjectName("plannedCharRole")
            role.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            cl.addWidget(role, alignment=Qt.AlignmentFlag.AlignHCenter)
            self.chars_grid.addWidget(cell, i // 4, i % 4, alignment=Qt.AlignmentFlag.AlignTop)
            if c.get("image"):
                self._avatars[c["image"]] = av
                w = ImageWorker(c["image"], ("char", anime["id"], c["image"]))
                w.signals.result.connect(self._on_img)
                run_worker(w)

    def _on_img(self, result):
        try:
            (_slot, aid, url), _s, path = result
        except Exception:
            return
        av = self._avatars.get(url)
        if path and av is not None and aid == self._anime_id:
            try:
                av.set_pixmap(QPixmap(str(path)))
            except RuntimeError:
                pass
