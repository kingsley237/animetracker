"""
Miroku - Dropped section for the detail panel.

A dropped show asks different questions than one you're watching:
where did I stop, why, has anything changed since, and is it worth another
go? Episode lists and ratings don't apply, so this replaces them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

from workers.workers import Worker, run_worker


def _card(title: str) -> QFrame:
    card = QFrame()
    card.setObjectName("detailCard")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(8)
    if title:
        lbl = QLabel(title)
        lbl.setObjectName("detailSectionLabel")
        lay.addWidget(lbl)
    return card


def _ago(ts) -> str:
    if not ts:
        return ""
    days = int((datetime.now().timestamp() - int(ts)) // 86400)
    if days < 1:
        return "today"
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    if days < 365:
        m = days // 30
        return f"{m} month{'s' if m != 1 else ''} ago"
    y = days // 365
    return f"{y} year{'s' if y != 1 else ''} ago"


class DroppedSection(QWidget):
    restored = pyqtSignal(int, str)     # new anime id, resulting watch status
    removed = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._anime: Optional[Dict] = None
        self._media: Optional[Dict] = None
        self._token = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # Where you stopped
        self.stop_card = _card("")
        sl = self.stop_card.layout()
        chip_row = QHBoxLayout()
        chip = QLabel("✕  DROPPED")
        chip.setObjectName("droppedStamp")
        chip_row.addWidget(chip)
        chip_row.addStretch()
        sl.addLayout(chip_row)
        self.stop_main = QLabel()
        self.stop_main.setObjectName("plannedReleaseMain")
        self.stop_bar = QProgressBar()
        self.stop_bar.setObjectName("droppedBar")
        self.stop_bar.setTextVisible(False)
        self.stop_bar.setFixedHeight(6)
        self.stop_sub = QLabel()
        self.stop_sub.setObjectName("plannedReleaseHint")
        self.stop_sub.setWordWrap(True)
        for w in (self.stop_main, self.stop_bar, self.stop_sub):
            sl.addWidget(w)
        lay.addWidget(self.stop_card)

        # Why
        self.why_card = _card("Why you dropped it")
        wl = self.why_card.layout()
        self.reason = QPlainTextEdit()
        self.reason.setObjectName("dropReason")
        self.reason.setPlaceholderText(
            "Too slow? Lost interest? Leave a note so future-you remembers.")
        self.reason.setFixedHeight(70)
        self.reason.textChanged.connect(self._reason_changed)
        self.save_reason = QPushButton("Save note")
        self.save_reason.setObjectName("secondaryBtn")
        self.save_reason.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.save_reason.clicked.connect(self._save_reason)
        self.save_reason.setVisible(False)
        wl.addWidget(self.reason)
        wl.addWidget(self.save_reason, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addWidget(self.why_card)

        # Since you left
        self.since_card = _card("Since you left")
        self.since_lines = QLabel("Checking AniList…")
        self.since_lines.setObjectName("plannedFactValue")
        self.since_lines.setWordWrap(True)
        self.since_lines.setTextFormat(Qt.TextFormat.RichText)
        self.nudge = QLabel()
        self.nudge.setObjectName("verdictLine")
        self.nudge.setWordWrap(True)
        self.since_card.layout().addWidget(self.since_lines)
        self.since_card.layout().addWidget(self.nudge)
        lay.addWidget(self.since_card)

        # Decide
        self.decide_card = _card("Decide")
        dl = self.decide_card.layout()
        self.retry_btn = QPushButton("↺  Give it another shot")
        self.retry_btn.setObjectName("primaryBtn")
        self.retry_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.retry_btn.clicked.connect(self._restore)
        self.retry_hint = QLabel()
        self.retry_hint.setObjectName("plannedReleaseHint")
        self.retry_hint.setWordWrap(True)
        self.remove_btn = QPushButton("Remove from Dropped")
        self.remove_btn.setObjectName("dangerBtn")
        self.remove_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.remove_btn.clicked.connect(self._remove)
        dl.addWidget(self.retry_btn)
        dl.addWidget(self.retry_hint)
        dl.addSpacing(4)
        dl.addWidget(self.remove_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.decide_card)

    # ── load ──────────────────────────────────────────────────────────────────

    def load(self, anime: Dict):
        self._anime = anime
        self._media = None
        self._token += 1
        last = int(anime.get("_last_episode") or 0)
        self.stop_main.setText(f"Stopped at episode {last}" if last else "Dropped before episode 1")
        self.stop_bar.setVisible(False)
        dropped_at = anime.get("_dropped_at")
        self.stop_sub.setText(
            f"Dropped {datetime.fromtimestamp(dropped_at).strftime('%b %d, %Y')} · {_ago(dropped_at)}"
            if dropped_at else "Drop date unknown")
        self.reason.blockSignals(True)
        self.reason.setPlainText(anime.get("_drop_reason") or "")
        self.reason.blockSignals(False)
        self.save_reason.setVisible(False)
        self.retry_hint.setText(
            f"Back into your library with episodes 1–{last} already ticked, so you pick up at episode {last + 1}."
            if last else "Back into your library from the start.")
        self.since_lines.setText("Checking AniList…")
        self.nudge.setText("")

        aid = anime.get("anilist_id")
        if aid:
            token = self._token

            def fetch():
                from core.api import get_anime_by_id
                return get_anime_by_id(aid)

            w = Worker(fetch)
            w.signals.result.connect(lambda m, t=token: self._on_media(m, t))
            run_worker(w)
        else:
            self.since_lines.setText("No AniList link for this one.")

    def _on_media(self, media: Optional[Dict], token: int):
        if token != self._token or not self._anime:
            return
        self._media = media or {}
        m = self._media
        last = int(self._anime.get("_last_episode") or 0)
        total = m.get("episodes") or 0
        status = (m.get("status") or "").upper()
        if total:
            pct = int(round(100 * min(last, total) / total))
            self.stop_main.setText(f"Stopped at episode {last} of {total}")
            self.stop_bar.setMaximum(total)
            self.stop_bar.setValue(min(last, total))
            self.stop_bar.setVisible(True)
            dropped_at = self._anime.get("_dropped_at")
            base = (f"Dropped {datetime.fromtimestamp(dropped_at).strftime('%b %d, %Y')} · {_ago(dropped_at)}"
                    if dropped_at else "")
            self.stop_sub.setText(f"{pct}% of the way" + (f"  ·  {base}" if base else ""))

        lines = []
        sc = m.get("averageScore")
        if sc:
            lines.append(f"<span style='color:#7b84a3'>Community score</span>&nbsp;&nbsp;"
                         f"<b style='color:#c4b8ff'>★ {sc / 10:.1f}</b>")
        if status == "RELEASING":
            nae = m.get("nextAiringEpisode") or {}
            out = (nae.get("episode") or 1) - 1
            lines.append(f"<span style='color:#7b84a3'>Status</span>&nbsp;&nbsp;Still airing"
                         + (f" · {out} episodes out" if out > 0 else ""))
        elif status in ("FINISHED", "CANCELLED"):
            lines.append(f"<span style='color:#7b84a3'>Status</span>&nbsp;&nbsp;"
                         f"{'Finished' if status == 'FINISHED' else 'Cancelled'}"
                         + (f" · {total} episodes" if total else ""))
        seq = next((n for n in self.db.get_active_notifications("new_season")
                    if ((n.get("payload") or {}).get("prequel") or {}).get("anilist_id")
                    == self._anime.get("anilist_id")), None)
        if seq:
            s = (seq.get("payload") or {}).get("sequel") or {}
            lines.append(f"<span style='color:#7b84a3'>New season</span>&nbsp;&nbsp;"
                         f"<b style='color:#fbbf24'>{s.get('title', 'announced')}</b>")
        self.since_lines.setText("<br>".join(lines) or "Nothing new on AniList.")

        remaining = max(0, total - last) if total else 0
        if sc and sc >= 80:
            nudge = "Fans rate it very highly. It might just have been the wrong time."
        elif sc and sc < 65:
            nudge = "The community wasn't sold on it either. Your call was reasonable."
        else:
            nudge = ""
        if remaining and remaining <= 4:
            nudge = (nudge + " " if nudge else "") + f"Only {remaining} episode{'s' if remaining != 1 else ''} left to finish it."
        self.nudge.setText(nudge)
        self.nudge.setVisible(bool(nudge))

    # ── actions ───────────────────────────────────────────────────────────────

    def _reason_changed(self):
        self.save_reason.setVisible(
            self.reason.toPlainText().strip() != (self._anime or {}).get("_drop_reason", "").strip())

    def _save_reason(self):
        a = self._anime
        if not a or not a.get("_dropped_id"):
            return
        text = self.reason.toPlainText().strip()
        self.db.update_drop_reason(a["_dropped_id"], text)
        a["_drop_reason"] = text
        self.save_reason.setVisible(False)
        from ui.toast import Toast
        Toast.show(self.window(), "Note saved.", kind="success")

    def _restore(self):
        a = self._anime
        if not a or not a.get("_dropped_id"):
            return
        last = int(a.get("_last_episode") or 0)
        new_id = self.db.restore_dropped(a["_dropped_id"])
        if not new_id:
            return
        m = self._media or {}
        status = (m.get("status") or "").upper()
        if m:
            from core.metadata_sync import media_to_row
            row = {k: v for k, v in media_to_row(m).items() if v not in (None, "", [])}
            self.db.update_anime(new_id, row)
        for ep in range(1, last + 1):
            self.db.set_episode_watched(new_id, ep, True)
        # The app keeps finished shows out of Watching: a finished show you're
        # part-way through lives in Completed with the rest flagged unwatched.
        ws = "completed" if status in ("FINISHED", "CANCELLED") and last > 0 else (
            "planned" if status in ("FINISHED", "CANCELLED") else "watching")
        self.db.update_anime(new_id, {"watch_status": ws})
        self.restored.emit(new_id, ws)

    def _remove(self):
        a = self._anime
        if not a or not a.get("_dropped_id"):
            return
        title = a.get("english_title") or a.get("romaji_title") or "this anime"
        res = QMessageBox.question(
            self, "Remove from Dropped?",
            f"Remove '{title}' from your Dropped list for good?\n"
            "Your note and stop point will be lost.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        self.db.delete_dropped_anime(a["_dropped_id"])
        self.removed.emit()
