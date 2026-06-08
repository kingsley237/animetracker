"""
Miroku — Trailer Player.

Stable in-app trailer playback. YouTube requires a valid Referer — we load
embeds via HTML + base URL and set Referer on direct loads.
"""
import html
import webbrowser

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QCursor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

# Stable https origin sent as Referer for YouTube embed policy.
_EMBED_ORIGIN = "https://miroku.app/"


def _has_webengine() -> bool:
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        return True
    except ImportError:
        return False


def _watch_url(trailer_id: str, site: str) -> str:
    if site.lower() == "youtube":
        return f"https://www.youtube.com/watch?v={trailer_id}"
    return f"https://www.dailymotion.com/video/{trailer_id}"


def _embed_url(trailer_id: str, site: str) -> str:
    site = site.lower()
    if site == "youtube":
        return (
            f"https://www.youtube-nocookie.com/embed/{trailer_id}"
            "?autoplay=1&rel=0&modestbranding=1&playsinline=1"
        )
    return f"https://www.dailymotion.com/embed/video/{trailer_id}?autoplay=1"


def _youtube_embed_html(trailer_id: str) -> str:
    src = html.escape(_embed_url(trailer_id, "youtube"), quote=True)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="referrer" content="strict-origin-when-cross-origin">
  <style>
    html, body {{
      margin: 0; padding: 0; width: 100%; height: 100%;
      background: #0a0c10; overflow: hidden;
    }}
    iframe {{
      position: fixed; inset: 0; width: 100%; height: 100%; border: 0;
    }}
  </style>
</head>
<body>
  <iframe
    src="{src}"
    title="Trailer"
    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
    allowfullscreen
    referrerpolicy="strict-origin-when-cross-origin">
  </iframe>
</body>
</html>"""


def _dailymotion_embed_html(trailer_id: str) -> str:
    src = html.escape(_embed_url(trailer_id, "dailymotion"), quote=True)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    html, body {{
      margin: 0; padding: 0; width: 100%; height: 100%;
      background: #0a0c10; overflow: hidden;
    }}
    iframe {{
      position: fixed; inset: 0; width: 100%; height: 100%; border: 0;
    }}
  </style>
</head>
<body>
  <iframe
    src="{src}"
    title="Trailer"
    allow="autoplay; fullscreen; picture-in-picture"
    allowfullscreen
    referrerpolicy="strict-origin-when-cross-origin">
  </iframe>
</body>
</html>"""


class TrailerDialog(QDialog):
    """Modal trailer dialog with stable direct embed playback."""

    VIDEO_W = 960
    VIDEO_H = 540

    def __init__(self, trailer_id: str, trailer_site: str,
                 anime_title: str, parent=None):
        super().__init__(parent)
        self._tid = trailer_id
        self._tsite = trailer_site.lower()
        self._title = anime_title or "Trailer"
        self._view = None
        self._stopping = False
        self._loaded = False
        self._fs_btn = None

        self.setWindowTitle(f"Trailer — {self._title}")
        self.setModal(True)
        self.setStyleSheet("background:#0a0c10;")
        self.resize(self.VIDEO_W, self.VIDEO_H + 48)
        self.setMinimumSize(760, 480)

        self._build()
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._exit_fullscreen)

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background:#0a0c10;")

        self._loading = QLabel("Loading trailer…")
        self._loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading.setStyleSheet(
            "color:#9da5c0;font-size:14px;background:#0a0c10;"
        )
        self._stack.addWidget(self._loading)

        if _has_webengine():
            self._build_player()
        else:
            self._build_fallback()

        lay.addWidget(self._stack, stretch=1)
        lay.addWidget(self._bottom_bar())

    def _build_player(self):
        from PyQt6.QtWebEngineCore import QWebEngineSettings
        from PyQt6.QtWebEngineWidgets import QWebEngineView

        self._view = QWebEngineView()
        self._view.setMinimumSize(640, 360)
        self._view.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._view.setStyleSheet("background:#0a0c10;")

        settings = self._view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture,
            False,
        )
        settings.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

        self._view.page().profile().setHttpUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        self._view.page().fullScreenRequested.connect(lambda req: req.accept())
        self._view.loadFinished.connect(self._on_load_finished)

        self._stack.addWidget(self._view)
        self._stack.setCurrentWidget(self._loading)

    def _build_fallback(self):
        ph = QWidget()
        ph.setStyleSheet("background:#111420;")
        inner = QVBoxLayout(ph)
        inner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.setSpacing(14)

        icon = QLabel("▶")
        icon.setStyleSheet("font-size:56px;color:#7c6af7;background:transparent;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(icon)

        msg = QLabel(
            "Trailer player requires PyQt6-WebEngine.\n\n"
            "Install it with:\n\npip install PyQt6-WebEngine\n\n"
            "Or open the trailer in your browser below."
        )
        msg.setStyleSheet("font-size:13px;color:#6b7280;background:transparent;")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        inner.addWidget(msg)

        btn = QPushButton(
            "Open in YouTube" if self._tsite == "youtube" else "Open in Browser"
        )
        btn.setObjectName("primaryBtn")
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setFixedWidth(180)
        btn.clicked.connect(lambda: webbrowser.open(_watch_url(self._tid, self._tsite)))
        inner.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._stack.addWidget(ph)
        self._stack.setCurrentWidget(ph)

    def _load_trailer(self):
        if self._view is None or self._loaded:
            return

        base = QUrl(_EMBED_ORIGIN)
        if self._tsite == "youtube":
            self._view.setHtml(_youtube_embed_html(self._tid), base)
        else:
            self._view.setHtml(_dailymotion_embed_html(self._tid), base)

    def showEvent(self, event):
        super().showEvent(event)
        parent_window = self.parent().window() if self.parent() else None
        screen = parent_window.screen() if parent_window else QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            w = min(self.VIDEO_W, avail.width() - 80)
            h = min(self.VIDEO_H + 48, avail.height() - 80)
            self.resize(w, h)
            self.move(
                avail.left() + (avail.width() - w) // 2,
                avail.top() + (avail.height() - h) // 2,
            )

        self._load_trailer()

    def _on_load_finished(self, ok: bool):
        self._loaded = True
        if self._view is not None:
            self._stack.setCurrentWidget(self._view)
        if not ok:
            self._loading.setText(
                "Could not load the in-app player.\n"
                "Use Open in YouTube below."
            )
            self._stack.setCurrentWidget(self._loading)

    def _bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(48)
        bar.setStyleSheet("background:#0f1118;border-top:1px solid #1a1d28;")
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(10)

        lbl = QLabel(self._title)
        lbl.setStyleSheet("font-size:12px;color:#6b7280;background:transparent;")
        row.addWidget(lbl)
        row.addStretch()

        ext = QPushButton(
            "Open in YouTube ↗" if self._tsite == "youtube" else "Open in Browser ↗"
        )
        ext.setStyleSheet(
            "QPushButton{background:transparent;color:#4a5070;"
            "border:none;font-size:11px;}"
            "QPushButton:hover{color:#9da5c0;}"
        )
        ext.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        ext.clicked.connect(lambda: webbrowser.open(_watch_url(self._tid, self._tsite)))
        row.addWidget(ext)

        self._fs_btn = QPushButton("Fullscreen")
        self._fs_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#4a5070;"
            "border:none;font-size:11px;}"
            "QPushButton:hover{color:#9da5c0;}"
        )
        self._fs_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._fs_btn.clicked.connect(self._toggle_fullscreen)
        row.addWidget(self._fs_btn)

        close = QPushButton("✕  Close")
        close.setStyleSheet(
            "QPushButton{background:#1a1d28;color:#9da5c0;"
            "border:1px solid #2a2d42;border-radius:6px;"
            "font-size:11px;font-weight:500;padding:6px 16px;}"
            "QPushButton:hover{background:#252a40;color:#c7cbd9;}"
        )
        close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        return bar

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self._exit_fullscreen()
        else:
            self.showFullScreen()
            if self._fs_btn is not None:
                self._fs_btn.setText("Exit fullscreen")

    def _exit_fullscreen(self):
        if not self.isFullScreen():
            return
        self.showNormal()
        if self._fs_btn is not None:
            self._fs_btn.setText("Fullscreen")

    def _stop_playback(self):
        if self._stopping:
            return
        self._stopping = True
        if self._view is not None:
            try:
                self._view.stop()
                self._view.setUrl(QUrl("about:blank"))
                self._view.deleteLater()
                self._view = None
            except Exception:
                pass

    def closeEvent(self, event):
        self._stop_playback()
        super().closeEvent(event)

    def accept(self):
        self._stop_playback()
        super().accept()

    def reject(self):
        self._stop_playback()
        super().reject()

    def done(self, result: int):
        self._stop_playback()
        super().done(result)


TrailerPlayer = TrailerDialog


def show_trailer(trailer_id: str, trailer_site: str,
                 anime_title: str, parent=None) -> None:
    dlg = TrailerDialog(trailer_id, trailer_site, anime_title, parent)
    dlg.exec()
