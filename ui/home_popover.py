"""
Raikō - the This week popover: click an entry in the weekly schedule and a
card opens right beside it (pointer arrow aimed at the entry) with what
matters for THAT kind of title, and buttons to go further.

  anime   episode · air time + live countdown · your progress · score · studio
  TV      SxxEyy + episode name + still · season progress · runtime · network
  movie   release timeline (cinemas / HD / disc) · runtime · score

Open details opens the full detail panel (as before); ▶ Trailer plays the
official trailer in-app. Closes on Esc, a click outside, or scrolling.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QLinearGradient, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from workers.workers import PRIORITY_INTERACTIVE, ImageWorker, run_worker

LIB = {"anime": ("MIROKU", "#8b7bff"), "tv": ("KINEMA · TV", "#38bdf8"), "movie": ("KINEMA · MOVIE", "#fbbf24")}
SHADOW = 18          # painted shadow margin
ARROW = 11           # pointer size
W = 384              # card width (without shadow)


def _clean(t: str, n: int = 210) -> str:
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t or "")).strip()
    return t if len(t) <= n else t[:n - 5].rsplit(" ", 1)[0] + "…"


def _span(secs: int) -> str:
    if secs <= 0:
        return "Out now"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"In {d}d {h}h"
    return f"In {h}h {m:02d}m" if h else f"In {m}m"


def _day(ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    today = datetime.now().date()
    if d.date() == today:
        return "Today"
    if (d.date() - today).days == 1:
        return "Tomorrow"
    return d.strftime("%a, %b ") + str(d.day)


class _Art(QWidget):
    """Header art with a soft fade into the card."""
    H = 148

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.H)
        self._pix: Optional[QPixmap] = None
        if url:
            w = ImageWorker(url, url)
            w.signals.result.connect(self._on_img)
            run_worker(w, PRIORITY_INTERACTIVE)

    def _on_img(self, result):
        try:
            _k, _s, path = result
            if path:
                self._pix = QPixmap(str(path))
                self.update()
        except RuntimeError:
            pass

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r.adjusted(0, 0, 0, 14), 14, 14)        # round top corners only
        p.setClipPath(path)
        if self._pix and not self._pix.isNull():
            sc = self._pix.scaled(self.width(), self.height(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(0, 0, sc, (sc.width() - self.width()) // 2, (sc.height() - self.height()) // 3,
                         self.width(), self.height())
        else:
            p.fillRect(r, QColor("#161a2a"))
        g = QLinearGradient(0, self.height() * 0.35, 0, self.height())
        g.setColorAt(0, QColor(15, 17, 26, 0))
        g.setColorAt(1, QColor(15, 17, 26, 255))
        p.fillRect(r, g)
        p.end()


class EpisodePopover(QWidget):
    open_details = pyqtSignal(int)
    play_trailer = pyqtSignal(str, str, str)
    closed = pyqtSignal()

    def __init__(self, item: Dict, db, host: QWidget):
        super().__init__(host)
        self.item = item
        self.db = db
        self._side = "left"            # which side the arrow is on
        self._arrow_y = 60
        tag, self.color = LIB[item["media"]]
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW + ARROW, SHADOW, SHADOW + ARROW, SHADOW)
        outer.setSpacing(0)
        card = QWidget()
        card.setFixedWidth(W)
        card.setStyleSheet("background:transparent;")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 16)
        cl.setSpacing(0)
        self.art = _Art(self._art_url())
        cl.addWidget(self.art)

        body = QVBoxLayout()
        body.setContentsMargins(20, 0, 20, 0)
        body.setSpacing(6)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        lib = QLabel(tag)
        lib.setStyleSheet(f"color:{self.color};background:rgba(8,9,14,0.7);border-radius:7px;"
                          "padding:2px 8px;font-size:9px;font-weight:900;letter-spacing:1.2px;")
        when = QLabel(_day(item["when"]).upper() + (datetime.fromtimestamp(item["when"]).strftime(" · %H:%M")
                                                     if item.get("exact") else ""))
        when.setStyleSheet(f"color:#0b0d12;background:{self.color};border-radius:7px;"
                           "padding:2px 8px;font-size:9px;font-weight:900;letter-spacing:1.2px;")
        chips.addWidget(lib)
        chips.addWidget(when)
        chips.addStretch()
        x = QPushButton("✕")
        x.setObjectName("popClose")
        x.setFixedSize(26, 26)
        x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x.clicked.connect(self.close_popover)
        chips.addWidget(x)
        body.addLayout(chips)
        body.addSpacing(4)
        t = QLabel(item["title"])
        t.setObjectName("popTitle")
        t.setWordWrap(True)
        body.addWidget(t)
        self.headline = QLabel(self._headline())
        self.headline.setObjectName("popHeadline")
        self.headline.setStyleSheet(f"color:{self.color};")
        self.headline.setWordWrap(True)
        body.addWidget(self.headline)
        self.countdown = QLabel()
        self.countdown.setObjectName("popCountdown")
        body.addWidget(self.countdown)

        facts = self._facts()
        if facts:
            grid = QGridLayout()
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(6)
            for i, (k, v) in enumerate(facts):
                kl = QLabel(k.upper())
                kl.setObjectName("popFactKey")
                vl = QLabel(v)
                vl.setObjectName("popFactValue")
                vl.setWordWrap(True)
                grid.addWidget(kl, i // 2 * 2, i % 2)
                grid.addWidget(vl, i // 2 * 2 + 1, i % 2)
            body.addSpacing(6)
            body.addLayout(grid)
        blurb = _clean(item["row"].get("description") or "")
        if blurb:
            b = QLabel(blurb)
            b.setObjectName("popBlurb")
            b.setWordWrap(True)
            body.addSpacing(6)
            body.addWidget(b)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        go = QPushButton("Open details  →")
        go.setObjectName("popPrimary")
        go.setStyleSheet(f"QPushButton#popPrimary{{background:{self.color};color:#0b0d12;}}")
        go.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        go.clicked.connect(lambda: (self.open_details.emit(item["id"]), self.close_popover()))
        btns.addWidget(go)
        tr = item["row"].get("trailer_id")
        if tr:
            tb = QPushButton("▶  Trailer")
            tb.setObjectName("popSecondary")
            tb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            tb.clicked.connect(lambda: self.play_trailer.emit(
                tr, item["row"].get("trailer_site") or "youtube", item["title"]))
            btns.addWidget(tb)
        btns.addStretch()
        body.addSpacing(10)
        body.addLayout(btns)
        cl.addLayout(body)
        outer.addWidget(card)

        self._tick()
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick)
        self._clock.start(30_000)

    # ── content per library ───────────────────────────────────────────────────

    def _art_url(self) -> str:
        it, row = self.item, self.item["row"]
        if it["media"] == "tv" and it.get("still"):
            return it["still"]
        return row.get("banner_url") or row.get("cover_url") or ""

    def _headline(self) -> str:
        it = self.item
        if it["media"] == "anime":
            total = it["row"].get("total_episodes")
            n = it.get("display_ep") or it.get("episode")
            if it["label"] == "Premiere":
                return "Premiere — Episode 1" + (f" of {total}" if total else "")
            return f"Episode {n}" + (f" of {total}" if total else "")
        if it["media"] == "tv":
            code = it["label"]
            name = it.get("ep_name") or ""
            if name and not name.lower().startswith("episode "):
                return f"{code} · “{name}”"
            return code
        return "Out in HD — ready to watch at home" if it["label"] == "Out in HD" else "In cinemas"

    def _facts(self) -> List[Tuple[str, str]]:
        it, row = self.item, self.item["row"]
        out: List[Tuple[str, str]] = []
        if it["media"] == "anime":
            total = row.get("total_episodes") or 0
            watched = self.db.get_watched_count(row["id"]) if row.get("id") else 0
            aired = (it.get("episode") or 1) - 1
            ws = row.get("watch_status")
            if ws == "watching":
                state = "caught up" if watched >= aired else f"{aired - watched} to watch first"
                out.append(("Your progress", f"{watched}/{total or '?'} · {state}"))
            else:
                out.append(("In your library", {"planned": "Plan to Watch", "completed": "Completed"}.get(ws, ws or "")))
            if row.get("average_score"):
                out.append(("Score", f"★ {row['average_score'] / 10:.1f} on AniList"))
            if row.get("studios"):
                out.append(("Studio", ", ".join(row["studios"][:2])))
            if row.get("duration"):
                out.append(("Episode length", f"{row['duration']} min"))
        elif it["media"] == "tv":
            p = self.db.tv_progress(row["id"])
            s = it.get("season")
            eps = [e for e in self.db.get_tv_episodes(row["id"], s)] if s else []
            seen = sum(1 for e in eps if e.get("watched"))
            if s:
                out.append((f"Season {s}", f"{seen}/{len(eps)} watched" if eps else "new season"))
            out.append(("Your progress", f"{p['watched']}/{p['aired']} aired" if p["aired"] else "not started"))
            rt = it.get("runtime") or row.get("duration")
            if rt:
                out.append(("Runtime", f"~{rt} min"))
            if row.get("studios"):
                out.append(("Network", row["studios"][0]))
            if row.get("average_score"):
                out.append(("Score", f"★ {row['average_score'] / 10:.1f} on TMDB"))
        else:
            rs = it.get("rs") or {}

            def d(ts):
                return datetime.fromtimestamp(ts).strftime("%b ") + str(datetime.fromtimestamp(ts).day) if ts else "—"
            out += [("In cinemas", d(rs.get("cinema_ts"))), ("Digital (HD)", d(rs.get("digital_ts")))]
            if rs.get("physical_ts"):
                out.append(("Disc", d(rs["physical_ts"])))
            if row.get("duration"):
                h, m = divmod(int(row["duration"]), 60)
                out.append(("Runtime", f"{h}h {m:02d}m" if h else f"{m}m"))
            if row.get("average_score"):
                out.append(("Score", f"★ {row['average_score'] / 10:.1f} on TMDB"))
        return out

    def _tick(self):
        secs = int(self.item["when"] - datetime.now().timestamp())
        if self.item.get("exact"):
            self.countdown.setText(_span(secs))
        else:
            days = (datetime.fromtimestamp(self.item["when"]).date() - datetime.now().date()).days
            self.countdown.setText("Today" if days <= 0 else ("Tomorrow" if days == 1 else f"In {days} days"))

    # ── placement, look & life cycle ──────────────────────────────────────────

    def show_at(self, anchor: QWidget):
        """Open beside `anchor` (right if there's room, else left), arrow aimed
        at its centre, kept inside the host."""
        host = self.parentWidget()
        self.adjustSize()
        a_tl = anchor.mapTo(host, QPoint(0, 0))
        a = QRect(a_tl, anchor.size())
        w, h = self.width(), self.height()
        margin = 8
        if a.right() + w - SHADOW < host.width() - margin:
            x, self._side = a.right() + 2 - SHADOW, "left"
        else:
            x, self._side = a.left() - w + SHADOW - 2, "right"
        x = max(margin - SHADOW, min(x, host.width() - w + SHADOW - margin))
        y = a.center().y() - h // 2
        y = max(margin - SHADOW, min(y, host.height() - h + SHADOW - margin))
        self._arrow_y = max(SHADOW + 26, min(a.center().y() - y, h - SHADOW - 26))
        self.move(x, y)
        self.show()
        self.raise_()
        self.setFocus()
        # entrance: fade + a few pixels of slide toward the entry
        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        fade = QPropertyAnimation(eff, b"opacity", self)
        fade.setDuration(170)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        slide = QPropertyAnimation(self, b"pos", self)
        slide.setDuration(190)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        dx = -8 if self._side == "left" else 8
        slide.setStartValue(QPoint(x - dx, y))
        slide.setEndValue(QPoint(x, y))
        fade.finished.connect(lambda: self.setGraphicsEffect(None))
        fade.start()
        slide.start()
        self._anims = (fade, slide)

    def close_popover(self):
        self.closed.emit()
        self.hide()
        self.deleteLater()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close_popover()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(SHADOW + ARROW, SHADOW, W, self.height() - 2 * SHADOW)
        shape = QPainterPath()
        shape.addRoundedRect(card, 14, 14)
        ay = float(self._arrow_y)
        tip = QPainterPath()
        if self._side == "left":
            tip.moveTo(card.left() + 1, ay - ARROW)
            tip.lineTo(card.left() - ARROW + 1, ay)
            tip.lineTo(card.left() + 1, ay + ARROW)
        else:
            tip.moveTo(card.right() - 1, ay - ARROW)
            tip.lineTo(card.right() + ARROW - 1, ay)
            tip.lineTo(card.right() - 1, ay + ARROW)
        tip.closeSubpath()
        shape = shape.united(tip)
        # soft shadow: a few expanding translucent strokes
        for i, a in ((14, 10), (10, 16), (6, 24), (3, 34)):
            p.setPen(QColor(0, 0, 0, a))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(shape.translated(0, i * 0.35))
        p.fillPath(shape, QColor("#0f111a"))
        p.setPen(QColor(255, 255, 255, 26))
        p.drawPath(shape)
        # library-colour hairline along the top
        top = QPainterPath()
        top.addRoundedRect(QRectF(card.left() + 14, card.top(), card.width() - 28, 2.5), 1, 1)
        p.fillPath(top, QColor(self.color))
        p.end()
