"""
Miroku — Splash screen and deferred loading indicator.

SplashScreen: shown at app startup while DB and workers initialize.
LoadingOverlay: shown over any widget when an operation exceeds SLOW_THRESHOLD_MS.
              Industry standard: show spinner only if wait > 300ms (Jakob Nielsen).
"""
from pathlib import Path

from PyQt6.QtWidgets import QSplashScreen, QWidget, QVBoxLayout, QLabel, QProgressBar, QFrame
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QLinearGradient


SLOW_THRESHOLD_MS = 300   # Nielsen: anything over 300ms needs feedback


class SplashScreen(QSplashScreen):
    """
    App startup splash — shown while main window initializes.
    Displays app name, version, and an indeterminate progress bar.
    """

    W, H = 560, 320

    def __init__(self, version: str = "", screen=None):
        px = self._render(version)
        self._base_px = px   # keep clean copy for progress redraws
        super().__init__(px, Qt.WindowType.WindowStaysOnTopHint)
        self.setMask(px.mask())
        if screen:
            avail = screen.availableGeometry()
            self.move(
                avail.left() + max(0, (avail.width() - self.W) // 2),
                avail.top() + max(0, (avail.height() - self.H) // 2),
            )

    def _render(self, version: str) -> QPixmap:
        px = QPixmap(self.W, self.H)
        px.fill(QColor(0, 0, 0, 0))

        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # ── Background ────────────────────────────────────────────────────
        p.setBrush(QColor("#0d0f18"))
        p.setPen(QColor("#1e2235"))
        p.drawRoundedRect(1, 1, self.W - 2, self.H - 2, 16, 16)

        # ── Subtle inner vignette — radial darkness at corners ────────────
        from PyQt6.QtGui import QRadialGradient
        vg = QRadialGradient(self.W / 2, self.H / 2, self.W * 0.72)
        vg.setColorAt(0.0, QColor(0, 0, 0, 0))
        vg.setColorAt(1.0, QColor(0, 0, 0, 60))
        p.setBrush(vg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(1, 1, self.W - 2, self.H - 2, 16, 16)

        # ── Logo mark — centered, upper third ────────────────────────────
        resources = Path(__file__).parent.parent / "resources"
        lettermark = self._load_pixmap(resources / "logo_lettermark_128.png")

        logo_y = 52
        if not lettermark.isNull():
            mark = lettermark.scaled(
                72, 72,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap((self.W - mark.width()) // 2, logo_y, mark)
            text_y = logo_y + mark.height() + 20
        else:
            # Fallback — draw the play-blade icon programmatically
            from PyQt6.QtGui import QPolygonF, QPen
            from PyQt6.QtCore import QPointF
            cx = self.W // 2
            cy = logo_y + 36
            # Triangle
            tg = QLinearGradient(cx - 28, cy - 24, cx + 28, cy + 24)
            tg.setColorAt(0.0, QColor("#7c6af7"))
            tg.setColorAt(1.0, QColor("#34d399"))
            p.setBrush(tg)
            p.setPen(Qt.PenStyle.NoPen)
            tri = QPolygonF([
                QPointF(cx - 22, cy - 24),
                QPointF(cx + 22, cy),
                QPointF(cx - 22, cy + 24),
            ])
            p.drawPolygon(tri)
            # Katana slash
            p.setPen(QPen(QColor("#f472b6"), 3,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(cx - 26, cy + 28, cx + 26, cy - 28)
            # Tsuba
            p.setBrush(QColor("#0d0f18"))
            p.setPen(QPen(QColor("#f472b6"), 2))
            p.drawEllipse(cx - 7, cy - 7, 14, 14)
            text_y = cy + 44

        # ── App name ──────────────────────────────────────────────────────
        wordmark = self._load_pixmap(resources / "logo_wordmark_dark.png")
        if not wordmark.isNull():
            wm = wordmark.scaledToWidth(
                180, Qt.TransformationMode.SmoothTransformation
            )
            p.drawPixmap((self.W - wm.width()) // 2, text_y, wm)
            text_y += wm.height() + 10
        else:
            f_name = QFont("Segoe UI", 28, QFont.Weight.Bold)
            f_name.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4.0)
            p.setFont(f_name)
            p.setPen(QColor("#f0f1f5"))
            p.drawText(0, text_y, self.W, 44,
                       Qt.AlignmentFlag.AlignHCenter, "MIROKU")
            text_y += 50

        # ── Tagline ───────────────────────────────────────────────────────
        f_tag = QFont("Segoe UI", 9)
        f_tag.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3.5)
        f_tag.setWeight(QFont.Weight.Medium)
        p.setFont(f_tag)
        p.setPen(QColor("#3b4260"))
        p.drawText(0, text_y, self.W, 22,
                   Qt.AlignmentFlag.AlignHCenter, "YOUR ANIME UNIVERSE")

        # ── Thin divider ──────────────────────────────────────────────────
        from PyQt6.QtGui import QPen
        p.setPen(QPen(QColor("#1a1d28"), 1))
        p.drawLine(40, self.H - 52, self.W - 40, self.H - 52)

       # ── Version — bottom right ────────────────────────────────────────
        if version:
            f_ver = QFont("Segoe UI", 8)
            p.setFont(f_ver)
            p.setPen(QColor("#2e3250"))
            p.drawText(self.W - 70, self.H - 20, 60, 14,
                       Qt.AlignmentFlag.AlignRight, f"v{version}")

        p.end()
        return px

    def _load_pixmap(self, path: Path) -> QPixmap:
        return QPixmap(str(path)) if path.exists() else QPixmap()

    def set_status(self, msg: str, progress: int = 0) -> None:
        self.showMessage(
            f"  {msg}",
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
            QColor("#4a5070"),
        )
        QApplication_processEvents()

    def _draw_progress(self, pct: int) -> None:
        """Redraw the splash pixmap with a filled progress bar at the bottom."""
        base = self._base_px.copy()
        p = QPainter(base)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Fill the gradient bar proportionally
        fill_w = int((self.W - 2) * max(0, min(pct, 100)) / 100)
        grad = QLinearGradient(0, 0, self.W, 0)
        grad.setColorAt(0.0, QColor("#7c6af7"))
        grad.setColorAt(0.5, QColor("#a78bfa"))
        grad.setColorAt(1.0, QColor("#34d399"))
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(1, self.H - 6, fill_w, 5, 2, 2)
        p.end()
        self.setPixmap(base)


def QApplication_processEvents():
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()


class LoadingOverlay(QWidget):
    """
    Transparent overlay with spinner — placed over any widget.
    Only appears if operation takes longer than SLOW_THRESHOLD_MS (300ms).

    Usage:
        overlay = LoadingOverlay(parent_widget)
        overlay.start()
        # ... long operation ...
        overlay.stop()
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setStyleSheet("background:rgba(10,12,16,0.75);border-radius:12px;")
        self.hide()

        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(12)

        self._spinner_lbl = QLabel("◌")
        self._spinner_lbl.setStyleSheet(
            "font-size:36px;color:#7c6af7;background:transparent;"
        )
        self._spinner_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._spinner_lbl)

        self._msg_lbl = QLabel("Loading…")
        self._msg_lbl.setStyleSheet(
            "font-size:12px;color:#4a5070;background:transparent;"
        )
        self._msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._msg_lbl)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setFixedWidth(160)
        self._bar.setFixedHeight(3)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet(
            "QProgressBar{background:#1a1d28;border:none;border-radius:2px;}"
            "QProgressBar::chunk{background:#7c6af7;border-radius:2px;}"
        )
        lay.addWidget(self._bar, alignment=Qt.AlignmentFlag.AlignCenter)

        # Spinner rotation
        self._spin_chars = ["◜", "◝", "◞", "◟"]
        self._spin_idx = 0
        self._spin_timer = QTimer()
        self._spin_timer.timeout.connect(self._tick)

        # Threshold timer — only show after SLOW_THRESHOLD_MS
        self._threshold_timer = QTimer()
        self._threshold_timer.setSingleShot(True)
        self._threshold_timer.timeout.connect(self._show_now)

    def start(self, message: str = "Loading…"):
        self._msg_lbl.setText(message)
        self._resize_to_parent()
        self._threshold_timer.start(SLOW_THRESHOLD_MS)
        self._spin_timer.start(120)

    def stop(self):
        self._threshold_timer.stop()
        self._spin_timer.stop()
        self.hide()

    def _show_now(self):
        self._resize_to_parent()
        self.show()
        self.raise_()

    def _tick(self):
        self._spin_idx = (self._spin_idx + 1) % len(self._spin_chars)
        self._spinner_lbl.setText(self._spin_chars[self._spin_idx])

    def _resize_to_parent(self):
        if self.parent():
            self.setGeometry(self.parent().rect())
