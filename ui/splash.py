"""
AnimeTracker — Splash screen and deferred loading indicator.

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

    W, H = 480, 280

    def __init__(self, version: str = "", screen=None):
        px = self._render(version)
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

        # Background rounded rect
        p.setBrush(QColor("#0f1118"))
        p.setPen(QColor("#1e2235"))
        p.drawRoundedRect(1, 1, self.W - 2, self.H - 2, 16, 16)

        # Accent bar top
        grad = QLinearGradient(0, 0, self.W, 0)
        grad.setColorAt(0.0, QColor("#7c6af7"))
        grad.setColorAt(1.0, QColor("#34d399"))
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(1, 1, self.W - 2, 4, 2, 2)

        # App name — large wordmark
        resources = Path(__file__).parent.parent / "resources"
        lettermark = self._load_pixmap(resources / "logo_lettermark_128.png")
        wordmark = self._load_pixmap(resources / "logo_wordmark_dark.png")

        y = 42
        if not lettermark.isNull():
            mark = lettermark.scaled(
                64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap((self.W - mark.width()) // 2, y, mark)
            y += mark.height() + 10

        if not wordmark.isNull():
            wm = wordmark.scaledToWidth(220, Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((self.W - wm.width()) // 2, y, wm)
            y += wm.height() + 6
        else:
            f = QFont("Segoe UI", 32, QFont.Weight.Bold)
            p.setFont(f)
            p.setPen(QColor("#f0f1f5"))
            p.drawText(0, y, self.W, 52, Qt.AlignmentFlag.AlignHCenter, "Miroku")
            y += 58

        # Tagline
        f2 = QFont("Segoe UI", 11)
        f2.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.5)
        p.setFont(f2)
        p.setPen(QColor("#4a5070"))
        p.drawText(0, y, self.W, 30, Qt.AlignmentFlag.AlignHCenter,
                   "YOUR ANIME UNIVERSE")

        # Version
        if version:
            f3 = QFont("Segoe UI", 9)
            p.setFont(f3)
            p.setPen(QColor("#2e3250"))
            p.drawText(0, self.H - 28, self.W, 20,
                       Qt.AlignmentFlag.AlignHCenter, f"v{version}")

        p.end()
        return px

    def _load_pixmap(self, path: Path) -> QPixmap:
        return QPixmap(str(path)) if path.exists() else QPixmap()

    def set_status(self, msg: str):
        self.showMessage(
            msg,
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
            QColor("#4a5070"),
        )
        QApplication_processEvents()


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
