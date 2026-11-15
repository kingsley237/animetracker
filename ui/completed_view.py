"""
Miroku - Completed list housekeeping.

The Completed list only ever grows. Like a watch diary (Letterboxd /
AniList / MAL style), it's shown as a timeline of when you finished things:
"Finished this month", "Earlier in 2026", "2025", ... Each group folds away
(older years start folded) and can be archived in one click. Archived shows
leave the everyday view but stay in stats, search, Hall of Fame and the
sequel checks; the Archived toggle brings them back.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

_MONTHS = "January February March April May June July August September October November December".split()


def finished_ts(anime: Dict) -> int:
    return int(anime.get("completed_at") or anime.get("last_watched_at")
               or anime.get("date_added") or 0)


def group_completed(anime_list: List[Dict], now: Optional[datetime] = None,
                    rewatching: Optional[set] = None, verb: str = "Finished"
                    ) -> List[Tuple[str, str, List[Dict]]]:
    """[(key, label, members)] newest first. Keys are stable so fold state
    can be remembered: 'rewatching', 'month', 'year', or a year like '2025'."""
    now = now or datetime.now()
    rewatching = rewatching or set()
    buckets: Dict[str, List[Dict]] = {}
    order: List[Tuple[str, str]] = []
    now_rw = [a for a in anime_list if a.get("id") in rewatching]
    if now_rw:
        buckets["rewatching"] = now_rw
        order.append(("rewatching", "Rewatching now"))
    for a in sorted(anime_list, key=finished_ts, reverse=True):
        if a.get("id") in rewatching:
            continue
        ts = finished_ts(a)
        dt = datetime.fromtimestamp(ts) if ts else None
        if dt and dt.year == now.year and dt.month == now.month:
            key, label = "month", f"{verb} this month · {_MONTHS[now.month - 1]}"
        elif dt and dt.year == now.year:
            key, label = "year", f"Earlier in {now.year}"
        elif dt:
            key, label = str(dt.year), str(dt.year)
        else:
            key, label = "unknown", "Date unknown"
        if key not in buckets:
            buckets[key] = []
            order.append((key, label))
        buckets[key].append(a)
    return [(k, lbl, buckets[k]) for k, lbl in order]


def default_collapsed(key: str, now: Optional[datetime] = None) -> bool:
    """This year's groups start open; past years start folded."""
    return key not in ("rewatching", "month", "year")


class SectionHeader(QWidget):
    """Full-width, clickable group header: ▾ label · count  [action]."""
    toggled = pyqtSignal(str)
    action = pyqtSignal(str)

    def __init__(self, key: str, label: str, count: int, color: str,
                 collapsed: bool = False, action_text: str = "",
                 collapsible: bool = True, parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("completedSectionHeader")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 10, 4, 4)
        lay.setSpacing(10)

        chevron = ("▸" if collapsed else "▾") if collapsible else "〡"
        self.title = QPushButton(f"{chevron}  {label.upper()}  ·  {count} {'title' if count == 1 else 'titles'}")
        self.title.setObjectName("sectionHeaderBtn")
        self.title.setStyleSheet(f"QPushButton#sectionHeaderBtn{{color:{color};}}")
        self.title.setCursor(QCursor(Qt.CursorShape.PointingHandCursor
                                     if collapsible else Qt.CursorShape.ArrowCursor))
        self.title.setFlat(True)
        if collapsible:
            self.title.setToolTip("Collapse" if not collapsed else "Expand")
            self.title.clicked.connect(lambda: self.toggled.emit(self.key))
        lay.addWidget(self.title)

        line = QLabel()
        line.setObjectName("sectionHeaderRule")
        line.setFixedHeight(1)
        lay.addWidget(line, 1, Qt.AlignmentFlag.AlignVCenter)

        if action_text:
            btn = QPushButton(action_text)
            btn.setObjectName("sectionHeaderAction")
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(lambda: self.action.emit(self.key))
            lay.addWidget(btn)


class CompletedToolbar(QWidget):
    """'Completed · N shown'  ...  [Archived (N)] toggle."""
    archived_toggled = pyqtSignal()

    def __init__(self, shown: int, archived: int, showing_archived: bool, parent=None,
                 media: str = "anime"):
        super().__init__(parent)
        self.setObjectName("completedToolbar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(10)
        if showing_archived:
            text = f"Archive  ·  {shown} {'title' if shown == 1 else 'titles'} filed away"
            hint = "Still counted in your stats, search and Hall of Fame."
        else:
            text = (f"Your movie diary  ·  {shown} {'film' if shown == 1 else 'films'}"
                    if media == "movie" else
                    f"Your completed timeline  ·  {shown} {'title' if shown == 1 else 'titles'}")
            hint = "Fold a year or archive it to keep this list short."
        t = QLabel(text)
        t.setObjectName("completedToolbarTitle")
        h = QLabel(hint)
        h.setObjectName("completedToolbarHint")
        lay.addWidget(t)
        lay.addWidget(h)
        lay.addStretch()
        btn = QPushButton("←  Back to Completed" if showing_archived else f"Archived ({archived})")
        btn.setObjectName("archivedToggle")
        btn.setProperty("active", "true" if showing_archived else "false")
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setEnabled(showing_archived or archived > 0)
        btn.clicked.connect(self.archived_toggled.emit)
        lay.addWidget(btn)
