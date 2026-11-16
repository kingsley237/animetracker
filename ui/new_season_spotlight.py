"""
Miroku - New-season spotlight.

A rich, art-led floating card that tells the user a sequel of something they
completed (or dropped) was announced, started airing, or is fully out.

Anchored bottom-right of the main window so it never collides with the
compact notification banner (top-right). Renders entirely from the
notification payload built by core.notification_service, so it shows
instantly with no network round-trip; artwork streams in afterwards.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import (
    Qt, QTimer, QRectF, QPoint, QPropertyAnimation, QEasingCurve, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QCursor, QFontMetrics, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QMenu,
    QPushButton, QVBoxLayout, QWidget,
)

from workers.workers import ImageWorker, Worker, run_worker

CARD_W = 460
HERO_H = 138
COVER_W, COVER_H = 70, 100
COVER_OVERLAP = 46          # how far the cover pokes up into the hero
RADIUS = 14
BG = QColor("#0f1118")
BORDER = QColor("#262b42")

# phase -> (badge text, accent, badge bg)
_PHASES = {
    "airing":    ("NEW SEASON · AIRING", "#fbbf24", "rgba(40, 28, 4, 0.92)"),
    "announced": ("SEASON ANNOUNCED",    "#a594f9", "rgba(24, 18, 56, 0.92)"),
    "complete":  ("NEW SEASON · OUT NOW", "#34d399", "rgba(6, 34, 25, 0.92)"),
}
_PHASE_ORDER = {"airing": 0, "announced": 1, "complete": 2}


def _rgba(color: str, alpha: float) -> str:
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def _fmt_span(seconds: int) -> str:
    d, rem = divmod(max(0, seconds), 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d >= 1:
        return f"{d}d {h:02d}h"
    if h >= 1:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


def _format_label(fmt: str) -> str:
    return {"TV": "TV", "TV_SHORT": "TV Short", "ONA": "ONA", "MOVIE": "Movie"}.get(fmt or "", fmt or "")


def _sort_key(item: Dict):
    p = item.get("payload") or {}
    seq = p.get("sequel") or {}
    phase = p.get("phase")
    when = seq.get("next_airing_at") or seq.get("start_ts") or 9_999_999_999
    # announced titles with no date at all sink below the dated ones
    if phase == "announced" and not seq.get("start_ts"):
        when = 9_999_999_999
    return (_PHASE_ORDER.get(phase, 3), when)


class _Cover(QWidget):
    """Rounded, anti-aliased cover thumbnail with a hairline ring."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(COVER_W, COVER_H)
        self._pix: Optional[QPixmap] = None
        self._tint = QColor("#2a2f48")

    def set_tint(self, color: str):
        if color:
            self._tint = QColor(color)
        self.update()

    def set_pixmap(self, pix: Optional[QPixmap]):
        self._pix = pix
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.setClipPath(path)
        if self._pix and not self._pix.isNull():
            scaled = self._pix.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (scaled.width() - self.width()) // 2
            y = (scaled.height() - self.height()) // 2
            p.drawPixmap(0, 0, scaled, x, y, self.width(), self.height())
        else:
            p.fillPath(path, self._tint.darker(160))
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 46), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()


class NewSeasonSpotlight(QFrame):
    """Queue-driven spotlight card for `new_season` notifications."""

    dismissed = pyqtSignal(int)           # notification id ("Not interested" / ✕)
    remind_later = pyqtSignal(int)        # notification id
    open_prequel = pyqtSignal(int)        # local anime id
    add_requested = pyqtSignal(int, str)  # notification id, watch_status

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("newSeasonSpotlight")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(CARD_W)
        self._queue: List[Dict] = []
        self._index = 0
        self._paused = False
        self._banner: Optional[QPixmap] = None
        self._img_cache: Dict[str, QPixmap] = {}
        self._anim: Optional[QPropertyAnimation] = None

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(42)
        shadow.setOffset(0, 14)
        shadow.setColor(QColor(0, 0, 0, 170))
        self.setGraphicsEffect(shadow)
        self._shadow = shadow

        self._build()
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._update_time_signal)
        self.hide()

    # ── Public API ────────────────────────────────────────────────────────────

    def show_notifications(self, items: List[Dict]):
        known = {n.get("id") for n in self._queue}
        added = False
        for item in items or []:
            if item.get("kind") != "new_season" or item.get("id") in known:
                continue
            self._queue.append(item)
            added = True
        if not added:
            return
        current = self._current()
        self._queue.sort(key=_sort_key)
        if current is not None and current in self._queue:
            self._index = self._queue.index(current)
        if not self.isVisible() and not self._paused:
            self._index = 0 if current is None else self._index
            self._render(animate=True)
        else:
            self._update_pager()

    def has_notification_for_prequel(self, anime_id: int) -> bool:
        return any((n.get("anime_id") == anime_id) for n in self._queue)

    def focus_prequel(self, anime_id: int, items: List[Dict]):
        """Bring the alert for a given prequel to the front (card ribbon click)."""
        self.show_notifications(items)
        for i, n in enumerate(self._queue):
            if n.get("anime_id") == anime_id:
                self._index = i
                self._paused = False
                self._render(animate=not self.isVisible())
                return

    def pause_for_detail(self):
        self._paused = True
        self._tick_timer.stop()
        self.hide()

    def resume_after_detail(self):
        self._paused = False
        if self._queue and not self.isVisible():
            self._render(animate=True)

    def remove_notification(self, notification_id: int):
        """Drop an item (after it was acted on) and advance."""
        for i, n in enumerate(self._queue):
            if n.get("id") == notification_id:
                self._queue.pop(i)
                if i < self._index or self._index >= len(self._queue):
                    self._index = max(0, self._index - 1) if i < self._index else 0
                break
        if not self._queue:
            self._tick_timer.stop()
            self.hide()
            return
        if not self._paused:
            self._render(animate=False)

    def reposition(self):
        parent = self.parentWidget()
        if not parent:
            return
        margin = 20
        self.move(parent.width() - self.width() - margin,
                  parent.height() - self.height() - margin)

    # ── Construction ──────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Hero area — painted by paintEvent; holds only overlay controls.
        self._hero = QWidget(self)
        self._hero.setFixedHeight(HERO_H)
        self._hero.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        hero_lay = QHBoxLayout(self._hero)
        hero_lay.setContentsMargins(16, 14, 12, 0)
        hero_lay.setSpacing(6)
        hero_lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._badge = QLabel()
        self._badge.setObjectName("spotlightBadge")
        hero_lay.addWidget(self._badge, alignment=Qt.AlignmentFlag.AlignTop)
        hero_lay.addStretch()

        self._prev_btn = self._chip_button("‹", "Previous")
        self._prev_btn.clicked.connect(lambda: self._step(-1))
        self._pager = QLabel()
        self._pager.setObjectName("spotlightPager")
        self._next_btn = self._chip_button("›", "Next")
        self._next_btn.clicked.connect(lambda: self._step(1))
        for w in (self._prev_btn, self._pager, self._next_btn):
            hero_lay.addWidget(w, alignment=Qt.AlignmentFlag.AlignTop)
        hero_lay.addSpacing(4)
        close = self._chip_button("✕", "Close (shows again later)")
        close.clicked.connect(self._close_for_now)
        hero_lay.addWidget(close, alignment=Qt.AlignmentFlag.AlignTop)
        root.addWidget(self._hero)

        body = QVBoxLayout()
        body.setContentsMargins(18, 10, 18, 16)
        body.setSpacing(10)

        # Identity — indented past the overlapping cover
        ident = QHBoxLayout()
        ident.setSpacing(0)
        ident.addSpacing(COVER_W + 14)
        ident_col = QVBoxLayout()
        ident_col.setSpacing(3)
        ident_col.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._title = QLabel()
        self._title.setObjectName("spotlightTitle")
        self._title.setWordWrap(True)
        self._title.setFixedWidth(CARD_W - 36 - COVER_W - 14)
        self._meta = QLabel()
        self._meta.setObjectName("spotlightMeta")
        ident_col.addWidget(self._title)
        ident_col.addWidget(self._meta)
        ident.addLayout(ident_col, 1)
        ident_wrap = QWidget()
        ident_wrap.setObjectName("spotlightIdent")
        ident_wrap.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        ident_wrap.setStyleSheet("QWidget#spotlightIdent{background:transparent;}")
        ident_wrap.setLayout(ident)
        ident.setContentsMargins(0, 0, 0, 0)
        # just tall enough that the next row clears the overlapping cover
        ident_wrap.setMinimumHeight(COVER_H - COVER_OVERLAP - 4)
        body.addWidget(ident_wrap)

        # Why line + time signal
        self._why = QLabel()
        self._why.setObjectName("spotlightWhy")
        self._why.setTextFormat(Qt.TextFormat.RichText)
        self._why.setWordWrap(True)
        self._why.setFixedWidth(CARD_W - 36)
        self._why.linkActivated.connect(self._on_why_link)
        body.addWidget(self._why)

        self._when = QLabel()
        self._when.setObjectName("spotlightWhen")
        body.addWidget(self._when, alignment=Qt.AlignmentFlag.AlignLeft)

        self._synopsis = QLabel()
        self._synopsis.setObjectName("spotlightSynopsis")
        self._synopsis.setWordWrap(False)   # lines are pre-wrapped/elided
        body.addWidget(self._synopsis)

        body.addSpacing(2)
        self._actions = QHBoxLayout()
        self._actions.setSpacing(8)
        body.addLayout(self._actions)

        root.addLayout(body)

        self._cover = _Cover(self)
        self._cover.move(18, HERO_H - COVER_OVERLAP)
        self._cover.raise_()

    def _chip_button(self, text: str, tip: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("spotlightChip")
        b.setFixedSize(26, 26)
        b.setToolTip(tip)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        return b

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _current(self) -> Optional[Dict]:
        if 0 <= self._index < len(self._queue):
            return self._queue[self._index]
        return None

    def _render(self, animate: bool = False):
        item = self._current()
        if item is None or self._paused:
            return
        payload = item.get("payload") or {}
        seq = payload.get("sequel") or {}
        pre = payload.get("prequel") or {}
        phase = payload.get("phase") or "announced"
        dropped = pre.get("source") == "dropped"

        text, accent, badge_bg = _PHASES.get(phase, _PHASES["announced"])
        if dropped:
            text = "FROM YOUR DROPPED · " + text.split(" · ")[-1]
        self._accent = accent
        self._badge.setText(text)
        self._badge.setStyleSheet(
            f"color:{accent};background:{badge_bg};"
            f"border:1px solid {_rgba(accent, 0.35)};"
        )

        self._title.setText(seq.get("title") or "New season")
        self._title.setToolTip(seq.get("romaji") or "")

        meta = [_format_label(seq.get("format"))]
        if seq.get("episodes") and seq.get("format") != "MOVIE":
            meta.append(f"{seq['episodes']} eps")
        if seq.get("season") and seq.get("season_year"):
            meta.append(f"{seq['season'].title()} {seq['season_year']}")
        elif seq.get("start_label"):
            meta.append(seq["start_label"])
        if seq.get("score"):
            meta.append(f"★ {seq['score'] / 10:.1f}")
        if seq.get("studios"):
            meta.append(seq["studios"][0])
        self._meta.setText("  ·  ".join(m for m in meta if m))

        self._why.setText(self._why_html(pre))
        self._synopsis.setText(self._elide_lines(seq.get("synopsis") or "", 2))
        self._synopsis.setVisible(bool(seq.get("synopsis")))

        self._build_actions(item, phase, seq)
        self._update_time_signal()
        self._update_pager()

        # Artwork
        self._banner = None
        self._cover.set_pixmap(None)
        self._cover.set_tint(seq.get("cover_color") or "")
        self._load_image(seq.get("banner_url") or seq.get("cover_url"), "banner", item.get("id"))
        self._load_image(seq.get("cover_url"), "cover", item.get("id"))

        self._fit_and_place(animate)
        self._tick_timer.start(1000)

    def _why_html(self, pre: Dict) -> str:
        name = (pre.get("title") or "an anime").replace("<", "&lt;")
        muted = "#7b84a3"
        if pre.get("source") == "dropped":
            at = pre.get("last_episode")
            where = f" at episode {at}" if at else ""
            return (f"<span style='color:{muted}'>You dropped </span>"
                    f"<span style='color:#e2e4ec'>{name}</span>"
                    f"<span style='color:{muted}'>{where} — the story continues. "
                    f"Worth another shot?</span>")
        link = (f"<a href='prequel' style='color:#c4b8ff;text-decoration:none'>{name}</a>"
                if pre.get("anime_id") and pre["anime_id"] > 0 else
                f"<span style='color:#e2e4ec'>{name}</span>")
        tail = ""
        rating = pre.get("rating")
        if rating:
            tail = f" · you rated it <span style='color:#fbbf24'>{rating:.0f}/6</span>"
        return (f"<span style='color:{muted}'>Sequel to </span>{link}"
                f"<span style='color:{muted}'>, which you completed{tail}</span>")

    def _update_time_signal(self):
        item = self._current()
        if not item:
            return
        p = item.get("payload") or {}
        seq = p.get("sequel") or {}
        phase = p.get("phase")
        now = int(datetime.now().timestamp())
        dot, color = "●", self._accent if hasattr(self, "_accent") else "#a594f9"

        if phase == "airing":
            at, ep = seq.get("next_airing_at"), seq.get("next_episode")
            if at and at > now:
                text = f"Episode {ep} airs in {_fmt_span(at - now)}" if ep else f"Next episode in {_fmt_span(at - now)}"
            elif ep and ep > 1:
                text = f"Airing now — episode {ep} is out"
            else:
                text = "Airing now"
        elif phase == "announced":
            start = seq.get("start_ts") or 0
            if seq.get("start_exact") and start > now:
                text = f"Premieres in {_fmt_span(start - now)}  ·  {seq.get('start_label')}"
            elif seq.get("start_label"):
                text = f"Premieres {seq['start_label']}"
            elif seq.get("season") and seq.get("season_year"):
                text = f"Expected {seq['season'].title()} {seq['season_year']}"
            else:
                dot, color = "○", "#9da5c0"
                text = "Release date not announced yet"
        else:
            eps = seq.get("episodes")
            if seq.get("format") == "MOVIE":
                text = "Out now — ready to watch"
            elif eps:
                text = f"All {eps} episodes are out — ready to binge"
            else:
                text = "Fully released — ready to binge"
        self._when.setText(f"{dot}  {text}")
        self._when.setStyleSheet(
            f"color:{color};background:{_rgba(color, 0.10)};"
            f"border:1px solid {_rgba(color, 0.28)};"
        )

    def _update_pager(self):
        many = len(self._queue) > 1
        for w in (self._prev_btn, self._pager, self._next_btn):
            w.setVisible(many)
        if many:
            self._pager.setText(f"{self._index + 1} / {len(self._queue)}")

    def _elide_lines(self, text: str, lines: int) -> str:
        """Greedy word-wrap into at most `lines` lines, eliding the last."""
        if not text:
            return ""
        fm = QFontMetrics(self._synopsis.font())
        width = CARD_W - 40
        words, out, line, i = text.split(), [], "", 0
        while i < len(words):
            trial = f"{line} {words[i]}".strip()
            if fm.horizontalAdvance(trial) <= width or not line:
                line = trial
                i += 1
                continue
            out.append(line)
            line = ""
            if len(out) == lines:
                break
        if line and len(out) < lines:
            out.append(line)
        if i < len(words) and out:
            tail = out[-1] + " " + " ".join(words[i:])
            out[-1] = fm.elidedText(tail, Qt.TextElideMode.ElideRight, width)
        return "\n".join(out)

    def _build_actions(self, item: Dict, phase: str, seq: Dict):
        while self._actions.count():
            it = self._actions.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        nid = item.get("id")

        def btn(label, obj, cb, tip=""):
            b = QPushButton(label)
            b.setObjectName(obj)
            b.setMinimumHeight(34)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(cb)
            self._actions.addWidget(b)
            return b

        if phase == "announced":
            btn("＋  Plan to Watch", "primaryBtn",
                lambda: self.add_requested.emit(nid, "planned"),
                "Add to your library as Plan to Watch")
        elif phase == "airing":
            btn("＋  Start Watching", "primaryBtn",
                lambda: self.add_requested.emit(nid, "watching"),
                "Add to your library as Watching")
        else:
            btn("View Details", "primaryBtn", lambda: self._open_details(seq))

        if seq.get("trailer_id") and seq.get("trailer_site") in ("youtube", "dailymotion"):
            btn("▶  Trailer", "secondaryBtn", lambda: self._open_trailer(seq))
        if phase != "complete":
            btn("Details", "secondaryBtn", lambda: self._open_details(seq))

        self._actions.addStretch()
        more = QPushButton("•••")
        more.setObjectName("spotlightMore")
        more.setFixedSize(38, 34)
        more.setToolTip("More options")
        more.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        menu = QMenu(more)
        menu.setObjectName("spotlightMenu")
        menu.addAction("Remind me tomorrow", lambda: self._remind(nid))
        menu.addAction("Not interested", lambda: self._dismiss(nid))
        more.clicked.connect(
            lambda: menu.exec(more.mapToGlobal(QPoint(more.width() - menu.sizeHint().width(), more.height() + 4)))
        )
        self._actions.addWidget(more)

    def _needed_height(self) -> int:
        self.ensurePolished()   # QSS fonts must be applied before measuring
        lay = self.layout()
        lay.invalidate()
        lay.activate()
        h = max(lay.sizeHint().height(), lay.minimumSize().height())
        if lay.hasHeightForWidth():
            h = max(h, lay.totalHeightForWidth(CARD_W))
        return max(h, HERO_H + 180)

    def _invalidate_shadow(self):
        # QGraphicsDropShadowEffect caches the rendered card; without this a
        # page switch can briefly show the previous card's layout.
        self._shadow.updateBoundingRect()
        self._shadow.update()
        self.update()

    def _refit(self):
        """Second pass once the card is on screen and fully styled."""
        self._invalidate_shadow()
        h = self._needed_height()
        if h != self.height():
            self.setFixedHeight(h)
            if not (self._anim and self._anim.state() == QPropertyAnimation.State.Running):
                self.reposition()
            elif self._anim:
                end = self._anim.endValue()
                self._anim.setEndValue(QPoint(end.x(), self.parentWidget().height() - h - 20))

    def _fit_and_place(self, animate: bool):
        self.setFixedHeight(self._needed_height())
        self.reposition()
        self.show()
        self.raise_()
        QTimer.singleShot(0, self._refit)
        if animate:
            end = self.pos()
            start = QPoint(end.x(), end.y() + 28)
            self.move(start)
            self._anim = QPropertyAnimation(self, b"pos", self)
            self._anim.setDuration(240)
            self._anim.setStartValue(start)
            self._anim.setEndValue(end)
            self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._anim.start()

    # ── Images ────────────────────────────────────────────────────────────────

    def _load_image(self, url: str, slot: str, nid):
        if not url:
            return
        if url in self._img_cache:
            self._apply_image(slot, nid, self._img_cache[url])
            return
        w = ImageWorker(url, (slot, nid, url))
        w.signals.result.connect(self._on_image)
        run_worker(w)

    def _on_image(self, result):
        try:
            (slot, nid, url), _size, path = result
        except Exception:
            return
        if not path:
            return
        pix = QPixmap(str(path))
        if pix.isNull():
            return
        self._img_cache[url] = pix
        self._apply_image(slot, nid, pix)

    def _apply_image(self, slot: str, nid, pix: QPixmap):
        cur = self._current()
        if not cur or cur.get("id") != nid:
            return
        if slot == "banner":
            self._banner = pix
        else:
            self._cover.set_pixmap(pix)
        self._invalidate_shadow()

    # ── Painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        card = QPainterPath()
        card.addRoundedRect(rect, RADIUS, RADIUS)
        p.fillPath(card, BG)

        # Hero art, clipped to the card's rounded top
        p.save()
        p.setClipPath(card)
        hero = QRectF(0, 0, self.width(), HERO_H)
        accent = QColor(getattr(self, "_accent", "#a594f9"))
        if self._banner and not self._banner.isNull():
            scaled = self._banner.scaled(
                int(hero.width()), int(hero.height()),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            sx = (scaled.width() - int(hero.width())) // 2
            sy = (scaled.height() - int(hero.height())) // 3
            p.drawPixmap(0, 0, scaled, sx, sy, int(hero.width()), int(hero.height()))
        else:
            g = QLinearGradient(0, 0, hero.width(), hero.height())
            g.setColorAt(0, accent.darker(380))
            g.setColorAt(1, QColor("#141726"))
            p.fillRect(hero, g)
        # Subtle accent glow along the left edge ties the card to its phase
        glow = QLinearGradient(0, 0, self.width() * 0.6, 0)
        c = QColor(accent)
        c.setAlpha(46)
        glow.setColorAt(0, c)
        c.setAlpha(0)
        glow.setColorAt(1, c)
        p.fillRect(hero, glow)
        # Fade the art into the card body + darken the top for badge contrast
        fade = QLinearGradient(0, 0, 0, HERO_H)
        fade.setColorAt(0.0, QColor(8, 10, 16, 120))
        fade.setColorAt(0.30, QColor(8, 10, 16, 20))
        fade.setColorAt(0.62, QColor(15, 17, 24, 120))
        fade.setColorAt(0.90, BG)
        fade.setColorAt(1.0, BG)
        p.fillRect(hero, fade)
        p.restore()

        p.setPen(QPen(BORDER, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(card)
        p.end()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _step(self, delta: int):
        if not self._queue:
            return
        self._index = (self._index + delta) % len(self._queue)
        self._render(animate=False)

    def _close_for_now(self):
        """✕ hides the card for this session; alerts stay active and return
        on the next launch or scan (use ••• → Not interested to silence)."""
        self._queue.clear()
        self._index = 0
        self._tick_timer.stop()
        self.hide()

    def _remind(self, nid):
        self.remind_later.emit(nid)
        self.remove_notification(nid)

    def _dismiss(self, nid):
        self.dismissed.emit(nid)
        self.remove_notification(nid)

    def _on_why_link(self, _href: str):
        item = self._current()
        pre = ((item or {}).get("payload") or {}).get("prequel") or {}
        if pre.get("anime_id") and pre["anime_id"] > 0:
            self.open_prequel.emit(pre["anime_id"])

    def _open_trailer(self, seq: Dict):
        from ui.trailer_player import show_trailer
        show_trailer(seq["trailer_id"], seq["trailer_site"], seq.get("title") or "", self.window())

    def _open_details(self, seq: Dict):
        from ui.anime_info import open_media_info
        open_media_info(media_from_snapshot(seq), self.window())


def media_from_snapshot(seq: Dict) -> Dict:
    """Rebuild an AniList-shaped media dict from the payload snapshot, for
    dialogs that expect API data (full data is fetched on open anyway)."""
    return {
        "id": seq.get("id"),
        "title": {"english": seq.get("title"), "romaji": seq.get("romaji") or seq.get("title")},
        "coverImage": {"large": seq.get("cover_url"), "medium": seq.get("cover_url"),
                       "color": seq.get("cover_color")},
        "bannerImage": seq.get("banner_url"),
        "status": seq.get("status"),
        "format": seq.get("format"),
        "episodes": seq.get("episodes"),
        "season": seq.get("season"),
        "seasonYear": seq.get("season_year"),
        "averageScore": seq.get("score"),
        "genres": seq.get("genres") or [],
        "description": seq.get("synopsis") or "",
        "trailer": {"id": seq.get("trailer_id"), "site": seq.get("trailer_site")}
        if seq.get("trailer_id") else None,
        "nextAiringEpisode": {"airingAt": seq.get("next_airing_at"), "episode": seq.get("next_episode")}
        if seq.get("next_airing_at") else None,
    }
