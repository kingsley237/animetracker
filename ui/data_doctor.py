"""
Miroku — Data Doctor

Interactive data integrity scanner and repair tool.
Finds logical inconsistencies in the anime database and lets the
user review and confirm each fix before anything is changed.

Issues detected:
  1. Watched count > total episodes (overcounting — the 10/7 bug)
  2. Watched count > aired episodes for releasing anime
  3. Anime marked Completed but watched < total episodes
  4. Anime status mismatch (DB says FINISHED but watch_status=watching)
  5. Duplicate anilist_ids
  6. Orphaned episode rows (anime deleted but episodes remain)
  7. Invalid genres/studios metadata
  8. Missing cached cover paths
  9. Hall of Fame ranking inconsistencies
 10. Duplicate watch activity rows
 11. Stale airing countdowns

UX pattern:
  - Scanning phase: animated progress, issues appear as they're found
  - Review phase: each issue is a card with description + proposed fix
    The user checks/unchecks which fixes to apply
  - Apply phase: fixes applied one by one with live status
  - Summary: what was fixed, what was skipped
"""
from __future__ import annotations

import json
from pathlib import Path
from time import time
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field

from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    pyqtSignal, QThread, QObject, QRunnable,
)
from PyQt6.QtGui import QColor, QCursor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QWidget, QCheckBox, QProgressBar,
    QApplication, QSizePolicy,
)

from core.database import DatabaseManager
from workers.workers import Worker, run_worker


# ── Issue data model ──────────────────────────────────────────────────────────

@dataclass
class Issue:
    """A single detected data integrity problem."""
    issue_id:    str          # unique key e.g. "overcount_42"
    severity:    str          # "error" | "warning" | "info"
    title:       str          # short headline
    detail:      str          # full description shown in the card
    anime_id:    Optional[int]
    anime_title: str
    fix_label:   str          # text on the fix button / checkbox
    fix_fn:      Callable[[], None]  # called if user approves
    checked:     bool = True  # pre-checked by default


# ── Scanner ───────────────────────────────────────────────────────────────────

class _Scanner:
    """
    Runs all integrity checks against the DB.
    Returns a list of Issue objects.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db

    def scan(self) -> List[Issue]:
        issues: List[Issue] = []
        conn = self.db._get_conn()

        anime_rows = conn.execute(
            "SELECT * FROM anime WHERE hof_only=0"
        ).fetchall()

        for row in anime_rows:
            a          = dict(row)
            aid        = a["id"]
            title      = a.get("english_title") or a.get("romaji_title") or f"ID {aid}"
            total      = a.get("total_episodes") or 0
            next_ep    = a.get("next_episode_num")
            api_status = (a.get("status") or "").upper()
            ws         = (a.get("watch_status") or "").lower()

            watched = conn.execute(
                "SELECT COUNT(*) FROM episodes WHERE anime_id=? AND watched=1",
                (aid,)
            ).fetchone()[0]

            aired = 0
            if next_ep and next_ep > 1:
                aired = next_ep - 1
            elif total and api_status in ("FINISHED", "CANCELLED"):
                aired = total

            # ── Issue 1: watched > total (the 10/7 bug) ───────────────────
            if total > 0 and watched > total:
                excess = watched - total
                issues.append(Issue(
                    issue_id    = f"overcount_{aid}",
                    severity    = "error",
                    title       = "Watched count exceeds total episodes",
                    detail      = (
                        f"You have {watched} episodes marked watched, but "
                        f"{title} only has {total} episodes total.  "
                        f"This usually happens from accidental double-marking.  "
                        f"Fix will remove the {excess} excess mark(s) by "
                        f"un-watching episodes above episode {total}."
                    ),
                    anime_id    = aid,
                    anime_title = title,
                    fix_label   = f"Remove {excess} excess mark(s)",
                    fix_fn      = lambda a=aid, t=total: self._fix_overcount(a, t),
                ))

            # ── Issue 2: watched > aired (impossible for releasing) ────────
            elif aired > 0 and watched > aired and api_status == "RELEASING":
                excess = watched - aired
                issues.append(Issue(
                    issue_id    = f"ahead_{aid}",
                    severity    = "warning",
                    title       = "Watched count exceeds aired episodes",
                    detail      = (
                        f"You have {watched} episodes marked watched, but only "
                        f"{aired} have aired so far for {title}.  "
                        f"Fix will un-watch the {excess} episode(s) above "
                        f"episode {aired}."
                    ),
                    anime_id    = aid,
                    anime_title = title,
                    fix_label   = f"Un-watch {excess} future episode(s)",
                    fix_fn      = lambda a=aid, ai=aired: self._fix_overcount(a, ai),
                ))

            # ── Issue 3: Completed but not fully watched ───────────────────
            if ws == "completed" and total > 0 and watched < total:
                missing = total - watched
                issues.append(Issue(
                    issue_id    = f"incomplete_{aid}",
                    severity    = "warning",
                    title       = "Marked completed but episodes missing",
                    detail      = (
                        f"{title} is marked Completed but you have only "
                        f"watched {watched} of {total} episodes — "
                        f"{missing} episode(s) are unmarked.  "
                        f"Fix will mark all {total} episodes as watched."
                    ),
                    anime_id    = aid,
                    anime_title = title,
                    fix_label   = f"Mark all {missing} missing episode(s) watched",
                    fix_fn      = lambda a=aid, t=total: self._fix_mark_all(a, t),
                    checked     = False,   # user should decide, not auto-fix
                ))

            # ── Issue 4: Status mismatch ───────────────────────────────────
            if api_status == "FINISHED" and ws == "watching":
                issues.append(Issue(
                    issue_id    = f"status_mismatch_{aid}",
                    severity    = "info",
                    title       = "Finished anime still marked as Watching",
                    detail      = (
                        f"{title} has finished airing (API status: FINISHED) "
                        f"but your watch status is still 'Watching'.  "
                        f"If you've finished it, change to Completed.  "
                        f"Fix will mark it Completed."
                    ),
                    anime_id    = aid,
                    anime_title = title,
                    fix_label   = "Mark as Completed",
                    fix_fn      = lambda a=aid: self._fix_status(a, "completed"),
                    checked     = False,
                ))

        # ── Issue 5: Duplicate anilist_ids ────────────────────────────────
        dup_rows = conn.execute(
            """SELECT anilist_id, COUNT(*) as c FROM anime
               WHERE anilist_id IS NOT NULL AND hof_only=0
               GROUP BY anilist_id HAVING c > 1"""
        ).fetchall()
        for dup in dup_rows:
            anilist_id = dup[0]
            count      = dup[1]
            dupes      = conn.execute(
                "SELECT id, romaji_title, date_added FROM anime "
                "WHERE anilist_id=? ORDER BY date_added DESC",
                (anilist_id,)
            ).fetchall()
            keep_id    = dupes[0][0]
            keep_title = dupes[0][1]
            remove_ids = [r[0] for r in dupes[1:]]
            issues.append(Issue(
                issue_id    = f"dup_{anilist_id}",
                severity    = "error",
                title       = "Duplicate entries for the same anime",
                detail      = (
                    f"'{keep_title}' appears {count} times in your library "
                    f"(AniList ID {anilist_id}).  "
                    f"Fix will keep the most recently added entry and "
                    f"delete the {len(remove_ids)} older duplicate(s)."
                ),
                anime_id    = keep_id,
                anime_title = keep_title,
                fix_label   = f"Remove {len(remove_ids)} duplicate(s)",
                fix_fn      = lambda ids=remove_ids: self._fix_duplicates(ids),
            ))

        # ── Issue 6: Orphaned episodes ────────────────────────────────────
        orphan_count = conn.execute(
            """SELECT COUNT(*) FROM episodes
               WHERE anime_id NOT IN (SELECT id FROM anime)"""
        ).fetchone()[0]
        if orphan_count > 0:
            issues.append(Issue(
                issue_id    = "orphan_eps",
                severity    = "info",
                title       = "Orphaned episode records",
                detail      = (
                    f"There are {orphan_count} episode record(s) in the "
                    f"database that belong to anime entries that no longer "
                    f"exist.  These are harmless but waste space.  "
                    f"Fix will delete them."
                ),
                anime_id    = None,
                anime_title = "Database",
                fix_label   = f"Delete {orphan_count} orphaned record(s)",
                fix_fn      = self._fix_orphans,
            ))

        for row in conn.execute(
            "SELECT id, romaji_title, english_title, genres, studios FROM anime"
        ).fetchall():
            aid = row["id"]
            title = row["english_title"] or row["romaji_title"] or f"ID {aid}"
            for column in ("genres", "studios"):
                raw = row[column]
                if raw in (None, ""):
                    continue
                try:
                    parsed = json.loads(raw)
                    if not isinstance(parsed, list):
                        raise ValueError("expected list")
                except Exception:
                    issues.append(Issue(
                        issue_id    = f"bad_json_{column}_{aid}",
                        severity    = "warning",
                        title       = f"Invalid {column} data",
                        detail      = (
                            f"{title} has malformed {column} data. This can "
                            "make filters, stats, and metadata behave "
                            "unpredictably. Fix will reset that field to an "
                            "empty list."
                        ),
                        anime_id    = aid,
                        anime_title = title,
                        fix_label   = f"Reset {column} to []",
                        fix_fn      = lambda a=aid, c=column: self._fix_json_column(a, c),
                    ))

        for row in conn.execute(
            """SELECT id, romaji_title, english_title, cover_local
               FROM anime
               WHERE cover_local IS NOT NULL AND TRIM(cover_local) != ''"""
        ).fetchall():
            local_path = row["cover_local"]
            if local_path and not Path(local_path).exists():
                aid = row["id"]
                title = row["english_title"] or row["romaji_title"] or f"ID {aid}"
                issues.append(Issue(
                    issue_id    = f"missing_cover_{aid}",
                    severity    = "info",
                    title       = "Cached cover file is missing",
                    detail      = (
                        f"{title} points to a local cover file that no longer "
                        "exists. Fix will clear the stale local path so Miroku "
                        "can download the cover again when needed."
                    ),
                    anime_id    = aid,
                    anime_title = title,
                    fix_label   = "Clear stale cover path",
                    fix_fn      = lambda a=aid: self._fix_cover_path(a),
                ))

        hof_table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='hall_of_fame'"
        ).fetchone() is not None

        if hof_table_exists:
            orphan_hof = conn.execute(
                """SELECT COUNT(*) FROM hall_of_fame h
                   LEFT JOIN anime a ON a.id = h.anime_id
                   WHERE a.id IS NULL"""
            ).fetchone()[0]
            if orphan_hof > 0:
                issues.append(Issue(
                    issue_id    = "orphan_hof",
                    severity    = "info",
                    title       = "Orphaned Hall of Fame records",
                    detail      = (
                        f"There are {orphan_hof} Hall of Fame record(s) pointing "
                        "to anime entries that no longer exist. Fix will remove "
                        "those stale ranking rows."
                    ),
                    anime_id    = None,
                    anime_title = "Hall of Fame",
                    fix_label   = f"Delete {orphan_hof} stale ranking row(s)",
                    fix_fn      = self._fix_orphan_hof,
                ))

            missing_hof_rows = conn.execute(
                """SELECT a.id, a.romaji_title, a.english_title
                   FROM anime a
                   LEFT JOIN hall_of_fame h ON h.anime_id = a.id
                   WHERE a.hof_only=1 AND h.anime_id IS NULL"""
            ).fetchall()
        else:
            missing_hof_rows = conn.execute(
                """SELECT id, romaji_title, english_title
                   FROM anime
                   WHERE hof_only=1"""
            ).fetchall()
        if missing_hof_rows:
            count = len(missing_hof_rows)
            sample = missing_hof_rows[0]
            sample_title = sample["english_title"] or sample["romaji_title"] or "Hall of Fame entry"
            issues.append(Issue(
                issue_id    = "missing_hof_ranks",
                severity    = "warning",
                title       = "Hall of Fame entries missing from ranking",
                detail      = (
                    f"{count} Hall of Fame-only entr{'y is' if count == 1 else 'ies are'} "
                    "saved in the anime table but missing from the ranking "
                    "table. Fix will add them back at the end of your Hall of "
                    "Fame list."
                ),
                anime_id    = sample["id"],
                anime_title = sample_title,
                fix_label   = f"Restore {count} Hall of Fame ranking row(s)",
                fix_fn      = self._fix_missing_hof_ranks,
            ))

        dup_log_groups = conn.execute(
            """SELECT COUNT(*) FROM (
                   SELECT anime_id, episode_num, watched_at, COUNT(*) AS c
                   FROM watch_log
                   GROUP BY anime_id, episode_num, watched_at
                   HAVING c > 1
               )"""
        ).fetchone()[0]
        if dup_log_groups > 0:
            issues.append(Issue(
                issue_id    = "duplicate_watch_log",
                severity    = "info",
                title       = "Duplicate activity log records",
                detail      = (
                    f"Found {dup_log_groups} duplicated watch activity group(s). "
                    "These can inflate heatmaps and streak stats. Fix will keep "
                    "the first record in each group and remove the extras."
                ),
                anime_id    = None,
                anime_title = "Watch history",
                fix_label   = "Remove duplicate activity rows",
                fix_fn      = self._fix_duplicate_watch_log,
            ))

        stale_cutoff = int(time()) - (7 * 24 * 60 * 60)
        for row in conn.execute(
            """SELECT id, romaji_title, english_title
               FROM anime
               WHERE status='RELEASING'
                 AND next_episode_at IS NOT NULL
                 AND next_episode_at < ?
                 AND hof_only=0""",
            (stale_cutoff,),
        ).fetchall():
            aid = row["id"]
            title = row["english_title"] or row["romaji_title"] or f"ID {aid}"
            issues.append(Issue(
                issue_id    = f"stale_airing_{aid}",
                severity    = "info",
                title       = "Airing countdown looks stale",
                detail      = (
                    f"{title} still has an airing timestamp from more than a "
                    "week ago. Fix will clear the stale countdown so the next "
                    "airing refresh can repopulate it cleanly."
                ),
                anime_id    = aid,
                anime_title = title,
                fix_label   = "Clear stale countdown",
                fix_fn      = lambda a=aid: self._fix_stale_airing(a),
                checked     = False,
            ))

        return issues

    # ── Fix implementations ───────────────────────────────────────────────────

    def _fix_overcount(self, anime_id: int, max_ep: int):
        conn = self.db._get_conn()
        conn.execute(
            "UPDATE episodes SET watched=0, watched_at=NULL "
            "WHERE anime_id=? AND episode_num > ? AND watched=1",
            (anime_id, max_ep),
        )
        conn.commit()

    def _fix_mark_all(self, anime_id: int, total: int):
        from datetime import datetime
        now = int(datetime.now().timestamp())
        for ep in range(1, total + 1):
            self.db.set_episode_watched(anime_id, ep, True)

    def _fix_status(self, anime_id: int, new_status: str):
        self.db.update_anime(anime_id, {"watch_status": new_status})

    def _fix_duplicates(self, remove_ids: List[int]):
        conn = self.db._get_conn()
        for rid in remove_ids:
            conn.execute("DELETE FROM anime WHERE id=?", (rid,))
        conn.commit()

    def _fix_orphans(self):
        conn = self.db._get_conn()
        conn.execute(
            "DELETE FROM episodes WHERE anime_id NOT IN (SELECT id FROM anime)"
        )
        conn.commit()

    def _ensure_hof_table(self, conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS hall_of_fame "
            "(rank INTEGER PRIMARY KEY, anime_id INTEGER UNIQUE, note TEXT DEFAULT '', added_at INTEGER)"
        )

    def _fix_json_column(self, anime_id: int, column: str):
        if column not in ("genres", "studios"):
            return
        conn = self.db._get_conn()
        conn.execute(f"UPDATE anime SET {column}='[]' WHERE id=?", (anime_id,))
        conn.commit()

    def _fix_cover_path(self, anime_id: int):
        conn = self.db._get_conn()
        conn.execute("UPDATE anime SET cover_local=NULL WHERE id=?", (anime_id,))
        conn.commit()

    def _fix_orphan_hof(self):
        conn = self.db._get_conn()
        self._ensure_hof_table(conn)
        conn.execute(
            "DELETE FROM hall_of_fame WHERE anime_id NOT IN (SELECT id FROM anime)"
        )
        conn.commit()

    def _fix_missing_hof_ranks(self):
        conn = self.db._get_conn()
        self._ensure_hof_table(conn)
        now = int(time())
        max_rank = conn.execute("SELECT MAX(rank) FROM hall_of_fame").fetchone()[0] or 0
        rows = conn.execute(
            """SELECT a.id FROM anime a
               LEFT JOIN hall_of_fame h ON h.anime_id = a.id
               WHERE a.hof_only=1 AND h.anime_id IS NULL
               ORDER BY a.date_added ASC, a.id ASC"""
        ).fetchall()
        for row in rows:
            max_rank += 1
            conn.execute(
                "INSERT OR IGNORE INTO hall_of_fame (rank, anime_id, added_at) VALUES (?,?,?)",
                (max_rank, row["id"], now),
            )
        conn.commit()

    def _fix_duplicate_watch_log(self):
        conn = self.db._get_conn()
        conn.execute(
            """DELETE FROM watch_log
               WHERE id NOT IN (
                   SELECT MIN(id)
                   FROM watch_log
                   GROUP BY anime_id, episode_num, watched_at
               )"""
        )
        conn.commit()

    def _fix_stale_airing(self, anime_id: int):
        conn = self.db._get_conn()
        conn.execute(
            "UPDATE anime SET next_episode_at=NULL, next_episode_num=NULL WHERE id=?",
            (anime_id,),
        )
        conn.commit()


# ── Issue card widget ─────────────────────────────────────────────────────────

class _IssueCard(QFrame):
    """Visual card for a single issue — checkbox, severity, detail, fix label."""

    _SEVERITY_STYLES = {
        "error":   ("#f87171", "#2a0a0a", "#7f1d1d"),
        "warning": ("#fbbf24", "#1f1500", "#92400e"),
        "info":    ("#7c6af7", "#11102a", "#2a2550"),
    }

    def __init__(self, issue: Issue, parent=None, on_changed: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.issue = issue
        self._on_changed = on_changed
        self.setObjectName("issueCard")
        fg, bg, border = self._SEVERITY_STYLES.get(
            issue.severity, self._SEVERITY_STYLES["info"]
        )
        self.setStyleSheet(
            f"QFrame#issueCard{{background:{bg};"
            f"border-radius:10px;padding:0;}}"
        )
        self._build(fg)

    def _build(self, fg: str):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(14)

        # Checkbox
        self._cb = QCheckBox()
        self._cb.setChecked(self.issue.checked)
        self._cb.stateChanged.connect(self._on_check_changed)
        self._cb.setFixedWidth(20)
        lay.addWidget(self._cb, 0, Qt.AlignmentFlag.AlignTop)

        # Content
        col = QVBoxLayout()
        col.setSpacing(5)
        col.setContentsMargins(0, 0, 0, 0)

        # Severity badge + title row
        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        badge = QLabel(self.issue.severity.upper())
        badge.setStyleSheet(
            f"font-size:9px;font-weight:700;color:{fg};"
            "background:rgba(255,255,255,0.07);border-radius:4px;"
            "padding:1px 6px;letter-spacing:0.5px;"
        )
        title_row.addWidget(badge)

        anime_lbl = QLabel(self.issue.anime_title[:40])
        anime_lbl.setStyleSheet(
            "font-size:11px;color:#9da5c0;background:transparent;"
        )
        title_row.addWidget(anime_lbl)
        title_row.addStretch()
        col.addLayout(title_row)

        title_lbl = QLabel(self.issue.title)
        title_lbl.setStyleSheet(
            f"font-size:13px;font-weight:700;color:{fg};background:transparent;"
        )
        col.addWidget(title_lbl)

        detail_lbl = QLabel(self.issue.detail)
        detail_lbl.setStyleSheet(
            "font-size:11px;color:#9da5c0;background:transparent;line-height:1.6;"
        )
        detail_lbl.setWordWrap(True)
        col.addWidget(detail_lbl)

        fix_lbl = QLabel(f"Fix: {self.issue.fix_label}")
        fix_lbl.setStyleSheet(
            f"font-size:11px;font-weight:600;color:{fg};"
            "background:transparent;font-style:italic;"
        )
        col.addWidget(fix_lbl)

        lay.addLayout(col)

    @property
    def is_checked(self) -> bool:
        return self._cb.isChecked()

    def _on_check_changed(self, state: int):
        self.issue.checked = bool(state)
        if self._on_changed:
            self._on_changed()


# ── Main dialog ───────────────────────────────────────────────────────────────

class DataDoctorDialog(QDialog):
    """
    Three-phase dialog:
      SCAN  → animated scan with issues appearing live
      REVIEW → user checks/unchecks which fixes to apply
      DONE  → summary of what was fixed
    """

    data_changed = pyqtSignal()   # emitted when any fix is applied

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db      = db
        self._issues: List[Issue]      = []
        self._cards:  List[_IssueCard] = []
        self._phase  = "scan"

        self.setWindowTitle("Data Doctor")
        self.setMinimumSize(620, 520)
        self.setStyleSheet("background:#0f1118;")

        # Center on parent screen
        if parent:
            pw = parent.window()
            screen = pw.screen() if pw else QApplication.primaryScreen()
            if screen:
                ag = screen.availableGeometry()
                self.move(
                    ag.left() + (ag.width()  - 620) // 2,
                    ag.top()  + (ag.height() - 520) // 2,
                )

        self._build()
        QTimer.singleShot(200, self._start_scan)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setStyleSheet(
            "background:#0a0c10;border-bottom:1px solid #1a1d28;"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24, 16, 24, 16)

        self._hdr_title = QLabel("Data Doctor")
        self._hdr_title.setStyleSheet(
            "font-size:17px;font-weight:700;color:#f0f1f5;"
        )
        hl.addWidget(self._hdr_title)
        hl.addStretch()

        self._hdr_badge = QLabel("Scanning…")
        self._hdr_badge.setStyleSheet(
            "font-size:11px;font-weight:600;color:#7c6af7;"
            "background:#151929;border-radius:8px;padding:3px 10px;"
        )
        hl.addWidget(self._hdr_badge)
        root.addWidget(hdr)

        # ── Scan progress bar ─────────────────────────────────────────────
        self._scan_bar = QProgressBar()
        self._scan_bar.setRange(0, 0)
        self._scan_bar.setFixedHeight(3)
        self._scan_bar.setTextVisible(False)
        self._scan_bar.setStyleSheet(
            "QProgressBar{background:#1a1d28;border:none;}"
            "QProgressBar::chunk{background:#7c6af7;}"
        )
        root.addWidget(self._scan_bar)

        # ── Body scroll area ──────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self._body_w = QWidget()
        self._body_w.setStyleSheet("background:transparent;")
        self._body_lay = QVBoxLayout(self._body_w)
        self._body_lay.setContentsMargins(24, 20, 24, 20)
        self._body_lay.setSpacing(12)
        self._body_lay.addStretch()

        self._scroll.setWidget(self._body_w)
        root.addWidget(self._scroll)

        # ── Footer ────────────────────────────────────────────────────────
        ftr = QWidget()
        ftr.setStyleSheet(
            "background:#0a0c10;border-top:1px solid #1a1d28;"
        )
        fl = QHBoxLayout(ftr)
        fl.setContentsMargins(24, 12, 24, 12)
        fl.setSpacing(10)

        self._status_lbl = QLabel("Scanning your library for issues…")
        self._status_lbl.setStyleSheet("font-size:12px;color:#4a5070;")
        fl.addWidget(self._status_lbl)
        fl.addStretch()

        self._select_all_btn = QPushButton("Select All")
        self._select_all_btn.setObjectName("secondaryBtn")
        self._select_all_btn.setFixedHeight(34)
        self._select_all_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._select_all_btn.clicked.connect(self._toggle_all)
        self._select_all_btn.setVisible(False)
        fl.addWidget(self._select_all_btn)

        self._action_btn = QPushButton("Scanning…")
        self._action_btn.setObjectName("primaryBtn")
        self._action_btn.setFixedHeight(34)
        self._action_btn.setMinimumWidth(140)
        self._action_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._action_btn.setEnabled(False)
        self._action_btn.clicked.connect(self._on_action)
        fl.addWidget(self._action_btn)

        root.addWidget(ftr)

    # ── Phase: Scan ───────────────────────────────────────────────────────────

    def _start_scan(self):
        self._phase = "scan"
        scanner = _Scanner(self.db)

        def do_scan():
            return scanner.scan()

        w = Worker(do_scan)
        w.signals.result.connect(self._on_scan_done)
        run_worker(w)

    def _on_scan_done(self, issues: List[Issue]):
        self._issues = issues
        self._scan_bar.setVisible(False)

        # Clear stretch
        while self._body_lay.count():
            item = self._body_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not issues:
            self._show_clean()
            return

        self._show_review(issues)

    # ── Phase: Clean ──────────────────────────────────────────────────────────

    def _show_clean(self):
        self._phase = "clean"
        self._hdr_badge.setText("All Clear")
        self._hdr_badge.setStyleSheet(
            "font-size:11px;font-weight:600;color:#34d399;"
            "background:#0e2a1f;border-radius:8px;padding:3px 10px;"
        )

        # Big checkmark illustration
        icon = QLabel("✓")
        icon.setStyleSheet(
            "font-size:64px;color:#34d399;background:transparent;"
        )
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._body_lay.addStretch()
        self._body_lay.addWidget(icon)

        title = QLabel("Your library looks healthy!")
        title.setStyleSheet(
            "font-size:18px;font-weight:700;color:#f0f1f5;background:transparent;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._body_lay.addWidget(title)

        sub = QLabel(
            "No watched count overflows, no duplicates,\n"
            "no orphaned records — everything checks out."
        )
        sub.setStyleSheet(
            "font-size:13px;color:#4a5070;background:transparent;"
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._body_lay.addWidget(sub)
        self._body_lay.addStretch()

        self._status_lbl.setText("No issues found.")
        self._action_btn.setText("Close")
        self._action_btn.setEnabled(True)
        self._action_btn.clicked.disconnect()
        self._action_btn.clicked.connect(self.accept)

    # ── Phase: Review ─────────────────────────────────────────────────────────

    def _show_review(self, issues: List[Issue]):
        self._phase = "review"
        errors   = sum(1 for i in issues if i.severity == "error")
        warnings = sum(1 for i in issues if i.severity == "warning")
        infos    = sum(1 for i in issues if i.severity == "info")

        badge_parts = []
        if errors:   badge_parts.append(f"{errors} error{'s' if errors > 1 else ''}")
        if warnings: badge_parts.append(f"{warnings} warning{'s' if warnings > 1 else ''}")
        if infos:    badge_parts.append(f"{infos} info")
        self._hdr_badge.setText(" · ".join(badge_parts))
        self._hdr_badge.setStyleSheet(
            "font-size:11px;font-weight:600;color:#f87171;"
            "background:#2a0a0a;border-radius:8px;padding:3px 10px;"
        ) if errors else self._hdr_badge.setStyleSheet(
            "font-size:11px;font-weight:600;color:#fbbf24;"
            "background:#1f1500;border-radius:8px;padding:3px 10px;"
        )

        # Summary line
        summary = QLabel(
            f"Found {len(issues)} issue{'s' if len(issues) != 1 else ''}.  "
            "Review each one below, then click Fix Selected."
        )
        summary.setStyleSheet("font-size:12px;color:#9da5c0;background:transparent;")
        summary.setWordWrap(True)
        self._body_lay.addWidget(summary)

        # Issue cards — errors first
        for issue in sorted(issues, key=lambda x: {"error":0,"warning":1,"info":2}[x.severity]):
            card = _IssueCard(issue, on_changed=self._update_fix_count)
            self._cards.append(card)
            self._body_lay.addWidget(card)

        self._body_lay.addStretch()

        self._status_lbl.setText(
            f"{len(issues)} issue{'s' if len(issues) != 1 else ''} found — review and confirm fixes."
        )
        self._select_all_btn.setVisible(True)
        self._action_btn.setEnabled(True)
        self._update_fix_count()

    # ── Phase: Apply ──────────────────────────────────────────────────────────

    def _on_action(self):
        if self._phase == "review":
            selected = [c for c in self._cards if c.is_checked]
            if not selected:
                self._status_lbl.setText("No fixes selected.")
                return
            self._apply_fixes(selected)

    def _apply_fixes(self, cards: List[_IssueCard]):
        self._phase = "applying"
        self._action_btn.setEnabled(False)
        self._select_all_btn.setVisible(False)
        self._scan_bar.setVisible(True)
        self._scan_bar.setRange(0, len(cards))
        self._scan_bar.setValue(0)

        fixed   = 0
        skipped = 0
        errors_encountered = []

        for i, card in enumerate(cards):
            self._status_lbl.setText(
                f"Fixing: {card.issue.title[:50]}…"
            )
            QApplication.processEvents()
            try:
                card.issue.fix_fn()
                fixed += 1
                # Hide the issue card entirely — replaced by summary
                card.setVisible(False)
            except Exception as exc:
                skipped += 1
                errors_encountered.append(f"{card.issue.title}: {exc}")
            self._scan_bar.setValue(i + 1)
            QApplication.processEvents()

        self._scan_bar.setVisible(False)
        self._show_summary(fixed, skipped, errors_encountered)

    # ── Phase: Summary ────────────────────────────────────────────────────────

    def _show_summary(self, fixed: int, skipped: int,
                      errors: List[str]):
        self._phase = "done"

        # Add summary card at top of scroll
        summary_card = QFrame()
        summary_card.setStyleSheet(
            "QFrame{background:#0e2a1f;"
            "border-radius:10px;}"
        )
        sc_lay = QVBoxLayout(summary_card)
        sc_lay.setContentsMargins(20, 16, 20, 16)
        sc_lay.setSpacing(6)

        done_lbl = QLabel(f"✓  {fixed} fix{'es' if fixed != 1 else ''} applied")
        done_lbl.setStyleSheet(
            "font-size:16px;font-weight:700;color:#34d399;background:transparent;"
        )
        sc_lay.addWidget(done_lbl)

        if skipped:
            skip_lbl = QLabel(f"{skipped} skipped due to errors")
            skip_lbl.setStyleSheet(
                "font-size:12px;color:#fbbf24;background:transparent;"
            )
            sc_lay.addWidget(skip_lbl)

        if errors:
            for e in errors[:3]:
                e_lbl = QLabel(f"  • {e[:80]}")
                e_lbl.setStyleSheet(
                    "font-size:11px;color:#f87171;background:transparent;"
                )
                sc_lay.addWidget(e_lbl)

        note = QLabel("Your library has been updated automatically.")
        note.setStyleSheet(
            "font-size:11px;color:#4a5070;background:transparent;"
        )
        note.setWordWrap(True)
        sc_lay.addWidget(note)

        # Insert at top (before existing cards)
        self._body_lay.insertWidget(0, summary_card)

        self._hdr_badge.setText("Done")
        self._hdr_badge.setStyleSheet(
            "font-size:11px;font-weight:600;color:#34d399;"
            "background:#0e2a1f;border-radius:8px;padding:3px 10px;"
        )
        self._status_lbl.setText(
            f"{fixed} issue{'s' if fixed != 1 else ''} resolved."
        )
        self._action_btn.setText("Close")
        self._action_btn.setEnabled(True)
        self._action_btn.clicked.disconnect()
        self._action_btn.clicked.connect(self.accept)
        # Notify parent to refresh library if anything changed
        if fixed > 0:
            self.data_changed.emit()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _toggle_all(self):
        all_checked = all(c.is_checked for c in self._cards)
        for card in self._cards:
            card._cb.setChecked(not all_checked)
        checked_count = sum(1 for c in self._cards if c.is_checked)
        self._action_btn.setText(f"Fix Selected ({checked_count})")
        self._select_all_btn.setText("Clear All" if checked_count else "Select All")

    def _update_fix_count(self):
        checked = sum(1 for c in self._cards if c.is_checked)
        self._action_btn.setText(f"Fix Selected ({checked})")
        self._select_all_btn.setText("Clear All" if checked else "Select All")


# ── Launch helper ─────────────────────────────────────────────────────────────

def open_data_doctor(db: DatabaseManager, parent=None) -> None:
    """Open the Data Doctor dialog. Call from Settings or a menu action."""
    dlg = DataDoctorDialog(db, parent)
    dlg.exec()
