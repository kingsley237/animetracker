"""
Raikō - the Hall of Fame page.

  The Pantheon       four pins across wings (top of the page)
  Wings              Miroku · Movies · TV — each its own ranking
  Views              Showcase · List (drag to reorder) · Tiers (drag between
                     tiers) · Timeline · Numbers
  Plaques            click any entry: its story, your note, favourite moment
                     and character, re-rank / pin / remove

Right-click any entry for the quick menu.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from core.hall import WING_NAMES, WINGS, Hall
from ui.hall_rank import GOLD, WING_COLORS, RankDialog, _year, induct
from ui.home_page import _Img
from ui.layout_helpers import FlowLayout
from workers.workers import ImageWorker, run_worker

VIEWS = [("showcase", "Showcase"), ("list", "List"), ("tiers", "Tiers"), ("timeline", "Timeline"),
         ("numbers", "Numbers")]


def _clear(layout):
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w is not None:
            w.deleteLater()
        elif it.layout() is not None:
            _clear(it.layout())


def _hours(minutes: int) -> str:
    if not minutes:
        return "—"
    h = minutes / 60
    return f"{h:.0f} h" if h >= 10 else f"{h:.1f} h".replace(".0 ", " ")


def _date(ts) -> str:
    if not ts:
        return "—"
    d = datetime.fromtimestamp(int(ts))
    return d.strftime("%b ") + str(d.day) + d.strftime(", %Y")


# ── posters ───────────────────────────────────────────────────────────────────

class _HallPoster(QWidget, _Img):
    """A ranked poster: big rank numeral, tier chip, wing hairline."""
    clicked = pyqtSignal(int)
    menu = pyqtSignal(int, QPoint)

    def __init__(self, entry: Dict, w: int, tiers: Dict[str, Dict], show_title=True, label="", parent=None):
        super().__init__(parent)
        self.entry = entry
        self.W, self.H = w, int(w * 1.5)
        self.tiers = tiers
        self.show_title = show_title
        self.label = label
        self.color = WING_COLORS.get(entry["wing"], GOLD)
        self._hover = False
        self.setFixedSize(self.W, self.H + (42 if show_title else 0))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(entry["title"])
        self._load_img(entry["row"].get("cover_url") or "")

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.entry["lib_id"])
        elif e.button() == Qt.MouseButton.RightButton:
            self.menu.emit(self.entry["lib_id"], e.globalPosition().toPoint())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rad = max(8, self.W // 14)
        r = QRectF(1, 1, self.W - 2, self.H - 2)
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)
        p.save()
        p.setClipPath(path)
        self._draw_cover(p, r, 0.3)
        g = QLinearGradient(0, r.bottom() - self.H * 0.42, 0, r.bottom())
        g.setColorAt(0, QColor(8, 9, 14, 0))
        g.setColorAt(1, QColor(8, 9, 14, 235))
        p.fillRect(r, g)
        p.restore()
        rank = self.entry["rank"]
        ring = QColor(GOLD) if rank <= 3 else QColor(self.color)
        if self._hover:
            p.setPen(QPen(ring, 2))
        else:
            p.setPen(QColor(255, 255, 255, 30))
        p.drawPath(path)
        # big rank numeral, bottom-left
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(max(18, int(self.W * 0.30)))
        p.setFont(f)
        p.setPen(QColor(GOLD) if rank <= 3 else QColor("#f4f5fa"))
        p.drawText(QRectF(r.left() + rad * 0.8, r.bottom() - self.W * 0.40, self.W, self.W * 0.38),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, str(rank))
        # tier chip, top-left
        t = self.tiers.get(self.entry.get("tier") or "")
        if t:
            f.setPixelSize(max(10, int(self.W * 0.085)))
            p.setFont(f)
            s = max(18, int(self.W * 0.16))
            chip = QRectF(r.left() + 7, r.top() + 7, max(s, p.fontMetrics().horizontalAdvance(t["label"]) + 10), s)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t["color"]))
            p.drawRoundedRect(chip, 5, 5)
            p.setPen(QColor("#0b0d12"))
            p.drawText(chip, Qt.AlignmentFlag.AlignCenter, t["label"])
        # pinned star, top-right
        if self.entry.get("pinned"):
            f.setPixelSize(max(11, int(self.W * 0.09)))
            p.setFont(f)
            p.setPen(QColor(GOLD))
            p.drawText(QRectF(r.right() - 26, r.top() + 6, 20, 20), Qt.AlignmentFlag.AlignCenter, "★")
        if self.show_title:
            f.setPixelSize(12)
            p.setFont(f)
            p.setPen(QColor("#e8eaf2"))
            p.drawText(QRectF(0, self.H + 5, self.W, 18), Qt.AlignmentFlag.AlignLeft,
                       p.fontMetrics().elidedText(self.entry["title"], Qt.TextElideMode.ElideRight, self.W))
            f.setBold(False)
            f.setPixelSize(11)
            p.setFont(f)
            p.setPen(QColor("#7f87a3"))
            p.drawText(QRectF(0, self.H + 23, self.W, 16), Qt.AlignmentFlag.AlignLeft,
                       self.label or _year(self.entry["row"]))
        p.end()


class _Feature(QWidget, _Img):
    """Your #1, given the whole width: banner art, poster, and its story."""
    clicked = pyqtSignal(int)
    menu = pyqtSignal(int, QPoint)

    def __init__(self, entry: Dict, story: Dict, tiers: Dict, parent=None, compact: bool = False):
        super().__init__(parent)
        self.entry = entry
        self.story = story
        self.tiers = tiers
        self.compact = compact
        self.H = 196 if compact else 250
        self.PW = 104 if compact else 140
        self.color = WING_COLORS.get(entry["wing"], GOLD)
        self.setFixedHeight(self.H)
        self.setMinimumWidth(380 if compact else 520)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        row = entry["row"]
        self._load_img(row.get("banner_url") or row.get("cover_url") or "")
        self.poster = _HallPoster(entry, self.PW, tiers, show_title=False, parent=self)
        self.poster.move(24, (self.H - self.poster.H) // 2)
        self.poster.clicked.connect(self.clicked.emit)
        self.poster.menu.connect(self.menu.emit)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.entry["lib_id"])
        elif e.button() == Qt.MouseButton.RightButton:
            self.menu.emit(self.entry["lib_id"], e.globalPosition().toPoint())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 18, 18)
        p.save()
        p.setClipPath(path)
        self._draw_cover(p, r, 0.25)
        g = QLinearGradient(0, 0, r.width(), 0)
        g.setColorAt(0, QColor(10, 11, 18, 250))
        g.setColorAt(0.55, QColor(10, 11, 18, 215))
        g.setColorAt(1, QColor(10, 11, 18, 90))
        p.fillRect(r, g)
        p.restore()
        rank = self.entry["rank"]
        p.setPen(QPen(QColor(GOLD) if rank <= 3 else QColor(255, 255, 255, 40), 1.2))
        p.drawPath(path)
        c = self.compact
        x = 24 + self.PW + (22 if c else 28)
        w = r.width() - x - 24
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(10)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.6)
        p.setFont(f)
        p.setPen(QColor(GOLD))
        p.drawText(QRectF(x, 24 if c else 30, w, 16), Qt.AlignmentFlag.AlignLeft,
                   f"YOUR #{rank} · {WING_NAMES[self.entry['wing']].upper()}")
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0)
        f.setPixelSize(19 if c else 26)
        p.setFont(f)
        p.setPen(QColor("#f6f7fb"))
        ty = 42 if c else 50
        p.drawText(QRectF(x, ty, w, 30 if c else 36), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(self.entry["title"], Qt.TextElideMode.ElideRight, int(w)))
        f.setBold(False)
        f.setPixelSize(12 if c else 13)
        p.setFont(f)
        p.setPen(QColor("#aab1c9"))
        bits = [b for b in (_year(self.entry["row"]),
                            ", ".join((self.entry["row"].get("studios") or [])[:1]),
                            None if c else f"in your Hall since {_date(self.entry.get('inducted_at'))}") if b]
        p.drawText(QRectF(x, ty + (32 if c else 38), w, 20), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText("  ·  ".join(bits), Qt.TextElideMode.ElideRight, int(w)))
        quote = self.entry.get("note") or self.entry.get("moment") or ""
        f.setItalic(bool(quote))
        f.setPixelSize(13 if c else 14)
        p.setFont(f)
        p.setPen(QColor("#e3e6f0") if quote else QColor("#6b7391"))
        qy = ty + (60 if c else 68)
        p.drawText(QRectF(x, qy, w, 44 if c else 60), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                   f"“{quote}”" if quote else ("Click to write why it's here." if c else
                                              "Click to write why it's here and your favourite moment."))
        f.setItalic(False)
        # facts row
        facts = []
        s = self.story
        if s.get("rating"):
            facts.append(("YOUR RATING", f"{s['rating']:.0f}/6" if s["rating"] <= 6 else f"{s['rating']:.0f}"))
        if s.get("minutes"):
            facts.append(("TIME SPENT", _hours(s["minutes"])))
        if s.get("best"):
            facts.append(("BEST", s["best"]))
        if s.get("rewatches"):
            facts.append(("REWATCHES", str(s["rewatches"])))
        if s.get("community") and len(facts) < 3:
            facts.append(("COMMUNITY", f"★ {s['community'] / 10:.1f}"))
        fx = x
        fy = self.H - (58 if c else 60)
        for k, v in facts[:(3 if c else 4)]:
            f.setBold(True)
            f.setPixelSize(9)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
            p.setFont(f)
            p.setPen(QColor("#6b7391"))
            p.drawText(QRectF(fx, fy, 200, 14), Qt.AlignmentFlag.AlignLeft, k)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0)
            f.setBold(True)
            f.setPixelSize(14)
            p.setFont(f)
            p.setPen(QColor("#f0f1f6"))
            p.drawText(QRectF(fx, fy + 16, 220, 22), Qt.AlignmentFlag.AlignLeft, v)
            fx += max(100 if c else 110, p.fontMetrics().horizontalAdvance(v) + 32)
            if fx > r.right() - 80:
                break
        p.end()


class _PantheonSlot(QWidget, _Img):
    clicked = pyqtSignal(int)          # slot number (1-4)
    menu = pyqtSignal(int, QPoint)
    W, H = 150, 225

    def __init__(self, slot: int, entry: Optional[Dict], parent=None):
        super().__init__(parent)
        self.slot = slot
        self.entry = entry
        self._hover = False
        self.setFixedSize(self.W, self.H + 44)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._pix = None
        if entry:
            self.setToolTip(entry["title"])
            self._load_img(entry["row"].get("cover_url") or "")

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.slot)
        elif e.button() == Qt.MouseButton.RightButton:
            self.menu.emit(self.slot, e.globalPosition().toPoint())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(2, 2, self.W - 4, self.H - 4)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        f = QFont(self.font())
        if not self.entry:
            p.setPen(QPen(QColor(GOLD if self._hover else "#3a3f57"), 1.4, Qt.PenStyle.DashLine))
            p.setBrush(QColor(255, 255, 255, 8 if self._hover else 4))
            p.drawPath(path)
            f.setPixelSize(26)
            p.setFont(f)
            p.setPen(QColor(GOLD if self._hover else "#4a5070"))
            p.drawText(r.adjusted(0, -16, 0, -16), Qt.AlignmentFlag.AlignCenter, "+")
            f.setPixelSize(11)
            p.setFont(f)
            p.drawText(r.adjusted(0, 30, 0, 30), Qt.AlignmentFlag.AlignCenter, "Pin a favourite")
        else:
            p.save()
            p.setClipPath(path)
            self._draw_cover(p, r, 0.3)
            p.restore()
            p.setPen(QPen(QColor(GOLD), 2 if self._hover else 1.2))
            p.drawPath(path)
            c = QColor(WING_COLORS.get(self.entry["wing"], GOLD))
            f.setBold(True)
            f.setPixelSize(9)
            p.setFont(f)
            lab = WING_NAMES[self.entry["wing"]].upper() + f" #{self.entry['rank']}"
            tw = p.fontMetrics().horizontalAdvance(lab) + 14
            chip = QRectF(r.left() + 8, r.bottom() - 28, tw, 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(8, 9, 14, 215))
            p.drawRoundedRect(chip, 7, 7)
            p.setPen(c)
            p.drawText(chip, Qt.AlignmentFlag.AlignCenter, lab)
            f.setPixelSize(12)
            p.setFont(f)
            p.setPen(QColor("#eef0f7"))
            p.drawText(QRectF(0, self.H + 6, self.W, 18), Qt.AlignmentFlag.AlignHCenter,
                       p.fontMetrics().elidedText(self.entry["title"], Qt.TextElideMode.ElideRight, self.W))
        f.setBold(True)
        f.setPixelSize(10)
        p.setFont(f)
        p.setPen(QColor(GOLD))
        if not self.entry:
            p.drawText(QRectF(0, self.H + 6, self.W, 18), Qt.AlignmentFlag.AlignHCenter, f"{self.slot}")
        p.end()


# ── list & tier views ─────────────────────────────────────────────────────────

class _ListRow(QWidget, _Img):
    H = 78

    def __init__(self, entry: Dict, move: int, tiers: Dict, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.move_by = move
        self.tiers = tiers
        self.setFixedHeight(self.H)
        self._load_img(entry["row"].get("cover_url") or "")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        e = self.entry
        f = QFont(self.font())
        f.setPixelSize(16)
        p.setFont(f)
        p.setPen(QColor("#4a5070"))
        p.drawText(QRectF(10, 0, 20, self.H), Qt.AlignmentFlag.AlignVCenter, "⋮⋮")
        f.setBold(True)
        f.setPixelSize(22)
        p.setFont(f)
        p.setPen(QColor(GOLD) if e["rank"] <= 3 else QColor("#f0f1f6"))
        p.drawText(QRectF(34, 0, 46, self.H), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   str(e["rank"]))
        r = QRectF(94, 7, 43, 64)
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        p.save()
        p.setClipPath(path)
        self._draw_cover(p, r)
        p.restore()
        x = 152
        w = self.width() - x - 120
        f.setPixelSize(14)
        p.setFont(f)
        p.setPen(QColor("#eef0f7"))
        p.drawText(QRectF(x, 14, w, 22), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(e["title"], Qt.TextElideMode.ElideRight, int(w)))
        f.setBold(False)
        f.setPixelSize(12)
        p.setFont(f)
        quote = e.get("note") or e.get("moment")
        p.setPen(QColor("#aab1c9") if quote else QColor("#6b7391"))
        sub = f"“{quote}”" if quote else "  ·  ".join(
            b for b in (_year(e["row"]), ", ".join((e["row"].get("genres") or [])[:3])) if b)
        p.drawText(QRectF(x, 40, w, 20), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(sub, Qt.TextElideMode.ElideRight, int(w)))
        rx = self.width() - 110
        t = self.tiers.get(e.get("tier") or "")
        if t:
            f.setBold(True)
            f.setPixelSize(11)
            p.setFont(f)
            chip = QRectF(rx, self.H / 2 - 11, 26, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t["color"]))
            p.drawRoundedRect(chip, 6, 6)
            p.setPen(QColor("#0b0d12"))
            p.drawText(chip, Qt.AlignmentFlag.AlignCenter, t["label"][:3])
        if self.move_by:
            f.setBold(True)
            f.setPixelSize(12)
            p.setFont(f)
            up = self.move_by > 0
            p.setPen(QColor("#34d399") if up else QColor("#f87171"))
            p.drawText(QRectF(rx + 34, 0, 60, self.H), Qt.AlignmentFlag.AlignVCenter,
                       ("▲ " if up else "▼ ") + str(abs(self.move_by)))
        p.setPen(QColor(255, 255, 255, 14))
        p.drawLine(94, self.H - 1, self.width() - 10, self.H - 1)
        p.end()


class _RankList(QListWidget):
    """Ranked rows; drag to reorder."""
    moved = pyqtSignal(object, int)       # id (lib id or song id), new rank
    opened = pyqtSignal(object)
    menu = pyqtSignal(object, QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hallList")
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.model().rowsMoved.connect(self._on_moved)
        self.itemClicked.connect(lambda it: self.opened.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx)

    def _ctx(self, pos):
        it = self.itemAt(pos)
        if it:
            self.menu.emit(it.data(Qt.ItemDataRole.UserRole), self.viewport().mapToGlobal(pos))

    def _on_moved(self, _parent, start, _end, _dest, row):
        new = row if row < start else row - 1
        it = self.item(new)
        if it is not None:
            self.moved.emit(it.data(Qt.ItemDataRole.UserRole), new + 1)

    def fit(self):
        self.setFixedHeight(sum(self.sizeHintForRow(i) for i in range(self.count())) + 4)


class _TierRow(QListWidget):
    """One tier's posters; drop a poster here to give it this tier."""
    dropped = pyqtSignal(int, str)         # lib id, tier key ('' = untiered)
    opened = pyqtSignal(int)
    menu = pyqtSignal(int, QPoint)

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("hallTierRow")
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(64, 96))
        self.setGridSize(QSize(74, 104))
        self.setMovement(QListWidget.Movement.Snap)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setWrapping(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumHeight(110)
        self.itemClicked.connect(lambda it: self.opened.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx)

    def _ctx(self, pos):
        it = self.itemAt(pos)
        if it:
            self.menu.emit(it.data(Qt.ItemDataRole.UserRole), self.viewport().mapToGlobal(pos))

    def dropEvent(self, e):
        src = e.source()
        it = src.currentItem() if isinstance(src, _TierRow) else None
        e.setDropAction(Qt.DropAction.IgnoreAction)
        e.accept()
        if it is not None:
            lib_id = it.data(Qt.ItemDataRole.UserRole)
            QTimer.singleShot(0, lambda: self.dropped.emit(lib_id, self.key))

    def add_entry(self, e: Dict):
        it = QListWidgetItem()
        it.setData(Qt.ItemDataRole.UserRole, e["lib_id"])
        it.setToolTip(f"#{e['rank']}  {e['title']}")
        it.setSizeHint(QSize(70, 100))
        self.addItem(it)
        url = e["row"].get("cover_url") or ""
        if url:
            w = ImageWorker(url, url)
            w.signals.result.connect(lambda res, it=it: self._set_icon(it, res))
            run_worker(w)

    def _set_icon(self, it, res):
        try:
            _k, _s, path = res
            if path:
                pm = QPixmap(str(path)).scaled(64, 96, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                              Qt.TransformationMode.SmoothTransformation)
                it.setIcon(QIcon(pm.copy((pm.width() - 64) // 2, 0, 64, 96)))
        except RuntimeError:
            pass

    def fit(self):
        per = max(1, (self.viewport().width() or 600) // 74)
        rows = max(1, -(-self.count() // per))
        self.setFixedHeight(rows * 104 + 8)


# ── numbers ───────────────────────────────────────────────────────────────────

class _Bars(QWidget):
    """Horizontal bars, one hue; value labels in text ink."""

    def __init__(self, title: str, items: List, color: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.items = items
        self.color = color
        self.setMinimumWidth(260)
        self.setFixedHeight(30 + max(1, len(items)) * 30)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(10)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        p.setFont(f)
        p.setPen(QColor("#8c93ad"))
        p.drawText(QRectF(0, 0, self.width(), 18), Qt.AlignmentFlag.AlignLeft, self.title.upper())
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0)
        if not self.items:
            f.setBold(False)
            f.setPixelSize(12)
            p.setFont(f)
            p.setPen(QColor("#6b7391"))
            p.drawText(QRectF(0, 28, self.width(), 20), Qt.AlignmentFlag.AlignLeft, "Not enough yet")
            p.end()
            return
        top = max(v for _k, v in self.items) or 1
        label_w = 120
        bar_w = self.width() - label_w - 40
        for i, (k, v) in enumerate(self.items):
            y = 30 + i * 30
            f.setBold(False)
            f.setPixelSize(12)
            p.setFont(f)
            p.setPen(QColor("#dfe2ee"))
            p.drawText(QRectF(0, y, label_w - 8, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       p.fontMetrics().elidedText(str(k), Qt.TextElideMode.ElideRight, label_w - 10))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 12))
            p.drawRoundedRect(QRectF(label_w, y + 6, bar_w, 8), 4, 4)
            p.setBrush(QColor(self.color))
            p.drawRoundedRect(QRectF(label_w, y + 6, max(8, bar_w * v / top), 8), 4, 4)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#eef0f7"))
            p.drawText(QRectF(label_w + bar_w + 8, y, 32, 20),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, str(v))
        p.end()


# ── plaque ────────────────────────────────────────────────────────────────────

class PlaqueDialog(QDialog):
    """An entry's plaque: its story, your words, and what you can do with it."""
    open_details = pyqtSignal(int)

    def __init__(self, hall: Hall, lib_id: int, parent=None):
        super().__init__(parent)
        self.hall = hall
        self.lib_id = lib_id
        self.action: Optional[str] = None
        e = hall.entry(lib_id)
        self.entry = e
        color = WING_COLORS.get(e["wing"], GOLD)
        self.setWindowTitle(e["title"])
        self.setObjectName("hallDialog")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 18)
        lay.setSpacing(0)
        from ui.home_popover import _Art
        art = _Art(e["row"].get("banner_url") or e["row"].get("cover_url") or "")
        lay.addWidget(art)
        body = QVBoxLayout()
        body.setContentsMargins(26, 0, 26, 0)
        body.setSpacing(8)
        top = QHBoxLayout()
        rank = QLabel(f"#{e['rank']}")
        rank.setObjectName("hallPlaqueRank")
        rank.setStyleSheet(f"color:{GOLD if e['rank'] <= 3 else '#f4f5fa'};")
        top.addWidget(rank)
        col = QVBoxLayout()
        col.setSpacing(2)
        kick = QLabel(f"{WING_NAMES[e['wing']].upper()} · HALL OF FAME"
                      + (f"  ·  ★ PANTHEON {e['pinned']}" if e.get("pinned") else ""))
        kick.setObjectName("hallKicker")
        kick.setStyleSheet(f"color:{color};")
        col.addWidget(kick)
        t = QLabel(e["title"])
        t.setObjectName("popTitle")
        t.setWordWrap(True)
        col.addWidget(t)
        top.addLayout(col, 1)
        body.addLayout(top)

        s = hall.story(lib_id)
        mv = hall.movement(lib_id)
        facts = [("Inducted", _date(e.get("inducted_at")))]
        if mv:
            facts.append(("Lately", ("▲ " if mv > 0 else "▼ ") + f"{abs(mv)} place{'s' if abs(mv) != 1 else ''}"))
        if s.get("rating"):
            facts.append(("Your rating", f"{s['rating']:.0f}/6"))
        if s.get("community"):
            facts.append(("Community", f"★ {s['community'] / 10:.1f}"))
        if s.get("minutes"):
            facts.append(("Time spent", _hours(s["minutes"])))
        if s.get("first") or s.get("finished"):
            a, b = _date(s.get("first")), _date(s.get("finished"))
            facts.append(("Watched", f"{a} → {b}" if s.get("first") and s.get("finished") and a != b
                          else (b if s.get("finished") else a)))
        if s.get("best"):
            facts.append(("Best", s["best"]))
        if s.get("rewatches"):
            facts.append(("Rewatches", str(s["rewatches"])))
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        for i, (k, v) in enumerate(facts):
            kl = QLabel(k.upper())
            kl.setObjectName("popFactKey")
            vl = QLabel(v)
            vl.setObjectName("popFactValue")
            grid.addWidget(kl, i // 3 * 2, i % 3)
            grid.addWidget(vl, i // 3 * 2 + 1, i % 3)
        body.addSpacing(4)
        body.addLayout(grid)
        body.addSpacing(10)

        def field(label, widget):
            l = QLabel(label.upper())
            l.setObjectName("popFactKey")
            body.addWidget(l)
            body.addWidget(widget)

        self.note = QTextEdit()
        self.note.setObjectName("hallField")
        self.note.setPlaceholderText("What makes it one of your all-time favourites?")
        self.note.setPlainText(e.get("note") or "")
        self.note.setFixedHeight(74)
        field("Why it's here", self.note)
        row2 = QHBoxLayout()
        self.moment = QLineEdit(e.get("moment") or "")
        self.moment.setObjectName("hallField")
        self.moment.setPlaceholderText("A scene, a line, an episode…")
        self.character = QLineEdit(e.get("character") or "")
        self.character.setObjectName("hallField")
        self.character.setPlaceholderText("Who you'd watch it for")
        c1, c2 = QVBoxLayout(), QVBoxLayout()
        for c, lab, w in ((c1, "Favourite moment", self.moment), (c2, "Favourite character", self.character)):
            l = QLabel(lab.upper())
            l.setObjectName("popFactKey")
            c.addWidget(l)
            c.addWidget(w)
        row2.addLayout(c1, 3)
        row2.addLayout(c2, 2)
        body.addLayout(row2)

        tl = QHBoxLayout()
        tl.setSpacing(6)
        l = QLabel("TIER")
        l.setObjectName("popFactKey")
        tl.addWidget(l)
        self.tier = e.get("tier") or ""
        self._tier_btns = []
        for tr in [{"key": "", "label": "—", "color": "#2a2f45"}] + hall.tiers():
            b = QPushButton(tr["label"])
            b.setObjectName("hallTierChip")
            b.setCheckable(True)
            b.setChecked(tr["key"] == self.tier)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setStyleSheet(f"QPushButton#hallTierChip:checked{{background:{tr['color']};color:#0b0d12;"
                            f"border-color:{tr['color']};}}")
            b.clicked.connect(lambda _=False, k=tr["key"]: self._set_tier(k))
            self._tier_btns.append((tr["key"], b))
            tl.addWidget(b)
        tl.addStretch()
        body.addSpacing(4)
        body.addLayout(tl)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        go = QPushButton("Open details  →")
        go.setObjectName("hallPrimary")
        go.setStyleSheet(f"QPushButton#hallPrimary{{background:{color};}}")
        go.clicked.connect(lambda: self._done("details"))
        btns.addWidget(go)
        rr = QPushButton("Re-rank")
        rr.setObjectName("hallGhost")
        rr.clicked.connect(lambda: self._done("rerank"))
        btns.addWidget(rr)
        pin = QPushButton("Unpin from Pantheon" if e.get("pinned") else "★ Pin to Pantheon")
        pin.setObjectName("hallGhost")
        pin.clicked.connect(lambda: self._done("unpin" if e.get("pinned") else "pin"))
        btns.addWidget(pin)
        btns.addStretch()
        rm = QPushButton("Remove")
        rm.setObjectName("hallDanger")
        rm.clicked.connect(lambda: self._done("remove"))
        btns.addWidget(rm)
        for b in (go, rr, pin, rm):
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setAutoDefault(False)
        body.addSpacing(10)
        body.addLayout(btns)
        lay.addLayout(body)

    def _set_tier(self, key: str):
        self.tier = key
        for k, b in self._tier_btns:
            b.setChecked(k == key)

    def save(self):
        self.hall.set_fields(self.lib_id, note=self.note.toPlainText().strip(), moment=self.moment.text().strip(),
                             character=self.character.text().strip(), tier=self.tier or None)

    def _done(self, action: str):
        self.action = action
        self.accept()

    def done(self, r):
        self.save()
        super().done(r)


# ── the page ──────────────────────────────────────────────────────────────────

class HallPage(QWidget):
    open_title = pyqtSignal(int)
    changed = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.hall = Hall(db)
        self.wing = "anime"
        self.view = "showcase"
        self.setObjectName("contentArea")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("homeScroll")
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
        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        kick = QLabel("RAIKŌ")
        kick.setObjectName("hallKicker")
        kick.setStyleSheet(f"color:{GOLD};")
        tcol.addWidget(kick)
        h = QLabel("Hall of Fame")
        h.setObjectName("hallTitle")
        tcol.addWidget(h)
        self.sub = QLabel()
        self.sub.setObjectName("homeDate")
        tcol.addWidget(self.sub)
        head.addLayout(tcol)
        head.addStretch()
        self.share_btn = QPushButton("Share card")
        self.share_btn.setObjectName("hallGhost")
        self.share_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.share_btn.clicked.connect(self._share)
        head.addWidget(self.share_btn, alignment=Qt.AlignmentFlag.AlignBottom)
        add = QPushButton("+  Induct a title")
        add.setObjectName("hallPrimary")
        add.setStyleSheet(f"QPushButton#hallPrimary{{background:{GOLD};}}")
        add.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add.clicked.connect(self._induct)
        head.addWidget(add, alignment=Qt.AlignmentFlag.AlignBottom)
        self.lay.addLayout(head)

        ps = QLabel("The Pantheon")
        ps.setObjectName("homeSection")
        self.lay.addSpacing(8)
        self.lay.addWidget(ps)
        psub = QLabel("Your four favourites of everything — anime, movies and TV together.")
        psub.setObjectName("homeDate")
        self.lay.addWidget(psub)
        self.pantheon = QHBoxLayout()
        self.pantheon.setSpacing(18)
        self.lay.addLayout(self.pantheon)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.wing_btns: Dict[str, QPushButton] = {}
        for w in list(WINGS) + ["honours"]:
            b = QPushButton()
            b.setObjectName("hallTab")
            b.setCheckable(True)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _=False, w=w: self._set_wing(w))
            self.wing_btns[w] = b
            bar.addWidget(b)
        bar.addStretch()
        self.view_btns: Dict[str, QPushButton] = {}
        for key, label in VIEWS:
            b = QPushButton(label)
            b.setObjectName("hallSeg")
            b.setCheckable(True)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _=False, k=key: self._set_view(k))
            self.view_btns[key] = b
            bar.addWidget(b)
        self.lay.addSpacing(12)
        self.lay.addLayout(bar)
        self.body = QVBoxLayout()
        self.body.setSpacing(16)
        self.lay.addLayout(self.body)
        self.lay.addStretch()

    # ── state ────────────────────────────────────────────────────────────────

    def load(self):
        self.hall.auto_pantheon()
        self._tiers = {t["key"]: t for t in self.hall.tiers()}
        total = self.hall.count()
        self.sub.setText(f"{total} title{'s' if total != 1 else ''} across your libraries, ranked by you."
                         if total else "Your all-time favourites, ranked honestly. Induct your first title.")
        for w, b in self.wing_btns.items():
            if w == "honours":
                from core.honours import Honours
                n = Honours(self.db).count()
                b.setText(f"🏆  Honours  {n}" if n else "🏆  Honours")
                color = GOLD
            else:
                b.setText(f"{WING_NAMES[w]}  {self.hall.count(w)}")
                color = WING_COLORS[w]
            b.setChecked(w == self.wing)
            b.setStyleSheet(f"QPushButton#hallTab:checked{{color:#0b0d12;background:{color};border-color:{color};}}")
        for k, b in self.view_btns.items():
            b.setChecked(k == self.view)
            b.setVisible(self.wing != "honours")
        _clear(self.pantheon)
        for i, e in enumerate(self.hall.pantheon(), start=1):
            s = _PantheonSlot(i, e)
            s.clicked.connect(self._on_slot)
            s.menu.connect(self._slot_menu)
            self.pantheon.addWidget(s)
        self.pantheon.addStretch()
        self._render()

    def _set_wing(self, w: str):
        self.wing = w
        self.load()

    def _set_view(self, v: str):
        self.view = v
        self.load()

    def _render(self):
        _clear(self.body)
        if self.wing == "honours":
            from ui.hall_honours import HonoursView
            v = HonoursView(self.db, self)
            v.changed.connect(self._changed)
            v.open_title.connect(self.open_title.emit)
            self.body.addWidget(v)
            return
        es = self.hall.entries(self.wing)
        if not es and self.view != "numbers":
            self._empty()
            return
        getattr(self, "_view_" + self.view)(es)

    def _empty(self):
        box = QFrame()
        box.setObjectName("hallEmpty")
        v = QVBoxLayout(box)
        v.setContentsMargins(30, 34, 30, 34)
        v.setSpacing(10)
        t = QLabel(f"Your {WING_NAMES[self.wing]} Hall is waiting for its first legend.")
        t.setObjectName("homeSection")
        t.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(t)
        n = len(self.hall.candidates(self.wing))
        s = QLabel((f"{n} finished title{'s' if n != 1 else ''} in your library can join — or search for "
                    "anything you've watched, even if it isn't in Raikō yet. " if n else
                    "Search for anything you've watched — it's added to your library and joins the Hall. ")
                   + "Raikō then asks a few “which do you love more?” questions to find its place.")
        s.setObjectName("homeDate")
        s.setWordWrap(True)
        s.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(s)
        if True:
            b = QPushButton("+  Induct a title")
            b.setObjectName("hallPrimary")
            b.setStyleSheet(f"QPushButton#hallPrimary{{background:{WING_COLORS[self.wing]};}}")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(self._induct)
            v.addWidget(b, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.body.addWidget(box)

    # ── views ────────────────────────────────────────────────────────────────

    def _wire(self, w):
        w.clicked.connect(self._plaque)
        w.menu.connect(self._menu)
        return w

    def _view_showcase(self, es: List[Dict]):
        self.body.addWidget(self._wire(_Feature(es[0], self.hall.story(es[0]["lib_id"]), self._tiers)))
        if len(es) > 1:
            row = QHBoxLayout()
            row.setSpacing(16)
            for e in es[1:3]:
                row.addWidget(self._wire(_Feature(e, self.hall.story(e["lib_id"]), self._tiers, compact=True)), 1)
            if len(es) == 2:
                row.addStretch(1)
            self.body.addLayout(row)
        if len(es) > 3:
            host = QWidget()
            flow = FlowLayout(host, 16, 18)
            for e in es[3:]:
                flow.addWidget(self._wire(_HallPoster(e, 128, self._tiers)))
            self.body.addWidget(host)

    def _view_list(self, es: List[Dict]):
        hint = QLabel("Drag a row to move it. Click to open its plaque.")
        hint.setObjectName("homeDate")
        self.body.addWidget(hint)
        lst = _RankList()
        for e in es:
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, e["lib_id"])
            it.setSizeHint(QSize(100, _ListRow.H))
            lst.addItem(it)
            lst.setItemWidget(it, _ListRow(e, self.hall.movement(e["lib_id"]), self._tiers))
        lst.fit()
        lst.moved.connect(self._on_list_move)
        lst.opened.connect(self._plaque)
        lst.menu.connect(self._menu)
        self.body.addWidget(lst)

    def _on_list_move(self, lib_id: int, rank: int):
        self.hall.move(lib_id, rank)
        QTimer.singleShot(0, self._changed)

    def _view_tiers(self, es: List[Dict]):
        hint = QLabel("Drag posters between tiers. Tiers are a second lens — your ranking stays as it is.")
        hint.setObjectName("homeDate")
        self.body.addWidget(hint)
        rows = self.hall.tiers() + [{"key": "", "label": "No tier", "color": "#2a2f45"}]
        lists = []
        for t in rows:
            frame = QFrame()
            frame.setObjectName("hallTierFrame")
            h = QHBoxLayout(frame)
            h.setContentsMargins(0, 0, 8, 0)
            h.setSpacing(10)
            lab = QLabel(t["label"])
            lab.setObjectName("hallTierLabel")
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setFixedWidth(84 if t["key"] == "" else 64)
            fg = "#0b0d12" if t["key"] else "#aab1c9"
            lab.setStyleSheet(f"background:{t['color']};color:{fg};"
                              + ("" if t["key"] else "font-size:12px;font-weight:800;"))
            h.addWidget(lab)
            lst = _TierRow(t["key"])
            for e in es:
                if (e.get("tier") or "") == t["key"] or (t["key"] == "" and e.get("tier") not in self._tiers):
                    lst.add_entry(e)
            lst.dropped.connect(self._on_tier_drop)
            lst.opened.connect(self._plaque)
            lst.menu.connect(self._menu)
            h.addWidget(lst, 1)
            self.body.addWidget(frame)
            lists.append(lst)
        QTimer.singleShot(0, lambda: [x.fit() for x in lists])
        edit = QPushButton("Rename tiers…")
        edit.setObjectName("hallGhost")
        edit.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        edit.clicked.connect(self._rename_tiers)
        self.body.addWidget(edit, alignment=Qt.AlignmentFlag.AlignLeft)

    def _on_tier_drop(self, lib_id: int, key: str):
        self.hall.set_fields(lib_id, tier=key or None)
        self._changed()

    def _rename_tiers(self):
        from PyQt6.QtWidgets import QInputDialog
        tiers = self.hall.tiers()
        cur = ", ".join(t["label"] for t in tiers)
        text, ok = QInputDialog.getText(self, "Rename tiers",
                                        "Tier names, best first, separated by commas (up to 6):", text=cur)
        if not ok:
            return
        names = [n.strip()[:12] for n in text.split(",") if n.strip()][:6]
        if not names:
            return
        palette = ["#f472b6", "#8b7bff", "#38bdf8", "#34d399", "#fbbf24", "#94a3b8"]
        new = []
        for i, n in enumerate(names):
            old = tiers[i] if i < len(tiers) else None
            new.append({"key": old["key"] if old else f"T{i}", "label": n,
                        "color": old["color"] if old else palette[i]})
        self.hall.set_tiers(new)
        self._changed()

    def _view_timeline(self, _es):
        items = self.hall.timeline()
        year = None
        for e in items:
            y = datetime.fromtimestamp(e["inducted_at"]).year if e.get("inducted_at") else None
            if y != year:
                year = y
                yl = QLabel(str(y) if y else "Earlier")
                yl.setObjectName("hallYear")
                self.body.addWidget(yl)
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(14)
            d = QLabel(datetime.fromtimestamp(e["inducted_at"]).strftime("%b ") +
                       str(datetime.fromtimestamp(e["inducted_at"]).day) if e.get("inducted_at") else "")
            d.setObjectName("hallTimeDate")
            d.setFixedWidth(60)
            h.addWidget(d)
            dot = QLabel()
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background:{WING_COLORS[e['wing']]};border-radius:5px;")
            h.addWidget(dot)
            p = _HallPoster(e, 46, self._tiers, show_title=False)
            self._wire(p)
            h.addWidget(p)
            txt = QLabel(f"<b>{e['title']}</b> entered your {WING_NAMES[e['wing']]} Hall"
                         f" — now <span style='color:{GOLD}'>#{e['rank']}</span>")
            txt.setObjectName("hallTimeText")
            txt.setWordWrap(True)
            h.addWidget(txt, 1)
            self.body.addWidget(row)

    def _view_numbers(self, _es):
        n = self.hall.numbers(self.wing)
        color = WING_COLORS[self.wing]
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        everything = sum(self.hall.count(w) for w in WINGS)
        for v, k in ((n["count"], f"in {WING_NAMES[self.wing]}"), (f"{n['hours']} h", "of your life, well spent"),
                     (everything, "across all wings")):
            t = QFrame()
            t.setObjectName("homeStat")
            tl = QVBoxLayout(t)
            tl.setContentsMargins(16, 12, 16, 12)
            a = QLabel(str(v))
            a.setObjectName("homeStatValue")
            b = QLabel(k.upper())
            b.setObjectName("homeStatLabel")
            tl.addWidget(a)
            tl.addWidget(b)
            tiles.addWidget(t)
        tiles.addStretch()
        self.body.addLayout(tiles)
        grid = QGridLayout()
        grid.setHorizontalSpacing(40)
        grid.setVerticalSpacing(20)
        top = Qt.AlignmentFlag.AlignTop
        grid.addWidget(_Bars("Genres", n["genres"], color), 0, 0, top)
        grid.addWidget(_Bars("Studios" if self.wing == "anime" else "Networks & studios", n["studios"], color),
                       0, 1, top)
        grid.addWidget(_Bars("Decades", n["decades"], color), 1, 0, top)
        self.body.addLayout(grid)

    # ── actions ──────────────────────────────────────────────────────────────

    def _changed(self):
        self.load()
        self.changed.emit()

    def _induct(self):
        wing = self.wing if self.wing in WINGS else "anime"
        if induct(self.hall, self, wing):
            from core.hall import Hall as _H
            self.wing = _H.wing_of(self.db.get_anime_by_id(self._last_inducted()) or {}) or wing
            self._changed()

    def _last_inducted(self) -> int:
        r = self.hall.conn.execute("SELECT lib_id FROM hof_entries ORDER BY inducted_at DESC, id DESC LIMIT 1").fetchone()
        return r[0] if r else 0

    def _plaque(self, lib_id: int):
        dlg = PlaqueDialog(self.hall, lib_id, self)
        dlg.exec()
        self._act(lib_id, dlg.action)

    def _act(self, lib_id: int, action: Optional[str]):
        if action == "details":
            self.open_title.emit(lib_id)
            return
        if action == "rerank":
            RankDialog(self.hall, lib_id, self).exec()
        elif action == "pin":
            slots = self.hall.pantheon()
            free = next((i + 1 for i, s in enumerate(slots) if s is None), None)
            if free is None:
                self._pin_menu(lib_id, QCursor.pos())
                return
            self.hall.pin(lib_id, free)
        elif action == "unpin":
            self.hall.unpin(lib_id)
        elif action == "remove":
            e = self.hall.entry(lib_id)
            if QMessageBox.question(self, "Remove from the Hall of Fame",
                                    f"Take {e['title']} out of your Hall of Fame? Its note and history go too."
                                    ) != QMessageBox.StandardButton.Yes:
                return
            self.hall.remove(lib_id)
        self._changed()

    def _menu(self, lib_id: int, pos: QPoint):
        e = self.hall.entry(lib_id)
        if not e:
            return
        m = QMenu(self)
        m.addAction("Open plaque", lambda: self._plaque(lib_id))
        m.addAction("Open details", lambda: self.open_title.emit(lib_id))
        m.addAction("Re-rank (which do you love more?)", lambda: self._act(lib_id, "rerank"))
        tm = m.addMenu("Tier")
        for t in [{"key": "", "label": "No tier"}] + self.hall.tiers():
            a = tm.addAction(t["label"], lambda k=t["key"]: self._on_tier_drop(lib_id, k))
            a.setCheckable(True)
            a.setChecked((e.get("tier") or "") == t["key"])
        pm = m.addMenu("Pantheon")
        slots = self.hall.pantheon()
        for i, s in enumerate(slots, start=1):
            label = f"Slot {i}" + (f" — replaces {s['title']}" if s and s["lib_id"] != lib_id else
                                   " (here)" if s else " — empty")
            pm.addAction(label, lambda i=i: (self.hall.pin(lib_id, i), self._changed()))
        if e.get("pinned"):
            pm.addAction("Unpin", lambda: self._act(lib_id, "unpin"))
        m.addSeparator()
        m.addAction("Remove from Hall", lambda: self._act(lib_id, "remove"))
        m.exec(pos)

    def _pin_menu(self, lib_id: int, pos: QPoint):
        m = QMenu(self)
        for i, s in enumerate(self.hall.pantheon(), start=1):
            m.addAction(f"Slot {i}" + (f" — replaces {s['title']}" if s else ""),
                        lambda i=i: (self.hall.pin(lib_id, i), self._changed()))
        m.exec(pos)

    def _on_slot(self, slot: int):
        e = self.hall.pantheon()[slot - 1]
        if e:
            self._plaque(e["lib_id"])
            return
        # empty slot: choose from the Hall
        m = QMenu(self)
        any_ = False
        for w in WINGS:
            es = [x for x in self.hall.entries(w) if not x.get("pinned")]
            if not es:
                continue
            sm = m.addMenu(WING_NAMES[w])
            for x in es[:25]:
                sm.addAction(f"#{x['rank']}  {x['title']}",
                             lambda lid=x["lib_id"]: (self.hall.pin(lid, slot), self._changed()))
                any_ = True
        if not any_:
            m.addAction("Induct a title first", self._induct)
        m.exec(QCursor.pos())

    def _slot_menu(self, slot: int, pos: QPoint):
        e = self.hall.pantheon()[slot - 1]
        if e:
            self._menu(e["lib_id"], pos)
        else:
            self._on_slot(slot)

    def _share(self):
        from ui.hall_share import ShareDialog
        ShareDialog(self.hall, self.wing if self.wing in WINGS else "anime", self).exec()
