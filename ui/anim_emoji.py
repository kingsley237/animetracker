"""
Raikō - animated emoji (Noto Emoji Animation by Google, CC BY 4.0).

AnimatedEmoji("🎃", 40) shows the animated version when Google publishes one
(downloaded once, cached in ~/.animetracker/cache/emoji, played natively by
QMovie as animated WebP) and the normal emoji otherwise or while offline.
With motion off (Settings or Windows' reduced motion) it stays still.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QFont, QMovie
from PyQt6.QtWidgets import QLabel

CACHE = Path.home() / ".animetracker" / "cache" / "emoji"
CDN = "https://fonts.gstatic.com/s/e/notoemoji/latest/{cp}/512.webp"
ATTRIBUTION = "Animated emoji: Noto Emoji Animation by Google, licensed CC BY 4.0."


def codepoint(emoji: str) -> str:
    """'🎃' -> '1f383', '❄️' -> '2744_fe0f' (Noto's file naming)."""
    return "_".join(f"{ord(c):x}" for c in emoji)


def cached(emoji: str):
    p = CACHE / f"{codepoint(emoji)}.webp"
    return p if p.exists() and p.stat().st_size > 2000 else None


class AnimatedEmoji(QLabel):
    def __init__(self, emoji: str, size: int = 40, parent=None):
        super().__init__(parent)
        self.emoji = emoji
        self.px = size
        self.movie = None
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont("Segoe UI Emoji")
        f.setPixelSize(int(size * 0.78))
        self.setFont(f)
        self.setText(emoji)                      # until (or unless) the animation is here
        self.setStyleSheet("background:transparent;")
        p = cached(emoji)
        if p is not None:
            self._play(p)
        else:
            self._download()

    def _download(self):
        from workers.workers import Worker, run_worker
        emoji = self.emoji

        def job():
            import requests
            r = requests.get(CDN.format(cp=codepoint(emoji)), timeout=20)
            if r.status_code != 200 or len(r.content) < 2000:
                return None
            CACHE.mkdir(parents=True, exist_ok=True)
            out = CACHE / f"{codepoint(emoji)}.webp"
            out.write_bytes(r.content)
            return str(out)

        w = Worker(job)
        w.signals.result.connect(lambda path: path and self._play(Path(path)))
        run_worker(w)

    def _play(self, path: Path):
        from PyQt6 import sip
        if sip.isdeleted(self):
            return
        mv = QMovie(str(path))
        if not mv.isValid():
            return
        mv.setScaledSize(QSize(self.px, self.px))
        mv.setCacheMode(QMovie.CacheMode.CacheAll)
        self.movie = mv
        self.setText("")
        self.setMovie(mv)
        try:
            from ui.decor import motion_level
            still = motion_level() == "off"
        except Exception:
            still = False
        if still:
            mv.jumpToFrame(0)
        else:
            mv.start()
