"""
Miroku - rich notification banner.
"""
from __future__ import annotations

from typing import Dict, List

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame


class NotificationBanner(QFrame):
    open_anime = pyqtSignal(int)
    mark_watched = pyqtSignal(int, int)
    move_to_watching = pyqtSignal(int)
    remind_later = pyqtSignal(int)
    dismissed = pyqtSignal(int)

    _ACCENTS = {
        "episode_aired": ("#fbbf24", "#201804"),
        "planned_started": ("#34d399", "#071f17"),
        "planned_ended": ("#9da5c0", "#151821"),
        "upcoming_date": ("#a594f9", "#15102c"),
        "upcoming_trailer": ("#38bdf8", "#071826"),
        "new_season": ("#f87171", "#240909"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: List[Dict] = []
        self._current: Dict | None = None
        self._queued_ids: set[int] = set()
        self.setObjectName("richNotification")
        self.setFixedWidth(420)
        self.setMinimumHeight(120)
        self.setStyleSheet(
            "QFrame#richNotification{background:#0a0c10;border:1px solid #252a40;"
            "border-radius:10px;}"
        )
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(16, 14, 16, 14)
        self._root.setSpacing(10)
        self.hide()

    def show_notifications(self, notifications: List[Dict]):
        if not notifications:
            return
        for notification in notifications:
            nid = notification.get("id")
            if nid is None:
                continue
            current_id = self._current.get("id") if self._current else None
            if nid == current_id or nid in self._queued_ids:
                continue
            self._queue.append(notification)
            self._queued_ids.add(nid)
        if not self.isVisible():
            self._show_next()

    def clear_if_idle(self):
        if self._current is None and not self._queue:
            self.hide()

    def _show_next(self):
        self._clear()
        if not self._queue:
            self._current = None
            self.hide()
            return
        self._current = self._queue.pop(0)
        self._queued_ids.discard(self._current.get("id"))
        self._build(self._current)
        self._fit_to_content()
        self._reposition()
        self.show()
        self.raise_()

    def _clear(self):
        while self._root.count():
            item = self._root.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _build(self, item: Dict):
        kind = item.get("kind", "")
        accent, bg = self._ACCENTS.get(kind, ("#a594f9", "#15102c"))

        top = QHBoxLayout()
        badge = QLabel(self._kind_label(kind))
        badge.setStyleSheet(
            f"font-size:10px;font-weight:700;color:{accent};"
            f"background:{bg};border-radius:7px;padding:3px 8px;"
        )
        top.addWidget(badge)
        top.addStretch()
        close = QPushButton("x")
        close.setObjectName("iconBtn")
        close.setFixedSize(26, 26)
        close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close.clicked.connect(self._dismiss_current)
        top.addWidget(close)
        self._root.addLayout(top)

        title = QLabel(item.get("title", "Notification"))
        title.setStyleSheet("font-size:16px;font-weight:700;color:#f0f1f5;")
        title.setWordWrap(True)
        self._root.addWidget(title)

        message = QLabel(item.get("message", ""))
        message.setStyleSheet("font-size:12px;color:#9da5c0;line-height:1.5;")
        message.setWordWrap(True)
        self._root.addWidget(message)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        for label, callback, primary in self._actions_for(item):
            btn = QPushButton(label)
            btn.setObjectName("primaryBtn" if primary else "secondaryBtn")
            btn.setMinimumHeight(34)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(callback)
            actions.addWidget(btn)
        self._root.addLayout(actions)

    def _fit_to_content(self):
        self._root.activate()
        hint = self.sizeHint()
        self.setFixedSize(420, max(150, hint.height()))
        QTimer.singleShot(0, self._reposition)

    def _actions_for(self, item: Dict):
        nid = item["id"]
        aid = item.get("anime_id") or 0
        payload = item.get("payload") or {}
        kind = item.get("kind")
        actions = []

        if kind == "episode_aired":
            episode = int(payload.get("episode") or 0)
            actions.append(("Mark Watched", lambda: self._mark_watched(aid, episode), True))
            actions.append(("Open", lambda: self._open(aid), False))
        elif kind == "planned_started":
            actions.append(("Move to Watching", lambda: self._move_to_watching(aid), True))
            actions.append(("Open", lambda: self._open(aid), False))
        else:
            actions.append(("View", lambda: self._open(aid), True))

        actions.append(("Later", lambda: self._remind(nid), False))
        actions.append(("Dismiss", lambda: self._dismiss(nid), False))
        return actions

    def _kind_label(self, kind: str) -> str:
        return {
            "episode_aired": "NEW EPISODE",
            "planned_started": "NOW AIRING",
            "planned_ended": "STATUS CHANGE",
            "upcoming_date": "RELEASE DATE",
            "upcoming_trailer": "TRAILER",
            "new_season": "NEW SEASON",
        }.get(kind, "MIROKU")

    def _open(self, anime_id: int):
        self.open_anime.emit(anime_id)
        self._dismiss_current()

    def _mark_watched(self, anime_id: int, episode: int):
        self.mark_watched.emit(anime_id, episode)
        self._dismiss_current()

    def _move_to_watching(self, anime_id: int):
        self.move_to_watching.emit(anime_id)
        self._dismiss_current()

    def _remind(self, notification_id: int):
        self.remind_later.emit(notification_id)
        self._show_next()

    def _dismiss(self, notification_id: int):
        self.dismissed.emit(notification_id)
        self._show_next()

    def _dismiss_current(self):
        if self._current:
            self.dismissed.emit(self._current["id"])
        self._show_next()

    def _reposition(self):
        parent = self.parentWidget()
        if not parent:
            return
        margin = 18
        self.move(
            parent.width() - self.width() - margin,
            margin,
        )
