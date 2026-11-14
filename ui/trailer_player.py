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
                 anime_title: str, parent=None, playlist=None, index: int = 0):
        super().__init__(parent)
        # Playlist mode: [{id, site, title, kind, thumb}], switch in place.
        self._playlist = [v for v in (playlist or []) if v.get("id")]
        if not self._playlist:
            self._playlist = [{"id": trailer_id, "site": trailer_site, "title": "Trailer"}]
        self._index = max(0, min(index, len(self._playlist) - 1))
        cur = self._playlist[self._index]
        self._tid = cur["id"]
        self._tsite = (cur.get("site") or "youtube").lower()
        self._title = anime_title or "Trailer"
        self._rows = []
        self._view = None
        self._stopping = False
        self._loaded = False
        self._fs_btn = None

        self.setWindowTitle(f"Trailers — {self._title}")
        self.setModal(True)
        self.setStyleSheet("background:#0a0c10;")
        self.resize(self.VIDEO_W, self.VIDEO_H + 48)
        self.setMinimumSize(760, 480)

        self._build()
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._exit_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, lambda: self._step(1))
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, lambda: self._step(-1))

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

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._stack, stretch=1)
        if len(self._playlist) > 1:
            body.addWidget(self._build_sidebar())
        lay.addLayout(body, stretch=1)
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

    # ── Playlist ──────────────────────────────────────────────────────────

    def _build_sidebar(self) -> QWidget:
        from PyQt6.QtWidgets import QScrollArea, QFrame
        side = QWidget()
        side.setFixedWidth(300)
        side.setStyleSheet("background:#0f1118;border-left:1px solid #1a1d28;")
        v = QVBoxLayout(side)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(6)
        head = QLabel(f"UP NEXT  ·  {len(self._playlist)} videos")
        head.setStyleSheet("color:#5c6482;font-size:10px;font-weight:700;"
                           "letter-spacing:1.5px;padding:0 14px;border:none;")
        v.addWidget(head)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        inner = QWidget()
        inner.setStyleSheet("border:none;")
        il = QVBoxLayout(inner)
        il.setContentsMargins(8, 4, 8, 12)
        il.setSpacing(4)
        for i, item in enumerate(self._playlist):
            row = _PlaylistRow(i, item)
            row.clicked.connect(self._select)
            il.addWidget(row)
            self._rows.append(row)
        il.addStretch()
        sa.setWidget(inner)
        v.addWidget(sa, 1)
        self._side_scroll = sa
        self._mark_current()
        return side

    def _mark_current(self):
        for r in self._rows:
            r.set_current(r.index == self._index)
        if self._rows and hasattr(self, "_side_scroll"):
            self._side_scroll.ensureWidgetVisible(self._rows[self._index], 0, 40)
        if getattr(self, "_counter", None) is not None:
            cur = self._playlist[self._index]
            self._counter.setText(f"{cur.get('title') or 'Trailer'}   ·   {self._index + 1} / {len(self._playlist)}")

    def _select(self, index: int):
        if index == self._index and self._loaded:
            return
        self._index = index
        cur = self._playlist[index]
        self._tid = cur["id"]
        self._tsite = (cur.get("site") or "youtube").lower()
        self._loaded = False
        if self._view is not None:
            self._stack.setCurrentWidget(self._loading)
            self._loading.setText("Loading…")
        self._mark_current()
        self._load_trailer()

    def _step(self, delta: int):
        if len(self._playlist) > 1:
            self._select((self._index + delta) % len(self._playlist))

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
            extra = 300 if len(self._playlist) > 1 else 0
            w = min(self.VIDEO_W + extra, avail.width() - 80)
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
        self._counter = None
        if len(self._playlist) > 1:
            nav = "QPushButton{background:#1a1d28;color:#c7cbd9;border:1px solid #2a2d42;" \
                  "border-radius:6px;font-size:13px;font-weight:700;padding:3px 10px;}" \
                  "QPushButton:hover{background:#4b3fa8;border-color:#4b3fa8;color:#fff;}"
            prev = QPushButton("‹")
            prev.setToolTip("Previous video (←)")
            nxt = QPushButton("›")
            nxt.setToolTip("Next video (→)")
            for b, d in ((prev, -1), (nxt, 1)):
                b.setStyleSheet(nav)
                b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                b.clicked.connect(lambda _=False, d=d: self._step(d))
            row.addSpacing(8)
            row.addWidget(prev)
            row.addWidget(nxt)
            self._counter = QLabel()
            self._counter.setStyleSheet("font-size:12px;color:#c4b8ff;font-weight:600;background:transparent;")
            row.addWidget(self._counter)
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
        if self._counter is not None:
            self._mark_current()

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


class _PlaylistRow(QWidget):
    """Thumbnail + title row in the Up Next list."""
    from PyQt6.QtCore import pyqtSignal as _sig
    clicked = _sig(int)

    def __init__(self, index: int, item: dict, parent=None):
        super().__init__(parent)
        self.index = index
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 6, 6, 6)
        h.setSpacing(10)
        self.thumb = QLabel()
        self.thumb.setFixedSize(112, 63)
        self.thumb.setStyleSheet("background:#1a1d28;border-radius:6px;border:none;")
        h.addWidget(self.thumb)
        col = QVBoxLayout()
        col.setSpacing(2)
        kind = {"music": "THEME", "promo": "PROMO"}.get(item.get("kind"), "VIDEO")
        k = QLabel(kind)
        k.setStyleSheet("color:#7c6af7;font-size:9px;font-weight:800;letter-spacing:1px;"
                        "background:transparent;border:none;")
        t = QLabel(item.get("title") or "Video")
        t.setWordWrap(True)
        t.setStyleSheet("color:#e2e4ec;font-size:11px;font-weight:600;background:transparent;border:none;")
        col.addWidget(k)
        col.addWidget(t)
        if item.get("artist"):
            a = QLabel(item["artist"])
            a.setStyleSheet("color:#7b84a3;font-size:10px;background:transparent;border:none;")
            col.addWidget(a)
        col.addStretch()
        h.addLayout(col, 1)
        self.set_current(False)
        thumb = item.get("thumb")
        if thumb:
            from workers.workers import ImageWorker, run_worker
            w = ImageWorker(thumb, index)
            w.signals.result.connect(self._on_img)
            run_worker(w)

    def _on_img(self, result):
        try:
            _i, _s, path = result
        except Exception:
            return
        if not path:
            return
        from PyQt6.QtGui import QPixmap, QPainter, QPainterPath
        px = QPixmap(str(path))
        if px.isNull():
            return
        W, H = self.thumb.width(), self.thumb.height()
        sc = px.scaled(W, H, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation)
        out = QPixmap(W, H)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, W, H, 6, 6)
        p.setClipPath(path)
        p.drawPixmap(0, 0, sc, (sc.width() - W) // 2, (sc.height() - H) // 2, W, H)
        p.end()
        try:
            self.thumb.setPixmap(out)
        except RuntimeError:
            pass

    def set_current(self, on: bool):
        self.setStyleSheet(
            "_PlaylistRow{background:#1e1a44;border:1px solid #4b3fa8;border-radius:8px;}"
            if on else
            "_PlaylistRow{background:transparent;border:1px solid transparent;border-radius:8px;}"
            "_PlaylistRow:hover{background:#151827;}")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)


TrailerPlayer = TrailerDialog


def show_trailer(trailer_id: str, trailer_site: str,
                 anime_title: str, parent=None, playlist=None, index: int = 0) -> None:
    dlg = TrailerDialog(trailer_id, trailer_site, anime_title, parent,
                        playlist=playlist, index=index)
    dlg.exec()
