"""
Miroku — AniList user avatar + account menu (library header).
"""
from __future__ import annotations

import webbrowser
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QMenu, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QCursor

from workers.workers import ImageWorker, run_worker


AVATAR_SIZE = 36


def _circle_pixmap(source: QPixmap, size: int) -> QPixmap:
    scaled = source.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    cx = max(0, (scaled.width() - size) // 2)
    cy = max(0, (scaled.height() - size) // 2)
    cropped = scaled.copy(cx, cy, size, size)

    out = QPixmap(size, size)
    out.fill(QColor(0, 0, 0, 0))
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(0, 0, size, size)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, cropped)
    painter.end()
    return out


class AvatarButton(QPushButton):
    """Circular avatar face for the account menu trigger."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._face: Optional[QPixmap] = None
        self.setObjectName("anilistAvatarBtn")
        self.setFixedSize(AVATAR_SIZE + 4, AVATAR_SIZE + 4)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def set_face(self, px: QPixmap):
        self._face = px
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._face is None or self._face.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = (self.width() - AVATAR_SIZE) // 2
        painter.drawPixmap(inset, inset, self._face)


class AniListUserMenu(QWidget):
    """Logged-in AniList avatar with dropdown; connect prompt when logged out."""

    connect_requested = pyqtSignal()
    account_settings_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._avatar_worker_url: Optional[str] = None
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._logged_in_w = QWidget()
        logged_lay = QHBoxLayout(self._logged_in_w)
        logged_lay.setContentsMargins(0, 0, 0, 0)
        logged_lay.setSpacing(8)

        self._avatar_btn = AvatarButton()
        self._avatar_btn.setToolTip("AniList account")
        self._avatar_btn.clicked.connect(self._show_menu)
        logged_lay.addWidget(self._avatar_btn)

        self._name_btn = QPushButton()
        self._name_btn.setObjectName("anilistUserNameBtn")
        self._name_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._name_btn.clicked.connect(self._show_menu)
        logged_lay.addWidget(self._name_btn)

        lay.addWidget(self._logged_in_w)

        self._connect_btn = QPushButton("Connect AniList")
        self._connect_btn.setObjectName("secondaryBtn")
        self._connect_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._connect_btn.clicked.connect(self.connect_requested.emit)
        lay.addWidget(self._connect_btn)

        self._set_logged_in_visible(False)

    def _set_logged_in_visible(self, logged_in: bool):
        self._logged_in_w.setVisible(logged_in)
        self._connect_btn.setVisible(not logged_in)

    def refresh(self):
        from core.anilist_auth import get_anilist_auth

        auth = get_anilist_auth(self.window())
        if not auth.is_logged_in():
            self._avatar_worker_url = None
            self._set_avatar_placeholder()
            self._set_logged_in_visible(False)
            return

        username = auth.get_username() or "AniList User"
        self._name_btn.setText(username)
        self._avatar_btn.setToolTip(f"AniList — {username}")
        self._set_logged_in_visible(True)

        avatar_url = auth.get_avatar_url()
        if avatar_url:
            self._load_avatar(avatar_url)
        else:
            self._set_avatar_placeholder(username)

    def _set_avatar_placeholder(self, initials_source: str = ""):
        px = QPixmap(AVATAR_SIZE, AVATAR_SIZE)
        px.fill(QColor(0, 0, 0, 0))
        painter = QPainter(px)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#2c3350"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, AVATAR_SIZE, AVATAR_SIZE)
        if initials_source:
            painter.setPen(QColor("#e2e4ec"))
            font = painter.font()
            font.setPointSize(11)
            font.setBold(True)
            painter.setFont(font)
            initials = "".join(part[0] for part in initials_source.split()[:2]).upper()
            painter.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, initials or "?")
        painter.end()
        self._avatar_btn.set_face(_circle_pixmap(px, AVATAR_SIZE))

    def _load_avatar(self, url: str):
        from core.image_cache import get_cached_path

        cached = get_cached_path(url)
        if cached:
            px = QPixmap(str(cached))
            if not px.isNull():
                self._avatar_btn.set_face(_circle_pixmap(px, AVATAR_SIZE))
                return

        if url == self._avatar_worker_url:
            return
        self._avatar_worker_url = url

        worker = ImageWorker(url, "anilist_avatar")
        worker.signals.result.connect(self._on_avatar_loaded)
        run_worker(worker)

    def _on_avatar_loaded(self, result):
        if not result:
            return
        _target_id, _size, path = result
        if not path:
            return
        px = QPixmap(path)
        if px.isNull():
            return
        self._avatar_btn.set_face(_circle_pixmap(px, AVATAR_SIZE))

    def _show_menu(self):
        from core.anilist_auth import get_anilist_auth

        auth = get_anilist_auth(self.window())
        if not auth.is_logged_in():
            self.connect_requested.emit()
            return

        menu = QMenu(self)
        username = auth.get_username() or "AniList User"

        header = menu.addAction(username)
        header.setEnabled(False)

        menu.addSeparator()

        profile_url = auth.get_profile_url()
        if profile_url:
            view_action = menu.addAction("View profile on AniList")
            view_action.triggered.connect(lambda: webbrowser.open(profile_url))

        settings_action = menu.addAction("Account settings…")
        settings_action.triggered.connect(self.account_settings_requested.emit)

        menu.addSeparator()

        logout_action = menu.addAction("Log out")
        logout_action.triggered.connect(self._confirm_logout)

        menu.exec(self._avatar_btn.mapToGlobal(
            self._avatar_btn.rect().bottomLeft()
        ))

    def _confirm_logout(self):
        from core.anilist_auth import get_anilist_auth

        auth = get_anilist_auth(self.window())
        username = auth.get_username() or "your account"
        res = QMessageBox.question(
            self.window(),
            "Log out of AniList?",
            f"Disconnect {username} from Miroku?\n"
            "Your local library and ratings stay on this device.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        auth.logout()
        from ui.toast import Toast
        Toast.show(self.window(), "AniList disconnected.", kind="info")
        self.refresh()
