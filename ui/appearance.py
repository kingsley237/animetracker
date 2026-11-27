"""
Raikō - Settings → Appearance.

  Theme       a gallery of live miniatures (painted with each theme's own
              colours and fonts). Click = apply now (and saved); "Preview"
              walks through the real app in that theme without committing.
  Accent      curated swatches (+ theme default), applied instantly.
  Text size   90 % - 125 %.
"""
from __future__ import annotations

from typing import Dict

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor as _RawColor, QCursor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from ui.layout_helpers import FlowLayout
from ui.theme import Mapper, ThemeManager, set_raw_style
from ui.themes_catalog import ACCENTS, ORDER, build, info


def _c(m: Mapper, h: str, a: int = 255) -> _RawColor:
    c = _RawColor(m.hex(h))
    c.setAlpha(a)
    return c


class ThemeCard(QWidget):
    """A miniature of Raikō in one theme."""
    chosen = pyqtSignal(str)
    preview = pyqtSignal(str)
    W, H = 236, 150

    def __init__(self, tid: str, accent: str = "", parent=None):
        super().__init__(parent)
        self.tid = tid
        self.accent = accent
        self.meta = info(tid)
        self.theme = build(tid, accent)
        self.m = Mapper(self.theme)
        self.current = False
        self._hover = False
        self.setFixedSize(self.W, self.H + 58)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(f"{self.meta['name']} — {self.meta['tagline']}\nClick to use it · Preview to walk through it")
        self.pv = QPushButton("Preview", self)
        self.pv.setObjectName("themePreviewBtn")
        self.pv.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.pv.clicked.connect(lambda: self.preview.emit(self.tid))
        self.pv.adjustSize()
        self.pv.move(self.W - self.pv.width() - 10, self.H - self.pv.height() - 10)
        self.pv.hide()

    def set_current(self, on: bool):
        self.current = on
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.pv.show()
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.pv.hide()
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(self.tid)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self.m
        r = QRectF(1, 1, self.W - 2, self.H - 2)
        rad = 12 * float(self.theme.extra.get("radius", 1.0))
        frame = QPainterPath()
        frame.addRoundedRect(r, rad, rad)
        p.save()
        p.setClipPath(frame)
        p.fillRect(r, _c(m, "#0b0d12"))
        # sidebar
        p.fillRect(QRectF(r.left(), r.top(), 52, r.height()), _c(m, "#0f111a"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(m, "#8b7bff"))
        p.drawEllipse(QRectF(18, 12, 16, 16))
        for i in range(5):
            p.setBrush(_c(m, "#f4f5fa" if i == 0 else "#4a5070", 230 if i == 0 else 200))
            p.drawRoundedRect(QRectF(12, 40 + i * 16, 28 if i else 30, 5), 2, 2)
        # greeting
        f = QFont(self.theme.fonts.get("display") or "Segoe UI")
        f.setPixelSize(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(_c(m, "#f4f5fa"))
        p.drawText(QRectF(64, 8, 160, 16), Qt.AlignmentFlag.AlignLeft, "Good evening")
        # spotlight
        sp = QRectF(64, 28, r.width() - 76, 56)
        g = QLinearGradient(sp.topLeft(), sp.topRight())
        g.setColorAt(0, _c(m, "#1a1d28"))
        g.setColorAt(1, _c(m, "#8b7bff", 150))
        p.setBrush(g)
        p.drawRoundedRect(sp, 6 * float(self.theme.extra.get("radius", 1.0)),
                          6 * float(self.theme.extra.get("radius", 1.0)))
        p.setBrush(_c(m, "#f87171"))
        p.drawRoundedRect(QRectF(sp.left() + 8, sp.top() + 8, 30, 7), 3, 3)
        p.setBrush(_c(m, "#f4f5fa"))
        p.drawRoundedRect(QRectF(sp.left() + 8, sp.top() + 22, 70, 7), 3, 3)
        p.setBrush(_c(m, "#8b7bff"))
        p.drawRoundedRect(QRectF(sp.left() + 8, sp.top() + 38, 34, 10), 4, 4)
        # cards
        accents = ["#8b7bff", "#38bdf8", "#fbbf24", "#34d399"]
        cw = (r.width() - 76 - 3 * 6) / 4
        for i in range(4):
            cr = QRectF(64 + i * (cw + 6), 92, cw, 46)
            p.setBrush(_c(m, "#1a1d28"))
            p.drawRoundedRect(cr, 4 * float(self.theme.extra.get("radius", 1.0)),
                              4 * float(self.theme.extra.get("radius", 1.0)))
            p.setBrush(_c(m, accents[i]))
            p.drawRoundedRect(QRectF(cr.left() + 5, cr.bottom() - 9, cw * 0.6, 4), 2, 2)
        p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.current:
            p.setPen(QPen(_RawColor(ThemeManager.get().hex("#8b7bff")), 2.5))
        elif self._hover:
            p.setPen(QPen(_RawColor(255, 255, 255, 90) if self.theme.dark else _RawColor(0, 0, 0, 90), 1.5))
        else:
            p.setPen(QPen(_RawColor(128, 128, 140, 70), 1))
        p.drawPath(frame)
        # caption (in the current app theme)
        tf = QFont(self.font())
        tf.setBold(True)
        tf.setPixelSize(13)
        p.setFont(tf)
        p.setPen(_RawColor(ThemeManager.get().hex("#eef0f7")))
        name = self.meta["name"] + ("   ✓" if self.current else "")
        p.drawText(QRectF(2, self.H + 6, self.W, 20), Qt.AlignmentFlag.AlignLeft, name)
        tf.setBold(False)
        tf.setPixelSize(11)
        p.setFont(tf)
        p.setPen(_RawColor(ThemeManager.get().hex("#8c93ad")))
        p.drawText(QRectF(2, self.H + 26, self.W - 4, 30), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                   self.meta["tagline"])
        p.end()


class AppearancePage(QWidget):
    preview_requested = pyqtSignal(str, str)        # theme id, accent

    def __init__(self, parent=None):
        super().__init__(parent)
        from core.app_settings import app_settings
        st = app_settings()
        self.tid = str(st.value("theme_id", "raiko_night") or "raiko_night")
        self.accent = str(st.value("theme_accent", "") or "")
        try:
            self.scale = float(st.value("font_scale", 1.0) or 1.0)
        except (TypeError, ValueError):
            self.scale = 1.0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.grid_host = QWidget()
        self.grid = FlowLayout(self.grid_host, 14, 16)
        lay.addWidget(self.grid_host)
        self.cards: Dict[str, ThemeCard] = {}
        for tid in ORDER:
            c = ThemeCard(tid)
            c.chosen.connect(self._choose)
            c.preview.connect(lambda t: self.preview_requested.emit(t, self.accent))
            self.cards[tid] = c
            self.grid.addWidget(c)

        acc_head = QLabel("ACCENT")
        acc_head.setObjectName("statusSwitchHead")
        lay.addSpacing(6)
        lay.addWidget(acc_head)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.swatches: Dict[str, QPushButton] = {}
        for h in [""] + ACCENTS:
            b = QPushButton("Theme" if not h else "")
            b.setObjectName("accentSwatch")
            b.setFixedSize(64 if not h else 30, 30)
            b.setCheckable(True)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setToolTip("The theme's own accent" if not h else h)
            if h:
                b.setProperty("swatch", h)
            b.clicked.connect(lambda _=False, h=h: self._set_accent(h))
            self.swatches[h] = b
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

        size_head = QLabel("TEXT SIZE")
        size_head.setObjectName("statusSwitchHead")
        lay.addSpacing(6)
        lay.addWidget(size_head)
        srow = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(90, 125)
        self.slider.setSingleStep(5)
        self.slider.setPageStep(5)
        self.slider.setValue(int(round(self.scale * 100)))
        self.slider.setFixedWidth(260)
        self.size_lbl = QLabel()
        self.size_lbl.setObjectName("settingsValueText")
        self.slider.valueChanged.connect(lambda v: self.size_lbl.setText(f"{v}%"))
        self.slider.sliderReleased.connect(self._set_scale)
        self.slider.valueChanged.connect(lambda _v: (not self.slider.isSliderDown()) and self._set_scale())
        srow.addWidget(self.slider)
        srow.addWidget(self.size_lbl)
        srow.addStretch()
        lay.addLayout(srow)
        self.size_lbl.setText(f"{self.slider.value()}%")

        mot_head = QLabel("MOTION")
        mot_head.setObjectName("statusSwitchHead")
        lay.addSpacing(6)
        lay.addWidget(mot_head)
        mrow = QHBoxLayout()
        mrow.setSpacing(6)
        self.motion_btns: Dict[str, QPushButton] = {}
        cur = str(st.value("motion", "calm") or "calm")
        for key, label, tip in (("on", "Full", "Ambient effects and animated ornaments"),
                                ("calm", "Calm", "Fewer, slower effects"),
                                ("off", "Off", "No ambient effects; ornaments stay still")):
            b = QPushButton(label)
            b.setObjectName("hallSeg")
            b.setCheckable(True)
            b.setChecked(key == cur)
            b.setToolTip(tip)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _=False, k=key: self._set_motion(k))
            self.motion_btns[key] = b
            mrow.addWidget(b)
        mrow.addSpacing(16)
        from PyQt6.QtWidgets import QCheckBox
        self.follow = QCheckBox("Follow Windows' animation setting")
        self.follow.setChecked(str(st.value("motion_follow_windows", "true")).lower() != "false")
        self.follow.toggled.connect(self._set_follow)
        mrow.addWidget(self.follow)
        mrow.addStretch()
        lay.addLayout(mrow)
        self.mascot = QCheckBox("Show Rai, the Raikō mascot, during events")
        self.mascot.setChecked(str(st.value("mascot", "true")).lower() != "false")
        self.mascot.toggled.connect(self._set_mascot)
        lay.addWidget(self.mascot)
        self._refresh()

    def _refresh(self):
        for tid, c in self.cards.items():
            c.set_current(tid == self.tid)
        for h, b in self.swatches.items():
            b.setChecked(h == self.accent)
            if h:
                col = h
                ring = ThemeManager.get().hex("#f4f5fa")
                set_raw_style(b, f"QPushButton#accentSwatch{{background:{col};border-radius:15px;"
                                 f"border:{'3px solid ' + ring if h == self.accent else '1px solid rgba(128,128,140,0.5)'};}}")

    def _apply(self):
        ThemeManager.get().save(self.tid, self.accent, self.scale)
        ThemeManager.get().apply(build(self.tid, self.accent), self.scale)
        self._refresh()

    def _choose(self, tid: str):
        self.tid = tid
        self._apply()

    def _set_accent(self, h: str):
        self.accent = h
        self._apply()

    def _decor_changed(self):
        tm = ThemeManager.get()
        tm.changed.emit(tm.theme)

    def _set_motion(self, key: str):
        from core.app_settings import app_settings
        app_settings().setValue("motion", key)
        for k, b in self.motion_btns.items():
            b.setChecked(k == key)
        self._decor_changed()

    def _set_follow(self, on: bool):
        from core.app_settings import app_settings
        app_settings().setValue("motion_follow_windows", "true" if on else "false")
        self._decor_changed()

    def _set_mascot(self, on: bool):
        from core.app_settings import app_settings
        app_settings().setValue("mascot", "true" if on else "false")
        self._decor_changed()

    def _set_scale(self):
        v = self.slider.value() / 100
        if abs(v - self.scale) < 0.001:
            return
        self.scale = v
        self._apply()
