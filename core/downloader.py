"""
Raikō - save an opening / ending / soundtrack to your Downloads folder.

  audio   MP3 (192 kbps)
  video   MP4 up to 1080p (video + audio merged)

Uses yt-dlp with the bundled ffmpeg (imageio-ffmpeg). Files are named
"<show> - <song>.mp3|mp4" and never overwrite each other. For personal use:
YouTube's terms don't allow downloading, so this is the user's call.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, Optional


def downloads_dir() -> Path:
    try:
        import ctypes
        # FOLDERID_Downloads
        guid = ctypes.c_char_p(b"\x90\xe2\x4d\x37\x3f\x12\x65\x45\x91\x64\x39\xc4\x92\x5e\x46\x7b")
        buf = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(guid, 0, None, ctypes.byref(buf)) == 0:
            p = Path(buf.value)
            ctypes.windll.ole32.CoTaskMemFree(buf)
            if p.exists():
                return p
    except Exception:
        pass
    p = Path.home() / "Downloads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name or "")
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:150] or "Raiko download"


def file_stem(item: Dict) -> str:
    song = (item.get("song") or item.get("title") or "").split("  ·  ")[0]
    src = item.get("source") or ""
    return _safe(f"{src} - {song}" if src and src.lower() not in song.lower() else song)


def _unique(folder: Path, stem: str, ext: str) -> Path:
    p = folder / f"{stem}.{ext}"
    i = 2
    while p.exists():
        p = folder / f"{stem} ({i}).{ext}"
        i += 1
    return p


def download(item: Dict, mode: str, progress: Optional[Callable[[float, str], None]] = None,
             folder: Optional[Path] = None) -> str:
    """Network: download `item` as 'audio' or 'video'. Returns the saved path.
    progress(fraction 0-1, text) is called from this (worker) thread."""
    import imageio_ffmpeg
    import yt_dlp
    folder = folder or downloads_dir()
    ext = "mp3" if mode == "audio" else "mp4"
    target = _unique(folder, file_stem(item), ext)
    tmpl = str(target.with_suffix("")) + ".%(ext)s"

    parts = 2 if mode == "video" else 1          # 1080p video = video stream + audio stream
    state = {"done": 0}

    def hook(d):
        if not progress:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            frac = (d.get("downloaded_bytes") or 0) / total if total else 0.0
            progress(min(0.96, (min(state["done"], parts - 1) + frac) / parts), "Downloading…")
        elif d.get("status") == "finished":
            state["done"] += 1
            if state["done"] >= parts:
                progress(0.97, "Converting…" if mode == "audio" else "Merging…")

    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, "outtmpl": tmpl,
            "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(), "progress_hooks": [hook],
            "socket_timeout": 30, "retries": 5, "fragment_retries": 10, "concurrent_fragment_downloads": 4}
    if mode == "audio":
        opts.update(format="bestaudio/best",
                    postprocessors=[{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}])
    else:
        opts.update(format="bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b", merge_output_format="mp4")
    url = f"https://www.youtube.com/watch?v={item['id']}"
    with yt_dlp.YoutubeDL(opts) as y:
        y.extract_info(url, download=True)
    if not target.exists():                      # yt-dlp picked another extension
        found = sorted(folder.glob(target.stem + ".*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not found:
            raise RuntimeError("The download finished but the file wasn't found.")
        target = found[0]
    if progress:
        progress(1.0, "Saved")
    return str(target)
