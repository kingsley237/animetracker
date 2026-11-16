"""
Miroku - small layout helpers shared by panels.

FlowLayout       - lays children out left-to-right and wraps to the next line
                   (genre chips, action buttons) instead of forcing width.
FitWidthScroll   - a vertical-only scroll area whose content is always exactly
                   as wide as the visible area, so nothing can ever scroll
                   sideways.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QFrame, QLayout, QScrollArea, QSizePolicy, QWidgetItem


class FlowLayout(QLayout):
    def __init__(self, parent=None, h_spacing: int = 6, v_spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._h = h_spacing
        self._v = v_spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)
        self.invalidate()

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def clear(self):
        while self._items:
            it = self._items.pop()
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.invalidate()

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = eff.x(), eff.y(), 0
        for it in self._items:
            w = it.widget()
            if w is not None and not w.isVisibleTo(w.parentWidget() or w):
                continue
            hint = it.sizeHint()
            hint.setWidth(min(hint.width(), max(eff.width(), 1)))
            nx = x + hint.width() + self._h
            if nx - self._h > eff.right() + 1 and line_h > 0:
                x = eff.x()
                y += line_h + self._v
                nx = x + hint.width() + self._h
                line_h = 0
            if apply:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x = nx
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


class FitWidthScroll(QScrollArea):
    """Vertical scroll only; content width is pinned to the viewport."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.viewport().installEventFilter(self)

    def setWidget(self, w):
        super().setWidget(w)
        w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._fit()

    def eventFilter(self, obj, ev):
        if obj is self.viewport() and ev.type() == QEvent.Type.Resize:
            self._fit()
        return super().eventFilter(obj, ev)

    def _fit(self):
        w = self.widget()
        if w is not None:
            w.setFixedWidth(self.viewport().width())
        self.horizontalScrollBar().setValue(0)
