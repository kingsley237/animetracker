"""
AnimeTracker - Trailer Player.

Uses QWebEngineView with a small local HTML player shell. The shell owns the
loader UI, so users never get stuck behind a Python overlay if WebEngine load
signals behave oddly.
"""
import html
import webbrowser

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _has_webengine() -> bool:
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa
        return True
    except ImportError:
        return False


def _watch_url(trailer_id: str, site: str) -> str:
    if site.lower() == "youtube":
        return f"https://www.youtube.com/watch?v={trailer_id}"
    return f"https://www.dailymotion.com/video/{trailer_id}"


def _player_html(trailer_id: str, site: str, title: str) -> str:
    title = html.escape(title or "Trailer")
    site = site.lower()
    if site == "youtube":
        watch = html.escape(_watch_url(trailer_id, site) + "&autoplay=1", quote=True)
        return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    html, body {{
      width: 100%; height: 100%; margin: 0; overflow: hidden;
      background: #0a0c10; color: #9da5c0;
      font-family: "Segoe UI", Arial, sans-serif;
    }}
    #loader {{
      position: fixed; inset: 0;
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      gap: 14px; background: #0a0c10;
    }}
    #play {{ color: #7c6af7; font-size: 54px; line-height: 1; }}
    #label {{ font-size: 14px; }}
    #bar {{ width: 240px; height: 3px; background: #1a1d28; border-radius: 999px; overflow: hidden; }}
    #fill {{ width: 0%; height: 100%; background: #7c6af7; border-radius: 999px; transition: width 120ms linear; }}
    #hint {{ margin-top: 6px; font-size: 11px; color: #4a5070; }}
  </style>
</head>
<body>
  <div id="loader">
    <div id="play">▶</div>
    <div id="label">Opening YouTube player... 0%</div>
    <div id="bar"><div id="fill"></div></div>
    <div id="hint">Loading the video directly, not embedded</div>
  </div>

  <script>
    let pct = 0;
    const label = document.getElementById('label');
    const fill = document.getElementById('fill');
    const tick = setInterval(() => {{
      pct = Math.min(100, pct + 20);
      label.textContent = `Opening YouTube player... ${{pct}}%`;
      fill.style.width = pct + '%';
      if (pct >= 100) {{
        clearInterval(tick);
        window.location.replace("{watch}");
      }}
    }}, 120);
  </script>
</body>
</html>"""
    else:
        src = f"https://www.dailymotion.com/embed/video/{html.escape(trailer_id)}?autoplay=1"
        allow = "autoplay; fullscreen; picture-in-picture"

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    html, body {{
      width: 100%; height: 100%; margin: 0; overflow: hidden;
      background: #0a0c10; color: #9da5c0;
      font-family: "Segoe UI", Arial, sans-serif;
    }}
    #player, iframe {{
      position: fixed; inset: 0; width: 100%; height: 100%;
      border: 0; background: #0a0c10;
    }}
    #loader {{
      position: fixed; inset: 0; z-index: 5;
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      gap: 14px; background: #0a0c10;
      transition: opacity 220ms ease;
    }}
    #play {{ color: #7c6af7; font-size: 54px; line-height: 1; }}
    #label {{ font-size: 14px; }}
    #bar {{ width: 240px; height: 3px; background: #1a1d28; border-radius: 999px; overflow: hidden; }}
    #fill {{ width: 0%; height: 100%; background: #7c6af7; border-radius: 999px; transition: width 140ms linear; }}
    #hint {{ margin-top: 6px; font-size: 11px; color: #4a5070; }}
    #open {{
      margin-top: 8px; border: 1px solid #2a2d42; background: #111420;
      color: #9da5c0; border-radius: 8px; padding: 8px 14px; cursor: pointer;
      font-size: 12px;
    }}
  </style>
</head>
<body>
  <div id="player">
    <iframe
      id="frame"
      title="{title}"
      src="{src}"
      allow="{allow}"
      allowfullscreen
      referrerpolicy="origin-when-cross-origin">
    </iframe>
  </div>

  <div id="loader">
    <div id="play">▶</div>
    <div id="label">Loading trailer... 0%</div>
    <div id="bar"><div id="fill"></div></div>
    <div id="hint">Preparing the player</div>
    <button id="open" onclick="window.location.href='{src}'">Reload player</button>
  </div>

  <script>
    let pct = 0;
    const label = document.getElementById('label');
    const fill = document.getElementById('fill');
    const loader = document.getElementById('loader');
    const frame = document.getElementById('frame');

    const tick = setInterval(() => {{
      pct = Math.min(95, pct + (pct < 50 ? 7 : 3));
      label.textContent = `Loading trailer... ${{pct}}%`;
      fill.style.width = pct + '%';
    }}, 220);

    function reveal() {{
      clearInterval(tick);
      label.textContent = 'Loading trailer... 100%';
      fill.style.width = '100%';
      setTimeout(() => {{
        loader.style.opacity = '0';
        loader.style.pointerEvents = 'none';
        setTimeout(() => loader.style.display = 'none', 240);
      }}, 260);
    }}

    frame.addEventListener('load', reveal);
    setTimeout(reveal, 4200);
  </script>
</body>
</html>"""


class TrailerDialog(QDialog):
    """Fullscreen modal trailer dialog."""

    VIDEO_W = 900
    VIDEO_H = int(900 * 9 / 16)

    def __init__(self, trailer_id: str, trailer_site: str,
                 anime_title: str, parent=None):
        super().__init__(parent)
        self._tid = trailer_id
        self._tsite = trailer_site.lower()
        self._title = anime_title
        self._view = None
        self._stopping = False

        self.setWindowTitle(f"Trailer - {anime_title}")
        self.setModal(True)
        self.setStyleSheet("background:#0a0c10;")
        self.resize(self.VIDEO_W, self.VIDEO_H + 48)
        self.setMinimumSize(760, 480)

        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        if _has_webengine():
            self._build_player(lay)
        else:
            self._build_fallback(lay)

        lay.addWidget(self._bottom_bar())

    def _build_player(self, lay):
        from PyQt6.QtWebEngineCore import QWebEngineSettings
        from PyQt6.QtWebEngineWidgets import QWebEngineView

        self._view = QWebEngineView()
        self._view.setMinimumSize(640, 360)
        self._view.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Expanding)
        self._view.setStyleSheet("background:#0a0c10;")

        settings = self._view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)

        self._view.page().profile().setHttpUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        self._view.page().fullScreenRequested.connect(lambda req: req.accept())

        self._view.setHtml(
            _player_html(self._tid, self._tsite, self._title),
            QUrl("https://www.youtube.com/" if self._tsite == "youtube" else "https://www.dailymotion.com/"),
        )
        lay.addWidget(self._view)

    def _build_fallback(self, lay):
        ph = QWidget()
        ph.setFixedSize(self.VIDEO_W, self.VIDEO_H)
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
            "It is bundled in the distributed exe.\n"
            "If you are running from source, run:\n\n"
            "pip install PyQt6-WebEngine\n\n"
            "Or open the trailer in your browser below."
        )
        msg.setStyleSheet("font-size:13px;color:#6b7280;background:transparent;")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        inner.addWidget(msg)

        btn = QPushButton("Open in YouTube" if self._tsite == "youtube" else "Open in Browser")
        btn.setObjectName("primaryBtn")
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setFixedWidth(180)
        btn.clicked.connect(lambda: webbrowser.open(_watch_url(self._tid, self._tsite)))
        inner.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

        lay.addWidget(ph)

    def showEvent(self, event):
        super().showEvent(event)
        parent_window = self.parent().window() if self.parent() else None
        screen = parent_window.screen() if parent_window else QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.availableGeometry())

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

        ext = QPushButton("Open in YouTube ↗" if self._tsite == "youtube" else "Open in Browser ↗")
        ext.setStyleSheet(
            "QPushButton{background:transparent;color:#4a5070;"
            "border:none;font-size:11px;}"
            "QPushButton:hover{color:#9da5c0;}"
        )
        ext.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        ext.clicked.connect(lambda: webbrowser.open(_watch_url(self._tid, self._tsite)))
        row.addWidget(ext)

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

    def _stop_playback(self):
        if self._stopping:
            return
        self._stopping = True
        if self._view is not None:
            try:
                self._view.stop()
                self._view.setHtml(
                    "<html><body style='margin:0;background:#0a0c10;'></body></html>",
                    QUrl("about:blank"),
                )
                self._view.deleteLater()
                self._view = None
            except Exception:
                pass

    def closeEvent(self, event):
        self._stop_playback()
        super().closeEvent(event)

    def hideEvent(self, event):
        self._stop_playback()
        super().hideEvent(event)

    def accept(self):
        self._stop_playback()
        super().accept()

    def reject(self):
        self._stop_playback()
        super().reject()

    def done(self, result: int):
        self._stop_playback()
        super().done(result)


def show_trailer(trailer_id: str, trailer_site: str,
                 anime_title: str, parent=None) -> None:
    dlg = TrailerDialog(trailer_id, trailer_site, anime_title, parent)
    dlg.exec()
