"""
Raikō - status switcher for the detail panel.

A segmented row (Watchlist · Watching · Finished · Dropped, depending on the
kind of title). The current status is filled in its colour; moves that make
no sense are greyed out, with the reason on hover. The rules live in
core.status_rules.
"""
from __future__ import annotations

from typing import Dict, List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

COLORS = {"planned": "#8b93b0", "watching": "#8b7bff", "completed": "#34d399", "dropped": "#f87171"}


class StatusSwitcher(QWidget):
    requested = pyqtSignal(str)          # status key the user picked

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusSwitch")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        head = QLabel("STATUS")
        head.setObjectName("statusSwitchHead")
        lay.addWidget(head)
        self.row_host = QWidget()
        self.row_host.setObjectName("statusSwitchTrack")
        self.row = QHBoxLayout(self.row_host)
        self.row.setContentsMargins(3, 3, 3, 3)
        self.row.setSpacing(3)
        lay.addWidget(self.row_host)
        self.hint = QLabel()
        self.hint.setObjectName("statusSwitchHint")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.buttons: Dict[str, QPushButton] = {}

    def set_options(self, opts: List[Dict], hint: str = ""):
        while self.row.count():
            it = self.row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.buttons = {}
        for o in opts:
            b = QPushButton(("✓  " if o["current"] else "") + o["label"])
            b.setObjectName("statusSeg")
            b.setProperty("current", "true" if o["current"] else "false")
            b.setProperty("blocked", "false" if o["allowed"] or o["current"] else "true")
            if o["current"]:
                c = COLORS.get(o["key"], "#8b7bff")
                b.setStyleSheet(f"QPushButton#statusSeg{{background:{c};color:#0b0d12;}}")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if o["allowed"] and not o["current"]
                                else Qt.CursorShape.ArrowCursor))
            b.setToolTip(o["reason"] or ("" if o["current"] else f"Move to {o['label']}"))
            if o["allowed"] and not o["current"]:
                b.clicked.connect(lambda _=False, k=o["key"]: self.requested.emit(k))
            self.buttons[o["key"]] = b
            self.row.addWidget(b, 1)
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))
