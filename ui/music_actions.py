"""
Raikō - the small music actions used everywhere a song plays:

  ♥  like / unlike            (gallery, player, Music page)
  ⬇  download as Audio (MP3) or Video (MP4) to your Downloads folder
  ☆  rank it                  (Music → Rankings)

MusicHub is the app-wide hub: it knows the library database (set by the main
window), runs downloads in the background with progress, and tells every
open view when likes / rankings / downloads change.
"""
from __future__ import annotations

import os
import subprocess
from typing import Dict, Optional

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QMenu, QPushButton, QWidget

MUSIC_KINDS = ("opening", "ending", "intro", "soundtrack")


def is_music(item: Optional[Dict]) -> bool:
    return bool(item) and item.get("kind") in MUSIC_KINDS


class MusicHub(QObject):
    likes_changed = pyqtSignal()
    ranks_changed = pyqtSignal()
    downloads_changed = pyqtSignal()
    progress = pyqtSignal(str, str, float, str)      # vid, mode, fraction, text
    finished = pyqtSignal(str, str, str)             # vid, mode, path
    failed = pyqtSignal(str, str, str)               # vid, mode, message
    _instance: Optional["MusicHub"] = None

    def __init__(self):
        super().__init__()
        self.db = None
        self.active: Dict[str, float] = {}           # "vid:mode" -> progress
        self._items: Dict[str, Dict] = {}
        self._window = None
        self.finished.connect(self._on_finished)
        self.failed.connect(self._on_failed)
        self.progress.connect(self._track)

    @classmethod
    def get(cls) -> "MusicHub":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def lib(self):
        if self.db is None:
            return None
        from core.music_library import MusicLibrary
        return MusicLibrary(self.db)

    # likes
    def toggle_like(self, item: Dict) -> bool:
        lib = self.lib()
        if lib is None:
            return False
        on = lib.toggle_like(item)
        self.likes_changed.emit()
        return on

    def is_liked(self, vid: str) -> bool:
        lib = self.lib()
        return bool(lib and lib.is_liked(vid))

    # downloads
    def download(self, item: Dict, mode: str, window: Optional[QWidget] = None):
        key = f"{item['id']}:{mode}"
        if key in self.active:
            return
        self.active[key] = 0.0
        self._window = window
        self._items[key] = dict(item)
        from ui.toast import Toast
        if window is not None:
            Toast.show(window, ("Downloading the audio…" if mode == "audio" else "Downloading the video…")
                       + " It'll be in your Downloads folder.", kind="info")
        from workers.workers import Worker, run_worker
        vid = item["id"]
        hub = self

        def job():
            from core.downloader import download
            return download(item, mode, lambda f, t: hub.progress.emit(vid, mode, float(f), t))

        w = Worker(job)
        w.signals.result.connect(lambda path: self.finished.emit(vid, mode, str(path)))
        w.signals.error.connect(lambda msg: self.failed.emit(vid, mode, str(msg)))
        run_worker(w)
        self.downloads_changed.emit()

    def _track(self, vid, mode, frac, _text):
        k = f"{vid}:{mode}"
        if k in self.active:
            self.active[k] = frac

    def _on_finished(self, vid, mode, path):
        key = f"{vid}:{mode}"
        self.active.pop(key, None)
        item = self._items.pop(key, {"id": vid})
        lib = self.lib()
        if lib is not None:
            lib.record_download(item, mode, path)
        self.downloads_changed.emit()
        from ui.toast import Toast
        w = getattr(self, "_window", None)
        if w is not None:
            try:
                Toast.show(w, f"Saved to Downloads: {os.path.basename(path)}", kind="success", duration=6000)
            except RuntimeError:
                pass

    def _on_failed(self, vid, mode, msg):
        self.active.pop(f"{vid}:{mode}", None)
        self.downloads_changed.emit()
        from ui.toast import Toast
        w = getattr(self, "_window", None)
        if w is not None:
            try:
                Toast.show(w, "Couldn't download that one — YouTube may be blocking it. Try again later.",
                           kind="error", duration=6000)
            except RuntimeError:
                pass


def reveal(path: str):
    """Show the file in Explorer (selected)."""
    try:
        if os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            from core.downloader import downloads_dir
            os.startfile(str(downloads_dir()))
    except Exception:
        pass


def download_menu(item: Dict, anchor: QWidget):
    """⬇ menu: Audio (MP3) / Video (MP4)."""
    m = QMenu(anchor)
    a = m.addAction("♪  Audio — MP3")
    v = m.addAction("▶  Video — MP4 (up to 1080p)")
    m.addSeparator()
    note = m.addAction("Saved to your Downloads folder · personal use")
    note.setEnabled(False)
    chosen = m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
    if chosen in (a, v):
        MusicHub.get().download(item, "audio" if chosen is a else "video", anchor.window())


class LikeButton(QPushButton):
    """♥ toggle for one song; follows likes made anywhere else."""

    def __init__(self, compact: bool = False, parent=None):
        super().__init__(parent)
        self.item: Optional[Dict] = None
        self.compact = compact
        self.setObjectName("musicLike")
        self.setCheckable(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.clicked.connect(self._click)
        MusicHub.get().likes_changed.connect(self.refresh)
        self.refresh()

    def set_item(self, item: Optional[Dict]):
        self.item = item
        self.refresh()

    def refresh(self):
        try:
            on = bool(self.item) and MusicHub.get().is_liked(self.item["id"])
            self.setChecked(on)
            self.setText(("♥" if on else "♡") if self.compact else ("♥  Liked" if on else "♡  Like"))
            self.setToolTip("Remove from Liked music" if on else "Add to Liked music")
        except RuntimeError:
            pass

    def _click(self):
        if self.item:
            MusicHub.get().toggle_like(self.item)
        self.refresh()


def download_button(item_getter, compact: bool = False) -> QPushButton:
    b = QPushButton("⬇" if compact else "⬇  Download")
    b.setObjectName("musicAction")
    b.setToolTip("Save to your Downloads folder as audio or video")
    b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    b.clicked.connect(lambda: item_getter() and download_menu(item_getter(), b))
    return b
