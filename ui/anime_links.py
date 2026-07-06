"""
Miroku — Anime quick-link UI (open menu, CRUD dialog).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QFrame,
    QVBoxLayout,
    QWidget,
)

from core.database import DatabaseManager
from core.link_opener import (
    detect_platform,
    open_link,
    platform_label,
    set_links_always_open_browser,
    links_always_open_browser,
)

PLATFORM_CHOICES = [
    ("Auto-detect", "auto"),
    ("Telegram", "telegram"),
    ("Crunchyroll", "crunchyroll"),
    ("Netflix", "netflix"),
    ("Disney+", "disney"),
    ("Hulu", "hulu"),
    ("Prime Video", "prime"),
    ("YouTube", "youtube"),
    ("Other", "other"),
]


class LinkOpenMenu(QMenu):
    """Popover menu to open saved links with browser override."""

    links_changed = pyqtSignal()

    def __init__(self, anime_id: int, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.anime_id = anime_id
        self.db = db
        self.setObjectName("animeLinkMenu")
        self._populate()

    def _populate(self):
        self.clear()
        links = self.db.get_anime_links(self.anime_id)
        if not links:
            empty = self.addAction("No links saved")
            empty.setEnabled(False)
            return

        for link in links:
            platform = link.get("platform") or detect_platform(link["url"])
            label = link.get("label") or platform_label(platform)
            action = self.addAction(f"{platform_label(platform)} — {label}")
            action.setData(link)
            action.triggered.connect(lambda checked=False, l=link: self._open_one(l, False))

        self.addSeparator()

        for link in links:
            platform = link.get("platform") or detect_platform(link["url"])
            label = link.get("label") or platform_label(platform)
            browser_action = self.addAction(f"Open in browser — {label}")
            browser_action.triggered.connect(
                lambda checked=False, l=link: self._open_one(l, True)
            )

        self.addSeparator()
        pref = links_always_open_browser()
        always = self.addAction(
            "✓ Always open in browser" if pref else "Always open in browser"
        )
        always.triggered.connect(self._toggle_always_browser)

    def _open_one(self, link: Dict, force_browser: bool):
        platform = link.get("platform") or detect_platform(link["url"])
        if platform == "auto":
            platform = detect_platform(link["url"])
        open_link(link["url"], force_browser=force_browser, platform=platform)

    def _toggle_always_browser(self):
        set_links_always_open_browser(not links_always_open_browser())
        self._populate()


class LinkEditDialog(QDialog):
    """Create or edit a single anime link."""

    def __init__(self, anime_id: int, db: DatabaseManager,
                 link: Optional[Dict] = None, parent=None):
        super().__init__(parent)
        self.anime_id = anime_id
        self.db = db
        self._link = link
        self.setWindowTitle("Edit link" if link else "Add link")
        self.setMinimumWidth(420)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("e.g. Official channel, Episodes, Fansub")
        form.addRow("Label", self.label_edit)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://t.me/channel or crunchyroll.com/…")
        form.addRow("URL", self.url_edit)

        self.platform_combo = QComboBox()
        for label, key in PLATFORM_CHOICES:
            self.platform_combo.addItem(label, key)
        form.addRow("Platform", self.platform_combo)

        lay.addLayout(form)

        hint = QLabel(
            "Telegram links open in the app by default. Use “Open in browser” "
            "from the link menu, or enable “Always open in browser” there."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size:11px;color:#6b7280;")
        lay.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        if self._link:
            self.label_edit.setText(self._link.get("label", ""))
            self.url_edit.setText(self._link.get("url", ""))
            platform = self._link.get("platform") or "auto"
            idx = self.platform_combo.findData(platform)
            if idx >= 0:
                self.platform_combo.setCurrentIndex(idx)

    def _save(self):
        label = self.label_edit.text().strip()
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Enter a link URL.")
            return
        platform = self.platform_combo.currentData()
        if platform == "auto":
            platform = detect_platform(url)

        if self._link:
            self.db.update_anime_link(
                self._link["id"],
                label=label or platform_label(platform),
                url=url,
                platform=platform,
            )
        else:
            self.db.add_anime_link(
                self.anime_id,
                label=label or platform_label(platform),
                url=url,
                platform=platform,
            )
        self.accept()


class LinksManagerWidget(QWidget):
    """Inline CRUD list for the detail panel."""

    links_changed = pyqtSignal()

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self._anime_id: Optional[int] = None
        self._rows: List[QWidget] = []
        self._list_lay = QVBoxLayout()
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(6)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._empty_lbl = QLabel("No quick links yet. Add Crunchyroll, Telegram, browser-only pages, or anything else you use.")
        self._empty_lbl.setStyleSheet("font-size:12px;color:#4a5070;")
        self._empty_lbl.setWordWrap(True)
        root.addWidget(self._empty_lbl)

        root.addLayout(self._list_lay)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        add_btn = QPushButton("Add link")
        add_btn.setObjectName("secondaryBtn")
        add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_btn.clicked.connect(self._add_link)
        actions.addWidget(add_btn)
        actions.addStretch()
        root.addLayout(actions)

    def load(self, anime_id: int):
        self._anime_id = anime_id
        self._rebuild()

    def _clear_rows(self):
        while self._list_lay.count():
            item = self._list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()

    def _rebuild(self):
        self._clear_rows()
        if not self._anime_id or self._anime_id < 0:
            self._empty_lbl.setVisible(True)
            return

        links = self.db.get_anime_links(self._anime_id)
        self._empty_lbl.setVisible(not links)

        for link in links:
            card = QFrame()
            card.setObjectName("detailLinkCard")
            card.setStyleSheet(
                "QFrame#detailLinkCard{background:#0d0f14;border:1px solid #1a1d28;"
                "border-radius:8px;}"
            )
            row = QVBoxLayout(card)
            row.setContentsMargins(10, 9, 10, 9)
            row.setSpacing(8)

            top = QHBoxLayout()
            top.setSpacing(8)

            platform = link.get("platform") or detect_platform(link["url"])
            badge = QLabel(platform_label(platform))
            badge.setStyleSheet(
                "font-size:10px;font-weight:700;color:#a594f9;"
                "background:#15102c;border-radius:6px;padding:3px 8px;"
            )
            top.addWidget(badge)

            title = QLabel(link.get("label") or link["url"])
            title.setStyleSheet("font-size:12px;color:#c7cbd9;")
            title.setToolTip(link["url"])
            title.setSizePolicy(title.sizePolicy().horizontalPolicy(), title.sizePolicy().verticalPolicy())
            top.addWidget(title, stretch=1)

            row.addLayout(top)

            actions = QHBoxLayout()
            actions.setSpacing(8)
            actions.addStretch()

            compact_style = "padding:4px 10px;font-size:11px;"

            open_btn = QPushButton("Open")
            open_btn.setObjectName("secondaryBtn")
            open_btn.setStyleSheet(compact_style)
            open_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            open_btn.clicked.connect(lambda _, l=link: self._open_link(l))
            actions.addWidget(open_btn)

            browser_btn = QPushButton("Browser")
            browser_btn.setObjectName("secondaryBtn")
            browser_btn.setStyleSheet(compact_style)
            browser_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            browser_btn.clicked.connect(lambda _, l=link: self._open_link(l, force_browser=True))
            actions.addWidget(browser_btn)

            edit_btn = QPushButton("Edit")
            edit_btn.setObjectName("secondaryBtn")
            edit_btn.setStyleSheet(compact_style)
            edit_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            edit_btn.clicked.connect(lambda _, l=link: self._edit_link(l))
            actions.addWidget(edit_btn)

            del_btn = QPushButton("×")
            del_btn.setObjectName("iconBtn")
            del_btn.setFixedSize(28, 28)
            del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            del_btn.clicked.connect(lambda _, l=link: self._delete_link(l))
            actions.addWidget(del_btn)

            row.addLayout(actions)

            self._list_lay.addWidget(card)
            self._rows.append(card)

    def _open_link(self, link: Dict, force_browser: bool = False):
        platform = link.get("platform") or detect_platform(link["url"])
        open_link(link["url"], platform=platform, force_browser=force_browser)

    def _add_link(self):
        if not self._anime_id or self._anime_id < 0:
            return
        dlg = LinkEditDialog(self._anime_id, self.db, parent=self.window())
        if dlg.exec():
            self._rebuild()
            self.links_changed.emit()

    def _edit_link(self, link: Dict):
        dlg = LinkEditDialog(self._anime_id, self.db, link=link, parent=self.window())
        if dlg.exec():
            self._rebuild()
            self.links_changed.emit()

    def _delete_link(self, link: Dict):
        name = link.get("label") or link["url"]
        res = QMessageBox.question(
            self.window(),
            "Delete link",
            f"Remove “{name}”?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        self.db.delete_anime_link(link["id"])
        self._rebuild()
        self.links_changed.emit()
