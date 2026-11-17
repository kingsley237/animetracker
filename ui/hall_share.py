"""
Raikō - Hall of Fame share card: a PNG of your Pantheon, a wing's Top 10,
your tier list or your Honours, made locally (no account, no server).
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from core.hall import WING_NAMES, WINGS, Hall
from ui.hall_rank import GOLD, WING_COLORS
from workers.workers import Worker, run_worker

W = 1080
MODES = [("pantheon", "Pantheon"), ("top", "Top 10"), ("tiers", "Tier list"), ("honours", "Honours")]


def _urls(hall: Hall, mode: str, wing: str) -> List[str]:
    if mode == "pantheon":
        return [e["row"].get("cover_url") for e in hall.pantheon() if e]
    if mode in ("top", "tiers"):
        es = hall.entries(wing)
        return [e["row"].get("cover_url") for e in (es[:10] if mode == "top" else es)]
    from core.honours import Honours
    out = []
    for a in Honours(hall.db).categories():
        e = a["entries"][0]
        if e:
            out.append(e.get("image"))
    return out


def _fetch(urls: List[str]) -> Dict[str, str]:
    from core.image_cache import download_image
    out = {}
    for u in urls:
        if u and u not in out:
            try:
                p = download_image(u)
                if p:
                    out[u] = str(p)
            except Exception:
                pass
    return out


class _Painter:
    def __init__(self, paths: Dict[str, str]):
        self.paths = paths
        self.cache: Dict[str, QPixmap] = {}

    def pix(self, url: Optional[str]) -> Optional[QPixmap]:
        if not url or url not in self.paths:
            return None
        if url not in self.cache:
            self.cache[url] = QPixmap(self.paths[url])
        return self.cache[url]

    def poster(self, p: QPainter, url: Optional[str], r: QRectF, rad=14, ring: Optional[str] = None):
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)
        p.save()
        p.setClipPath(path)
        pm = self.pix(url)
        if pm and not pm.isNull():
            sc = pm.scaled(int(r.width()), int(r.height()), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int(r.x()), int(r.y()), sc, (sc.width() - int(r.width())) // 2,
                         (sc.height() - int(r.height())) // 4, int(r.width()), int(r.height()))
        else:
            p.fillRect(r, QColor("#1a1e2e"))
        p.restore()
        p.setPen(QPen(QColor(ring) if ring else QColor(255, 255, 255, 40), 2 if ring else 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


def _font(px: int, bold=True, spacing: float = 0) -> QFont:
    f = QFont("Segoe UI")
    f.setPixelSize(px)
    f.setBold(bold)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def render(hall: Hall, mode: str, wing: str, paths: Dict[str, str]) -> QImage:
    pt = _Painter(paths)
    if mode == "pantheon":
        H = 820
    elif mode == "top":
        n = len(hall.entries(wing)[:10])
        H = 210 + 450 + 70 + (299 if n > 1 else 0) + (299 if n > 5 else 0) + 90
    elif mode == "tiers":
        H = 300 + max(1, len(hall.tiers())) * 190
    else:
        from core.honours import Honours
        H = 300 + max(1, -(-len([a for a in Honours(hall.db).categories() if a["entries"][0]]) // 2)) * 200
    img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    bg = QLinearGradient(0, 0, 0, H)
    bg.setColorAt(0, QColor("#11131d"))
    bg.setColorAt(1, QColor("#08090e"))
    p.fillRect(0, 0, W, H, bg)
    glow = QRadialGradient(W / 2, -60, W * 0.7)
    accent = QColor(GOLD if mode in ("pantheon", "honours") else WING_COLORS.get(wing, GOLD))
    c = QColor(accent)
    c.setAlpha(46)
    glow.setColorAt(0, c)
    glow.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(0, 0, W, H, glow)

    title = {"pantheon": "My Pantheon", "top": f"My top {WING_NAMES[wing]}",
             "tiers": f"{WING_NAMES[wing]} tier list", "honours": "My Honours"}[mode]
    if mode == "top":
        title = {"anime": "My top anime", "movie": "My top movies", "tv": "My top TV shows"}[wing]
    p.setFont(_font(18, spacing=5))
    p.setPen(accent)
    p.drawText(QRectF(0, 64, W, 30), Qt.AlignmentFlag.AlignHCenter, "HALL OF FAME")
    p.setFont(_font(56))
    p.setPen(QColor("#f6f7fb"))
    p.drawText(QRectF(0, 96, W, 80), Qt.AlignmentFlag.AlignHCenter, title)
    y = 210

    def label(text, x, yy, w, px=20, color="#eef0f7", bold=True, align=Qt.AlignmentFlag.AlignHCenter):
        p.setFont(_font(px, bold))
        p.setPen(QColor(color))
        p.drawText(QRectF(x, yy, w, px + 10), align,
                   p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(w)))

    if mode == "pantheon":
        slots = hall.pantheon()
        pw, ph, gap = 222, 333, 24
        x0 = (W - (4 * pw + 3 * gap)) / 2
        for i, e in enumerate(slots):
            x = x0 + i * (pw + gap)
            r = QRectF(x, y + 30, pw, ph)
            if e:
                pt.poster(p, e["row"].get("cover_url"), r, ring=GOLD)
                label(e["title"], x, r.bottom() + 18, pw, 19)
                label(WING_NAMES[e["wing"]].upper(), x, r.bottom() + 48, pw, 13,
                      WING_COLORS.get(e["wing"], GOLD))
            else:
                p.setPen(QPen(QColor("#2e3348"), 2, Qt.PenStyle.DashLine))
                p.drawRoundedRect(r, 14, 14)
    elif mode == "top":
        es = hall.entries(wing)[:10]
        if es:
            e = es[0]
            r = QRectF(W / 2 - 150, y, 300, 450)
            pt.poster(p, e["row"].get("cover_url"), r, ring=GOLD)
            p.setFont(_font(92))
            p.setPen(QColor(GOLD))
            p.drawText(QRectF(r.left() - 140, r.top() + 150, 120, 120), Qt.AlignmentFlag.AlignRight, "1")
            label(e["title"], 120, r.bottom() + 16, W - 240, 24)
            yy = r.bottom() + 70
            for row_es, start in ((es[1:5], 2), (es[5:10], 6)):
                if not row_es:
                    continue
                n = len(row_es)
                pw, ph, gap = 170, 255, 22
                x0 = (W - (n * pw + (n - 1) * gap)) / 2
                for i, e in enumerate(row_es):
                    x = x0 + i * (pw + gap)
                    rr = QRectF(x, yy, pw, ph)
                    pt.poster(p, e["row"].get("cover_url"), rr, 12, GOLD if start + i <= 3 else None)
                    p.setFont(_font(40))
                    p.setPen(QColor(GOLD) if start + i <= 3 else QColor("#ffffff"))
                    p.drawText(QRectF(rr.left() + 12, rr.bottom() - 60, 80, 54),
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, str(start + i))
                yy += ph + 44
    elif mode == "tiers":
        es = hall.entries(wing)
        for t in hall.tiers():
            members = [e for e in es if e.get("tier") == t["key"]]
            r = QRectF(60, y, 110, 160)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t["color"]))
            p.drawRoundedRect(r, 14, 14)
            p.setFont(_font(44 if len(t["label"]) <= 2 else 22))
            p.setPen(QColor("#0b0d12"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, t["label"])
            x = 190
            for e in members[:8]:
                pt.poster(p, e["row"].get("cover_url"), QRectF(x, y, 104, 156), 10)
                x += 112
            if len(members) > 8:
                label(f"+{len(members) - 8}", x, y + 60, 60, 22, "#aab1c9")
            y += 190
    else:
        from core.honours import Honours
        cats = [a for a in Honours(hall.db).categories() if a["entries"][0]]
        for i, a in enumerate(cats):
            e = a["entries"][0]
            x = 60 + (i % 2) * 490
            yy = y + (i // 2) * 200
            card = QRectF(x, yy, 470, 176)
            p.setPen(QPen(QColor(255, 255, 255, 22), 1))
            p.setBrush(QColor(255, 255, 255, 8))
            p.drawRoundedRect(card, 16, 16)
            pt.poster(p, e.get("image"), QRectF(x + 16, yy + 16, 96, 144), 10)
            label(a["label"].upper(), x + 130, yy + 22, 320, 14, GOLD, align=Qt.AlignmentFlag.AlignLeft)
            p.setFont(_font(24))
            p.setPen(QColor("#f4f5fa"))
            p.drawText(QRectF(x + 130, yy + 50, 320, 70), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                       e["label"])
            label(e.get("sub") or "", x + 130, yy + 126, 320, 15, "#8c93ad", False, Qt.AlignmentFlag.AlignLeft)

    p.setFont(_font(15, spacing=3))
    p.setPen(QColor("#6b7391"))
    d = datetime.now()
    p.drawText(QRectF(0, H - 56, W, 24), Qt.AlignmentFlag.AlignHCenter,
               f"RAIKŌ  ·  {d.strftime('%B').upper()} {d.year}")
    p.end()
    return img


class ShareDialog(QDialog):
    def __init__(self, hall: Hall, wing: str, parent=None):
        super().__init__(parent)
        self.hall = hall
        self.wing = wing if wing in WINGS else "anime"
        self.mode = "pantheon"
        self.img: Optional[QImage] = None
        self.setWindowTitle("Share card")
        self.setObjectName("hallDialog")
        self.resize(760, 860)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(12)
        bar = QHBoxLayout()
        self.btns = {}
        for k, name in MODES:
            b = QPushButton(name)
            b.setObjectName("hallSeg")
            b.setCheckable(True)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _=False, k=k: self._set(k))
            self.btns[k] = b
            bar.addWidget(b)
        bar.addSpacing(16)
        self.wbtns = {}
        for w in WINGS:
            b = QPushButton(WING_NAMES[w])
            b.setObjectName("hallTab")
            b.setCheckable(True)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setStyleSheet(f"QPushButton#hallTab:checked{{color:#0b0d12;background:{WING_COLORS[w]};}}")
            b.clicked.connect(lambda _=False, w=w: self._set_wing(w))
            self.wbtns[w] = b
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        self.preview = QLabel("Making your card…")
        self.preview.setObjectName("homeDate")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(600)
        lay.addWidget(self.preview, 1)
        foot = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName("homeDate")
        foot.addWidget(self.status, 1)
        copy = QPushButton("Copy image")
        copy.setObjectName("hallGhost")
        copy.clicked.connect(self._copy)
        save = QPushButton("Save PNG…")
        save.setObjectName("hallPrimary")
        save.setStyleSheet(f"QPushButton#hallPrimary{{background:{GOLD};}}")
        save.clicked.connect(self._save)
        for b in (copy, save):
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setAutoDefault(False)
            foot.addWidget(b)
        lay.addLayout(foot)
        self._set("pantheon")

    def _set(self, mode: str):
        self.mode = mode
        for k, b in self.btns.items():
            b.setChecked(k == mode)
        for b in self.wbtns.values():
            b.setVisible(mode in ("top", "tiers"))
        self._set_wing(self.wing)

    def _set_wing(self, w: str):
        self.wing = w
        for k, b in self.wbtns.items():
            b.setChecked(k == w)
        self.preview.setText("Making your card…")
        urls = _urls(self.hall, self.mode, self.wing)
        mode, wing = self.mode, self.wing
        wk = Worker(_fetch, urls)
        wk.signals.result.connect(lambda paths: self._render(paths, mode, wing))
        run_worker(wk)

    def _render(self, paths, mode, wing):
        try:
            if (mode, wing) != (self.mode, self.wing):
                return
            self.img = render(self.hall, mode, wing, paths)
            pm = QPixmap.fromImage(self.img).scaled(
                self.preview.width() - 8, self.preview.height() - 8, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self.preview.setPixmap(pm)
            self.status.setText(f"{self.img.width()} × {self.img.height()} px")
        except RuntimeError:
            pass

    def _save(self):
        if self.img is None:
            return
        from pathlib import Path
        name = {"pantheon": "pantheon", "top": f"top-{self.wing}", "tiers": f"tiers-{self.wing}",
                "honours": "honours"}[self.mode]
        path, _ = QFileDialog.getSaveFileName(self, "Save share card",
                                              str(Path.home() / "Pictures" / f"raiko-{name}.png"), "PNG (*.png)")
        if path:
            self.img.save(path, "PNG")
            self.status.setText(f"Saved to {path}")

    def _copy(self):
        if self.img is not None:
            QGuiApplication.clipboard().setImage(self.img)
            self.status.setText("Copied — paste it anywhere")
