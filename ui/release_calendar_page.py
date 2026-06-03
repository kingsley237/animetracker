"""
Miroku - Release Calendar

Local-first weekly airing schedule for titles already in the library.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy,
)

from core.database import DatabaseManager


class ReleaseCalendarPage(QWidget):
    anime_selected = pyqtSignal(int)
    data_changed = pyqtSignal(int)

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self._items: List[Dict] = []
        self._build_ui()

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._refresh_countdowns)
        self._tick_timer.start(60_000)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 0)
        root.setSpacing(0)

        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(3)

        title = QLabel("Release Calendar")
        title.setObjectName("pageTitle")
        title_col.addWidget(title)

        subtitle = QLabel("Your next seven days of airing and upcoming episodes.")
        subtitle.setStyleSheet("font-size:13px;color:#626a80;")
        title_col.addWidget(subtitle)

        header.addLayout(title_col)
        header.addStretch()

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setObjectName("secondaryBtn")
        self._refresh_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._refresh_btn.clicked.connect(self.load)
        header.addWidget(self._refresh_btn)
        root.addLayout(header)
        root.addSpacing(16)

        self._summary_row = QHBoxLayout()
        self._summary_row.setSpacing(10)
        self._summary_cards: Dict[str, QLabel] = {}
        for key, label, color in [
            ("today", "Today", "#a594f9"),
            ("week", "This Week", "#34d399"),
            ("missed", "Recently Aired", "#fbbf24"),
        ]:
            card = QFrame()
            card.setStyleSheet(
                "QFrame{background:#111420;border-radius:8px;}"
            )
            card.setFixedHeight(72)
            card.setMinimumWidth(132)
            lay = QVBoxLayout(card)
            lay.setContentsMargins(14, 9, 14, 9)
            lay.setSpacing(1)
            value = QLabel("0")
            value.setStyleSheet(f"font-size:22px;font-weight:700;color:{color};")
            lay.addWidget(value)
            label_w = QLabel(label.upper())
            label_w.setStyleSheet(
                "font-size:10px;font-weight:700;color:#626a80;letter-spacing:1px;"
            )
            lay.addWidget(label_w)
            self._summary_cards[key] = value
            self._summary_row.addWidget(card)
        self._summary_row.addStretch()
        root.addLayout(self._summary_row)
        root.addSpacing(18)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._body = QWidget()
        self._body.setStyleSheet("background:transparent;")
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 0, 8, 20)
        self._body_lay.setSpacing(10)
        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll)

    def load(self):
        self._clear_body()
        now = datetime.now()
        start_ts = int((now - timedelta(hours=12)).timestamp())
        end_ts = int((now + timedelta(days=7)).timestamp())

        all_items = [
            a for a in self.db.get_all_anime()
            if a.get("next_episode_at")
            and start_ts <= int(a.get("next_episode_at") or 0) <= end_ts
            and a.get("watch_status") in ("watching", "planned")
        ]
        all_items.sort(key=lambda a: int(a.get("next_episode_at") or 0))
        self._items = all_items
        self._update_summary(all_items)

        if not all_items:
            self._show_empty()
            return

        grouped: Dict[str, List[Dict]] = {}
        for item in all_items:
            day_key = datetime.fromtimestamp(int(item["next_episode_at"])).strftime("%Y-%m-%d")
            grouped.setdefault(day_key, []).append(item)

        for day_key, items in grouped.items():
            self._add_day_group(day_key, items)
        self._body_lay.addStretch()

    def _clear_body(self):
        while self._body_lay.count():
            item = self._body_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _update_summary(self, items: List[Dict]):
        now = datetime.now()
        today = now.date()
        today_count = 0
        missed_count = 0
        for item in items:
            airing = datetime.fromtimestamp(int(item["next_episode_at"]))
            if airing.date() == today:
                today_count += 1
            if airing < now:
                missed_count += 1
        self._summary_cards["today"].setText(str(today_count))
        self._summary_cards["week"].setText(str(len(items)))
        self._summary_cards["missed"].setText(str(missed_count))

    def _show_empty(self):
        box = QFrame()
        box.setStyleSheet(
            "QFrame{background:#111420;border-radius:8px;}"
        )
        lay = QVBoxLayout(box)
        lay.setContentsMargins(28, 28, 28, 28)
        lay.setSpacing(8)
        title = QLabel("No scheduled releases yet")
        title.setStyleSheet("font-size:17px;font-weight:700;color:#f0f1f5;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        sub = QLabel(
            "Add airing or upcoming anime, then refresh airing data to populate this calendar."
        )
        sub.setWordWrap(True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("font-size:13px;color:#626a80;")
        lay.addWidget(sub)
        self._body_lay.addStretch()
        self._body_lay.addWidget(box)
        self._body_lay.addStretch()

    def _add_day_group(self, day_key: str, items: List[Dict]):
        day = datetime.strptime(day_key, "%Y-%m-%d")
        today = datetime.now().date()
        if day.date() == today:
            label = "Today"
        elif day.date() == today + timedelta(days=1):
            label = "Tomorrow"
        else:
            label = day.strftime("%A, %b %d")

        header = QLabel(f"{label}  -  {len(items)} release{'s' if len(items) != 1 else ''}")
        header.setStyleSheet(
            "font-size:10px;font-weight:700;color:#4e566d;letter-spacing:1.4px;"
            "padding:10px 0 2px 0;"
        )
        self._body_lay.addWidget(header)

        for item in items:
            self._body_lay.addWidget(_CalendarRow(item, self.db, self))

    def _refresh_countdowns(self):
        self.load()

    def open_anime(self, anime_id: int):
        self.anime_selected.emit(anime_id)

    def mark_aired_episode(self, anime: Dict):
        next_ep = int(anime.get("next_episode_num") or 0)
        episode_to_mark = max(1, next_ep - 1) if next_ep else 0
        if not episode_to_mark:
            return
        self.db.set_episode_watched(anime["id"], episode_to_mark, True)
        self.data_changed.emit(anime["id"])
        from ui.toast import Toast
        Toast.show(
            self.window(),
            f"Episode {episode_to_mark} marked watched.",
            kind="success",
        )
        self.load()


class _CalendarRow(QFrame):
    def __init__(self, anime: Dict, db: DatabaseManager, page: ReleaseCalendarPage):
        super().__init__(page)
        self.anime = anime
        self.db = db
        self.page = page
        self.setStyleSheet(
            "QFrame{background:#111420;border-radius:8px;}"
            "QFrame:hover{border-color:#2e3354;background:#141829;}"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(14)

        accent = QFrame()
        accent.setFixedWidth(4)
        accent.setStyleSheet(f"background:{self._accent_color()};border-radius:2px;")
        lay.addWidget(accent)

        time_box = QVBoxLayout()
        time_box.setSpacing(2)
        airing = datetime.fromtimestamp(int(self.anime["next_episode_at"]))
        time_lbl = QLabel(airing.strftime("%H:%M"))
        time_lbl.setStyleSheet("font-size:18px;font-weight:700;color:#f0f1f5;")
        time_box.addWidget(time_lbl)
        date_lbl = QLabel(airing.strftime("%b %d"))
        date_lbl.setStyleSheet("font-size:11px;color:#626a80;")
        time_box.addWidget(date_lbl)
        lay.addLayout(time_box)

        info = QVBoxLayout()
        info.setSpacing(3)
        title = self.anime.get("english_title") or self.anime.get("romaji_title") or "Unknown"
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size:14px;font-weight:700;color:#dde0ed;")
        title_lbl.setWordWrap(True)
        info.addWidget(title_lbl)

        meta = QLabel(self._meta_text(airing))
        meta.setStyleSheet("font-size:12px;color:#8a91a6;")
        info.addWidget(meta)
        lay.addLayout(info, stretch=1)

        open_btn = QPushButton("Open")
        open_btn.setObjectName("secondaryBtn")
        open_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        open_btn.clicked.connect(lambda: self.page.open_anime(self.anime["id"]))
        lay.addWidget(open_btn)

        if self._can_mark_watched(airing):
            watch_btn = QPushButton("Mark Watched")
            watch_btn.setObjectName("primaryBtn")
            watch_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            watch_btn.clicked.connect(lambda: self.page.mark_aired_episode(self.anime))
            lay.addWidget(watch_btn)

    def _accent_color(self) -> str:
        status = self.anime.get("watch_status")
        if status == "planned":
            return "#9d8fff"
        if self._can_mark_watched(datetime.fromtimestamp(int(self.anime["next_episode_at"]))):
            return "#fbbf24"
        return "#34d399"

    def _meta_text(self, airing: datetime) -> str:
        next_ep = self.anime.get("next_episode_num")
        episode = f"Episode {next_ep}" if next_ep else "Episode TBA"
        status = (self.anime.get("watch_status") or "").replace("_", " ").title()
        now = datetime.now()
        delta = airing - now
        if delta.total_seconds() < 0:
            countdown = "aired recently"
        elif delta.days > 0:
            countdown = f"in {delta.days}d {delta.seconds // 3600}h"
        elif delta.seconds >= 3600:
            countdown = f"in {delta.seconds // 3600}h {(delta.seconds % 3600) // 60}m"
        else:
            countdown = f"in {max(1, delta.seconds // 60)}m"
        return f"{episode} - {status} - {countdown}"

    def _can_mark_watched(self, airing: datetime) -> bool:
        if airing > datetime.now():
            return False
        next_ep = int(self.anime.get("next_episode_num") or 0)
        if next_ep <= 1:
            return False
        watched = self.db.get_watched_count(self.anime["id"])
        return watched < next_ep - 1
