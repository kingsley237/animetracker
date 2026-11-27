"""
Raikō — Data Doctor

Finds problems in your library (anime, movies, TV shows, the library file
itself, and errors the app caught) and lets you review and approve each fix
before anything changes. The checks live in core/data_health.py.

UX:
  - Scanning: animated progress
  - Review: one card per issue with what's wrong and the proposed fix;
    pick which fixes to apply
  - Apply: fixes run one by one with live status
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
from ui.theme import QColor  # noqa: E402,F811  (theme-aware colours)
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QWidget, QCheckBox, QProgressBar,
    QApplication, QSizePolicy,
)

from core.database import DatabaseManager
from workers.workers import Worker, run_worker


# Checks and fixes live in core.data_health (also used by the background
# health check that raises "Open Data Doctor" alerts).
from core.data_health import Issue, Scanner as _Scanner  # noqa: E402


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

        area = getattr(self.issue, "area", "")
        anime_lbl = QLabel((f"{area}  ·  " if area and area != self.issue.anime_title else "") + self.issue.anime_title[:40])
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
