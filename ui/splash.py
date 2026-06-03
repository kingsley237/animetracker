"""
Miroku splash screen and deferred loading indicator.

SplashScreen is shown at startup while DB and workers initialize.
LoadingOverlay appears over a widget only after a short delay.
"""
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import QLabel, QProgressBar, QSplashScreen, QVBoxLayout, QWidget


SLOW_THRESHOLD_MS = 300


class SplashScreen(QSplashScreen):
    """
    App startup splash shown while the main window initializes.
    """

    W, H = 560, 320

    def __init__(self, version: str = "", screen=None):
        px = self._render(version)
        self._base_px = px
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

        p.setBrush(QColor("#0d0f18"))
        p.setPen(QColor("#1e2235"))
        p.drawRoundedRect(1, 1, self.W - 2, self.H - 2, 16, 16)

        vignette = QRadialGradient(self.W / 2, self.H / 2, self.W * 0.72)
        vignette.setColorAt(0.0, QColor(0, 0, 0, 0))
        vignette.setColorAt(1.0, QColor(0, 0, 0, 60))
        p.setBrush(vignette)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(1, 1, self.W - 2, self.H - 2, 16, 16)

        resources = Path(__file__).parent.parent / "resources"
        wordmark = self._load_pixmap(resources / "miroku_wordmark_1600x600.png")
        if wordmark.isNull():
            wordmark = self._load_pixmap(resources / "miroku_wordmark.png")

        text_y = 86
        if not wordmark.isNull():
            wm = wordmark.scaledToWidth(
                280, Qt.TransformationMode.SmoothTransformation
            )
            p.drawPixmap((self.W - wm.width()) // 2, text_y, wm)
            text_y += wm.height() + 18
        else:
            f_name = QFont("Segoe UI", 28, QFont.Weight.Bold)
            f_name.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4.0)
            p.setFont(f_name)
            p.setPen(QColor("#f0f1f5"))
            p.drawText(
                0,
                text_y,
                self.W,
                44,
                Qt.AlignmentFlag.AlignHCenter,
                "MIROKU",
            )
            text_y += 50

        f_tag = QFont("Segoe UI", 9)
        f_tag.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3.5)
        f_tag.setWeight(QFont.Weight.Medium)
        p.setFont(f_tag)
        p.setPen(QColor("#3b4260"))
        p.drawText(
            0,
            text_y,
            self.W,
            22,
            Qt.AlignmentFlag.AlignHCenter,
            "YOUR ANIME UNIVERSE",
        )

        p.setPen(QPen(QColor("#1a1d28"), 1))
        p.drawLine(40, self.H - 52, self.W - 40, self.H - 52)

        if version:
            f_ver = QFont("Segoe UI", 8)
            p.setFont(f_ver)
            p.setPen(QColor("#2e3250"))
            p.drawText(
                self.W - 70,
                self.H - 20,
                60,
                14,
                Qt.AlignmentFlag.AlignRight,
                f"v{version}",
            )

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
    Transparent overlay with spinner placed over any widget.
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setStyleSheet("background:rgba(10,12,16,0.75);border-radius:12px;")
        self.hide()

        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(12)

        self._spinner_lbl = QLabel("|")
        self._spinner_lbl.setStyleSheet(
            "font-size:36px;color:#7c6af7;background:transparent;"
        )
        self._spinner_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._spinner_lbl)

        self._msg_lbl = QLabel("Loading...")
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

        self._spin_chars = ["|", "/", "-", "\\"]
        self._spin_idx = 0
        self._spin_timer = QTimer()
        self._spin_timer.timeout.connect(self._tick)

        self._threshold_timer = QTimer()
        self._threshold_timer.setSingleShot(True)
        self._threshold_timer.timeout.connect(self._show_now)

    def start(self, message: str = "Loading..."):
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
