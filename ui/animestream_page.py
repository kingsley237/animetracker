"""
Miroku - Stream Page
Coming Soon section for the anime download/streaming feature.
Shows the concept, pricing tiers, and lets users register interest.
Payment via MTN MoMo / Orange Money → Telegram channel access.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QLineEdit, QMessageBox,
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QCursor, QFont


STREAM_NAME = "Miroku Stream"


class AnimeStreamPage(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db       = db
        from core.app_settings import app_settings
        self.settings = app_settings()
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(40, 32, 40, 40)
        lay.setSpacing(0)

        # ── Hero ──────────────────────────────────────────────────────────
        coming_badge = QLabel("COMING SOON")
        coming_badge.setStyleSheet(
            "font-size:11px;font-weight:700;color:#7c6af7;"
            "background:#1e1847;border-radius:12px;"
            "padding:4px 14px;letter-spacing:2px;"
        )
        coming_badge.setFixedHeight(28)
        lay.addWidget(coming_badge, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addSpacing(16)

        hero_title = QLabel(STREAM_NAME)
        hero_title.setStyleSheet(
            "font-size:36px;font-weight:700;color:#f0f1f5;letter-spacing:-0.5px;"
        )
        lay.addWidget(hero_title)

        hero_sub = QLabel(
            "Watch anime as it airs — in HD, directly from Miroku.\n"
            "No ads. No accounts. Just anime."
        )
        hero_sub.setStyleSheet("font-size:16px;color:#6b7280;line-height:1.6;")
        hero_sub.setWordWrap(True)
        lay.addWidget(hero_sub)
        lay.addSpacing(32)

        # ── How it works ──────────────────────────────────────────────────
        lay.addWidget(self._section("HOW IT WORKS"))
        lay.addSpacing(12)

        steps = [
            ("1", "Choose a plan", "Select Monthly or Seasonal access below."),
            ("2", "Pay via MoMo or Orange Money",
             "Instant mobile payment. No card required."),
            ("3", "Get instant access",
             "Receive a private Telegram channel invite immediately after payment. "
             "New episodes posted automatically as they air — in 480p, 720p, and 1080p."),
            ("4", "Watch on any device",
             "Open the Telegram channel on your phone, tablet, or PC. "
             "Download or stream directly."),
        ]

        for num, title, desc in steps:
            row = self._step_row(num, title, desc)
            lay.addWidget(row)
            lay.addSpacing(10)

        lay.addSpacing(24)

        # ── Pricing ───────────────────────────────────────────────────────
        lay.addWidget(self._section("PRICING PLANS"))
        lay.addSpacing(12)

        pricing_row = QHBoxLayout()
        pricing_row.setSpacing(16)

        plans = [
            ("Monthly",  "XAF 1,500 / mo",  ["All airing anime", "720p + 1080p", "New eps within 2h of airing", "Cancel anytime"], False),
            ("Seasonal", "XAF 4,000 / season", ["Everything in Monthly", "Full season archive", "Best value — save 11%", "3-month access"], True),
        ]

        for name, price, features, featured in plans:
            card = self._pricing_card(name, price, features, featured)
            pricing_row.addWidget(card)

        lay.addLayout(pricing_row)
        lay.addSpacing(32)

        # ── Notify me ──────────────────────────────────────────────────────
        lay.addWidget(self._section("GET NOTIFIED WHEN WE LAUNCH"))
        lay.addSpacing(12)

        notify_desc = QLabel(
            "Leave your phone number and we will send you a MoMo payment request "
            f"the day {STREAM_NAME} goes live. No spam - one message only."
        )
        notify_desc.setStyleSheet("font-size:13px;color:#6b7280;")
        notify_desc.setWordWrap(True)
        lay.addWidget(notify_desc)
        lay.addSpacing(10)

        # Check if already registered
        saved_phone = self.settings.value("animestream_phone", "")

        if saved_phone:
            confirmed = QLabel(f"✓  {saved_phone} registered for launch notification.")
            confirmed.setStyleSheet("font-size:13px;color:#34d399;")
            lay.addWidget(confirmed)

            change = QPushButton("Change number")
            change.setObjectName("secondaryBtn")
            change.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            change.clicked.connect(lambda: self._reset_notify(lay))
            lay.addWidget(change, alignment=Qt.AlignmentFlag.AlignLeft)
        else:
            notify_row = QHBoxLayout()
            self._phone_input = QLineEdit()
            self._phone_input.setObjectName("searchBar")
            self._phone_input.setPlaceholderText(
                "Enter your phone number (e.g. 6XXXXXXXX)"
            )
            self._phone_input.setFixedHeight(38)
            self._phone_input.setMaximumWidth(300)
            notify_row.addWidget(self._phone_input)

            notify_btn = QPushButton("Notify Me")
            notify_btn.setObjectName("primaryBtn")
            notify_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            notify_btn.clicked.connect(self._register_notify)
            notify_row.addWidget(notify_btn)
            notify_row.addStretch()
            lay.addLayout(notify_row)

        lay.addSpacing(32)

        # ── Transparency note ─────────────────────────────────────────────
        disclaimer = QFrame()
        disclaimer.setStyleSheet(
            "background:#0e1620;border-radius:10px;"
        )
        dl = QVBoxLayout(disclaimer)
        dl.setContentsMargins(20, 16, 20, 16)
        dl.setSpacing(6)

        dt = QLabel("A note on content")
        dt.setStyleSheet("font-size:13px;font-weight:700;color:#c7cbd9;")
        dl.addWidget(dt)

        dd = QLabel(
            f"{STREAM_NAME} aggregates content from community sources and provides "
            "organised access to it. We do not host files directly. "
            "Access is to a curated Telegram channel updated by our team "
            "as new episodes become available from the community."
        )
        dd.setStyleSheet("font-size:12px;color:#4a5070;line-height:1.6;")
        dd.setWordWrap(True)
        dl.addWidget(dd)
        lay.addWidget(disclaimer)

        lay.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _section(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            "font-size:10px;font-weight:700;color:#3b4260;letter-spacing:1.8px;"
        )
        return l

    def _step_row(self, num: str, title: str, desc: str) -> QFrame:
        row = QFrame()
        row.setStyleSheet(
            "QFrame{background:#111420;border-radius:10px;}"
        )
        row.setFixedHeight(72)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(16, 0, 20, 0)
        lay.setSpacing(16)

        num_lbl = QLabel(num)
        num_lbl.setFixedSize(32, 32)
        num_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        num_lbl.setStyleSheet(
            "background:#1e1847;color:#7c6af7;font-size:14px;"
            "font-weight:700;border-radius:16px;"
        )
        lay.addWidget(num_lbl)

        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet("font-size:13px;font-weight:600;color:#dde0ed;")
        col.addWidget(t)
        d = QLabel(desc)
        d.setStyleSheet("font-size:11px;color:#4a5070;")
        d.setWordWrap(True)
        col.addWidget(d)
        lay.addLayout(col)
        return row

    def _pricing_card(self, name: str, price: str,
                       features: list, featured: bool) -> QFrame:
        card = QFrame()
        border = "#4b3fa8" if featured else "#1a1d28"
        bg     = "#151929" if featured else "#111420"
        card.setStyleSheet(
            f"QFrame{{background:{bg};border-radius:12px;}}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)

        if featured:
            best = QLabel("BEST VALUE")
            best.setStyleSheet(
                "font-size:9px;font-weight:700;color:#7c6af7;"
                "letter-spacing:1.5px;background:transparent;"
            )
            lay.addWidget(best)

        n = QLabel(name)
        n.setStyleSheet("font-size:18px;font-weight:700;color:#f0f1f5;background:transparent;")
        lay.addWidget(n)

        p = QLabel(price)
        p.setStyleSheet(
            "font-size:24px;font-weight:700;color:#7c6af7;background:transparent;"
        )
        lay.addWidget(p)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#1e2130;")
        lay.addWidget(sep)

        for feat in features:
            fl = QLabel(f"✓  {feat}")
            fl.setStyleSheet("font-size:12px;color:#9da5c0;background:transparent;")
            lay.addWidget(fl)

        lay.addStretch()

        btn = QPushButton("Coming Soon")
        btn.setEnabled(False)
        btn.setStyleSheet(
            "QPushButton{background:#1e2130;color:#4a5070;border:none;"
            "border-radius:8px;padding:10px;font-size:13px;font-weight:600;}"
        )
        lay.addWidget(btn)
        return card

    def _register_notify(self):
        phone = self._phone_input.text().strip()
        if len(phone) < 8:
            QMessageBox.warning(self, "Invalid Number",
                                "Please enter a valid phone number.")
            return
        self.settings.setValue("animestream_phone", phone)
        from ui.toast import Toast
        Toast.show(self.window(), f"{phone} has been saved.\n\nWe will notify you the day {STREAM_NAME} launches.", kind="success")
        

    def _reset_notify(self, lay):
        self.settings.remove("animestream_phone")
        from ui.toast import Toast
        Toast.show(self.window(), "Your number has been removed.", kind="info")
